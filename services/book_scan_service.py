# -*- coding: utf-8 -*-
import os
import subprocess
import sys
from repositories.book_scan_repository import BookScanRepository
from utils.redis_helper import redis_delete_pattern
from tools.scanner import (
    merge_local_metadata,
    extract_cover_from_b64,
    get_series_cover_fallback,
    get_folder_banner,
    collect_zip_offsets_data,
    parse_comicinfo_from_cbz
)
from tools.scanner.metadata import merge_metadata_links, parse_embedded_metadata, merge_embedded_metadata

_COMICINFO_SINGLE_BOOK_FIELDS = (
    'title', 'author', 'localized_series', 'cover_artist', 'teams', 'locations', 'characters',
    'publisher', 'summary', 'release_date', 'genre', 'tags', 'books_lv', 'link'
)


def _merge_comicinfo_metadata(target, comicinfo):
    """Use archive metadata only for fields not supplied by a folder sidecar."""
    if not isinstance(comicinfo, dict):
        return
    for key in _COMICINFO_SINGLE_BOOK_FIELDS:
        if key == 'link' and comicinfo.get(key):
            target[key] = merge_metadata_links(target.get(key, ''), comicinfo[key])
        elif comicinfo.get(key) and not target.get(key):
            target[key] = comicinfo[key]


class BookScanService:
    @staticmethod
    def scan_document_books(db_type, book_ids, task_id=None):
        """Extract selected EPUB/PDF covers in one isolated process and await completion."""
        ids = []
        for raw_id in book_ids or ():
            try:
                book_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if book_id > 0 and book_id not in ids:
                ids.append(book_id)
        if not ids:
            return False, 'EPUB/PDF 표지 스캔에 유효한 도서 ID가 없습니다.', {}
        if db_type not in ('general', 'adult', 'audiobook'):
            return False, f'지원하지 않는 도서 데이터베이스입니다: {db_type}', {}

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script_path = os.path.join(base_dir, 'tools', 'lazy_scanner.py')
        command = [
            sys.executable,
            script_path,
            '--book-ids',
            *[str(book_id) for book_id in ids],
            '--db-type',
            str(db_type),
            '--force-document-covers',
        ]
        if task_id is not None:
            command.extend(['--task-id', str(int(task_id))])

        print(f"[BookScanService] 문서 표지 격리 스캔 시작: IDs={ids}, DB={db_type}")
        try:
            result = subprocess.run(
                command,
                cwd=base_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception as error:
            message = f'EPUB/PDF 격리 스캐너 실행 실패: {error}'
            print(f"[BookScanService ERROR] {message}")
            return False, message, {book_id: None for book_id in ids}

        from services.cover_storage_service import get_covers_dir

        outcomes = {}
        for book_id in ids:
            try:
                book = BookScanRepository.get_book_basic_info_raw(db_type, book_id)
                cover_image = book.get('cover_image') if book else None
                cover_path = os.path.join(get_covers_dir(), cover_image) if cover_image else ''
                if (
                    result.returncode == 0
                    and cover_image
                    and cover_image != 'NO_COVER'
                    and os.path.isfile(cover_path)
                    and os.path.getsize(cover_path) > 0
                ):
                    outcomes[book_id] = cover_image
                    # The isolated scanner updates books; keep the representative series cover
                    # in sync as the synchronous scan path did.
                    try:
                        BookScanRepository.update_book_scanned_metadata(
                            db_type,
                            book_id,
                            book.get('series_name') or '',
                            cover_image,
                            {
                                'author': '', 'publisher': '', 'link': '', 'score': 0,
                                'summary': '', 'release_date': '',
                            },
                        )
                    except Exception as sync_error:
                        print(f"[BookScanService WARNING] 시리즈 표지 동기화 실패 (book_id={book_id}): {sync_error}")
                else:
                    outcomes[book_id] = None
            except Exception as check_error:
                print(f"[BookScanService WARNING] 문서 표지 결과 확인 실패 (book_id={book_id}): {check_error}")
                outcomes[book_id] = None

        successful_count = sum(1 for cover in outcomes.values() if cover)
        try:
            redis_delete_pattern(f"cache:recent_added*:{db_type}:*")
            redis_delete_pattern(f"cache:history*:{db_type}:*")
        except Exception as cache_error:
            print(f"[BookScanService WARNING] 레디스 캐시 소거 실패: {cache_error}")

        message = f'EPUB/PDF 표지 스캔 완료 · 표지 확인 {successful_count}/{len(ids)}권'
        if result.returncode != 0:
            message += f' (격리 스캐너 종료 코드 {result.returncode})'
        return successful_count == len(ids), message, outcomes

    @staticmethod
    def scan_single_book(db_type, book_id):
        """지정 도서의 메타데이터를 동기화하고, 가능한 표지와 로컬 오프셋도 갱신합니다."""
        print(f"[BookScanService] 단일 도서 스캔 요청 시작: DB={db_type}, ID={book_id}")
        try:
            # 1. 도서 기본 정보 조회
            book = BookScanRepository.get_book_basic_info_raw(db_type, book_id)
            if not book:
                print(f"[BookScanService ERROR] DB에서 book_id={book_id}를 찾을 수 없습니다.")
                return False, "존재하지 않는 도서입니다.", None
                
            file_path = book['file_path']
            library_id = book['library_id']
            series_name = book['series_name']
            file_format = book['file_format']
            print(f"[BookScanService] 대상 도서 매칭 성공: Title='{book['title']}', Path='{file_path}'")

            from utils.drive_helper import is_remote_path
            is_remote_file = is_remote_path(file_path, book.get('library_is_remote'))
            
            original_file_path = file_path
            is_imgdir = (file_format == 'imgdir') or file_path.lower().endswith('.imgdir')

            # 가상 책(imgdir)인 경우 __folder__.imgdir 파일은 존재하지 않으므로 부모 폴더가 존재하는지 검증합니다.
            check_path = os.path.dirname(file_path) if is_imgdir else file_path

            if not is_remote_file and not os.path.exists(check_path):
                print(f"[BookScanService ERROR] 물리 파일/디렉토리가 경로에 존재하지 않음: {check_path}")
                return False, f"서버에 물리 파일/디렉토리가 경로에 존재하지 않습니다: {check_path}", None

            # PDF와 원격 EPUB은 파일 파서를 API/큐 워커 안에서 직접 실행하지 않고,
            # Lazy Scanner 한 프로세스에서 처리해 시리즈 배치 내 여러 권의 경합을 막는다.
            filename = os.path.basename(file_path)
            file_format_lower = (file_format or '').lower()
            is_pdf = file_format_lower == 'pdf' or file_path.lower().endswith('.pdf')
            is_remote_epub = (file_format_lower == 'epub' or file_path.lower().endswith('.epub')) and is_remote_file
            if is_pdf or is_remote_epub:
                scan_ok, scan_message, scan_outcomes = BookScanService.scan_document_books(
                    db_type, [book_id]
                )
                cover_image = scan_outcomes.get(int(book_id))
                return scan_ok, f"'{filename}' {scan_message}", cover_image
                
            # 부모 폴더 경로
            parent_dir = os.path.dirname(file_path)
            print(f"[BookScanService] 부모 폴더 디렉토리 수색: '{parent_dir}'")
            
            # 2. 로컬 메타데이터 파일 탐색
            merged_meta = merge_local_metadata(parent_dir, is_remote=is_remote_file)
            embedded_metadata_checked = False

            # 단일 도서 재스캔도 CBZ/ZIP 내부 ComicInfo.xml을 반영한다.
            # rclone/FUSE 경로는 parser의 제한 시간 안에서만 읽는다.
            if (file_format or '').lower() in ('cbz', 'zip'):
                try:
                    comicinfo_status = {}
                    comicinfo = parse_comicinfo_from_cbz(
                        file_path,
                        is_remote=is_remote_file,
                        status_out=comicinfo_status,
                    )
                    _merge_comicinfo_metadata(merged_meta, comicinfo)
                    embedded_metadata_checked = bool(comicinfo_status.get('parsed'))
                    if any(comicinfo.get(key) for key in _COMICINFO_SINGLE_BOOK_FIELDS):
                        print(f"[BookScanService] ComicInfo.xml 메타데이터 추출 성공: {filename}")
                except Exception as comicinfo_err:
                    print(f"[BookScanService WARNING] ComicInfo.xml 파싱 실패(무시): {comicinfo_err}")

            file_format_lower = (file_format or '').lower()
            defer_epub_metadata = (
                file_format_lower == 'epub'
                and not is_remote_file
                and filename not in merged_meta.get('cover_b64_map', {})
            )
            embedded_meta = {}
            epub_opf_read = {}
            if file_format_lower in ('epub', 'pdf') and not defer_epub_metadata:
                embedded_status = {}
                embedded_meta = parse_embedded_metadata(
                    file_path,
                    file_format,
                    is_remote=is_remote_file,
                    status_out=embedded_status,
                )
                embedded_metadata_checked = bool(embedded_status.get('parsed'))

            # 원격 라이브러리는 배너를 건너뛴다. 표지는 아래에서 첫 아카이브 페이지를 제한 시간 내 읽는다.
            banner_image = None
            if not is_remote_file:
                try:
                    banner_image = get_folder_banner(
                        file_path,
                        parent_dir,
                        banner_b64=merged_meta.get('banner_b64'),
                        force=True,
                        library_id=library_id
                    )
                    if banner_image:
                        print(f"[BookScanService] 폴더 배너 확인 및 변환 완료: {banner_image}")
                except Exception as banner_err:
                    print(f"[BookScanService WARNING] 폴더 배너 처리 실패(무시): {banner_err}")
            else:
                print(f"[BookScanService] 원격 파일은 배너 처리를 건너뛰고, 메타데이터와 첫 페이지 표지를 갱신합니다: {filename}")
            
            # 3. 커버 이미지 결정 (Force 재추출 강제 지정)
            cover_image = None
            filename = os.path.basename(file_path)
            if filename in merged_meta['cover_b64_map']:
                print(f"[BookScanService] YAML cover_b64_map 매칭 발견, Base64 추출 진행")
                cover_image = extract_cover_from_b64(filename, merged_meta['cover_b64_map'][filename], force=True, library_id=library_id)
            if not cover_image:
                print(f"[BookScanService] get_series_cover_fallback 실행 시도 (Force=True, remote={is_remote_file})")
                cover_image = get_series_cover_fallback(
                    series_name,
                    parent_dir,
                    force=True,
                    is_remote=is_remote_file,
                    filename=filename,
                    file_path=file_path,
                    library_id=library_id,
                    allow_remote_archive_read=is_remote_file,
                    epub_metadata_out=embedded_meta if defer_epub_metadata else None,
                    epub_opf_read_out=epub_opf_read if defer_epub_metadata else None,
                )

            if defer_epub_metadata and not epub_opf_read.get('parsed'):
                # A sidecar/loose cover may win before EPUB extraction opens the archive.
                # In that case read OPF metadata once here; otherwise the cover extractor
                # already supplied it from the OPF it opened to locate the cover image.
                embedded_status = {}
                embedded_meta = parse_embedded_metadata(
                    file_path,
                    'epub',
                    is_remote=False,
                    status_out=embedded_status,
                )
            else:
                embedded_status = {'parsed': True}
            if defer_epub_metadata:
                embedded_metadata_checked = bool(
                    epub_opf_read.get('parsed') or embedded_status.get('parsed')
                )
            if embedded_meta:
                merge_embedded_metadata(merged_meta, embedded_meta)
                print(f"[BookScanService] {file_format.upper()} 내장 메타데이터 추출 성공: {', '.join(sorted(embedded_meta))}")
            if embedded_metadata_checked:
                merged_meta['_embedded_metadata_checked'] = True

            # cover_b64_map은 파일별 Base64 커버 원본을 통째로 담고 있어 그대로 출력하면
            # 로그 파일 용량을 불필요하게 낭비하므로, 개수만 요약해서 남긴다.
            meta_summary = {k: (f"<{len(v)} items>" if k == 'cover_b64_map' else v) for k, v in merged_meta.items()}
            print(f"[BookScanService] 파싱된 로컬 메타데이터: {meta_summary}")
                
            print(f"[BookScanService] 최종 매핑된 커버 이미지명: {cover_image}")
            
            # 4. 오프셋 재수집 (ZIP/CBZ인 경우)
            offsets_data = []
            if file_format in ('zip', 'cbz') and not is_remote_file:
                print(f"[BookScanService] ZIP/CBZ 포맷 오프셋 재생성 진행...")
                offsets_data = collect_zip_offsets_data(file_path)
                
            # 5. DB 업데이트 실행
            print(f"[BookScanService] DB 업데이트 트랜잭션 쿼리 빌드")
            
            # 시리즈명은 (gdrive 로컬 캐시 경로가 아니라) 원본 가상/실제 경로의 폴더 구조에서 유도한다.
            series_parent_dir = os.path.dirname(original_file_path)
            if is_imgdir:
                series_folder = os.path.basename(os.path.dirname(series_parent_dir.rstrip('/\\')))
            else:
                series_folder = os.path.basename(series_parent_dir.rstrip('/\\'))
            real_series_name = series_folder or ""

            if real_series_name:
                import re
                real_series_name = re.sub(r'^\[(?:단행|연재|소설|만화|웹툰|일반)\]\s*', '', real_series_name).strip()

            BookScanRepository.update_book_scanned_metadata(
                db_type,
                book_id,
                real_series_name,
                cover_image,
                merged_meta,
                banner_image=banner_image
            )
            
            if offsets_data:
                count = BookScanRepository.sync_book_offsets_transaction(db_type, book_id, offsets_data)
                print(f"[BookScanService] 오프셋 DB 데이터 {count}건 동기화 처리")

            # 대시보드 "신규 추가 도서"/최근기록 레디스 캐시가 갱신 전(빈 커버) 상태로
            # 굳어버리지 않도록, DB 반영 직후 관련 캐시를 함께 소거한다.
            try:
                redis_delete_pattern(f"cache:recent_added*:{db_type}:*")
                redis_delete_pattern(f"cache:history*:{db_type}:*")
            except Exception as cache_err:
                print(f"[BookScanService WARNING] 레디스 캐시 소거 실패: {cache_err}")

            print(f"[BookScanService SUCCESS] '{filename}' 단독 재스캔 처리 최종 완료.")
            if is_remote_file:
                cover_status = '메타데이터와 표지를 갱신했습니다.' if cover_image else '메타데이터를 갱신했습니다. 표지를 추출하지 못했습니다.'
                return True, f"'{filename}' 원격 도서 {cover_status} 배너와 페이지 오프셋은 즉시 스캔에서 건너뛰었습니다.", cover_image
            return True, f"'{filename}' 도서 스캔 및 메타데이터 동기화 완료!", cover_image
            
        except Exception as e:
            print(f"[BookScanService ERROR] 처리 중 예외 발생: {str(e)}")
            return False, f"도서 스캔 실패: {str(e)}", None

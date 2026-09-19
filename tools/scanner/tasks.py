# -*- coding: utf-8 -*-
import os
import sys

MEDIA_SERVER_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if MEDIA_SERVER_DIR not in sys.path:
    sys.path.append(MEDIA_SERVER_DIR)

import gc
from tools.scanner.metadata import parse_info_xml, parse_kavita_yaml, parse_series_json, parse_comicinfo_from_cbz, parse_embedded_metadata, merge_embedded_metadata, merge_local_metadata, merge_metadata_links, is_consonant_folder
from tools.scanner.cover import get_folder_batch_cover, get_series_cover_fallback, get_imgdir_cover, extract_cover_from_b64, download_cover_from_url, get_folder_banner
from tools.scanner.folder_image import COMMON_BANNER_NAMES, find_common_banner
from tools.scanner.offset import collect_zip_offsets_data
from tools.scanner.path_utils import canonical_path, join_canonical
from embedded_metadata_version import EMBEDDED_METADATA_FORMATS

SUPPORTED_FORMATS = ('.zip', '.cbz', '.epub', '.pdf', '.txt')
SUPPORTED_METADATA_TITLE_FORMATS = ('.zip', '.cbz', '.epub', '.pdf')
SUPPORTED_IMAGE_FORMATS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif')
IMGDIR_VIRTUAL_FILENAME = '__folder__.imgdir'


def _compute_offsets(full_path, filename, is_remote, root, gdrive_file_ids):
    """zip/cbz의 페이지 오프셋을 계산한다. 로컬이면 파일을 직접 열어서, 진짜 gdrive://
    가상 경로면 Range 요청으로 파일 끝(central directory)만 받아서 계산한다(전체 다운로드 없음).
    is_remote가 True인 다른 원격(rclone 마운트 등)은 기존처럼 건너뛴다 — 그런 라이브러리는
    이 함수가 손대지 않고 계속 빈 리스트를 반환한다(원래도 로컬 마운트라 직접 열어도
    되지만, 그 개선은 이 변경의 범위 밖이다)."""
    if root.startswith(('gdrive:', 'gdrive://')):
        file_id = gdrive_file_ids.get(filename) if gdrive_file_ids else None
        if not file_id:
            return []
        from utils.drive_helper import fetch_gdrive_zip_offsets
        try:
            offsets_data, _total_size = fetch_gdrive_zip_offsets(file_id)
            if offsets_data:
                print(f"[Scanner-DEBUG-Task] ⚡ [gdrive Range] '{filename}' 오프셋 계산 완료 ({len(offsets_data)}p, 전체 다운로드 없음)")
            return offsets_data
        except Exception as e:
            print(f"[Scanner-DEBUG-Task] ❌ gdrive Range 오프셋 계산 실패: '{filename}' - {e}")
            return []
    if is_remote:
        return []
    return collect_zip_offsets_data(full_path)


def _full_path_for(root, filename, gdrive_file_ids):
    """root+filename을 합친 경로에, gdrive 등록분이면 실제 Drive file_id를 얹어 반환한다.

    filename 자체는 절대 건드리지 않는다 — 제목/확장자 판별은 이 함수가 만드는
    full_path가 아니라 별도로 전달되는 원본 filename에서만 이뤄지므로, 여기서
    file_id를 붙여도 화면에 보이는 제목 등은 오염되지 않는다.
    """
    base = join_canonical(root, filename)
    if not gdrive_file_ids:
        return base
    file_id = gdrive_file_ids.get(filename)
    if not file_id:
        return base
    from utils.drive_helper import encode_gdrive_file_id
    return encode_gdrive_file_id(base, file_id)


_META_EXTENSIONS = ('.yaml', '.yml', '.json', '.xml')


def _stage_gdrive_metadata_folder(root, files, gdrive_file_ids):
    """gdrive 폴더에 kavita.yaml/series.json/info.xml 등 메타데이터 파일이 있으면
    실제 내용을 로컬 스테이징 폴더로 받아와, merge_local_metadata()가 평소처럼
    os.path.join(folder_path, filename) + open()으로 읽을 수 있게 해준다.

    이렇게 해두면 kavita.yaml에 임베드된 Base64 커버(cover_b64_map)를 커버 스캔 때
    바로 쓸 수 있어, 표지 하나 뽑자고 수십~수백MB 압축 파일 전체를 받을 필요가 없다.

    실패해도 예외를 전파하지 않고 원본 root를 그대로 반환한다(항상 안전한 폴백).
    """
    if not gdrive_file_ids:
        return root, False

    meta_filenames = [
        f for f in files
        if f.lower().endswith(_META_EXTENSIONS) and gdrive_file_ids.get(f)
    ]
    if not meta_filenames:
        return root, False

    try:
        import hashlib
        from utils.drive_helper import download_gdrive_file
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        staging_dir = os.path.join(base_dir, 'cache', 'gdrive_meta', hashlib.md5(root.encode('utf-8')).hexdigest())
        os.makedirs(staging_dir, exist_ok=True)

        any_ready = False
        for fname in meta_filenames:
            dest = os.path.join(staging_dir, fname)
            done_marker = dest + '.done'
            if os.path.exists(dest) and os.path.exists(done_marker):
                any_ready = True
                continue
            file_id = gdrive_file_ids.get(fname)
            if download_gdrive_file(file_id, dest):
                with open(done_marker, 'w') as f:
                    f.write('done')
                any_ready = True
            else:
                print(f"[Scanner-DEBUG-Task] ⚠️ gdrive 메타데이터 파일 다운로드 실패, 건너뜀: '{fname}'")

        if any_ready:
            return staging_dir, True
    except Exception as e:
        print(f"[Scanner-DEBUG-Task] ⚠️ gdrive 메타데이터 스테이징 실패, 원본 경로로 폴백: {e}")

    return root, False


def _normalize_series_text(name):
    """Normalize folder-derived series text."""
    if not name:
        return ''
    import re
    return re.sub(r'^\[(?:단행|연재|소설|만화|웹툰|일반)\]\s*', '', str(name)).strip()


def _merge_comicinfo_fallback(target, comicinfo):
    """Fill empty per-book metadata fields from that archive's ComicInfo.xml."""
    if not isinstance(comicinfo, dict):
        return
    for key in (
        'title', 'author', 'localized_series', 'cover_artist', 'teams', 'locations', 'characters',
        'publisher', 'summary', 'release_date', 'genre', 'tags', 'books_lv', 'link'
    ):
        if key == 'link' and comicinfo.get(key):
            target[key] = merge_metadata_links(target.get(key, ''), comicinfo[key])
        elif comicinfo.get(key) and not target.get(key):
            target[key] = comicinfo[key]


def process_folder_task(root, files, force, db_meta_full, db_offsets_cached, db_folder_mtimes, is_remote=False, library_id=None, db_files_cache=None, library_root=None, gdrive_file_ids=None, db_type=None, db_book_ids=None, db_banner_missing=None, db_banner_images=None, use_folder_cover=False, db_cover_images=None, progress_callback=None, db_metadata_title_unchecked=None, db_embedded_metadata_outdated=None):
    """Independent I/O scan task per folder (DB independent, pure FS/I/O scaling)"""
    root = canonical_path(root)
    db_banner_images = db_banner_images or {}
    db_cover_images = db_cover_images or {}
    db_metadata_title_unchecked = db_metadata_title_unchecked or set()
    db_embedded_metadata_outdated = db_embedded_metadata_outdated or set()
    print(f"[Scanner-DEBUG-Task] 📂 entering process_folder_task - folder: '{root}'")

    def report_progress(event, current):
        if not callable(progress_callback):
            return
        try:
            progress_callback(event, current=current)
        except Exception:
            # UI progress reporting must not interrupt file scanning.
            pass

    report_progress('folder_start', root)
    
    media_files = [f for f in files if f.lower().endswith(SUPPORTED_FORMATS)]
    image_files = [f for f in files if f.lower().endswith(SUPPORTED_IMAGE_FORMATS)]
    has_imgdir_candidate = bool(image_files) and not media_files
    if not media_files and not has_imgdir_candidate:
        print(f"[Scanner-DEBUG-Task] 📁 Unsupported folder (skip) - folder: '{root}'")
        return None

    # 1. Pre-check if metadata file exists
    has_yaml = any(f.lower() == 'kavita.yaml' for f in files)
    has_xml = any(f.lower() == 'info.xml' for f in files)
    
    dir_mtime = None
    meta_mtime = None
    
    if is_remote or root.startswith(('gdrive:', 'gdrive://')):
        is_remote = True
        dir_mtime = 0.0
        meta_mtime = 0.0
    else:
        try:
            dir_mtime = os.path.getmtime(root)
            meta_mtimes_list = []
            if has_yaml:
                yaml_file = next(f for f in files if f.lower() == 'kavita.yaml')
                meta_mtimes_list.append(os.path.getmtime(join_canonical(root, yaml_file)))
            if has_xml:
                xml_file = next(f for f in files if f.lower() == 'info.xml')
                meta_mtimes_list.append(os.path.getmtime(join_canonical(root, xml_file)))
            
            if meta_mtimes_list:
                meta_mtime = max(meta_mtimes_list)
            else:
                meta_mtime = 0.0
        except Exception as e:
            print(f"[Scanner-DEBUG-Task] ⚠️ Failed to get mtime for folder '{root}': {e}")
            dir_mtime = None

    # rclone/CIFS/NFS mounts expose ordinary filesystem paths and can read small
    # sidecar images directly. gdrive:// is an API-backed virtual path, not a
    # mounted directory, so keep its existing staged-metadata behavior.
    can_read_folder_banner = not (is_remote and root.startswith(('gdrive:', 'gdrive://')))
    imgdir_virtual_path = join_canonical(root, IMGDIR_VIRTUAL_FILENAME)
    batch_cover_image = None
    if use_folder_cover and can_read_folder_banner:
        try:
            batch_cover_image = get_folder_batch_cover(root, library_id, force=force)
        except Exception as e:
            print(f"[Scanner-DEBUG-Task] ⚠️ Shared cover processing failed ('{root}'): {e}")

    folder_book_paths = [
        canonical_path(_full_path_for(root, filename, gdrive_file_ids))
        for filename in media_files
    ]
    if has_imgdir_candidate:
        folder_book_paths.append(canonical_path(imgdir_virtual_path))
    folder_cover_recheck_needed = bool(
        batch_cover_image
        and db_book_ids
        and any(
            path in db_book_ids and db_cover_images.get(path) != batch_cover_image
            for path in folder_book_paths
        )
    )

    # 2. Early skip if files are unchanged (mtime & size match DB cache)
    skipped_files = set()
    imgdir_skip = False
    if not force and db_files_cache:
        for filename in media_files:
            full_path = _full_path_for(root, filename, gdrive_file_ids)
            if full_path in db_files_cache:
                try:
                    p_mtime = os.path.getmtime(full_path)
                    p_size = os.path.getsize(full_path)
                    c_mtime, c_size = db_files_cache[full_path]
                    
                    if int(c_mtime) == int(p_mtime) and c_size == p_size:
                        file_ext = os.path.splitext(filename)[1].lower()
                        if (
                            full_path in db_metadata_title_unchecked
                            and file_ext in SUPPORTED_METADATA_TITLE_FORMATS
                        ):
                            # Existing unchanged rows from older scanners have not
                            # had a chance to populate metadata_title yet.
                            # Process them once; the DB marker is set after the
                            # result is committed, even when the file has no title.
                            continue
                        if (
                            full_path in db_embedded_metadata_outdated
                            and file_ext.lstrip('.') in EMBEDDED_METADATA_FORMATS
                        ):
                            # A legacy row may look complete according to a few
                            # headline fields while newer embedded fields were
                            # never inspected. Bypass the unchanged-file fast
                            # path once for the current extractor version.
                            continue
                        if file_ext in ('.zip', '.cbz') and not is_remote and full_path not in db_offsets_cached:
                            continue
                        # TXT는 오프셋/표지 강제 재시도가 필요 없으므로 mtime/size 동일 시 바로 스킵
                        if file_ext == '.txt':
                            skipped_files.add(filename)
                            continue
                        if full_path not in db_meta_full:
                            continue
                        skipped_files.add(filename)
                except Exception:
                    # 원격 드라이브이고 이미 DB 캐시(mtime, 메타데이터, 커버)가 있는 경우 예외가 나더라도 스킵 처리
                    if is_remote and full_path in db_meta_full:
                        c_mtime, c_size = db_files_cache[full_path]
                        if c_mtime > 0.0:
                            skipped_files.add(filename)

        if has_imgdir_candidate and imgdir_virtual_path in db_files_cache:
            try:
                p_mtime = os.path.getmtime(root)
                p_size = sum(
                    os.path.getsize(join_canonical(root, f))
                    for f in image_files
                    if os.path.exists(join_canonical(root, f))
                )
                c_mtime, c_size = db_files_cache[imgdir_virtual_path]
                if int(c_mtime) == int(p_mtime) and int(c_size) == int(p_size):
                    imgdir_skip = True
            except Exception:
                imgdir_skip = False

        all_files_skipped = (
            len(skipped_files) == len(media_files)
            and (not has_imgdir_candidate or imgdir_skip)
        )
        if all_files_skipped:
            cached_paths_missing_banner = set(db_banner_missing or ())
            folder_book_paths = [
                _full_path_for(root, filename, gdrive_file_ids)
                for filename in media_files
            ]
            if has_imgdir_candidate:
                folder_book_paths.append(imgdir_virtual_path)
            has_cached_book_without_banner = bool(
                can_read_folder_banner
                and cached_paths_missing_banner.intersection(folder_book_paths)
            )

            has_cached_book_with_banner = any(
                db_banner_images.get(full_path) for full_path in folder_book_paths
            )
            banner_sidecar_listed = any(
                filename.lower() in COMMON_BANNER_NAMES for filename in files
            )
            banner_source_candidate = banner_sidecar_listed
            if (has_cached_book_without_banner or has_cached_book_with_banner) and not banner_source_candidate:
                try:
                    banner_source_candidate = bool(find_common_banner(root))
                except Exception as e:
                    # Let the normal extraction path report the read failure.
                    print(f"[Scanner-DEBUG-Task] ⚠️ Banner sidecar probe failed ('{root}'): {e}")
                    banner_source_candidate = True

            # Folder mtimes do not change when an existing sidecar is edited in
            # place, and mounted rclone paths deliberately have unknown (0)
            # mtimes. Recheck folders with a stored banner, a visible sidecar,
            # or remote YAML so ordinary scans can detect both replacement and
            # removal without reopening unchanged book archives.
            banner_recheck_needed = bool(
                can_read_folder_banner
                and (
                    has_cached_book_with_banner
                    or banner_source_candidate
                    or (is_remote and has_yaml)
                )
            )
            if banner_recheck_needed:
                print(f"[Scanner-DEBUG-Task] 🖼️ Checking folder banner source during normal scan: '{root}'")
            elif folder_cover_recheck_needed:
                print(f"[Scanner-DEBUG-Task] 🖼️ Applying changed shared cover to cached books: '{root}'")
            elif not has_yaml and not has_xml:
                print(f"[Scanner-DEBUG-Task] ⚡ [Ultra-fast skip] All files unchanged (mtime/size match) - folder: '{root}'")
                return None
            else:
                if dir_mtime is not None:
                    cached_mtimes = db_folder_mtimes.get(root)
                    if cached_mtimes:
                        c_dir_mtime, c_meta_mtime = cached_mtimes
                        if int(c_dir_mtime) == int(dir_mtime) and int(c_meta_mtime) == int(meta_mtime):
                            print(f"[Scanner-DEBUG-Task] ⚡ [Ultra-fast skip] All files unchanged and meta mtime unchanged - folder: '{root}'")
                            return None
                        else:
                            print(f"[Scanner-DEBUG-Task] ⚠️ [Ultra-fast skip failed] mtime changed (dir: {int(c_dir_mtime)}->{int(dir_mtime)}, meta: {int(c_meta_mtime)}->{int(meta_mtime)}) - folder: '{root}'")

    # 일반 파일(archive/txt/pdf/epub)은 "현재 폴더명"을 시리즈로 사용한다.
    # 즉, 라이브러리 루트와 현재 폴더 사이의 중간 경로는 모두 무시한다.
    series_name = _normalize_series_text(os.path.basename(root.rstrip('/')))

    print(f"[Scanner-DEBUG-Task]   - Metadata YAML/XML/JSON load started")
    meta_folder_path, meta_staged_locally = (root, False)
    if is_remote and root.startswith(('gdrive:', 'gdrive://')):
        meta_folder_path, meta_staged_locally = _stage_gdrive_metadata_folder(root, files, gdrive_file_ids)
    merged_meta = merge_local_metadata(meta_folder_path, files=files, is_remote=is_remote and not meta_staged_locally)
    print(f"[Scanner-DEBUG-Task]   - Metadata load completed")

    parser_warnings = merged_meta.pop('parser_warnings', [])

    banner_source_checked = can_read_folder_banner
    banner_sidecar_listed = any(
        filename.lower() in COMMON_BANNER_NAMES for filename in files
    )
    banner_source_present = bool(merged_meta.get('banner_b64')) or banner_sidecar_listed
    folder_book_paths = [
        _full_path_for(root, filename, gdrive_file_ids) for filename in media_files
    ]
    if has_imgdir_candidate:
        folder_book_paths.append(imgdir_virtual_path)
    has_cached_book_with_banner = any(
        db_banner_images.get(full_path) for full_path in folder_book_paths
    )
    if can_read_folder_banner and has_cached_book_with_banner and not banner_source_present:
        try:
            banner_source_present = banner_source_present or bool(find_common_banner(root))
        except Exception as e:
            # A failed source probe must preserve the old DB value, not interpret
            # an I/O error as an intentional banner deletion.
            banner_source_checked = False
            print(f"[Scanner-DEBUG-Task] ⚠️ Banner source probe failed ('{root}'): {e}")
    if has_yaml and parser_warnings:
        banner_source_checked = False

    meta_has_data = bool(
        merged_meta['author'] or merged_meta['publisher'] or
        merged_meta['summary'] or merged_meta['release_date'] or
        merged_meta['cover_b64_map'] or
        merged_meta.get('books_lv') or merged_meta.get('publication_status')
    )

    is_series_folder = bool(merged_meta.get('has_yaml') and merged_meta.get('is_webtoon'))
    is_json_only_webtoon = bool(not merged_meta.get('has_yaml') and merged_meta.get('is_webtoon'))
    series_cover_url = merged_meta.get('cover_image_url', '') if is_json_only_webtoon else ''
    shared_cover_image = None

    # 배너는 표지와 달리 권마다 다를 필요 없는 시리즈/폴더 단위 이미지다.
    # 일반 경로와 rclone 같은 마운트 경로 모두에서 YAML 또는 loose sidecar만 읽고,
    # gdrive:// 가상 경로는 직접 파일 접근을 하지 않는다.
    shared_banner_image = None
    if can_read_folder_banner and media_files:
        try:
            banner_seed_path = _full_path_for(root, media_files[0], gdrive_file_ids)
            shared_banner_image = get_folder_banner(banner_seed_path, root, banner_b64=merged_meta.get('banner_b64'), force=force, library_id=library_id)
        except Exception as e:
            print(f"[Scanner-DEBUG-Task] ⚠️ Banner extraction failed ('{root}'): {e}")

    import zipfile
    results = []
    errors = list(parser_warnings)
    for filename in media_files:
        # Folder sidecars apply to every item, but ComicInfo.xml belongs to one archive.
        # Keep a per-item copy so a rating or author cannot leak to sibling volumes.
        book_meta = dict(merged_meta)
        book_meta['cover_b64_map'] = merged_meta.get('cover_b64_map', {})
        full_path = _full_path_for(root, filename, gdrive_file_ids)
        report_progress('item_start', full_path)
        _, ext = os.path.splitext(filename)
        file_format = ext.replace('.', '').lower()

        skip = False
        if (
            not force
            and not meta_has_data
            and full_path in db_meta_full
            and full_path in db_offsets_cached
            and full_path not in db_metadata_title_unchecked
            and full_path not in db_embedded_metadata_outdated
        ):
            skip = True
        elif filename in skipped_files:
            skip = True

        cover_image = None
        offsets_data = []
        offset_only = False  # Cover/meta complete, offset-only fast path flag
        needs_folder_cover_update = bool(
            batch_cover_image
            and db_book_ids
            and canonical_path(full_path) in db_book_ids
            and db_cover_images.get(canonical_path(full_path)) != batch_cover_image
        )
        folder_cover_only_update = bool(skip and needs_folder_cover_update)

        if skip:
            if folder_cover_only_update:
                cover_image = batch_cover_image
            # Fully cached book — only emit a minimal cover update when its shared
            # folder-cover reference differs from the configured sidecar.

        elif (
            not force and
            not meta_has_data and
            full_path in db_meta_full and
            full_path not in db_offsets_cached and
            full_path not in db_metadata_title_unchecked and
            full_path not in db_embedded_metadata_outdated and
            file_format in ('zip', 'cbz') and
            (not is_remote or root.startswith(('gdrive:', 'gdrive://')))
        ):
            # ── [Offset-only Fast Path] ──
            # If existing book has cover/meta but no offset:
            # Completely skip ComicInfo parsing and cover extraction pipeline
            # Only read ZIP central directory (collect offsets) - Minimize I/O
            # (gdrive:// 가상 경로면 전체 다운로드 없이 Range 요청만으로 처리 — _compute_offsets 참조)
            offset_only = True
            if needs_folder_cover_update:
                folder_cover_only_update = True
                cover_image = batch_cover_image
            try:
                offsets_data = _compute_offsets(full_path, filename, is_remote, root, gdrive_file_ids)
                if offsets_data:
                    print(f"[Scanner-DEBUG-Task] ⚡ [Offset-only] '{filename}' ({len(offsets_data)}p)")
                else:
                    print(f"[Scanner-DEBUG-Task] ⚡ [Offset-only] Skip ZIP without images: '{filename}'")
            except Exception as e:
                print(f"[Scanner-DEBUG-Task] ❌ Offset-only collection failed: '{filename}' - {e}")
                errors.append({
                    'file_path': full_path,
                    'filename': filename,
                    'error_type': 'OffsetError',
                    'message': f"Offset-only collection failed: {str(e)}"
                })

        else:
            # ── [General Path] Cover extraction + Offset collection ──
            print(f"[Scanner-DEBUG-Task]   - File processing started: '{filename}'")
            try:
                embedded_metadata_checked = file_format in EMBEDDED_METADATA_FORMATS and (
                    is_remote and root.startswith(('gdrive:', 'gdrive://'))
                )
                # A mounted rclone/FUSE path can be opened like a local ZIP, but a
                # gdrive:// virtual URL cannot. The parser bounds remote reads so a
                # stalled VFS object cannot block this scanner worker indefinitely.
                comicinfo_fields = (
                    'title', 'author', 'localized_series', 'cover_artist', 'teams', 'locations', 'characters',
                    'publisher', 'summary', 'release_date', 'genre', 'tags', 'books_lv', 'link'
                )
                can_read_comicinfo = not (
                    is_remote and root.startswith(('gdrive:', 'gdrive://'))
                )
                if (
                    file_format in ('cbz', 'zip')
                    and can_read_comicinfo
                    and any(not book_meta.get(key) for key in comicinfo_fields)
                ):
                    try:
                        comicinfo_status = {}
                        comicinfo = parse_comicinfo_from_cbz(
                            full_path,
                            is_remote=is_remote,
                            status_out=comicinfo_status,
                        )
                        _merge_comicinfo_fallback(book_meta, comicinfo)
                        embedded_metadata_checked = bool(comicinfo_status.get('parsed'))
                        if comicinfo.get('author') and book_meta.get('author') == comicinfo['author']:
                            print(f"[Scanner-DEBUG-Task]     - ComicInfo.xml author fallback: {comicinfo['author']}")
                        if comicinfo.get('books_lv') and book_meta.get('books_lv') == comicinfo['books_lv']:
                            print(f"[Scanner-DEBUG-Task]     - ComicInfo.xml AgeRating fallback: {comicinfo['books_lv']}")
                    except Exception as ce:
                        print(f"[Scanner-DEBUG-Task]     - ComicInfo.xml parsing skipped: {ce}")
                elif file_format in ('cbz', 'zip') and can_read_comicinfo:
                    # Sidecar metadata already supplied every supported field,
                    # so opening the archive cannot add a fallback value.
                    embedded_metadata_checked = True

                defer_local_epub_metadata = (
                    file_format == 'epub'
                    and not is_remote
                    and not root.startswith(('gdrive:', 'gdrive://'))
                )
                epub_embedded_meta = {}
                epub_opf_read = {}
                if (
                    file_format in ('epub', 'pdf')
                    and not defer_local_epub_metadata
                    and not (is_remote and root.startswith(('gdrive:', 'gdrive://')))
                ):
                    embedded_status = {}
                    embedded_meta = parse_embedded_metadata(
                        full_path,
                        file_format,
                        is_remote=is_remote,
                        status_out=embedded_status,
                    )
                    embedded_metadata_checked = bool(embedded_status.get('parsed'))
                    if embedded_meta:
                        merge_embedded_metadata(book_meta, embedded_meta)
                        print(f"[Scanner-DEBUG-Task]     - {file_format.upper()} embedded metadata loaded: {', '.join(sorted(embedded_meta))}")

                # Convert keys to lowercase to prevent case issues in Linux
                filename_lower = filename.lower()
                b64_keys_lower = {k.lower(): v for k, v in book_meta['cover_b64_map'].items()}
                
                if batch_cover_image:
                    cover_image = batch_cover_image
                elif filename_lower in b64_keys_lower:
                    print(f"[Scanner-DEBUG-Task]     - YAML b64 cover decoding started")
                    cover_image = extract_cover_from_b64(full_path, b64_keys_lower[filename_lower], force=force, library_id=library_id)
                
                if not cover_image:
                    if (is_series_folder or is_json_only_webtoon) and shared_cover_image:
                        print(f"[Scanner-DEBUG-Task]     - Series cover (thumbnail) cloned")
                        cover_image = shared_cover_image
                    elif is_json_only_webtoon and series_cover_url:
                        print(f"[Scanner-DEBUG-Task]     - series.json URL cover download started")
                        cover_image = download_cover_from_url(full_path, series_cover_url, force=force, library_id=library_id)
                    else:
                        print(f"[Scanner-DEBUG-Task]     - Fallback cover extraction started")
                        cover_image = get_series_cover_fallback(
                            series_name,
                            root,
                            force=force,
                            is_remote=is_remote,
                            filename=filename,
                            file_path=full_path,
                            library_id=library_id,
                            epub_metadata_out=epub_embedded_meta if defer_local_epub_metadata else None,
                            epub_opf_read_out=epub_opf_read if defer_local_epub_metadata else None,
                        )

                if defer_local_epub_metadata:
                    if not epub_opf_read.get('parsed'):
                        # If a sidecar or loose image supplied the cover, the archive
                        # was not opened by cover extraction; parse OPF once now.
                        embedded_status = {}
                        epub_embedded_meta = parse_embedded_metadata(
                            full_path,
                            'epub',
                            is_remote=False,
                            status_out=embedded_status,
                        )
                    else:
                        embedded_status = {'parsed': True}
                    embedded_metadata_checked = bool(
                        epub_opf_read.get('parsed') or embedded_status.get('parsed')
                    )
                    if epub_embedded_meta:
                        merge_embedded_metadata(book_meta, epub_embedded_meta)
                        print(f"[Scanner-DEBUG-Task]     - EPUB embedded metadata loaded: {', '.join(sorted(epub_embedded_meta))}")
                
                # Save first successful cover as shared thumbnail for series folder regardless of source
                if (is_series_folder or is_json_only_webtoon) and cover_image and not shared_cover_image:
                    shared_cover_image = cover_image

                # Real-time check if extracted cover is 0 bytes
                if cover_image:
                    from services.cover_storage_service import get_covers_dir
                    cover_filepath = os.path.join(get_covers_dir(), cover_image)
                    if os.path.exists(cover_filepath) and os.path.getsize(cover_filepath) == 0:
                        print(f"[Scanner-DEBUG-Task] ⚠️ Extracted cover file is 0 bytes: {cover_filepath}")
                        try:
                            os.remove(cover_filepath)
                        except Exception:
                            pass
                        cover_image = None  # Invalidate to include in error report collection
                
                # EPUB 사전 캐싱 (Pre-caching) 트리거
                # get_epub_meta()는 book_id가 있어야만(캐시 키를 만들 수 있어야만) 실제로
                # Redis에 결과를 써서 캐싱한다. 이 시점은 아직 신규 도서를 DB에 insert하기
                # 전(폴더 단위 순수 I/O 스캔 - 실제 insert/update 분기 및 커밋은 나중에
                # engine.py의 as_completed 루프+process_batch에서 일괄 처리됨)라, 신규 도서는
                # book_id가 없어 캐싱이 스킵된다. 다만 재스캔되는 "기존" 도서는 스캔 시작
                # 시점에 이미 조회해둔 db_book_ids(파일 경로 -> book id)로 알 수 있으므로,
                # 이 경우엔 실제로 캐시를 채워 이후 뷰어가 처음 열 때부터 바로 히트하게 한다.
                if file_format == 'epub' and not is_remote:
                    try:
                        from services.text_epub_content_service import TextEpubContentService
                        existing_book_id = db_book_ids.get(full_path) if db_book_ids else None
                        TextEpubContentService.get_epub_meta(full_path, existing_book_id, db_type)
                    except Exception as pre_err:
                        print(f"[Scanner-EPUB-Precache] Notice: {pre_err}")

                # Log to error list if Zip/EPUB format but no cover acquired
                if not cover_image and file_format in ('zip', 'cbz', 'epub'):
                    if is_remote:
                        print(f"[Scanner-DEBUG-Task] ⚠️ No cover for remote archive (deferred to lazy scanner): '{filename}'")
                    else:
                        errors.append({
                            'file_path': full_path,
                            'filename': filename,
                            'error_type': 'NoCover',
                            'message': 'ERR_NO_COVER'
                        })
            except zipfile.BadZipFile as bzf:
                print(f"[Scanner-DEBUG-Task] ❌ BadZipFile detected: '{filename}' - {bzf}")
                errors.append({
                    'file_path': full_path,
                    'filename': filename,
                    'error_type': 'BadZipFile',
                    'message': str(bzf)
                })
            except ValueError as ve:
                print(f"[Scanner-DEBUG-Task] ❌ ValueError detected: '{filename}' - {ve}")
                errors.append({
                    'file_path': full_path,
                    'filename': filename,
                    'error_type': 'NoCover',
                    'message': str(ve)
                })
            except Exception as e:
                print(f"[Scanner-DEBUG-Task] ❌ General exception detected: '{filename}' - {e}")
                errors.append({
                    'file_path': full_path,
                    'filename': filename,
                    'error_type': 'Exception',
                    'message': str(e)
                })

            try:
                if file_format in ('zip', 'cbz') and (force or full_path not in db_offsets_cached):
                    print(f"[Scanner-DEBUG-Task]     - Offset analysis started: '{filename}'")
                    offsets_data = _compute_offsets(full_path, filename, is_remote, root, gdrive_file_ids)
            except Exception as e:
                print(f"[Scanner-DEBUG-Task] ❌ Offset analysis failed: '{filename}' - {e}")
                if not any(err['file_path'] == full_path for err in errors):
                    errors.append({
                        'file_path': full_path,
                        'filename': filename,
                        'error_type': 'OffsetAnalysis',
                        'message': f"ERR_OFFSET_FAIL: {str(e)}"
                    })
            print(f"[Scanner-DEBUG-Task]   - File processing completed: '{filename}'")

        f_mtime = 0.0
        f_size = 0
        try:
            f_mtime = os.path.getmtime(full_path)
            f_size = os.path.getsize(full_path)
        except Exception:
            pass

        results.append({
            'full_path': full_path,
            'filename': filename,
            'file_format': file_format,
            'series_name': series_name,
            'title': None,
            'cover_image': cover_image,
            'banner_image': shared_banner_image,
            'clear_banner': bool(
                banner_source_checked
                and db_banner_images.get(full_path)
                and not banner_source_present
            ),
            'folder_cover_only': folder_cover_only_update,
            'offsets_data': offsets_data,
            'merged_meta': {
                key: value for key, value in book_meta.items()
                if key not in ('cover_b64_map', 'parser_warnings')
            },
            'skip': skip,
            'offset_only': offset_only,  # Whether it's offset-only fast path
            'embedded_metadata_checked': (
                embedded_metadata_checked if not skip and not offset_only else False
            ),
            'file_mtime': f_mtime,
            'file_size': f_size,
        })
        report_progress('item_done', full_path)

    if has_imgdir_candidate:
        # 이미지 폴더(imgdir)는 "현재 폴더=책", "부모 폴더=시리즈" 규칙을 사용한다.
        parent_folder = os.path.basename(os.path.dirname(root.rstrip('/')))
        imgdir_series_name = _normalize_series_text(parent_folder) if parent_folder else series_name
        imgdir_title = os.path.basename(root)
        imgdir_folder_cover_only_update = bool(
            imgdir_skip
            and batch_cover_image
            and db_book_ids
            and imgdir_virtual_path in db_book_ids
            and db_cover_images.get(canonical_path(imgdir_virtual_path)) != batch_cover_image
        )
        imgdir_cover = batch_cover_image
        imgdir_banner = shared_banner_image
        if not imgdir_skip and not imgdir_cover:
            try:
                imgdir_cover = get_imgdir_cover(root, imgdir_virtual_path, force=force, library_id=library_id)
            except Exception as e:
                print(f"[Scanner-DEBUG-Task] ❌ IMGDIR cover extraction failed: '{root}' - {e}")
                errors.append({
                    'file_path': imgdir_virtual_path,
                    'filename': IMGDIR_VIRTUAL_FILENAME,
                    'error_type': 'NoCover',
                    'message': f"IMGDIR cover extraction failed: {str(e)}"
                })
        if imgdir_banner is None and can_read_folder_banner:
            try:
                imgdir_banner = get_folder_banner(imgdir_virtual_path, root, banner_b64=merged_meta.get('banner_b64'), force=force, library_id=library_id)
            except Exception as e:
                print(f"[Scanner-DEBUG-Task] ⚠️ IMGDIR banner extraction failed ('{root}'): {e}")

        f_mtime = 0.0
        f_size = 0
        try:
            f_mtime = os.path.getmtime(root)
            f_size = sum(
                os.path.getsize(join_canonical(root, f))
                for f in image_files
                if os.path.exists(join_canonical(root, f))
            )
        except Exception:
            pass

        results.append({
            'full_path': imgdir_virtual_path,
            'filename': IMGDIR_VIRTUAL_FILENAME,
            'file_format': 'imgdir',
            'series_name': imgdir_series_name,
            'title': imgdir_title,
            'cover_image': imgdir_cover,
            'banner_image': imgdir_banner,
            'clear_banner': bool(
                banner_source_checked
                and db_banner_images.get(imgdir_virtual_path)
                and not banner_source_present
            ),
            'folder_cover_only': imgdir_folder_cover_only_update,
            'offsets_data': [],
            'skip': imgdir_skip,
            'offset_only': False,
            'file_mtime': f_mtime,
            'file_size': f_size,
        })

    # Clear references to large base64 maps used to free memory
    merged_meta.pop('cover_b64_map', None)

    gc.collect()
    print(f"[Scanner-DEBUG-Task] 📁 process_folder_task completed - folder: '{root}'")
    return {
        'root': root,
        'merged_meta': merged_meta,
        'results': results,
        'errors': errors,
        'dir_mtime': dir_mtime,
        'meta_mtime': meta_mtime
    }

def process_folder_covers(parent_dir, folder_rows, is_remote, library_id, use_folder_cover=False):
    """Extract covers by folder. Share to rest if first book succeeds."""
    if use_folder_cover:
        shared_folder_cover = get_folder_batch_cover(parent_dir, library_id, force=True)
        if shared_folder_cover:
            results = []
            for row in folder_rows:
                try:
                    metadata_locked = row['metadata_locked']
                except (KeyError, IndexError):
                    metadata_locked = 0
                if not int(metadata_locked or 0):
                    results.append((row['id'], shared_folder_cover))
            return results

    merged_meta = merge_local_metadata(parent_dir, is_remote=is_remote)
    
    is_series = bool(merged_meta.get('has_yaml') and merged_meta.get('is_webtoon'))
    is_json_only = bool(not merged_meta.get('has_yaml') and merged_meta.get('is_webtoon'))
    series_cover_url = merged_meta.get('cover_image_url', '') if is_json_only else ''
    b64_keys_lower = {k.lower(): v for k, v in merged_meta.get('cover_b64_map', {}).items()}
    
    shared_cover = None
    results = []
    
    for row in folder_rows:
        book_id = row['id']
        file_path = row['file_path']
        filename = os.path.basename(file_path)
        series_name = row['series_name']
        file_format = (row['file_format'] or '').lower() if 'file_format' in row.keys() else ''
        is_imgdir = (file_format == 'imgdir') or file_path.lower().endswith('.imgdir')
        imgdir_folder_path = os.path.dirname(file_path) if is_imgdir else None
        
        file_exists = os.path.exists(file_path)
        
        cover_image = None
        filename_lower = filename.lower()
        
        # 1) kavita.yaml Base64 cover - no actual file access needed, remote files supported
        if filename_lower in b64_keys_lower:
            cover_image = extract_cover_from_b64(file_path, b64_keys_lower[filename_lower], force=True, library_id=library_id)
        
        # 2) Reuse already shared cover (if series folder) - no file access needed
        if not cover_image and (is_series or is_json_only) and shared_cover:
            print(f"[Scanner-Covers] Series cover cloned: '{filename}'")
            cover_image = shared_cover
        
        # 3) series.json URL download - no actual file access needed, remote files supported
        if not cover_image and is_json_only and series_cover_url:
            cover_image = download_cover_from_url(file_path, series_cover_url, force=True, library_id=library_id)
        
        # 4) Fallback: first image in archive - requires file access, skip if none -> delegate to Lazy Scanner
        if not cover_image:
            if is_imgdir and imgdir_folder_path and os.path.isdir(imgdir_folder_path):
                cover_image = get_imgdir_cover(imgdir_folder_path, file_path, force=True, library_id=library_id)
            elif not file_exists:
                print(f"[Scanner-Covers] Remote file unreachable -> Delegated to Lazy scanner: '{filename}'")
            else:
                cover_image = get_series_cover_fallback(
                    series_name, parent_dir, force=True, is_remote=is_remote,
                    filename=filename, file_path=file_path, library_id=library_id
                )

        
        # Cache upon first successful shared cover
        if (is_series or is_json_only) and cover_image and not shared_cover:
            shared_cover = cover_image
        
        if cover_image:
            results.append((book_id, cover_image))
    
    return results

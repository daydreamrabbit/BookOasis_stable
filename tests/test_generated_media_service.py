import os
import time
import pytest
from services import generated_media_service as media


def test_readable_stable_names_and_collision_protection():
    path = '/book/작품/작품 04권.cbz'
    name = media.generated_image_name(path)
    assert name.startswith('작품_04권__bo_cover_')
    assert name == media.generated_image_name(path)
    assert name != media.generated_image_name('/other/작품/작품 04권.cbz')
    assert name != media.generated_image_name(path, 'external')
    assert '작품_배너_' in media.generated_image_name(path, 'banner', content=b'a')
    assert media.generated_image_name(path, 'banner', content=b'a') != media.generated_image_name(path, 'banner', content=b'b')
    assert media.generated_file(name)
    assert '_12화_' in media.generated_image_name('/book/작품/작품12화.cbz')


def test_safe_filename_and_length():
    name = media.generated_image_name('/x/04.cbz', series_name='한'*200 + ':?*#')
    assert len(name.encode()) < 255
    assert not any(c in name for c in ':?*#/\\')
    assert name.startswith('한'*10 + '_04권_')


def test_truncated_series_keep_distinct_identity():
    prefix = '가나다라마바사아자차'
    first = media.generated_image_name('/books/a/01권.cbz', series_name=prefix+'첫작품')
    second = media.generated_image_name('/books/b/01권.cbz', series_name=prefix+'다른작품')
    assert first.startswith(prefix+'_01권_')
    assert second.startswith(prefix+'_01권_')
    assert first != second


def test_plugin_url_key_uses_real_title_and_preserves_volume_after_truncation():
    key = 'rabbit_plugins:url-cover:https://img.ridicdn.net/cover/2066001321/xxlarge#1'
    name = media.generated_image_name(key, 'external', series_name='긴 작품명'*60, book_title='작품 04권 (교보)')
    assert name.startswith('긴 작품명') and '_04권__bo_external_' in name
    assert '2066001321' not in name and len(name.encode()) < 255
    assert '_1권' not in media.generated_image_name(key, 'external')
    for volume in range(1, 5):
        assert f'_{volume:02}권_' in media.generated_image_name(key, 'external', series_name='작품', book_title=f'작품 {volume:02}권')


@pytest.fixture
def covers(tmp_path, monkeypatch):
    monkeypatch.setattr(media, 'get_covers_dir', lambda: str(tmp_path))
    folder = tmp_path/'15'
    folder.mkdir()
    return folder


def test_deleted_category_cleans_unreferenced_only(covers):
    (covers/'keep.webp').write_bytes(b'a')
    (covers/'old.webp').write_bytes(b'b')
    result = media.cleanup_library_images(15, True, 0, ({'15/keep.webp'}, set()))
    assert result == ['15/old.webp']
    assert (covers/'keep.webp').exists()


def test_same_id_in_other_database_protects_unknown_files(covers):
    (covers/'manual.png').write_bytes(b'a')
    assert media.cleanup_library_images(15, True, 0, (set(), {'15'})) == []


def test_startup_cleanup_keeps_recent_and_referenced_images(covers, monkeypatch, capsys):
    names = [media.generated_image_name('/books/' + str(i)) for i in range(3)]
    for name in names:
        (covers/name).write_bytes(b'image')
    old = time.time() - 90000
    for name in names[:2]:
        os.utime(covers/name, (old, old))
    monkeypatch.setattr(media, 'reference_snapshot', lambda: ({'15/' + names[1]}, {'15'}))
    assert media.cleanup_generated_images() == ['15/' + names[0]]
    assert (covers/names[1]).exists()
    assert (covers/names[2]).exists()
    assert 'removed 1 files' in capsys.readouterr().out


def test_startup_cleanup_database_failure_keeps_images(covers, monkeypatch):
    name = media.generated_image_name('/books/old')
    (covers/name).write_bytes(b'image')
    os.utime(covers/name, (0, 0))
    def unavailable():
        raise RuntimeError('database unavailable')
    monkeypatch.setattr(media, 'reference_snapshot', unavailable)
    media.cleanup_generated_images()
    assert (covers/name).exists()


def test_background_grace_period_manual_files_and_symlink(covers, tmp_path):
    name = media.generated_image_name('/book/작품/04권.cbz')
    recent = covers/name
    recent.write_bytes(b'a')
    (covers/'manual.png').write_bytes(b'b')
    original = tmp_path/'original.txt'
    original.write_text('keep')
    (covers/('book_' + 'a'*32 + '.webp')).symlink_to(original)
    assert media.cleanup_library_images(15, snapshot=(set(), set())) == []
    os.utime(recent, (0, time.time()-90000))
    assert media.cleanup_library_images(15, snapshot=(set(), set())) == ['15/'+name]
    assert original.read_text() == 'keep'


def test_failed_reference_check_never_deletes(covers, monkeypatch):
    item = covers/('banner_' + 'a'*32 + '.webp')
    item.write_bytes(b'keep')
    monkeypatch.setattr(media, 'reference_snapshot', lambda: (_ for _ in ()).throw(RuntimeError('DB unavailable')))
    with pytest.raises(RuntimeError):
        media.cleanup_library_images(15, True, 0)
    assert item.exists()


def test_reference_paths_with_browser_prefix():
    assert media.normalized_reference('/covers/15/작품.webp?t=2') == '15/작품.webp'
    assert media.normalized_reference('https://external/15/pic.webp') is None


@pytest.mark.skipif(os.getenv('BOOKOASIS_TEST_WATCH_DB') != '1', reason='disposable database only')
def test_snapshot_protects_other_db_and_plugin_preferences():
    import database
    import json
    database.init_databases()
    with database.connection('adult') as conn:
        conn.execute('INSERT OR REPLACE INTO settings (`key`,value) VALUES (?,?)',
                     ('test_image_preferences', json.dumps({'book': {'path': '15/preferred.webp'}})))
        conn.execute('INSERT OR REPLACE INTO settings (`key`,value) VALUES (?,?)',
                     ('rabbit_plugins:external-cover-preferences:v1',
                      json.dumps({'999999999': {'path': '17/deleted-book.webp'}})))
        conn.commit()
    refs, _ = media.reference_snapshot()
    assert '15/preferred.webp' in refs
    assert '17/deleted-book.webp' not in refs

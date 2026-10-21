"""Selected upstream fixes against disposable data; never production libraries."""
import contextlib
import importlib
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from tools.scanner import core, engine
from services import video_scanner, audiobook_scanner


class DialectConnection:
    """Exercise both repository SQL dialects on the same disposable fixture."""
    def __init__(self, conn): self.conn = conn
    def cursor(self): return self
    def execute(self, sql, args=()):
        self.cur = self.conn.execute(sql.replace('%s', '?'), args)
        return self
    def fetchall(self): return self.cur.fetchall()
    def fetchone(self): return self.cur.fetchone()
    @property
    def lastrowid(self): return self.cur.lastrowid
    @property
    def rowcount(self): return self.cur.rowcount
    def commit(self): self.conn.commit()
    def rollback(self): self.conn.rollback()
    def close(self): pass


class FolderScopeTests(unittest.TestCase):
    def test_partial_query_has_literal_folder_boundary_and_full_scan_still_reads_all(self):
        with sqlite3.connect(':memory:') as conn:
            conn.execute('CREATE TABLE folder_mtimes(folder_path TEXT PRIMARY KEY,dir_mtime REAL,meta_mtime REAL)')
            paths = ['/books/A%_!', '/books/A%_!/one', '/books/A%_! 외전', '/books/AxxZ/one', '/other/two']
            conn.executemany('INSERT INTO folder_mtimes VALUES(?,1,2)', [(p,) for p in paths])
            cursor = conn.cursor()
            engine._load_folder_mtimes(cursor, '/books/A%_!/')
            self.assertEqual({r[0] for r in cursor.fetchall()}, set(paths[:2]))
            engine._load_folder_mtimes(cursor)
            self.assertEqual(len(cursor.fetchall()), len(paths))

    def test_file_input_aligns_traversal_scope_and_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            book = Path(folder)/'a.epub'; book.touch()
            for scope in (None, str(book)):
                with self.subTest(scope=scope), \
                     patch.object(core.database, 'get_connection', return_value=MagicMock()), \
                     patch.object(core, '_scan_library_internal') as scan, \
                     patch.object(core, 'trigger_vfs_refresh') as refresh, \
                     patch.object(core, '_save_report_unless_saved'), \
                     patch.object(core, 'is_remote_path', return_value=False):
                    core.scan_library_path('/tmp/media_general.db', 1, str(book), path_scope=scope, allow_missing=False)
                    self.assertEqual(scan.call_args.args[3], folder)
                    self.assertEqual(scan.call_args.kwargs['path_scope'], folder)
                    self.assertFalse(scan.call_args.kwargs['allow_missing'])
                    refresh.assert_called_once_with('/tmp/media_general.db', 1, folder)

    def test_missing_file_does_not_turn_into_a_parent_scan(self):
        with patch.object(core, '_scan_library_internal') as scan:
            with self.assertRaises(FileNotFoundError):
                core.scan_library_path('/tmp/media_general.db', 1, '/nonexistent/disposable-file.epub')
            scan.assert_not_called()


class VideoScanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = temporary.name
        self.course = str(Path(self.folder)/'course'); Path(self.course).mkdir()
        Path(self.course, '1.mp4').write_bytes(b'one')

    def run_scan(self, signatures, **kwargs):
        from repositories.video_repository import VideoRepository
        with patch.object(VideoRepository, 'get_folder_paths', return_value=[self.course]), \
             patch.object(VideoRepository, 'get_episode_signatures', return_value={self.course:signatures}), \
             patch.object(video_scanner, 'scan_and_save_video_folder', return_value=7) as scan:
            count = video_scanner.scan_video_library(self.folder, library_id=1, **kwargs)
            return count, scan.call_count

    def test_unchanged_skips(self): self.assertEqual(self.run_scan({('1.mp4',3)}), (0,0))
    def test_added_episode_reprocesses(self):
        Path(self.course, '2.MKV').write_bytes(b'two')
        self.assertEqual(self.run_scan({('1.mp4',3)}), (1,1))
    def test_removed_episode_reprocesses(self): self.assertEqual(self.run_scan({('1.mp4',3),('2.mp4',3)}),(1,1))
    def test_renamed_episode_reprocesses(self): self.assertEqual(self.run_scan({('old.mp4',3)}),(1,1))
    def test_resized_episode_reprocesses(self): self.assertEqual(self.run_scan({('1.mp4',4)}),(1,1))
    def test_force_still_reprocesses(self): self.assertEqual(self.run_scan({('1.mp4',3)},force=True),(1,1))
    def test_cancel_is_preserved(self):
        event=threading.Event();event.set()
        self.assertEqual(self.run_scan({('1.mp4',3)},cancel_event=event),(0,0))
    def test_default_audio_signature_unchanged(self):
        Path(self.course, 'sound.mp3').write_bytes(b'audio')
        self.assertEqual(set(audiobook_scanner._audio_signature(self.course)), {('sound.mp3',5)})
        self.assertEqual(set(audiobook_scanner._audio_signature(self.course,video_scanner.VIDEO_EXTENSIONS)), {('1.mp4',3)})


class RepositoryTests(unittest.TestCase):
    def test_video_rescan_keeps_existing_episode_id_and_watch_progress(self):
        from services.db_migration_service import _SCHEMA_SQL
        from repositories.sqlite.video_repository import VideoRepository
        with sqlite3.connect(':memory:') as conn:
            conn.row_factory=sqlite3.Row
            conn.executescript(_SCHEMA_SQL)
            meta=dict(title='course',sort_title='course',web_id='',genres='',poster='',backdrop='',premiered='',
                      description='',folder_name='course',folder_path='/course',total_duration=100,total_episodes=1)
            episode=dict(episode_number=1,episode_code='',title='one',filename='1.mp4',file_path='/course/1.mp4',
                         file_mtime=10,file_size=3,duration=100,width=1920,height=1080,premiered='',format='mp4',subtitle_path='')
            with patch('database.get_connection',return_value=DialectConnection(conn)):
                # save_video_scan uses lastrowid and rowcount from its cursor.
                first=VideoRepository.save_video_scan('/course',None,meta,[episode])
                old_id=conn.execute('SELECT id FROM video_episodes').fetchone()[0]
                conn.execute('INSERT INTO video_episode_progress(video_id,episode_id,user_id,current_time,progress_pct) VALUES(?,?,1,42,42)',(first['video_id'],old_id))
                conn.commit()
                second=VideoRepository.save_video_scan('/course',None,{**meta,'total_episodes':2},[episode,{**episode,'episode_number':2,'title':'two','filename':'2.mp4','file_path':'/course/2.mp4'}])
            self.assertEqual(second['video_id'],first['video_id'])
            self.assertEqual(second['episode_inserts'],1)
            self.assertEqual(conn.execute("SELECT id FROM video_episodes WHERE filename='1.mp4'").fetchone()[0],old_id)
            self.assertEqual(conn.execute('SELECT "current_time" FROM video_episode_progress WHERE episode_id=?',(old_id,)).fetchone()[0],42)

    def test_episode_signatures_filter_library_for_both_dialects(self):
        for dialect in ('sqlite','mariadb'):
            module=importlib.import_module(f'repositories.{dialect}.video_repository')
            with self.subTest(dialect=dialect), sqlite3.connect(':memory:') as conn:
                conn.row_factory=sqlite3.Row
                conn.executescript("CREATE TABLE videos(id INTEGER,library_id INTEGER,folder_path TEXT);"
                    "CREATE TABLE video_episodes(video_id INTEGER,file_path TEXT,file_size INTEGER);"
                    "INSERT INTO videos VALUES(1,1,'/course'),(2,2,'/other');"
                    "INSERT INTO video_episodes VALUES(1,'/course/sub/one.mp4',3),(2,'/other/two.mp4',4);")
                @contextlib.contextmanager
                def connection(*_): yield DialectConnection(conn)
                with patch.object(module.database,'connection',connection):
                    self.assertEqual(module.VideoRepository.get_episode_signatures(1),{'/course':{('sub/one.mp4',3)}})
                    self.assertEqual(len(module.VideoRepository.get_episode_signatures()),2)

    def test_category_task_cleanup_does_not_touch_similar_ids_or_other_sessions(self):
        for dialect in ('sqlite','mariadb'):
            module=importlib.import_module(f'repositories.{dialect}.category_repository')
            with self.subTest(dialect=dialect), sqlite3.connect(':memory:') as conn:
                conn.row_factory=sqlite3.Row
                tables={'user_category_permissions':'library_id INTEGER','series':'library_id INTEGER',
                    'audiobook_progress':'audiobook_id INTEGER,current_track_id INTEGER',
                    'audiobook_tracks':'id INTEGER,audiobook_id INTEGER','audiobooks':'id INTEGER,library_id INTEGER',
                    'videos':'id INTEGER,library_id INTEGER','video_episodes':'video_id INTEGER',
                    'video_progress':'video_id INTEGER','video_episode_progress':'video_id INTEGER',
                    'books':'id INTEGER,library_id INTEGER','libraries':'id INTEGER,physical_path TEXT',
                    'folder_mtimes':'folder_path TEXT','scanner_progress':'library_id TEXT','scanner_tasks':'task_key TEXT'}
                tables.update({t:'book_id INTEGER' for t in ['book_offsets','user_progress','user_reading_log','user_favorites','tts_progress']})
                for name,cols in tables.items(): conn.execute(f'CREATE TABLE {name}({cols})')
                keys=['library_scan_general_1','cover_scan_general_1','lazy_scan_library_general_1',
                      'library_scan_general_11','library_scan_general_21','library_scan_adult_1','folder_watch_x1']
                conn.executemany('INSERT INTO scanner_tasks VALUES(?)',[(k,) for k in keys]);conn.commit()
                with patch.object(module.database,'get_connection',return_value=DialectConnection(conn)):
                    module.CategoryRepository.delete_library('general',1)
                self.assertEqual({r[0] for r in conn.execute('SELECT task_key FROM scanner_tasks')},set(keys[3:]))


if __name__=='__main__': unittest.main()

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import FIELDS, Library, scan_track
from writer import write_track, payload_hash
from mutagen.mp3 import MP3
from mutagen.id3 import TXXX

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio_fixture import make_mp3

class WriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.mp3'
        make_mp3(self.source)
        audio = MP3(self.source)
        audio.tags.delall('TCON')
        audio.tags.add(TXXX(encoding=3, desc='DJ note', text=['Keep this']))
        audio.save()
        self.row = scan_track(self.source)
        self.row.update(decision='accepted', manual={'title':'Test Title','artist':'Test Artist','genre':'House'})
        self.before = self.source.read_bytes()
        self.payload = payload_hash(self.source)

    def test_fill_missing_preserves_existing_and_custom_frames(self):
        self.row['manual'] = {'genre':'House'}
        result = write_track(self.row, {}, self.root/'backup', FIELDS)
        audio = MP3(self.source)
        self.assertEqual(str(audio.tags['TCON']), 'House')
        self.assertEqual(str(audio.tags['TIT2']), self.row['current']['title'])
        self.assertEqual(str(audio.tags['TXXX:DJ note']), 'Keep this')
        self.assertEqual(payload_hash(self.source), self.payload)
        self.assertEqual(Path(result['backup']).read_bytes(), self.before)
        self.assertEqual(scan_track(self.source)['has_cover'], self.row['has_cover'])

    def test_overwrite_and_rename(self):
        result = write_track(self.row, {'overwrite':True,'rename':True}, self.root/'backup', FIELDS)
        destination = self.root/'Test Artist - Test Title.mp3'
        self.assertFalse(self.source.exists())
        self.assertEqual(result['path'], str(destination))
        self.assertEqual(str(MP3(destination).tags['TIT2']), 'Test Title')
        self.assertEqual(payload_hash(destination), self.payload)

    def test_collision_leaves_both_files_unchanged(self):
        destination = self.root/'Test Artist - Test Title.mp3'
        destination.write_bytes(b'Other file')
        with self.assertRaises(ValueError):
            write_track(self.row, {'overwrite':True,'rename':True}, self.root/'backup', FIELDS)
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertEqual(destination.read_bytes(), b'Other file')

    def test_changed_file_is_rejected(self):
        self.source.write_bytes(self.before+b'x')
        with self.assertRaises(ValueError):
            write_track(self.row, {'overwrite':True}, self.root/'backup', FIELDS)
        self.assertFalse((self.root/'backup').exists())

    def test_failed_verification_keeps_original(self):
        with patch('writer.payload_hash', side_effect=['before','different']):
            with self.assertRaises(ValueError):
                write_track(self.row, {'overwrite':True}, self.root/'backup', FIELDS)
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertFalse(list(self.root.glob('.tagpuliti-*')))

    def test_unapproved_review_cannot_be_written(self):
        lib = Library(self.root/'data')
        self.row.update(status='review', decision='pending')
        lib.state['rows']=[self.row]
        with self.assertRaises(ValueError):
            lib.write([self.row['id']])
        self.assertEqual(self.source.read_bytes(), self.before)

    def test_write_receipt_persists_original_path_and_blocks_rewrite(self):
        lib=Library(self.root/'data');lib.state['rows']=[self.row]
        lib.state['options']={'overwrite':True,'rename':True}
        lib.write([self.row['id']])
        import json
        manifest=json.loads(next((lib.data_dir/'backups').glob('*/manifest.json')).read_text())
        self.assertEqual(manifest['files'][0]['original'], str(self.source))
        self.assertEqual(len(manifest['files']),1)
        with self.assertRaises(ValueError):
            lib.write([self.row['id']])

    def test_safe_row_does_not_auto_accept_different_unsafe_candidate(self):
        lib=Library(self.root/'data')
        self.row.update(status='safe',decision='pending',selected=1,
                        candidates=[{'safe':True},{'safe':False}])
        lib.state['rows']=[self.row]
        with self.assertRaises(ValueError):
            lib.write([self.row['id']])
        self.assertEqual(self.source.read_bytes(), self.before)

    def test_deselection_survives_session_restore(self):
        lib=Library(self.root/'data');lib.state['rows']=[self.row]
        lib.include(self.row['id'],False)
        restored=Library(lib.data_dir);restored.restore()
        self.assertFalse(restored.state['rows'][0]['include'])

    def test_manual_override_works_with_fill_missing_policy(self):
        result=write_track(self.row, {}, self.root/'backup', FIELDS)
        self.assertEqual(str(MP3(self.source).tags['TIT2']), 'Test Title')
        self.assertEqual(payload_hash(self.source),self.payload)

    def test_keep_row_is_not_in_final_commit(self):
        lib=Library(self.root/'data');self.row['decision']='skipped';lib.state['rows']=[self.row]
        lib.state['options']={'overwrite':True,'rename':True};lib.commit()
        self.assertEqual(self.source.read_bytes(),self.before)
        self.assertFalse((lib.data_dir/'backups').exists())

    def test_cover_is_embedded_only_at_final_write_and_audio_is_preserved(self):
        import base64
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        lib=Library(self.root/'data');lib.state['rows']=[self.row]
        lib.upload_cover(self.row['id'],base64.b64encode(png).decode())
        self.assertEqual(self.source.read_bytes(),self.before)
        normalized=Path(self.row['local_cover']['path']).read_bytes()
        self.assertTrue(normalized.startswith(b'\xff\xd8\xff'))
        lib.commit()
        self.assertTrue(any(c.data==normalized and c.mime=='image/jpeg' and c.type==3 for c in MP3(self.source).tags.getall('APIC')))
        self.assertEqual(MP3(self.source).tags.version[:2],(2,3))
        self.assertEqual(payload_hash(self.source),self.payload)

    def test_cover_can_be_added_after_tags_have_already_been_written(self):
        import base64
        from review import describe
        lib=Library(self.root/'data');lib.state['rows']=[self.row]
        lib.commit();self.assertIn('write_result',self.row)
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        lib.upload_cover(self.row['id'],base64.b64encode(png).decode())
        self.assertNotIn('write_result',self.row)
        self.assertEqual(len(self.row['write_history']),1)
        self.assertTrue(describe(self.row,lib.state['options'])['will_write'])
        lib.commit()
        self.assertEqual(self.row['write_result']['fields'],['cover'])
        self.assertEqual(describe(self.row,lib.state['options'])['cover_status'],'embedded')
        self.assertEqual(payload_hash(self.source),self.payload)

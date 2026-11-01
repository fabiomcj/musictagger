import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Library, scan_track
sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio_fixture import make_mp3


class LibraryTests(unittest.TestCase):
    def test_scan_skips_backup_subdirectories_and_unsupported_formats(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'music';root.mkdir()
            (root / 'one.mp3').touch();(root / 'unsupported.flac').touch()
            backup = root / 'backup_originali';backup.mkdir();(backup / 'two.mp3').touch()
            with patch('app.scan_track', side_effect=lambda p: {'path': str(p)}):
                lib = Library(Path(directory) / 'data');lib.scan(str(root))
            self.assertEqual(len(lib.state['rows']), 1)
            self.assertEqual(lib.state['skipped'], {'.flac': 1})

    def test_corrupted_file_does_not_stop_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'music';root.mkdir();(root / 'bad.mp3').write_bytes(b'not mp3')
            lib = Library(Path(directory) / 'data');lib.scan(str(root))
            self.assertEqual(lib.state['rows'], [])
            self.assertEqual(len(lib.state['errors']), 1)
            self.assertEqual((root / 'bad.mp3').read_bytes(), b'not mp3')

    def test_decisions_persist_without_writing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / 'song.mp3';original.write_bytes(b'original')
            lib = Library(Path(directory) / 'data')
            lib.state['rows'] = [{'id': 'test', 'path': str(original), 'candidates': [], 'manual': {}}]
            lib.decide('test', 0, 'accepted', {'title': 'My Song'})
            self.assertEqual(original.read_bytes(), b'original')
            saved = json.loads((lib.data_dir / 'last-session.json').read_text())
            self.assertEqual(saved['rows'][0]['manual']['title'], 'My Song')
            restored = Library(lib.data_dir);restored.restore()
            self.assertEqual(restored.state['rows'][0]['decision'], 'accepted')

    def test_invalid_candidate_index_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            lib = Library(directory);lib.state['rows'] = [{'id': 'test', 'candidates': [{}]}]
            with self.assertRaises(ValueError):
                lib.decide('test', 4, 'accepted', {})

    def test_scan_mp3_files_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / 'music';original.mkdir()
            files = [make_mp3(original / ('track-%d.mp3' % i)) for i in range(3)]
            before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
            lib = Library(Path(directory) / 'data');lib.scan(str(original))
            self.assertEqual(len(lib.state['rows']), len(files))
            self.assertTrue(all(r['current']['title'] and r['current']['artist'] for r in lib.state['rows']))
            self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files})

    def test_filename_remix_overrides_incorrect_original_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = make_mp3(Path(directory) / 'Song (DJ Extended Remix) (128kbit_AAC).mp3', title='Song')
            row = scan_track(reference)
            self.assertEqual(row['identity']['title'], 'Song (DJ Extended Remix)')
            self.assertTrue(row['identity']['conflict'])


if __name__ == '__main__':
    unittest.main()

import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matching import clean_filename, filename_identity, rank_candidates, version, base_title


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.row = {'identity': {'title': 'Good Life (Extended Mix)', 'artist': 'Inner City, LOSTBOYJAY',
                                 'artist_origin': 'filename', 'conflict': False}, 'duration': 331}
        self.candidate = {'kind': 'song', 'trackId': 1, 'trackName': 'Good Life (Extended Mix)',
                          'artistName': 'Inner City & LOSTBOYJAY', 'collectionName': 'Good Life',
                          'trackTimeMillis': 331000, 'releaseDate': '2026-08-21T00:00:00Z'}

    def rank(self, candidate=None, row=None):
        return rank_candidates(row or self.row, [candidate or self.candidate])[0]

    def test_correct_match(self):
        self.assertTrue(self.rank()['safe'])

    def test_wrong_artist_even_with_same_title_and_duration(self):
        wrong = dict(self.candidate, artistName='Summer Is Calling, Inner City')
        self.assertFalse(self.rank(wrong)['safe'])

    def test_wrong_mix_with_same_duration(self):
        wrong = dict(self.candidate, trackName='Good Life (Radio Edit)')
        self.assertFalse(self.rank(wrong)['safe'])

    def test_no_artist_is_never_safe(self):
        row = copy.deepcopy(self.row);row['identity']['artist'] = ''
        self.assertFalse(self.rank(row=row)['safe'])

    def test_duration_mismatch(self):
        self.assertFalse(self.rank(dict(self.candidate, trackTimeMillis=268000))['safe'])

    def test_conflicting_existing_tags(self):
        row = copy.deepcopy(self.row);row['identity']['conflict'] = True
        self.assertFalse(self.rank(row=row)['safe'])

    def test_topic_author_can_omit_collaborators(self):
        row = copy.deepcopy(self.row);row['identity']['artist_origin'] = 'youtube_topic'
        self.assertFalse(self.rank(row=row)['safe'])

    def test_competing_albums(self):
        candidates = rank_candidates(self.row, [self.candidate, dict(self.candidate, trackId=2, collectionName='Compilation')])
        self.assertFalse(candidates[0]['safe'])

    def test_same_record_deduplicates(self):
        self.assertEqual(len(rank_candidates(self.row, [self.candidate, self.candidate])), 1)

    def test_unrelated_title_excluded(self):
        self.assertEqual(rank_candidates(self.row, [dict(self.candidate, trackName='XYZ 123')]), [])

    def test_filename_preserves_remix_and_removes_encoding(self):
        self.assertEqual(clean_filename('Slap Of Mine (Dompe Extended Remix) (128kbit_AAC).mp3'), 'Slap Of Mine (Dompe Extended Remix)')
        artist, title = filename_identity('Crusy - Rising (Original Mix) [BOTANIQ] (128kbit_AAC).mp3')
        self.assertEqual((artist, title), ('Crusy', 'Rising (Original Mix)'))

    def test_quoted_filename(self):
        self.assertEqual(filename_identity('EASTTOWN \'Adumu\' (152kbit_Opus).mp3'), ('EASTTOWN', 'Adumu'))

    def test_remixers_are_not_interchangeable(self):
        self.assertNotEqual(version('Song (Dompe Remix)'), version('Song (Capri Remix)'))

    def test_meaningful_parenthetical_title_is_preserved(self):
        self.assertNotEqual(base_title('(I Just) Died In Your Arms'), base_title('Died In Your Arms'))

    def test_missing_duration_not_safe(self):
        self.assertFalse(self.rank(dict(self.candidate, trackTimeMillis=0))['safe'])

    def test_reissue_album_not_safe_even_with_exact_recording(self):
        row = copy.deepcopy(self.row);row['current'] = {'album': 'Original Album'}
        self.assertFalse(self.rank(row=row)['safe'])

    def test_store_album_suffix_does_not_create_a_conflict(self):
        row = copy.deepcopy(self.row);row['current'] = {'album': 'Good Life'}
        self.assertTrue(self.rank(dict(self.candidate, collectionName='Good Life - Single'),row)['safe'])


if __name__ == '__main__':
    unittest.main()

import json
import secrets
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Handler, Library, FIELDS


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.library = Library(cls.temp.name)
        cls.server.token = secrets.token_urlsafe(32)
        cls.url = 'http://127.0.0.1:%d' % cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.temp.cleanup()

    def request(self, path, data=None, headers=None):
        request = urllib.request.Request(self.url + path,
            data=json.dumps(data).encode() if data is not None else None, headers=headers or {})
        try:
            return urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as exc:
            return exc

    def test_local_page_available(self):
        response = self.request('/')
        self.assertEqual(response.status, 200)
        self.assertIn(b'TagPuliti', response.read())
        self.assertIn('frame-ancestors', response.headers['Content-Security-Policy'])

    def test_unknown_path_and_arbitrary_cover_rejected(self):
        self.assertEqual(self.request('/cover/../../etc/passwd').status, 404)
        self.assertEqual(self.request('/app.py').status, 404)

    def test_post_requires_token(self):
        self.assertEqual(self.request('/api/cancel', {}).status, 403)

    def test_foreign_origin_rejected_even_with_token(self):
        response = self.request('/api/cancel', {}, {'X-TagPuliti-Token': self.server.token, 'Origin': 'https://example.org'})
        self.assertEqual(response.status, 403)

    def test_foreign_host_rejected(self):
        self.assertEqual(self.request('/api/state', headers={'Host': 'attacker.invalid'}).status, 403)

    def test_export_preserves_fields_not_provided_by_catalog_and_neutralizes_formula(self):
        current = {field: '' for field in FIELDS};current['label'] = 'My Label'
        self.server.library.state['rows'] = [{'path': '=HYPERLINK("bad")', 'status': 'review', 'decision': 'pending',
            'current': current, 'manual': {}, 'selected': 0, 'candidates': [{'proposed': {'title': 'Song'}, 'url': ''}]}]
        response = self.request('/export.csv')
        self.assertEqual(response.status, 200)
        body = response.read().decode('utf-8-sig')
        self.assertIn("'=HYPERLINK", body)
        self.assertIn('label,My Label,My Label', body)
        self.server.library.state['rows'] = []


if __name__ == '__main__':
    unittest.main()

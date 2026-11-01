"""Public API adapters, bounded requests, persistent cache, no page scraping."""
import json
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path


class Catalog:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(exist_ok=True, parents=True)
        self.db = directory / 'catalog.sqlite3'
        self.lock = threading.Lock()
        self.last_apple = 0
        self.host_locks = {}
        self.last_request = {}
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE IF NOT EXISTS cache (url TEXT PRIMARY KEY, stamp REAL, body TEXT)')

    def get_json(self, url, cancelled=lambda: False):
        with sqlite3.connect(self.db) as db:
            entry = db.execute('SELECT stamp, body FROM cache WHERE url=?', (url,)).fetchone()
        if entry and time.time() - entry[0] < 7 * 86400:
            return json.loads(entry[1])
        host = urllib.parse.urlparse(url).hostname
        interval = {'itunes.apple.com':3.2, 'musicbrainz.org':1.1, 'api.deezer.com':.25}.get(host, .1)
        with self.lock:
            host_lock = self.host_locks.setdefault(host, threading.Lock())
        with host_lock:
            while time.monotonic() - self.last_request.get(host, 0) < interval:
                if cancelled():
                    raise InterruptedError('Ricerca interrotta')
                time.sleep(.1)
            self.last_request[host] = time.monotonic()
        if cancelled():
            raise InterruptedError('Ricerca interrotta')
        request = urllib.request.Request(url, headers={'User-Agent': 'TagPuliti/1.0 (local personal music tagger; https://musicbrainz.org/doc/MusicBrainz_API)'})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=12) as response:
                    payload = response.read(2_000_001)
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
                for _ in range((attempt + 1) * 20):
                    if cancelled():raise InterruptedError('Ricerca interrotta')
                    time.sleep(.1)
        if len(payload) > 2_000_000:
            raise ValueError('Risposta del catalogo troppo grande')
        body = json.loads(payload)
        if isinstance(body, dict) and body.get('error'):
            raise ValueError(str(body['error']))
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT OR REPLACE INTO cache VALUES (?, ?, ?)', (url, time.time(), json.dumps(body)))
        return body

    def search(self, term, country='IT', cancelled=lambda: False):
        url = 'https://itunes.apple.com/search?' + urllib.parse.urlencode(
            {'term': term, 'entity': 'song', 'media': 'music', 'limit': 25, 'country': country})
        return self.get_json(url, cancelled).get('results', [])

    def youtube(self, source, cancelled=lambda: False):
        parsed = urllib.parse.urlparse(source)
        if parsed.hostname in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
            vid = urllib.parse.parse_qs(parsed.query).get('v', [''])[0]
        elif parsed.hostname == 'youtu.be':
            vid = parsed.path.lstrip('/').split('/')[0]
        else:
            return None
        if len(vid) != 11 or not all(c.isalnum() or c in '_-' for c in vid):
            return None
        canonical = 'https://www.youtube.com/watch?v=' + vid
        url = 'https://www.youtube.com/oembed?' + urllib.parse.urlencode({'url': canonical, 'format': 'json'})
        return self.get_json(url, cancelled)

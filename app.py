#!/usr/bin/env python3
"""TagPuliti: preview, review and backed-up metadata writes."""
import argparse
import base64
import hashlib
import csv
import io
import json
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mutagen.mp3 import MP3
from writer import write_track, proposal
from review import FIELDS, describe
from research import Research, image_mime, download_cover
from covers import normalize_image, artwork_matches
from catalog import Catalog
from matching import filename_identity, normalize, rank_candidates, similarity, base_title, version

ROOT = Path(__file__).resolve().parent

def scan_track(path):
    audio = MP3(path)
    tags = audio.tags
    current = {name: str(tags.get(frame, '')) if tags else '' for name, frame in FIELDS.items()}
    sources = []
    if tags:
        for frame in tags.values():
            if getattr(frame, 'url', None):
                sources.append(frame.url)
            for text in getattr(frame, 'text', []):
                sources.extend(re.findall(r'https?://[^\s<>]+', str(text)))
    filename_artist, filename_title = filename_identity(path.name)
    # Filename mix names are retained even when older tags point to an original.
    artist = current['artist'] or filename_artist
    title = current['title'] or filename_title
    if filename_artist or (version(filename_title) and
                           base_title(filename_title) == base_title(current['title'])):
        title = filename_title
    conflict = bool(filename_artist and current['artist'] and
                    similarity(filename_artist, current['artist']) < .90)
    if (current['title'] and version(filename_title) and
            base_title(filename_title) == base_title(current['title']) and
            version(filename_title) != version(current['title'])):
        conflict = True
    issues = []
    for name, label in [('title', 'Titolo'), ('artist', 'Artista'), ('album', 'Album'), ('genre', 'Genere')]:
        if not current[name]:
            issues.append(label + ' mancante')
    if not tags or not tags.getall('APIC'):
        issues.append('Copertina mancante')
    if tags and tags.getall('USLT'):
        issues.append('Testo presente: da verificare, non verrà eliminato automaticamente')
    if conflict:
        issues.append('Nome del file e tag esistenti non concordano')
    if current['title'] and normalize(current['title']) != normalize(filename_title):
        issues.append('Titolo nei tag diverso dal nome del file: controllare la versione')
    stat = path.stat()
    return {'id': secrets.token_hex(8), 'path': str(path), 'filename': path.name,
            'current': current, 'duration': round(audio.info.length, 3),
            'bitrate': round(audio.info.bitrate / 1000),
            'has_cover': bool(tags and tags.getall('APIC')), 'issues': issues,
            'sources': list(dict.fromkeys(sources)),
            'identity': {'artist': artist, 'title': title,
                         'artist_origin': 'tags' if current['artist'] else 'filename', 'conflict': conflict},
            'snapshot': {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns},
            'status': 'pending', 'candidates': [], 'error': '', 'decision': 'pending', 'selected': 0,
            'manual': {}}


class Library:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.catalog = Catalog(self.data_dir)
        self.researcher = Research(self.catalog, self.data_dir)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.busy = False
        self.revision = 0
        self.state = {'folder': '', 'rows': [], 'phase': 'idle', 'done': 0, 'total': 0,
                      'step': 1, 'options': {'country': 'IT', 'overwrite': False, 'rename': False}, 'errors': [], 'skipped': {}, 'message': 'Scegli una cartella per iniziare.'}

    def snapshot(self):
        with self.lock:
            result = deepcopy(self.state)
            result['version'] = '1.0'
            for row in result['rows']:
                row['review'] = describe(row, result.get('options', {}))
            return result

    def summary(self):
        with self.lock:
            return {'phase': self.state['phase'], 'done': self.state['done'],
                    'total': self.state['total'], 'rows': len(self.state['rows']),
                    'revision': self.revision, 'message': self.state.get('message', '')}

    def start(self, action, **kwargs):
        with self.lock:
            if self.busy:
                raise ValueError('È già in corso un’operazione. Attendi o interrompila.')
            if action == 'search' and not self.state['rows']:
                raise ValueError('Prima scegli e analizza una cartella.')
            self.busy = True
            self.stop.clear()
            self.state['phase'] = action
            self.state['done'] = 0
            self.state['message'] = {'scan': 'Lettura dei file…', 'search': 'Ricerca delle pubblicazioni…', 'write': 'Preparazione dei backup e scrittura dei tag…', 'commit': 'Preparazione dei backup e scrittura dei tag…'}.get(action, '')
        threading.Thread(target=self.run, args=(action, kwargs), daemon=True).start()

    def run(self, action, kwargs):
        try:
            if action == 'scan':
                self.scan(**kwargs)
                self.state['step'] = 2 if self.state['rows'] else 1
            elif action == 'search':
                self.search(**kwargs)
                self.state['step'] = 4
            elif action == 'write':
                self.write(**kwargs)
            elif action == 'commit':
                self.commit()
        except Exception as exc:
            with self.lock:
                self.state['errors'].append(str(exc))
                self.state['message'] = 'Operazione non completata: ' + str(exc)
        finally:
            with self.lock:
                if action == 'search':
                    self.state['step'] = 4
                self.state['phase'] = 'cancelled' if self.stop.is_set() else 'ready'
                self.busy = False
                self.persist()

    def scan(self, folder, recursive=True):
        path = Path(folder).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError('Il percorso deve essere una cartella.')
        if path == Path('/'):
            raise ValueError('Scegli una cartella musicale specifica.')
        paths, skipped, errors = [], {}, []
        def walk_error(error):
            errors.append(str(error))
        for directory, dirs, files in os.walk(path, onerror=walk_error, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith('.') and
                             not re.search(r'backup|tagpuliti', d, re.I)) if recursive else []
            for name in sorted(files):
                f = Path(directory) / name
                if f.is_symlink():
                    continue
                suffix = f.suffix.lower()
                if suffix == '.mp3':
                    paths.append(f)
                elif suffix in ('.m4a', '.flac', '.aif', '.aiff', '.wav'):
                    skipped[suffix] = skipped.get(suffix, 0) + 1
            if self.stop.is_set():
                break
        with self.lock:
            self.state.update(folder=str(path), rows=[], total=len(paths), done=0,
                              errors=errors, skipped=skipped, message='Lettura dei file musicali…')
        for i, f in enumerate(paths):
            if self.stop.is_set():
                break
            try:
                row = scan_track(f)
                with self.lock:
                    self.state['rows'].append(row)
            except Exception as exc:
                with self.lock:
                    self.state['errors'].append('%s: %s' % (f.name, exc))
            with self.lock:
                self.state['done'] = i + 1
        with self.lock:
            self.state['message'] = '%d MP3 letti. Puoi avviare la ricerca online.' % len(self.state['rows'])

    def search(self, country='IT', only_unresolved=False, overwrite=False, rename=False,
               providers=None, depth='world', covers=True):
        providers = ['apple','musicbrainz','deezer'] if providers is None else providers
        if (not isinstance(providers,list) or not providers or
                any(p not in ('apple','musicbrainz','deezer') for p in providers)):
            raise ValueError('Seleziona almeno una fonte di ricerca valida.')
        if depth not in ('quick','world','deep'):
            raise ValueError('Profondità della ricerca non valida.')
        options={'overwrite':overwrite,'rename':rename,'providers':providers,'depth':depth,'covers':covers}
        with self.lock:
            self.state.update(step=3,options=options)
            targets=[r for r in self.state['rows'] if not only_unresolved or r['status'] in ('pending','error','not_found')]
            self.state.update(total=len(targets),done=0,message='Ricerca mondiale su più cataloghi…')
        for index,row in enumerate(targets):
            if self.stop.is_set():break
            try:
                stat=Path(row['path']).stat()
                if {'size':stat.st_size,'mtime_ns':stat.st_mtime_ns} != row['snapshot']:
                    raise ValueError('Il file è cambiato dopo l’analisi. Leggi nuovamente la cartella.')
                def activity(source):
                    with self.lock:
                        self.state['message']='%d / %d · %s · %s' % (index+1,len(targets),row['filename'],source)
                # Existing YouTube links add identity hints, never a trusted automatic match.
                youtube_reports=[]
                if not row['identity']['artist']:
                    for source in row.get('sources',[]):
                        if 'youtube.com/' in source or 'youtu.be/' in source:
                            try:
                                video=self.catalog.youtube(source,self.stop.is_set)
                                if video and video.get('author_name','').endswith(' - Topic'):
                                    row['identity'].update(artist=video['author_name'][:-8],artist_origin='youtube_topic')
                                youtube_reports.append({'name':'YouTube oEmbed','status':'ok','url':source})
                            except Exception as exc:
                                youtube_reports.append({'name':'YouTube oEmbed','status':'error','error':str(exc),'url':source})
                            break
                candidates,reports=self.researcher.search(row,options,self.stop.is_set,activity)
                with self.lock:
                    row.update(candidates=candidates,research=youtube_reports+reports,selected=0,decision='pending',
                               manual={},status=('safe' if candidates[0]['safe'] else 'review') if candidates else 'not_found',error='')
                    for key in ('write_result','local_cover','cover_choice'):
                        row.pop(key,None)
            except InterruptedError:
                break
            except Exception as exc:
                with self.lock:row.update(status='error',error=str(exc))
            with self.lock:
                self.state['done']=index+1
                self.persist()
        with self.lock:
            self.state['message']='Ricerca interrotta: i risultati già ottenuti sono disponibili.' if self.stop.is_set() else 'Ricerca completata. Correggi ciò che vuoi oppure lascia i brani come sono. Conferma solo quando vuoi scrivere i tag.'

    def commit(self):
        ids=[r['id'] for r in self.state['rows'] if describe(r,self.state.get('options',{}))['will_write']]
        if not ids:
            self.state['message']='Nessuna modifica da scrivere. I file sono già come richiesto.'
            return
        self.write(ids)

    def write(self, ids):
        if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)):
            raise ValueError('Seleziona almeno un brano, senza duplicati.')
        rows = {r['id']: r for r in self.state['rows']}
        targets = []
        for row_id in ids:
            row = rows.get(row_id)
            if not row or row.get('write_result') or not (row['decision'] == 'accepted' or
                    (row['decision'] == 'pending' and row['candidates'] and row['candidates'][row['selected']].get('safe'))):
                raise ValueError('Approva prima le proposte da controllare.')
            targets.append(row)
        backup_dir = self.data_dir / 'backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3))
        backup_dir.mkdir(parents=True)
        manifest = {'options': self.state.get('options', {}), 'planned': [{'id': r['id'], 'original': r['path'], 'backup': str(backup_dir / (r['id'] + '.mp3'))} for r in targets], 'files': [], 'errors': []}
        manifest_path = backup_dir / 'manifest.json'
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        self.state.update(total=len(targets), done=0, step=4)
        for index, row in enumerate(targets):
            if self.stop.is_set():
                break
            try:
                original_path = row['path']
                options = dict(self.state.get('options', {}))
                options['rename'] = describe(row, options)['rename']
                result = write_track(row, options, backup_dir, FIELDS)
                refreshed = scan_track(Path(result['path']))
                row.update(path=refreshed['path'], filename=refreshed['filename'],
                           current=refreshed['current'], snapshot=refreshed['snapshot'],
                           has_cover=refreshed['has_cover'], identity=refreshed['identity'], issues=refreshed['issues'], write_result=result, error='')
                manifest['files'].append(dict(id=row['id'], original=original_path, **result))
            except Exception as exc:
                row['error'] = str(exc)
                row['status'] = 'error'
                row['decision'] = 'pending'
                manifest['errors'].append({'file': row['path'], 'error': str(exc)})
            self.state['done'] = index + 1
            self.state['message'] = 'Scrittura e verifica: %d / %d' % (index + 1, len(targets))
            temporary_manifest = backup_dir / 'manifest.tmp'
            temporary_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
            temporary_manifest.replace(manifest_path)
            self.persist()
        self.state['message'] = 'Scrittura completata: %d file verificati, %d errori. Backup: %s' % (len(manifest['files']), len(manifest['errors']), backup_dir)

    def decide(self, row_id, selected, decision, manual):
        with self.lock:
            if self.busy:
                raise ValueError('Interrompi o attendi la ricerca prima di modificare le proposte.')
            row = next((r for r in self.state['rows'] if r['id'] == row_id), None)
            if row is None:
                raise ValueError('Brano non trovato.')
            if decision not in ('pending', 'accepted', 'skipped'):
                raise ValueError('Scelta non valida.')
            if not isinstance(selected, int) or selected < 0 or (row['candidates'] and selected >= len(row['candidates'])):
                raise ValueError('Proposta non valida.')
            if not isinstance(manual, dict) or any(k not in FIELDS or not isinstance(v, str) or len(v) > 2000 for k, v in manual.items()):
                raise ValueError('Dati non validi.')
            if decision == 'accepted' and not row['candidates'] and not manual and not row.get('local_cover'):
                raise ValueError('Scegli una proposta o inserisci i dati.')
            if decision == 'accepted':self.reopen_written(row)
            row.update(selected=selected, decision=decision, manual=manual, include=decision!='skipped')
            if decision == 'accepted':
                row['error'] = ''
            self.persist()

    def reopen_written(self,row):
        if row.get('write_result'):
            row.setdefault('write_history',[]).append(row.pop('write_result'))

    def upload_cover(self, row_id, encoded):
        with self.lock:
            if self.busy:raise ValueError('Attendi la fine dell’operazione.')
            row=next((r for r in self.state['rows'] if r['id']==row_id),None)
            if not row:raise ValueError('Brano non trovato.')
            data=base64.b64decode(encoded,validate=True)
            if len(data)>5_000_000:raise ValueError('Copertina superiore a 5 MB.')
            cover=normalize_image(data,self.data_dir/'artwork','Immagine scelta manualmente')
            self.reopen_written(row)
            row.update(local_cover=cover,cover_choice='replace',decision='accepted')
            self.persist()

    def choose_cover(self,row_id,selected):
        with self.lock:
            if self.busy:raise ValueError('Attendi la fine dell’operazione.')
            row=next((r for r in self.state['rows'] if r['id']==row_id),None)
            if not row or not isinstance(selected,int) or not 0<=selected<len(row['candidates']):
                raise ValueError('Pubblicazione non valida.')
            cover=row['candidates'][selected].get('cover_file')
            if not cover:
                candidate=row['candidates'][selected]
                if not candidate.get('artwork'):raise ValueError('Questa pubblicazione non offre una copertina.')
                if not artwork_matches(row,candidate):raise ValueError('L’immagine appartiene a un brano o artista diverso. Scegli la pubblicazione corretta oppure un’immagine dal computer.')
                cover=download_cover(candidate['artwork'],self.data_dir/'artwork')
            self.reopen_written(row)
            row.update(local_cover=cover,cover_choice='replace',decision='accepted')
            self.persist()

    def include(self, row_id, included):
        with self.lock:
            if self.busy:
                raise ValueError('Attendi la fine dell’operazione.')
            row = next((r for r in self.state['rows'] if r['id'] == row_id), None)
            if row is None or not isinstance(included, bool):
                raise ValueError('Scelta non valida.')
            row['include'] = included
            self.persist()

    def persist(self):
        # Persist workflow, proposals and write receipts.
        self.revision += 1
        temporary = self.data_dir / 'last-session.tmp'
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.data_dir / 'last-session.json')

    def restore(self):
        with self.lock:
            if self.busy:
                raise ValueError('Attendi la fine dell’operazione.')
            path = self.data_dir / 'last-session.json'
            if not path.exists():
                raise ValueError('Non ci sono sessioni precedenti.')
            state = json.loads(path.read_text(encoding='utf-8'))
            state.setdefault('step', 4)
            if state['step'] == 3:
                state['step'] = 4
            state.setdefault('options', {'country': 'IT', 'overwrite': False, 'rename': False})
            state.update(phase='ready', message='Sessione precedente ripristinata. Puoi controllare e confermare le scelte.')
            self.state = state
            self.revision += 1


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, body, content_type='application/json; charset=utf-8', status=200, extra=None):
        body = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' https:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def allowed(self):
        return self.headers.get('Host') in ('127.0.0.1:%d' % self.server.server_port, 'localhost:%d' % self.server.server_port)

    def do_GET(self):
        if not self.allowed():
            return self.send('{}', status=403)
        route = urllib.parse.urlparse(self.path).path
        if route == '/':
            return self.send((ROOT / 'web/index.html').read_bytes(), 'text/html; charset=utf-8')
        if route in ('/app.js', '/style.css'):
            return self.send((ROOT / 'web' / route[1:]).read_bytes(), 'text/javascript; charset=utf-8' if route.endswith('js') else 'text/css; charset=utf-8')
        if route == '/api/state':
            return self.send(json.dumps(self.server.library.snapshot(), ensure_ascii=False))
        if route == '/api/status':
            return self.send(json.dumps(self.server.library.summary()))
        if route == '/api/config':
            return self.send(json.dumps({'token': self.server.token}))
        if route.startswith('/proposed-cover/'):
            row_id=route.rsplit('/',1)[-1]
            row=next((r for r in self.server.library.snapshot()['rows'] if r['id']==row_id),None)
            cover=(row.get('local_cover') or (row['candidates'][row['selected']].get('cover_file') if row.get('candidates') else None)) if row else None
            try:
                if cover:
                    path=Path(cover['path']).resolve()
                    if path.parent == (self.server.library.data_dir/'artwork').resolve():
                        return self.send(path.read_bytes(),cover['mime'])
            except Exception:pass
            return self.send('{}',status=404)
        if route.startswith('/cover/'):
            row_id = route.rsplit('/', 1)[-1]
            row = next((r for r in self.server.library.snapshot()['rows'] if r['id'] == row_id), None)
            try:
                covers = MP3(row['path']).tags.getall('APIC') if row else []
                cover = next((c for c in covers if c.type == 3), covers[0] if covers else None)
                if cover and cover.mime in ('image/jpeg', 'image/png') and len(cover.data) <= 10_000_000:
                    return self.send(cover.data, cover.mime)
            except Exception:
                pass
            return self.send('{}', status=404)
        if route in ('/export.json', '/export.csv'):
            state = self.server.library.snapshot()
            if route.endswith('json'):
                payload = json.dumps(state, ensure_ascii=False, indent=2)
                ct = 'application/json; charset=utf-8'
            else:
                output = io.StringIO()
                fields = ['file', 'status', 'decision', 'field', 'current', 'proposed', 'source']
                writer = csv.DictWriter(output, fields)
                writer.writeheader()
                def safe_cell(value):
                    text = str(value or '')
                    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text
                for row in state['rows']:
                    candidate = row['candidates'][row['selected']] if row['candidates'] else {}
                    proposed = proposal(row, state.get('options', {}).get('overwrite', False), FIELDS)
                    for field in FIELDS:
                        writer.writerow({k: safe_cell(v) for k, v in {
                            'file': row['path'], 'status': row['status'], 'decision': row['decision'],
                            'field': field, 'current': row['current'].get(field, ''),
                            'proposed': proposed.get(field, ''), 'source': candidate.get('url', '')}.items()})
                payload, ct = '\ufeff' + output.getvalue(), 'text/csv; charset=utf-8'
            return self.send(payload, ct, extra={'Content-Disposition': 'attachment; filename="TagPuliti.' + route.split('.')[-1] + '"'})
        self.send('{}', status=404)

    def do_POST(self):
        origin = self.headers.get('Origin')
        expected = 'http://' + self.headers.get('Host', '')
        if (not self.allowed() or origin not in (None, expected) or
                not secrets.compare_digest(self.headers.get('X-TagPuliti-Token', ''), self.server.token)):
            return self.send('{}', status=403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            maximum = 7_000_000 if urllib.parse.urlparse(self.path).path == '/api/cover' else 200_000
            if length < 0 or length > maximum:
                raise ValueError('Richiesta troppo grande.')
            data = json.loads(self.rfile.read(length) or b'{}')
            route = urllib.parse.urlparse(self.path).path
            lib = self.server.library
            if route == '/api/folder':
                chosen = subprocess.run(['osascript', '-e', 'POSIX path of (choose folder with prompt "Scegli la cartella dei brani")'], capture_output=True, text=True, timeout=120)
                return self.send(json.dumps({'folder': chosen.stdout.strip() if chosen.returncode == 0 else ''}))
            if route == '/api/scan':
                lib.start('scan', folder=data['folder'], recursive=bool(data.get('recursive', True)))
            elif route == '/api/search':
                lib.start('search', country=data.get('country', 'IT'), only_unresolved=bool(data.get('only_unresolved', True)), overwrite=bool(data.get('overwrite', False)), rename=bool(data.get('rename', False)), providers=data.get('providers'), depth=data.get('depth','world'), covers=bool(data.get('covers',True)))
            elif route == '/api/commit':
                lib.start('commit')
            elif route == '/api/cover-candidate':
                lib.choose_cover(data['id'],data.get('selected',0))
            elif route == '/api/cover':
                lib.upload_cover(data['id'],data['image'])
            elif route == '/api/write':
                lib.start('write', ids=data.get('ids', []))
            elif route == '/api/cancel':
                lib.stop.set()
            elif route == '/api/decision':
                lib.decide(data['id'], data.get('selected', 0), data['decision'], data.get('manual', {}))
            elif route == '/api/include':
                lib.include(data['id'], data.get('included'))
            elif route == '/api/restore':
                lib.restore()
            else:
                return self.send('{}', status=404)
            self.send('{"ok":true}')
        except subprocess.TimeoutExpired:
            self.send(json.dumps({'error': 'Selezione della cartella scaduta. Riprova.'}), status=400)
        except Exception as exc:
            self.send(json.dumps({'error': str(exc)}, ensure_ascii=False), status=400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.library = Library(ROOT / '.data')
    try:
        previous=json.loads((ROOT / '.data/last-session.json').read_text(encoding='utf-8'))
        folder=previous.get('folder','')
        if folder and Path(folder).is_dir():server.library.state['folder']=folder
    except (OSError,ValueError):
        pass
    server.token = secrets.token_urlsafe(32)
    url = 'http://127.0.0.1:%d' % server.server_port
    print('TagPuliti pronto: ' + url, flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.library.stop.set()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()

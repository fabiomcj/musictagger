"""Conservative matching: uncertain identity must never become a safe proposal."""
import re
import unicodedata
from difflib import SequenceMatcher


def normalize(value):
    value = unicodedata.normalize('NFKD', value or '').casefold()
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return re.sub(r'[^\w]+', ' ', value).strip()


def clean_filename(name):
    name = re.sub(r'\.(mp3|m4a|flac|aiff?|wav)$', '', name, flags=re.I)
    name = re.sub(r'\s*\(\d+kbit_(?:AAC|Opus|MP3)\)', '', name, flags=re.I)
    name = re.sub(r'\s*(?:my-free-mp3s\.com|ytshorts\.savetube\.me)\s*', '', name, flags=re.I)
    return name.replace(' – ', ' - ').replace(' — ', ' - ').strip(' -')


def filename_identity(name):
    cleaned = clean_filename(name)
    if ' - ' in cleaned:
        artist, title = cleaned.split(' - ', 1)
        title = re.sub(r'\s*[|¦].*$', '', title)
        # Label after a named mix, not all square brackets (which can contain mixes).
        title = re.sub(r'(\([^)]*(?:mix|edit)[^)]*\))\s*\[[^]]+\]$', r'\1', title, flags=re.I)
        return artist.strip(), title.strip()
    quoted = re.fullmatch(r'(.+?)\s+[\"\'](.+)[\"\']', cleaned)
    return (quoted[1], quoted[2]) if quoted else ('', cleaned)


def version(title):
    """Keep names of remixers; 'original mix' alone is a catalog convention."""
    pieces = re.findall(r'\(([^)]+)\)|\[([^]]+)\]|\{([^}]+)\}', title or '')
    versions = []
    for group in pieces:
        part = normalize(next(p for p in group if p))
        if re.search(r'\b(mix|remix|edit|extended|dub|live|acoustic|instrumental|acapella|version)\b', part):
            if part != 'original mix':
                versions.append(part)
    # Spotify-style suffixes also occur in filenames.
    if ' - ' in (title or ''):
        suffix = normalize(title.rsplit(' - ', 1)[1])
        if re.search(r'\b(mix|remix|edit|extended|dub|live)\b', suffix):
            versions.append(suffix)
    return ' '.join(versions)


def base_title(title):
    def remove_metadata(match):
        part = normalize(match[0])
        return '' if re.search(r'\b(mix|remix|edit|extended|dub|live|acoustic|instrumental|acapella|version|feat|featuring)\b', part) else match[0]
    title = re.sub(r'\([^)]*\)|\[[^]]*\]|\{[^}]*\}', remove_metadata, title or '')
    title = re.sub(r'\s+-\s+[^-]*(?:mix|remix|edit|extended|dub|live).*$', '', title, flags=re.I)
    return normalize(title)


def similarity(a, b):
    a, b = normalize(a), normalize(b)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0


def artist_similarity(a, b):
    # 'feat.' credits can move between the artist and title fields.
    return similarity(re.split(r'\bfeat\.?|\bfeaturing\b', a, flags=re.I)[0],
                      re.split(r'\bfeat\.?|\bfeaturing\b', b, flags=re.I)[0])


def album_identity(album):
    return re.sub(r'\s+(?:ep|single)$', '', normalize(album))


def rank_candidates(row, results):
    hints = row['identity']
    title, artist = hints['title'], hints['artist']
    ranked, seen = [], set()
    for result in results:
        if result.get('kind') != 'song' or not result.get('trackId'):
            continue
        if result['trackId'] in seen:
            continue
        seen.add(result['trackId'])
        candidate_title = result.get('trackName', '')
        ts = similarity(base_title(title), base_title(candidate_title))
        if ts < .55:
            continue
        ars = artist_similarity(artist, result.get('artistName', ''))
        cv, lv = version(candidate_title), version(title)
        same_mix = cv == lv
        current_album = row.get('current', {}).get('album', '')
        album_conflict = bool(current_album and album_identity(current_album) != album_identity(result.get('collectionName', '')))
        duration = result.get('trackTimeMillis', 0) / 1000
        delta = abs(duration - row.get('duration', 0)) if duration and row.get('duration') else None
        seconds_score = max(0, 1 - delta / 30) if delta is not None else 0
        score = round(100 * (.40 * ts + .30 * ars + .20 * seconds_score + .10 * same_mix))
        reasons = []
        if not artist:
            reasons.append('Artista non identificato: il titolo da solo non basta.')
        elif ars < .94:
            reasons.append('Artista diverso o non del tutto corrispondente.')
        if not same_mix:
            reasons.append('Versione o remix diverso: non sostituire il titolo del file.')
        if delta is None:
            reasons.append('Durata non disponibile per il confronto.')
        elif delta > 3:
            reasons.append('Durata diversa di %.1f secondi.' % delta)
        if ts < .97:
            reasons.append('Titolo non identico.')
        if hints.get('conflict'):
            reasons.append('Nome del file e tag esistenti non concordano.')
        if album_conflict:
            reasons.append('Album diverso da quello attuale: potrebbe essere una ristampa o una raccolta.')
        if hints.get('artist_origin') == 'youtube_topic':
            reasons.append('Il canale YouTube può omettere gli altri artisti: conferma i crediti.')
        safe = (ts >= .97 and ars >= .94 and same_mix and delta is not None
                and delta <= 3 and not hints.get('conflict')
                and not album_conflict
                and hints.get('artist_origin') != 'youtube_topic')
        proposed = {
            'title': candidate_title, 'artist': result.get('artistName', ''),
            'album': result.get('collectionName', ''), 'date': result.get('releaseDate', '')[:10],
            'genre': result.get('primaryGenreName', ''),
            'track': ('%s/%s' % (result['trackNumber'], result['trackCount']) if result.get('trackNumber') and result.get('trackCount') else str(result.get('trackNumber') or '')),
            'disc': ('%s/%s' % (result['discNumber'], result['discCount']) if result.get('discNumber') and result.get('discCount') else str(result.get('discNumber') or '')),
        }
        proposed.update({k:v for k,v in result.get('_proposed', {}).items() if v})
        proposed = {k:v for k,v in proposed.items() if v and v != '/'}
        ranked.append({'score': score, 'safe': safe, 'reasons': reasons,
                       'proposed': proposed, 'duration': duration,
                       'duration_delta': round(delta, 2) if delta is not None else None,
                       'track_id': result['trackId'], 'source': result.get('_source', 'Apple Music / iTunes'),
                       'url': result.get('_url', result.get('trackViewUrl', '')),
                       'artwork': result.get('artworkUrl100', ''),
                       'same_mix': same_mix})
    ranked.sort(key=lambda c: (-c['score'], c['duration_delta'] if c['duration_delta'] is not None else 99999))
    # Distinct records with comparable evidence are not an unambiguous album choice.
    if len(ranked) > 1 and ranked[0]['score'] - ranked[1]['score'] < 5:
        ranked[0]['safe'] = False
        ranked[0]['reasons'].append('Più pubblicazioni hanno una corrispondenza simile: scegli l’album.')
    return ranked[:8]

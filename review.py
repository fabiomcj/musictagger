"""One explicit final write; uncertain online data stays a suggestion."""
FIELDS = {'title':'TIT2','artist':'TPE1','album_artist':'TPE2','album':'TALB','date':'TDRC',
          'genre':'TCON','label':'TPUB','bpm':'TBPM','key':'TKEY','track':'TRCK','disc':'TPOS',
          'composer':'TCOM','remixer':'TPE4','isrc':'TSRC'}
LABELS = {'title':'Titolo','artist':'Artista','album_artist':'Artista album','album':'Album',
          'date':'Data','genre':'Genere','label':'Etichetta','bpm':'BPM','key':'Tonalità',
          'track':'Traccia','disc':'Disco','composer':'Compositore','remixer':'Remixer','isrc':'ISRC'}


def candidate_for(row):
    items = row.get('candidates', [])
    selected = row.get('selected', 0)
    return items[selected] if isinstance(selected, int) and 0 <= selected < len(items) else {}


def effective_values(row, overwrite=False, fields=FIELDS):
    result = dict(row.get('current', {}))
    if row.get('decision') == 'skipped':
        return result
    candidate = candidate_for(row)
    # Never promote an ambiguous match merely because the user edited another field.
    if candidate.get('safe'):
        for key, value in candidate.get('proposed', {}).items():
            if key in fields and isinstance(value, str) and value.strip() and (overwrite or not result.get(key)):
                result[key] = value.strip()
    # Explicit manual edits always win, even with fill-missing enabled; blank clears a field.
    for key, value in row.get('manual', {}).items():
        if key in fields:
            result[key] = value.strip()
    return result


def cover_for(row, options):
    if row.get('write_result') or row.get('decision') == 'skipped' or row.get('cover_choice') == 'keep':
        return None
    if row.get('local_cover'):
        return row['local_cover']
    candidate = candidate_for(row)
    if (options.get('covers', True) and not row.get('has_cover') and (candidate.get('safe') or candidate.get('cover_verified'))
            and candidate.get('cover_file')):
        return candidate['cover_file']
    return None


def describe(row, options):
    values = effective_values(row, options.get('overwrite', False))
    changes = [k for k in FIELDS if values.get(k, '') != row.get('current', {}).get(k, '')]
    cover = cover_for(row, options)
    problems = []
    def issue(field, message, level='warning'):
        problems.append({'field':field, 'message':message, 'level':level})
    for field in ('title','artist','album','date','genre'):
        if not values.get(field):
            issue(field, LABELS[field] + ' mancante', 'error' if field in ('title','artist') else 'warning')
    if not row.get('has_cover') and not cover:
        issue('cover','Copertina mancante')
    candidate = candidate_for(row)
    if row.get('decision') != 'accepted':
        if candidate and not candidate.get('safe'):
            for reason in candidate.get('reasons', []):
                issue('match', reason)
        elif row.get('status') == 'not_found':
            issue('match','Nessuna corrispondenza trovata. Puoi lasciare il brano com’è o inserire i dati.')
        elif row.get('status') == 'pending':
            issue('match','Ricerca non eseguita o interrotta per questo brano.')
    if row.get('error'):
        issue('file', row['error'], 'error')
    failures = [r for r in row.get('research', []) if r.get('status') == 'error']
    if failures:
        issue('sources', '%d fonti non disponibili: ricerca parziale.' % len(failures))
    skipped = row.get('decision') == 'skipped'
    saved = bool(row.get('write_result'))
    rename = bool(options.get('rename') and not skipped and
                  (candidate.get('safe') or row.get('manual')) and values.get('artist') and values.get('title'))
    will_write = not skipped and not saved and bool(changes or cover or rename)
    cover_status='pending' if cover else 'embedded' if row.get('has_cover') else 'preview' if candidate.get('artwork') else 'missing'
    return {'cover_status':cover_status,'values':values, 'changes':changes, 'cover_pending':bool(cover), 'rename':rename,
            'problems':problems, 'will_write':will_write,
            'status': 'written' if saved else 'kept' if skipped else 'edited' if row.get('manual') else
                      'problem' if problems else 'ready'}

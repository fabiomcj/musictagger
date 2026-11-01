"""Backed-up, atomic ID3 writes with unchanged MPEG payload verification."""
import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path
from mutagen.mp3 import MP3
from mutagen.id3 import Frames, APIC
from review import effective_values, cover_for
from research import image_mime


def payload_hash(path):
    data = Path(path).read_bytes()
    while data[:3] == b'ID3' and len(data) >= 10:
        size = sum((data[6+i] & 127) << (21-7*i) for i in range(4))
        data = data[10+size:]
    if data[-128:-125] == b'TAG':
        data = data[:-128]
    return hashlib.sha256(data).hexdigest()


def proposal(row, overwrite, fields):
    return effective_values(row, overwrite, fields)


def write_track(row, options, backup_dir, fields):
    source = Path(row['path'])
    if source.is_symlink():
        raise ValueError('Il file è un collegamento: rileggi la cartella.')
    stat = source.stat()
    if row['snapshot'] != {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}:
        raise ValueError('File cambiato dopo la lettura: rileggi la cartella.')
    values = proposal(row, options.get('overwrite', False), fields)
    changed = [k for k in fields if values.get(k, '') != row['current'].get(k, '')]
    cover = cover_for(row, options)
    cover_data = Path(cover['path']).read_bytes() if cover else None
    if cover_data:
        if len(cover_data) > 5_000_000:raise ValueError('Copertina superiore a 5 MB.')
        image_mime(cover_data)
    target = source
    if options.get('rename', False):
        artist, title = values.get('artist'), values.get('title')
        if not artist or not title:
            raise ValueError('Per rinominare servono artista e titolo.')
        name = re.sub(r'[\x00-\x1f/\\:]', ' ', artist + ' - ' + title)
        name = re.sub(r'\s+', ' ', name).strip(' .')
        while len(name.encode('utf-8')) > 220:
            name = name[:-1]
        target = source.with_name(name + '.mp3')
        if target != source and target.exists():
            raise ValueError('Nome già occupato: ' + target.name)
    if not changed and not cover_data and target == source:
        return {'path': str(source), 'fields': [], 'backup': '', 'unchanged': True}
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    audio_before = payload_hash(source)
    backup = Path(backup_dir) / (row['id'] + '.mp3')
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    if hashlib.sha256(backup.read_bytes()).hexdigest() != before:
        raise ValueError('Verifica del backup non riuscita.')
    fd, temporary = tempfile.mkstemp(prefix='.tagpuliti-', suffix='.mp3', dir=source.parent)
    os.close(fd)
    temporary = Path(temporary)
    try:
        shutil.copy2(source, temporary)
        audio = MP3(temporary)
        if audio.tags is None:
            audio.add_tags()
        for key in changed:
            frame = fields[key]
            audio.tags.delall(frame)
            if values.get(key):
                audio.tags.add(Frames[frame](encoding=3, text=[values[key]]))
        if cover_data:
            audio.tags.setall('APIC',[c for c in audio.tags.getall('APIC') if c.type != 3])
            audio.tags.add(APIC(encoding=0,mime=image_mime(cover_data),type=3,desc='Cover',data=cover_data))
        audio.save(v2_version=3)
        if payload_hash(temporary) != audio_before:
            raise ValueError('Audio diverso: scrittura annullata.')
        reread = MP3(temporary)
        if cover_data and not any(c.data == cover_data for c in reread.tags.getall('APIC')):
            raise ValueError('Verifica della copertina non riuscita.')
        if any(str(reread.tags.get(fields[k], '')) != values.get(k, '') for k in changed):
            raise ValueError('Verifica dei tag non riuscita.')
        if hashlib.sha256(source.read_bytes()).hexdigest() != before:
            raise ValueError('File cambiato durante la scrittura: operazione annullata.')
        if target == source:
            os.replace(temporary, source)
        else:
            os.link(temporary, target)  # exclusive: never replace another track
            try:
                source.unlink()
            except Exception:
                target.unlink()
                raise
        return {'path': str(target), 'fields': changed + (['cover'] if cover_data else []), 'backup': str(backup), 'unchanged': False}
    finally:
        temporary.unlink(missing_ok=True)

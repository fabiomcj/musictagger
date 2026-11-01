"""Identify and prepare real front covers for ID3, never confuse preview with embedding."""
import hashlib
import subprocess
import tempfile
from pathlib import Path
from matching import artist_similarity, base_title, similarity, normalize, version


def artwork_matches(row,candidate):
    values=dict(row.get('current',{}));values.update(row.get('manual',{}))
    title=values.get('title') or row.get('identity',{}).get('title','')
    artist=values.get('artist') or row.get('identity',{}).get('artist','')
    found=candidate.get('proposed',{})
    if similarity(base_title(title),base_title(found.get('title',''))) < .94:return False
    credit=found.get('artist','')
    artist_ok=bool(artist and artist_similarity(artist,credit)>=.88)
    # A remix may be released under the credited remixers rather than the sampled artist.
    remixer_ok=bool(credit and len(normalize(credit))>5 and normalize(credit) in normalize(title))
    if not artist_ok and not remixer_ok:return False
    local_mix,remote_mix=version(title),version(found.get('title',''))
    if local_mix and remote_mix and local_mix != remote_mix:return False
    return True


def normalize_image(data,directory,source=''):
    if len(data)>5_000_000:raise ValueError('Copertina superiore a 5 MB.')
    if data.startswith(b'\xff\xd8\xff'):suffix='.jpg'
    elif data.startswith(b'\x89PNG\r\n\x1a\n'):suffix='.png'
    else:raise ValueError('La copertina deve essere JPEG o PNG.')
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    output=directory/(hashlib.sha256(data).hexdigest()+'.jpg')
    if not output.exists():
        with tempfile.TemporaryDirectory(prefix='tagpuliti-cover-') as tmp:
            original=Path(tmp)/('original'+suffix);original.write_bytes(data)
            converted=Path(tmp)/'front.jpg'
            profile=Path('/System/Library/ColorSync/Profiles/sRGB Profile.icc')
            args=['/usr/bin/sips','-s','format','jpeg','-s','formatOptions','88','-Z','1000']
            if profile.is_file():args+=['--matchTo',str(profile)]
            result=subprocess.run(args+[str(original),'--out',str(converted)],capture_output=True,timeout=20)
            if result.returncode or not converted.exists():raise ValueError('Impossibile convertire la copertina in JPEG compatibile.')
            image=converted.read_bytes()
            if not image.startswith(b'\xff\xd8\xff'):raise ValueError('Conversione della copertina non riuscita.')
            output.write_bytes(image)
    return {'path':str(output),'mime':'image/jpeg','source':source,'normalized':True}

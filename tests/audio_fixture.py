"""Generated silent MPEG frames: no personal files or copyrighted recordings."""
import base64
from pathlib import Path
from mutagen.mp3 import MP3
from mutagen.id3 import TIT2, TPE1, TALB, TDRC, TCON, APIC


def make_mp3(path, title='Fixture Song', artist='Fixture Artist'):
    path = Path(path)
    # MPEG-1 Layer III, 128 kbit/s, 44.1 kHz; zero side-information and data encode silence.
    frame = b'\xff\xfb\x90\x00' + bytes(413)
    path.write_bytes(frame * 40)
    audio = MP3(path)
    audio.add_tags()
    for cls, text in [(TIT2, title), (TPE1, artist), (TALB, 'Fixture Album'),
                      (TDRC, '2020'), (TCON, 'House')]:
        audio.tags.add(cls(encoding=3, text=[text]))
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
    audio.tags.add(APIC(encoding=0, mime='image/png', type=3, desc='Cover', data=png))
    audio.save(v2_version=3)
    return path

# MusicTagger · TagPuliti

App locale per macOS per sistemare i metadati dei brani prima di importarli in rekordbox.

**Cartella → analisi → opzioni → ricerca → risultati → conferma e scrittura.**

- Ricerca su Apple Music/iTunes, MusicBrainz e Deezer, con più mercati Apple.
- Problemi evidenziati per ogni brano; tutti i campi sono modificabili manualmente.
- Puoi lasciare un brano esattamente com’è, senza approvazioni obbligatorie.
- Copertine incorporate negli MP3 come JPEG Front Cover, con stato distinto dalle anteprime online.
- Backup integrali, verifica dei tag riletti e controllo che il contenuto MPEG resti identico.

## Avvio su Mac

Richiede Python 3.9 o successivo. Per la conversione delle copertine usa `sips`, incluso in macOS.

```sh
git clone https://github.com/fabiomcj/musictagger.git
cd musictagger
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

Si apre il browser su un indirizzo locale. In alternativa, dopo aver creato l’ambiente, fai doppio clic su **Avvia TagPuliti.command**. Lascia il processo aperto durante l’uso.

## Uso e limiti

Per il flusso completo, le fonti consultate, le opzioni di ricerca e il ripristino dei backup, leggi [LEGGIMI.md](LEGGIMI.md).

Il formato attualmente supportato è **MP3**. L’app non calcola BPM o tonalità dall’audio e non modifica il database di rekordbox. Per aggiornare i brani già importati in rekordbox, usa **Reload Tag** dalla collezione.

Le ricerche inviano metadati ai cataloghi, non l’audio. Sessioni, copertine preparate, cache e backup sono salvati nella cartella locale `.data`, esclusa da Git insieme all’ambiente Python e ai file musicali.

## Test

```sh
.venv/bin/python -m unittest discover -s tests -v
node --test tests/frontend-approval.test.cjs
```

I test generano piccoli MP3 silenziosi temporanei: non richiedono una libreria musicale personale né accesso alla rete esterna. I test delle copertine richiedono macOS; i test frontend richiedono Node.js.

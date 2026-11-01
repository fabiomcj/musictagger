# TagPuliti 1.0

App locale per Mac per analizzare MP3, recuperare metadati da più cataloghi, correggere a mano e scrivere i tag con una sola conferma finale.

## Il flusso

1. **Cartella:** scegli la cartella, con sottocartelle facoltative.
2. **Analisi:** legge i file e i tag, controlla la durata e la presenza della copertina. Non modifica nulla.
3. **Opzioni:** scegli fonti, ampiezza della ricerca, compilazione dei soli campi vuoti o sostituzione dei tag, copertine e rinomina facoltativa.
4. **Ricerca:** interroga i servizi indipendentemente e mostra l’avanzamento. Un servizio non disponibile non blocca gli altri. Puoi interrompere e utilizzare i brani già elaborati.
5. **Risultati:** mostra tutti i brani, con problemi precisi per ciascuno. I filtri servono solo a trovare più rapidamente i problemi, le modifiche manuali e i brani lasciati intatti.

Apri un brano per vedere dati attuali, dati che verranno scritti, pubblicazioni trovate, motivi di incertezza e fonti effettivamente consultate. Ogni campo è modificabile, anche quando la compilazione automatica è impostata sui soli campi vuoti. **Usa i dati di questa pubblicazione** riporta nei campi i dati della pubblicazione scelta; puoi correggerli prima di salvare.

**Salva modifiche** prepara i dati. **Lascia com’è** esclude ogni modifica di quel brano, copertina e rinomina comprese. Chiudere semplicemente il dettaglio mantiene il comportamento automatico: le proposte incerte non vengono applicate di nascosto. Non devi risolvere tutti gli avvisi o approvare uno per uno i brani per poter procedere.

**Conferma e scrivi i tag** scrive soltanto le modifiche effettive mostrate nel riepilogo. I file senza modifiche e quelli lasciati come sono restano intatti. Non ci sono checkbox per selezionare i brani, né code di approvazioni obbligatorie.

## Fonti e ricerca mondiale

- **MusicBrainz:** ricerca mondiale di registrazioni e pubblicazioni; dettagli di etichetta, artista album, data, traccia/disco, ISRC, genere, remixer e compositori quando disponibili.
- **Deezer:** ricerca globale, dettagli della traccia e dell’album, inclusi ISRC, BPM ed etichetta quando forniti.
- **Apple Music / iTunes:** ricerca in più mercati. Rapida: Italia e Stati Uniti. Completa: IT, US, GB, DE, FR, NL, JP, BR. Approfondita: anche AU, CA, ES, SE, ZA, MX, NZ, IN, AR, CH, BE, AT.
- **YouTube oEmbed:** indizi dai link già presenti, se manca l’artista. I canali Topic restano indizi da controllare.
- **Cover Art Archive:** ricerca e preparazione di immagini JPEG/PNG da incorporare quando la pubblicazione è identificata. Le immagini dei cataloghi vengono preparate per l’incorporamento quando titolo e artista corrispondono; una pubblicazione incerta può essere scelta manualmente.
- Il dettaglio contiene link a Google, Discogs, Beatport, Traxsource, Bandcamp e YouTube per ulteriori verifiche manuali. Questi link non vengono presentati come ricerche automatiche già effettuate.

Nessun servizio consente di trovare ogni informazione presente in ogni sito del mondo. L’app distingue risultati, assenze e problemi dei servizi, senza inventare dati. Non usa riconoscimento acustico e non calcola BPM o tonalità dall’audio. Cerca confrontando titolo, artista, versione, durata e pubblicazione. Le ricerche inviano metadati, non i file audio.

Le richieste rispettano i limiti dei servizi; Apple usa un intervallo di 3,2 secondi e MusicBrainz 1,1 secondi. Le risposte sono conservate per sette giorni. La ricerca completa di una cartella grande può richiedere tempo; cache e avanzamento evitano di nasconderlo. Gli errori HTTP temporanei vengono ritentati fino a tre volte.

## Copertine

Le immagini dei cataloghi supportati vengono scaricate nella cartella interna dell’app e verificate come JPEG/PNG, fino a 5 MB. Le copertine di una pubblicazione sicura vengono applicate automaticamente ai file che ne sono privi, se l’opzione è attiva. Per una pubblicazione incerta puoi scegliere esplicitamente **Usa la copertina trovata**. Puoi inoltre scegliere una copertina dal tuo computer. Nessuna immagine viene incorporata nel brano prima della conferma finale.

Le copertine già presenti vengono conservate, salvo scelta manuale di sostituzione.

## Scrittura e sicurezza dei file

Prima di una modifica viene salvata una copia integrale originale in `.data/backups/<sessione>/`, con `manifest.json` che associa originale, backup e risultato. La scrittura viene preparata su un file temporaneo; i tag vengono riletti e il contenuto MPEG deve avere la stessa impronta prima e dopo. Un file cambiato dopo l’analisi o un nome di destinazione già occupato blocca quel brano senza sostituirlo. Gli altri possono essere completati.

Le copertine vengono convertite in JPEG sRGB fino a 1000 pixel e incorporate come Front Cover nei tag ID3v2.3. Lo stato distingue copertina solo in anteprima, da incorporare e incorporata. È possibile aggiungere una copertina anche dopo una prima scrittura dei tag, mantenendo la ricevuta precedente.

La modifica è atomica per singolo file, non per l’intera cartella. Il ripristino è manuale copiando il backup nel percorso indicato dal manifest. Le modifiche manuali hanno sempre precedenza sui dati del catalogo: svuotare esplicitamente un campo ne elimina il tag.

La rinomina può richiedere di ricollegare il brano in rekordbox; i file accessori non vengono rinominati. Il database di rekordbox non viene mai modificato. Testi e tag personalizzati vengono conservati se non modificati.

## Avvio

Doppio clic su **Avvia TagPuliti.command**. Lascia aperta la finestra Terminale durante l’uso; Ctrl+C chiude il programma. Il servizio ascolta solo sul computer locale, su una porta libera.

Supporto attuale: **MP3**. Altri formati vengono elencati tra gli esclusi; i file corrotti vengono segnalati. Non è ancora una `.app` firmata.

Per installare su un altro Mac occorre Python 3.9 o successivo:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Per verificare:

```sh
.venv/bin/python -m unittest discover -s tests -v
node --test tests/frontend-approval.test.cjs
```

Cache, sessioni, copertine preparate e backup sono in `.data`. CSV e JSON contengono percorsi locali: controllali prima di condividerli.

## Documentazione dei servizi

- [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API)
- [Ricerca MusicBrainz](https://musicbrainz.org/doc/MusicBrainz_API/Search)
- [Cover Art Archive API](https://musicbrainz.org/doc/Cover_Art_Archive/API)
- [Apple iTunes Search API](https://performance-partners.apple.com/search-api)

"""Independent global catalog searches, traceable results and bounded artwork downloads."""
import hashlib
import re
import urllib.parse
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from matching import rank_candidates, normalize, base_title
from covers import artwork_matches, normalize_image

MARKETS = ['IT','US','GB','DE','FR','NL','JP','BR']
DEEP_MARKETS = MARKETS + ['AU','CA','ES','SE','ZA','MX','NZ','IN','AR','CH','BE','AT']


def artist_credit(credit):
    return ''.join((p.get('name') or p.get('artist', {}).get('name','')) + p.get('joinphrase','')
                   for p in credit if isinstance(p,dict))


def mb_records(body):
    records=[]
    for recording in body.get('recordings',[]):
        for release in (recording.get('releases') or [{}])[:5]:
            identifier=recording.get('id','')
            rid=release.get('id','')
            records.append({'kind':'song','trackId':'mb:'+identifier+':'+rid,
                'trackName':recording.get('title',''), 'artistName':artist_credit(recording.get('artist-credit',[])),
                'collectionName':release.get('title',''), 'releaseDate':release.get('date') or recording.get('first-release-date',''),
                'trackTimeMillis':recording.get('length',0), '_source':'MusicBrainz',
                '_url':'https://musicbrainz.org/recording/'+identifier, '_recording':identifier, '_release':rid,
                '_proposed':{'isrc':next(iter(recording.get('isrcs',[])),''),
                             'genre':', '.join(t.get('name','') for t in recording.get('tags',[])[:3])}})
    return records


def deezer_records(body):
    return [{'kind':'song','trackId':'dz:'+str(t['id']), 'trackName':t.get('title',''),
             'artistName':t.get('artist',{}).get('name',''), 'collectionName':t.get('album',{}).get('title',''),
             'trackTimeMillis':t.get('duration',0)*1000, '_source':'Deezer', '_url':t.get('link',''),
             'artworkUrl100':t.get('album',{}).get('cover_medium',''), '_deezer_id':t['id']}
            for t in body.get('data',[]) if t.get('id')]


def merge_candidates(candidates):
    merged=[]
    for item in sorted(candidates,key=lambda c:-c['score']):
        key=(normalize(item['proposed'].get('title','')),normalize(item['proposed'].get('artist','')),
             normalize(item['proposed'].get('album','')),round(item.get('duration',0)))
        existing=next((c for k,c in merged if k==key),None)
        link={'name':item['source'],'url':item.get('url','')}
        if existing:
            if link not in existing['sources']:existing['sources'].append(link)
            for field,value in item['proposed'].items():
                if value and not existing['proposed'].get(field):existing['proposed'][field]=value
            if item.get('cover_verified'):existing['cover_verified']=True
            for field in ('cover_file','artwork'):
                if item.get(field) and not existing.get(field):existing[field]=item[field]
        else:
            item['sources']=[link];merged.append((key,item))
    result=[c for _,c in merged]
    # Same recording in different releases is still a release-choice ambiguity.
    if len(result)>1 and result[0]['score']-result[1]['score']<5:
        if normalize(result[0]['proposed'].get('album',''))!=normalize(result[1]['proposed'].get('album','')):
            result[0]['safe']=False
            reason='Più pubblicazioni compatibili: controlla album e versione.'
            if reason not in result[0]['reasons']:result[0]['reasons'].append(reason)
    return result[:20]


class ArtworkRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_art_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def check_art_url(url):
    parsed=urllib.parse.urlparse(url)
    host=parsed.hostname or ''
    allowed=('archive.org','mzstatic.com','dzcdn.net','bcbits.com','traxsource.com','beatport.com')
    if parsed.scheme!='https' or not (host=='coverartarchive.org' or any(host==domain or host.endswith('.'+domain) for domain in allowed)):
        raise ValueError('Indirizzo della copertina non consentito.')


def image_mime(data):
    if data.startswith(b'\xff\xd8\xff'):return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png'
    raise ValueError('Copertina non valida: usa JPEG o PNG.')


def download_cover(url, directory):
    check_art_url(url)
    request=urllib.request.Request(url,headers={'User-Agent':'TagPuliti/1.0 (personal music tagger)'})
    with urllib.request.build_opener(ArtworkRedirect()).open(request,timeout=12) as response:
        data=response.read(5_000_001)
    if len(data)>5_000_000:raise ValueError('Copertina superiore a 5 MB.')
    return normalize_image(data,directory,url)


class Research:
    def __init__(self,catalog,directory):
        self.catalog=catalog;self.directory=Path(directory)

    def search(self,row,options,cancelled=lambda:False,activity=lambda message:None):
        reports=[];raw=[]
        identity=row['identity'];title=identity['title'];artist=identity['artist']
        term=(artist+' '+title).strip()
        if not term:raise ValueError('Mancano titolo e artista: puoi inserirli manualmente nei risultati.')
        def query(name,url):
            if cancelled():raise InterruptedError()
            activity(name)
            try:
                body=self.catalog.get_json(url,cancelled)
                count=len(body.get('results',body.get('recordings',body.get('data',[]))))
                reports.append({'name':name,'url':url,'status':'ok','count':count})
                return body
            except InterruptedError:raise
            except urllib.error.HTTPError as exc:
                if exc.code == 404 and name.startswith('Cover Art Archive'):
                    reports.append({'name':name,'url':url,'status':'ok','count':0})
                    return {}
                reports.append({'name':name,'url':url,'status':'error','error':str(exc)})
                return {}
            except Exception as exc:
                reports.append({'name':name,'url':url,'status':'error','error':str(exc)})
                return {}
        providers=options.get('providers',['apple','musicbrainz','deezer'])
        def apple():
            found=[]
            markets=MARKETS if options.get('depth','world')=='world' else DEEP_MARKETS if options.get('depth')=='deep' else ['IT','US']
            for market in markets:
                url='https://itunes.apple.com/search?'+urllib.parse.urlencode({'term':term,'entity':'song','media':'music','limit':25,'country':market})
                for value in query('Apple Music · '+market,url).get('results',[]):
                    value=dict(value,_source='Apple Music · '+market);found.append(value)
            return found
        def musicbrainz():
            # Quote and escape values so titles cannot alter the Lucene expression.
            quote=lambda s:'"'+s.replace('\\','\\\\').replace('"','\\"')+'"'
            expression='recording:'+quote(title)+((' AND artist:'+quote(artist)) if artist else '')
            url='https://musicbrainz.org/ws/2/recording/?'+urllib.parse.urlencode({'query':expression,'fmt':'json','limit':25})
            values=mb_records(query('MusicBrainz · mondiale',url))
            if not values and base_title(title)!=normalize(title):
                expression='recording:'+quote(base_title(title))+((' AND artist:'+quote(artist)) if artist else '')
                url='https://musicbrainz.org/ws/2/recording/?'+urllib.parse.urlencode({'query':expression,'fmt':'json','limit':25})
                values=mb_records(query('MusicBrainz · titolo senza versione',url))
            return values
        def deezer():
            url='https://api.deezer.com/search?'+urllib.parse.urlencode({'q':term,'limit':25})
            return deezer_records(query('Deezer · mondiale',url))
        tasks={'apple':apple,'musicbrainz':musicbrainz,'deezer':deezer}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(tasks[p]) for p in providers if p in tasks]
            for future in futures:raw.extend(future.result())
        # Rank providers independently to avoid duplicate store entries creating false ambiguity.
        ranked=[]
        for record in raw:
            candidate=rank_candidates(row,[record])
            if candidate:ranked.extend(candidate)
        ranked.sort(key=lambda c:-c['score'])
        # Fetch detailed credits for the best MusicBrainz and Deezer releases.
        for provider in ('MusicBrainz','Deezer'):
            candidate=next((c for c in ranked if c['source'].startswith(provider)),None)
            if not candidate or candidate['score']<65:continue
            record=next((r for r in raw if r['trackId']==candidate['track_id']),{})
            if provider=='MusicBrainz':
                rid=record.get('_release');recording=record.get('_recording')
                if rid and re.fullmatch(r'[0-9a-f-]{36}',rid):
                    body=query('MusicBrainz · dettagli pubblicazione','https://musicbrainz.org/ws/2/release/'+rid+'?fmt=json&inc=labels+artist-credits+recordings+release-groups')
                    labels=[i.get('label',{}).get('name','') for i in body.get('label-info',[])]
                    candidate['proposed'].update({k:v for k,v in {'label':', '.join(filter(None,labels)),
                        'album_artist':artist_credit(body.get('artist-credit',[])), 'date':body.get('date','')}.items() if v})
                    for medium in body.get('media',[]):
                        for track in medium.get('tracks',[]):
                            if track.get('recording',{}).get('id')==recording:
                                candidate['proposed']['track']=str(track.get('number',''))+'/'+str(medium.get('track-count',''))
                                candidate['proposed']['disc']=str(medium.get('position',''))+'/'+str(len(body.get('media',[])))
                    if options.get('covers',True) and not row.get('has_cover'):
                        art=query('Cover Art Archive','https://coverartarchive.org/release/'+rid)
                        front=next((i for i in art.get('images',[]) if i.get('front')),None)
                        group=body.get('release-group',{}).get('id','')
                        if not front and re.fullmatch(r'[0-9a-f-]{36}',group):
                            art=query('Cover Art Archive · album','https://coverartarchive.org/release-group/'+group)
                            front=next((i for i in art.get('images',[]) if i.get('front')),None)
                        if front:
                            url=front.get('thumbnails',{}).get('500') or front.get('image','')
                            url=url.replace('http://','https://',1)
                            try:
                                candidate['cover_file']=download_cover(url,self.directory/'artwork')
                                candidate['artwork']=url
                            except Exception as exc:
                                reports.append({'name':'Download copertina','status':'error','error':str(exc)})
                if recording:
                    body=query('MusicBrainz · crediti e ISRC','https://musicbrainz.org/ws/2/recording/'+recording+'?fmt=json&inc=artists+isrcs+artist-rels+work-rels+genres')
                    for key,value in {'isrc':next(iter(body.get('isrcs',[])),''),
                                      'genre':', '.join(g.get('name','') for g in body.get('genres',[])[:3]),
                                      'remixer':', '.join(r.get('artist',{}).get('name','') for r in body.get('relations',[]) if r.get('type')=='remixer')}.items():
                        if value:candidate['proposed'][key]=value
                    works=[r.get('work',{}).get('id') for r in body.get('relations',[]) if r.get('work',{}).get('id')]
                    composers=[]
                    for work in works[:2]:
                        details=query('MusicBrainz · compositori','https://musicbrainz.org/ws/2/work/'+work+'?fmt=json&inc=artist-rels')
                        composers.extend(r.get('artist',{}).get('name','') for r in details.get('relations',[]) if r.get('type')=='composer')
                    if composers:candidate['proposed']['composer']=', '.join(dict.fromkeys(filter(None,composers)))
            else:
                identifier=record.get('_deezer_id')
                body=query('Deezer · dettagli traccia','https://api.deezer.com/track/'+str(identifier))
                for key,value in {'isrc':body.get('isrc',''),'bpm':str(body.get('bpm') or ''),
                                  'date':body.get('release_date',''),'track':str(body.get('track_position') or ''),
                                  'disc':str(body.get('disk_number') or '')}.items():
                    if value:candidate['proposed'][key]=value
                album_id=body.get('album',{}).get('id')
                if album_id:
                    album=query('Deezer · dettagli album','https://api.deezer.com/album/'+str(album_id))
                    for key,value in {'label':album.get('label',''),'album_artist':album.get('artist',{}).get('name',''),
                        'genre':', '.join(g.get('name','') for g in album.get('genres',{}).get('data',[]))}.items():
                        if value:candidate['proposed'][key]=value
        # A compilation without artwork must not prevent trying other matched releases.
        if options.get('covers',True) and not row.get('has_cover') and not any(c.get('cover_file') for c in ranked):
            seen_albums=set();attempts=0
            for alternative in ranked:
                if alternative['source']!='MusicBrainz' or alternative['score']<65:continue
                album=normalize(alternative['proposed'].get('album',''))
                if album in seen_albums:continue
                seen_albums.add(album)
                if len(seen_albums)==1:continue  # already checked above
                rid=alternative['track_id'].rsplit(':',1)[-1]
                if not re.fullmatch(r'[0-9a-f-]{36}',rid):continue
                attempts+=1
                art=query('Cover Art Archive · altra pubblicazione','https://coverartarchive.org/release/'+rid)
                front=next((i for i in art.get('images',[]) if i.get('front')),None)
                if not front:
                    details=query('MusicBrainz · altra pubblicazione','https://musicbrainz.org/ws/2/release/'+rid+'?fmt=json&inc=release-groups')
                    group=details.get('release-group',{}).get('id','')
                    if re.fullmatch(r'[0-9a-f-]{36}',group):
                        art=query('Cover Art Archive · altro album','https://coverartarchive.org/release-group/'+group)
                        front=next((i for i in art.get('images',[]) if i.get('front')),None)
                if front:
                    url=(front.get('thumbnails',{}).get('500') or front.get('image','')).replace('http://','https://',1)
                    try:
                        alternative['cover_file']=download_cover(url,self.directory/'artwork')
                        alternative['artwork']=url
                        break
                    except Exception as exc:reports.append({'name':'Download copertina','status':'error','error':str(exc)})
                if attempts>=3:break
        # Prepare matching catalog covers too; a displayed image alone is never a write receipt.
        if options.get('covers',True) and not row.get('has_cover'):
            cached={}
            for item in ranked:
                if not artwork_matches(row,item):continue
                if item.get('cover_file'):
                    item['cover_verified']=True
                    continue
                if not item.get('artwork'):continue
                url=item['artwork']
                if '.mzstatic.com/' in url:url=re.sub(r'/100x100bb\.(jpg|png)$','/600x600bb.jpg',url)
                try:
                    if url not in cached:
                        cached[url]=download_cover(url,self.directory/'artwork')
                    item.update(cover_file=cached[url],cover_verified=True)
                    if len(cached)>=3:break
                except Exception as exc:
                    reports.append({'name':'Recupero copertina catalogo','status':'error','error':str(exc),'url':url})
        if cancelled():raise InterruptedError()
        return merge_candidates(ranked),reports

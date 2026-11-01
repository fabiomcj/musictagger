'use strict';
const $=id=>document.getElementById(id);
const labels={title:'Titolo',artist:'Artista',album_artist:'Artista album',album:'Album',date:'Data',genre:'Genere',label:'Etichetta',bpm:'BPM',key:'Tonalità',track:'Traccia',disc:'Disco',composer:'Compositore',remixer:'Remixer',isrc:'ISRC'};
const statusLabels={ready:'Pronto',problem:'Da controllare',edited:'Modificato a mano',kept:'Lasciato com’è',written:'Scritto'};
let token='',state=null,view=null,filter='all',page=0,lastRevision='',refreshTask=null,editorId=null,draft={},choice=0,saving=false;
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function busy(){return state&&['scan','search','write','commit'].includes(state.phase);}
function tell(message='',inside=false){const target=inside?$('editor-notice'):$('notice');target.hidden=!message;target.textContent=message;}
async function api(route,data={}){
 const response=await fetch('/api/'+route,{method:'POST',headers:{'Content-Type':'application/json','X-TagPuliti-Token':token},body:JSON.stringify(data)});
 const body=await response.json();if(!response.ok)throw Error(body.error||'Operazione non riuscita.');return body;
}
async function act(fn,inside=false){tell('',inside);try{await fn();}catch(e){tell(e.message,inside);}}
function stage(){if(state.phase==='scan')return 'analysis';if(state.phase==='search')return 'search';return view||(state.step===4?'results':state.rows.length?'options':'folder');}
function options(){return{providers:['apple','musicbrainz','deezer'].filter(p=>$('provider-'+p).checked),depth:$('depth').value,overwrite:$('overwrite').checked,rename:$('rename').checked,covers:$('covers').checked,only_unresolved:false};}
function syncOptions(){const o=state.options||{};for(const p of ['apple','musicbrainz','deezer'])$('provider-'+p).checked=(o.providers||['apple','musicbrainz','deezer']).includes(p);$('depth').value=o.depth||'world';$('overwrite').checked=!!o.overwrite;$('rename').checked=!!o.rename;$('covers').checked=o.covers!==false;}
function matched(row,key){if(key==='all')return true;if(key==='problem')return row.review.status!=='kept'&&row.review.problems.length>0;return row.review.status===key;}
function rowsForDisplay(){const query=$('filter').value.toLocaleLowerCase();return state.rows.filter(r=>matched(r,filter)&&`${r.filename} ${r.review.values.title||''} ${r.review.values.artist||''}`.toLocaleLowerCase().includes(query));}
function render(){
 const currentStage=stage(),isBusy=busy();
 for(const s of ['folder','analysis','options','search','results'])$(s+'-panel').hidden=s!==currentStage;
 const stages=['folder','analysis','options','search','results'];document.querySelectorAll('[data-stage]').forEach(e=>{e.classList.toggle('active',e.dataset.stage===currentStage);e.classList.toggle('done',stages.indexOf(e.dataset.stage)<stages.indexOf(currentStage));});
 $('progress-panel').hidden=!isBusy;$('progress').max=Math.max(state.total,1);$('progress').value=state.done;
 $('progress-title').textContent=state.phase==='scan'?'Analisi dei file':state.phase==='search'?'Ricerca nei cataloghi':'Scrittura e verifica';$('progress-count').textContent=`${state.done} / ${state.total}`;$('activity').textContent=state.message;
 for(const id of ['scan','choose','restore','search','back-folder','back-options'])$(id).disabled=isBusy;
 if(state.folder&&!$('folder').value)$('folder').value=state.folder;
 $('analysis-summary').replaceChildren(node('strong',`${state.rows.length} brani analizzati`),node('p',state.folder),node('p',`${state.rows.filter(r=>!r.current.artist||!r.current.title).length} con titolo o artista mancanti · ${state.rows.filter(r=>!r.has_cover).length} senza copertina · ${state.errors.length} problemi di lettura`));
 const ready=state.rows.filter(r=>r.review.will_write),problems=state.rows.filter(r=>matched(r,'problem'));
 $('stats').replaceChildren();for(const [value,label]of [[state.rows.length,'Brani'],[problems.length,'Con qualcosa da controllare'],[ready.length,'Con modifiche da scrivere'],[state.rows.filter(r=>r.review.status==='kept').length,'Lasciati come sono']]){const box=node('div',undefined,'stat');box.append(node('strong',String(value)),node('span',label));$('stats').append(box);}
 document.querySelectorAll('[data-filter]').forEach(b=>{const key=b.dataset.filter;b.classList.toggle('active',key===filter);b.textContent=({all:'Tutti',problem:'Con problemi',edited:'Modificati a mano',kept:'Lasciati come sono'})[key]+` (${state.rows.filter(r=>matched(r,key)).length})`;});
 const filtered=rowsForDisplay();page=Math.min(page,Math.max(0,Math.ceil(filtered.length/75)-1));$('tracks').replaceChildren();
 for(const row of filtered.slice(page*75,(page+1)*75)){
  const review=row.review,tr=node('tr');tr.tabIndex=0;tr.setAttribute('aria-label','Modifica '+row.filename);
  const name=node('td');name.append(node('strong',review.values.title||row.identity.title||'Titolo da inserire'),node('small',row.filename));
  const info=node('td');
  if(review.status==='kept')info.append(node('div','Non verrà modificato. Puoi riaprirlo quando vuoi.','fine-line'));
  else if(review.status==='written'){info.append(node('div','Tag scritti e audio verificato.','fine-line'));for(const problem of review.problems.slice(0,2))info.append(node('div',problem.message,'issue-line'));}
  else if(review.problems.length){for(const problem of review.problems.slice(0,2))info.append(node('div',problem.message,'issue-line'));if(review.problems.length>2)info.append(node('small',`Altri ${review.problems.length-2} dettagli · clicca per vedere tutto`));}
  else info.append(node('div',review.will_write?`${review.changes.length} ${review.changes.length===1?'campo':'campi'} da aggiornare${review.cover_pending?' + copertina':''}`:'Tag già completi, nessuna modifica necessaria.','fine-line'));
  const status=node('td');status.append(node('span',statusLabels[review.status],'badge '+review.status));status.append(node('small',({embedded:'Copertina incorporata',pending:'Copertina da incorporare',preview:'Copertina solo in anteprima',missing:'Copertina mancante'})[review.cover_status]||''));
  tr.append(name,node('td',review.values.artist||'Artista da inserire'),info,status);
  tr.onclick=()=>openEditor(row.id);tr.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();openEditor(row.id);}};$('tracks').append(tr);
 }
 $('empty').hidden=filtered.length>0;$('page-info').textContent=filtered.length?`${page*75+1}–${Math.min(filtered.length,(page+1)*75)} di ${filtered.length}`:'0 brani';$('previous').disabled=page===0;$('next').disabled=(page+1)*75>=filtered.length;
 $('write-summary').textContent=`${ready.length} ${ready.length===1?'brano':'brani'} con modifiche da scrivere`;
 $('write-detail').textContent=`${state.rows.length-ready.length} ${state.rows.length-ready.length===1?'resta com’è':'restano come sono'}. ${state.options?.overwrite?'Sostituzione dei tag esistenti abilitata.':'Compilazione dei campi vuoti + tue modifiche manuali.'} Backup incluso. ${state.rows.filter(r=>r.has_cover).length}/${state.rows.length} copertine incorporate nei file.`;
 $('commit').disabled=isBusy||!ready.length;$('commit').textContent=isBusy&&['commit','write'].includes(state.phase)?'Scrittura in corso…':'Conferma e scrivi i tag';
 const messages=[...state.errors,...Object.entries(state.skipped||{}).map(([ext,count])=>`${count} file ${ext} esclusi: formato non supportato.`)];$('diagnostics').hidden=!messages.length;$('diagnostics-content').textContent=messages.join('\n');
 if(['commit','write'].includes(state.phase)||state.rows.some(r=>r.write_result))tell(state.message);
}
async function refresh(force=false){
 if(refreshTask){await refreshTask;if(!force)return;}
 const task=(async()=>{const response=await fetch('/api/status');if(!response.ok)throw Error('Il server locale non risponde.');const summary=JSON.stringify(await response.json());if(!force&&summary===lastRevision)return;const result=await fetch('/api/state');if(!result.ok)throw Error('Impossibile leggere la sessione.');const before=state;state=await result.json();lastRevision=summary;if(before&&['scan','search'].includes(before.phase)&&!busy()){view=before.phase==='scan'?'options':'results';filter='all';page=0;if(view==='options')syncOptions();}render();})();
 refreshTask=task;try{await task;}finally{if(refreshTask===task)refreshTask=null;}
}
function formatTime(value){const n=Math.round(value||0);return `${Math.floor(n/60)}:${String(n%60).padStart(2,'0')}`;}
function safeLink(url,label){try{const parsed=new URL(url);if(!['https:','http:'].includes(parsed.protocol))return null;const a=node('a',label);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;}catch{return null;}}
function currentRow(){return state.rows.find(r=>r.id===editorId);}
function readDraft(){for(const input of $('fields').querySelectorAll('input[data-field]'))draft[input.dataset.field]=input.value;}
function drawFields(){const row=currentRow();$('fields').replaceChildren();for(const [field,label]of Object.entries(labels)){const tr=node('tr'),cell=node('td'),input=node('input');input.value=draft[field]??'';input.dataset.field=field;input.setAttribute('aria-label',label+' da scrivere');input.placeholder='Nessun dato';if(row.review.problems.some(p=>p.field===field))input.classList.add('flagged');input.oninput=()=>{draft[field]=input.value;};cell.append(input);const origin=Object.prototype.hasOwnProperty.call(row.manual||{},field)?'Modifica manuale':draft[field]===row.current[field]?'Dato attuale':'Proposta del catalogo';cell.append(node('div',origin,'field-note'));tr.append(node('td',label),node('td',row.current[field]||'—'),cell);$('fields').append(tr);}}
function drawCandidate(){const row=currentRow(),candidate=row.candidates[choice];$('candidate-reasons').textContent=candidate?`${candidate.source} · file ${formatTime(row.duration)} / catalogo ${formatTime(candidate.duration)} · ${candidate.reasons.length?candidate.reasons.join(' '):'Titolo, artista, versione e durata concordano.'}`:'Nessun risultato utilizzabile. Puoi inserire i dati a mano o lasciare il brano com’è.';$('candidate-sources').replaceChildren();for(const source of candidate?.sources|| (candidate?[{name:candidate.source,url:candidate.url}]:[])){const link=safeLink(source.url,source.name+' ↗');if(link)$('candidate-sources').append(link);}$('use-candidate').disabled=busy()||!candidate;}
function drawArtwork(){const row=currentRow(),candidate=row.candidates[choice];$('use-cover').hidden=!candidate?.artwork&&!candidate?.cover_file;$('use-cover').disabled=saving||busy();$('artwork').replaceChildren();let url='';if(row.local_cover)url='/proposed-cover/'+row.id;else if(row.has_cover)url='/cover/'+row.id;else if(candidate?.artwork)url=candidate.artwork;if(url){const img=node('img');img.src=url;img.alt='Copertina del brano';img.referrerPolicy='no-referrer';$('artwork').append(img);}else $('artwork').append(node('div','♫','art-placeholder'));$('cover-note').textContent=row.has_cover&&row.write_result?'Copertina incorporata nel file e verificata dopo la scrittura.':row.local_cover?'Copertina scelta da te: verrà incorporata alla conferma finale.':row.review.cover_pending?'Copertina recuperata: verrà incorporata alla conferma finale.':row.has_cover?'La copertina presente viene conservata.':candidate?.artwork?'Anteprima del catalogo; per incorporare una copertina puoi scegliere un file JPEG o PNG.':'Nessuna copertina trovata.';}
function openEditor(id){
 if(busy()||saving)return;editorId=id;const row=currentRow();choice=row.selected||0;draft={...row.review.values};tell('',true);
 $('editor-title').textContent=row.review.values.title||row.identity.title||row.filename;$('editor-file').textContent=row.path;
 $('editor-problems').replaceChildren();if(row.review.problems.length){const box=node('div',undefined,'problem-list');box.append(node('strong',`${row.review.problems.length} cose da controllare · puoi anche ignorarle`));const ul=node('ul');for(const problem of row.review.problems)ul.append(node('li',problem.message));box.append(ul);$('editor-problems').append(box);}
 $('candidate').replaceChildren();if(!row.candidates.length){const option=node('option','Nessuna pubblicazione trovata');$('candidate').append(option);}row.candidates.forEach((c,index)=>{const op=node('option',`${c.proposed.artist} — ${c.proposed.title} · ${c.proposed.album||'Album non disponibile'} · ${formatTime(c.duration)} · ${c.source}`);op.value=index;$('candidate').append(op);});$('candidate').value=String(choice);$('candidate').disabled=!row.candidates.length;
 drawFields();drawCandidate();drawArtwork();
 const term=encodeURIComponent((row.identity.artist+' '+row.identity.title).trim());$('web-links').replaceChildren();for(const [name,url]of [['Google','https://www.google.com/search?q='+term],['Discogs','https://www.discogs.com/search/?q='+term+'&type=all'],['Beatport','https://www.beatport.com/search?q='+term],['Traxsource','https://www.traxsource.com/search?term='+term],['Bandcamp','https://bandcamp.com/search?q='+term],['YouTube','https://www.youtube.com/results?search_query='+term]]){const link=safeLink(url,name+' ↗');if(link)$('web-links').append(link);}
 $('research-log').replaceChildren();for(const report of row.research||[]){const line=node('div',`${report.name}: ${report.status==='error'?'non disponibile — '+report.error:'consultata'+(report.count!==undefined?' · '+report.count+' risultati':'')}`,'research-row '+report.status);const link=safeLink(report.url,'Fonte ↗');if(link)line.append(node('br'),link);$('research-log').append(line);}if(!row.research?.length)$('research-log').append(node('p','Nessuna ricerca registrata in questa sessione.'));
 const disabled=false;for(const id of ['save-row','keep-row','reset-row','cover-file'])$(id).disabled=disabled;$('reset-row').hidden=!row.manual||!Object.keys(row.manual).length&&row.decision!=='skipped';if(row.write_result)tell('Tag già scritti. Puoi preparare altre modifiche o aggiungere una copertina e poi confermare nuovamente.',true);
 $('editor').showModal();
}
async function saveRow(decision){
 if(saving)return;readDraft();const payload={id:editorId,selected:choice,decision,manual:decision==='accepted'?{...draft}:{}};
 saving=true;for(const id of ['save-row','keep-row','reset-row'])$(id).disabled=true;$('save-row').textContent='Salvataggio…';
 try{await api('decision',payload);await refresh(true);$('editor').close();tell(decision==='skipped'?'Il brano resterà esattamente com’è.':decision==='pending'?'Ripristinata la proposta automatica.':'Modifiche preparate. Saranno scritte solo con la conferma finale.');}
 finally{saving=false;$('save-row').textContent='Salva modifiche';for(const id of ['save-row','keep-row','reset-row'])$(id).disabled=false;}
}
$('choose').onclick=()=>act(async()=>{const result=await api('folder');if(result.folder)$('folder').value=result.folder;});
$('scan').onclick=()=>act(async()=>{if(!$('folder').value.trim())throw Error('Scegli una cartella per iniziare.');view=null;await api('scan',{folder:$('folder').value.trim(),recursive:$('recursive').checked});await refresh(true);if(!busy()&&state.rows.length){view='options';syncOptions();render();}});
$('restore').onclick=()=>act(async()=>{await api('restore');view=null;await refresh(true);syncOptions();$('folder').value=state.folder;});
$('search').onclick=()=>act(async()=>{const o=options();if(!o.providers.length)throw Error('Scegli almeno una fonte di ricerca.');view=null;filter='all';page=0;await api('search',o);await refresh(true);});
$('back-folder').onclick=()=>{view='folder';render();};$('back-options').onclick=()=>{view='options';syncOptions();render();};
$('cancel').onclick=()=>act(async()=>{await api('cancel');await refresh(true);});
$('commit').onclick=()=>act(async()=>{await api('commit');await refresh(true);});
$('filter').oninput=()=>{page=0;render();};document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.filter;page=0;render();});$('previous').onclick=()=>{page--;render();};$('next').onclick=()=>{page++;render();};
$('close-editor').onclick=()=>$('editor').close();$('save-row').onclick=()=>act(()=>saveRow('accepted'),true);$('keep-row').onclick=()=>act(()=>saveRow('skipped'),true);$('reset-row').onclick=()=>act(()=>saveRow('pending'),true);
$('candidate').onchange=()=>{readDraft();choice=Number($('candidate').value);drawCandidate();drawArtwork();};
$('use-candidate').onclick=()=>{readDraft();const c=currentRow().candidates[choice];if(!c)return;for(const [field,value]of Object.entries(c.proposed))if(value&&field in labels)draft[field]=value;drawFields();tell('Dati riportati nei campi. Puoi modificarli prima di salvare.',true);};
$('use-cover').onclick=()=>act(async()=>{readDraft();await api('cover-candidate',{id:editorId,selected:choice});await refresh(true);drawArtwork();tell('Copertina preparata per la scrittura finale.',true);},true);
$('cover-file').onchange=()=>act(async()=>{const file=$('cover-file').files[0];if(!file)return;if(file.size>5000000)throw Error('Scegli un’immagine JPEG o PNG sotto i 5 MB.');readDraft();const image=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('Impossibile leggere l’immagine.'));reader.readAsDataURL(file);});await api('cover',{id:editorId,image});await refresh(true);drawArtwork();tell('Copertina preparata. Verrà scritta con la conferma finale.',true);$('cover-file').value='';},true);
(async()=>{try{token=(await(await fetch('/api/config')).json()).token;await refresh(true);syncOptions();setInterval(()=>refresh().catch(e=>tell('Connessione al programma interrotta: '+e.message)),1400);}catch(e){tell(e.message);}})();

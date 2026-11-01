const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function setup(){
 const nodes=new Map();
 const document={getElementById(id){if(!nodes.has(id))nodes.set(id,{hidden:true,disabled:false,textContent:'',value:'',open:false,querySelectorAll:()=>[],close(){this.open=false;}});return nodes.get(id);},querySelectorAll:()=>[]};
 const code=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
 const context=vm.createContext({document,console,setInterval:()=>{}});
 vm.runInContext(code.slice(0,code.lastIndexOf('(async()=>{try{token=')),context);
 const backend={phase:'ready',step:4,rows:['a','b'].map(id=>({id,filename:id+'.mp3',candidates:[],decision:'pending',review:{status:'problem',values:{title:'Old'},problems:[{field:'cover'}]}}))};
 context.fixture=structuredClone(backend);
 vm.runInContext("render=()=>{};token='test';state=fixture;",context);
 let revision=0;const calls=[];
 context.fetch=async(url,options)=>{
  if(url==='/api/decision'){const data=JSON.parse(options.body);calls.push(data);const row=backend.rows.find(r=>r.id===data.id);row.decision=data.decision;row.manual=data.manual;row.review.status=data.decision==='skipped'?'kept':'edited';revision++;return{ok:true,json:async()=>({ok:true})};}
  return{ok:true,json:async()=>url==='/api/status'?{revision}:structuredClone(backend)};
 };
 return{context,nodes,backend,calls,run:code=>vm.runInContext(code,context)};
}
test('two different tracks can be saved successively without approval gates',async()=>{
 const h=setup();
 for(const id of ['a','b']){h.run(`editorId='${id}';draft={title:'Edited ${id}'};choice=0;$('editor').open=true;`);await h.run("saveRow('accepted')");assert.equal(h.nodes.get('editor').open,false);assert.equal(h.nodes.get('save-row').disabled,false);}
 assert.deepEqual(h.calls.map(c=>c.id),['a','b']);assert.ok(h.backend.rows.every(r=>r.decision==='accepted'));
});
test('save waits for an older poll and refreshes the latest manual edit',async()=>{
 const h=setup();let release;const original=h.context.fetch;let first=true;
 h.context.fetch=async(url,options)=>{if(url==='/api/state'&&first){first=false;const old=structuredClone(h.backend);return{ok:true,json:()=>new Promise(resolve=>release=()=>resolve(old))};}return original(url,options);};
 const polling=h.run('refresh()');await new Promise(setImmediate);h.run("editorId='a';draft={title:'New'};$('editor').open=true;");const save=h.run("saveRow('accepted')");await new Promise(setImmediate);release();await Promise.all([save,polling]);assert.equal(h.run("state.rows[0].manual.title"),'New');
});
test('failed save remains in the editor, shows the error and can be retried',async()=>{
 const h=setup(),original=h.context.fetch;h.run("editorId='a';draft={title:'New'};$('editor').open=true;");
 h.context.fetch=async(url,options)=>url==='/api/decision'?{ok:false,json:async()=>({error:'Salvataggio non riuscito'})}:original(url,options);
 await h.run("act(()=>saveRow('accepted'),true)");assert.equal(h.nodes.get('editor').open,true);assert.equal(h.nodes.get('editor-notice').textContent,'Salvataggio non riuscito');assert.equal(h.nodes.get('save-row').disabled,false);
 h.context.fetch=original;await h.run("saveRow('accepted')");assert.equal(h.backend.rows[0].manual.title,'New');
});
test('leave unchanged clears the staged edits without writing tags',async()=>{
 const h=setup();h.run("editorId='a';draft={title:'Unwanted'};$('editor').open=true;");await h.run("saveRow('skipped')");assert.equal(h.calls[0].decision,'skipped');assert.deepEqual(h.calls[0].manual,{});assert.equal(h.backend.rows[0].review.status,'kept');
});
test('problem filtering never hides a manual edit that still lacks a cover',()=>{
 const h=setup();h.run("state.rows[0].review.status='edited';state.rows[1].review.status='kept';");assert.equal(h.run("matched(state.rows[0],'problem')"),true);assert.equal(h.run("matched(state.rows[1],'problem')"),false);assert.equal(h.run("matched(state.rows[0],'all')"),true);
});
test('saving captures every visible field, including an explicit blank',async()=>{
 const h=setup();h.run("editorId='a';draft={};$('fields');$('editor').open=true;");h.nodes.get('fields').querySelectorAll=()=>[{value:'Manual title',dataset:{field:'title'}},{value:'',dataset:{field:'genre'}}];await h.run("saveRow('accepted')");assert.equal(h.calls[0].manual.title,'Manual title');assert.equal(h.calls[0].manual.genre,'');
});

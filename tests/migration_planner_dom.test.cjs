const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
test('snapshot import/preview is read-only, evidence renders safely, editing invalidates export',async()=>{
  const dom=new JSDOM(fs.readFileSync('web_ui/templates/migration_planner.html','utf8'),{runScripts:'outside-only',url:'http://localhost/migration-planner'});
  const w=dom.window,calls=[];
  w.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>url.endsWith('/example')?{version:1,candidates:[]}:{notice:'not authorization',source:'operator',candidates:[{label:'<img onerror=bad>',blockers:['exact hash unknown'],evidence_complete:false}],additional_transfer_bytes:1000,execution_authorized:false}};};
  w.eval(fs.readFileSync('web_ui/static/js/migration_planner.js','utf8'));
  const $=id=>w.document.getElementById(id);
  await $('example').onclick();assert.equal(JSON.parse($('snapshot').value).version,1);
  await $('preview').onclick();assert.equal($('export').disabled,false);
  assert.equal($('rows').querySelector('img'),null);assert.match($('rows').textContent,/Blocked/);
  assert.match($('status').textContent,/not authorization/);
  assert.deepEqual(calls.map(c=>c.url),['/api/migration-planner/example','/api/migration-planner/preview']);
  assert.ok(calls[1].options.headers['X-CSRF-Token']);
  $('snapshot').oninput();assert.equal($('export').disabled,true);
  dom.window.close();
});

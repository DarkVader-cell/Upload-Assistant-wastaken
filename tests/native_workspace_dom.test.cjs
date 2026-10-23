/* Run with NODE_PATH pointing at dependencies in tests/ui/package.json. No network/uploads. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const babel = require('@babel/core');
const dom = new JSDOM('<!doctype html><div id="root"></div>', {url:'http://localhost/'});
global.window=dom.window; global.document=dom.window.document; global.HTMLElement=dom.window.HTMLElement;
global.IS_REACT_ACT_ENVIRONMENT=true;
const React=require('react'); global.React=React;
const {createRoot}=require('react-dom/client');
const {act}=React;
const code=babel.transformSync(fs.readFileSync(path.join(__dirname,'../web_ui/static/js/native_workspaces.js'),'utf8'),{configFile:false,babelrc:false,plugins:[[require.resolve('@babel/plugin-transform-react-jsx'), {runtime:'classic'}]]}).code;
// Only compile and execute the local UI component in this synthetic DOM.
require('node:vm').runInThisContext(code);
const delay=(ms)=>new Promise(resolve=>setTimeout(resolve,ms));
const settle=()=>act(async()=>{await delay(260);});
const label=(text)=>document.querySelector(`[aria-label="${text}"]`);
const button=(text)=>Array.from(document.querySelectorAll('button')).find(b=>b.textContent.startsWith(text));

test('native checkbox filters auto-update, facets combine, bulk retry and reset work', async()=>{
  const dataset=Array.from({length:205},(_,i)=>({id:String(i),release_name:'Film '+i,source_path:'/dummy/'+i,category:i%2?'TV':'MOVIE',resolution:i%2?'1080p':'2160p',trackers:['A','B'],successful_trackers:i%2?[]:['A'],failed_trackers:['B'],status:'completed',attempts:1}));
  const requests=[],prepared=[];
  const apiFetch=async(url,options)=>{
    requests.push(url);
    if(url.endsWith('/retry-plan')){
      const body=JSON.parse(options.body);
      return {ok:true,json:async()=>({plans:body.ids.map(id=>({id,path:'/dummy/'+id,trackers:body.trackers})),skipped:[]})};
    }
    const p=new URLSearchParams(url.split('?')[1]),targets=p.getAll('tracker'),mode=p.get('mode');
    let rows=dataset.filter(r=>!targets.length||targets.some(t=>mode==='uploaded'?r.successful_trackers.includes(t):mode==='failed'?r.failed_trackers.includes(t):mode==='unattempted'?!r.trackers.includes(t):!r.successful_trackers.includes(t)));
    if(p.get('category'))rows=rows.filter(r=>r.category===p.get('category'));
    if(p.get('resolution'))rows=rows.filter(r=>r.resolution===p.get('resolution'));
    if(p.get('q'))rows=rows.filter(r=>r.release_name.includes(p.get('q')));
    const total=rows.length,start=Number(p.get('offset'));
    return {ok:true,json:async()=>({rows:rows.slice(start,start+100),total,trackers:['A','B','C'],facets:{category:['MOVIE','TV'],resolution:['1080p','2160p']},tracker_counts:{A:{uploaded:103}}})};
  };
  const root=createRoot(document.getElementById('root'));
  await act(async()=>{root.render(React.createElement(window.UANativeWorkspace,{workspace:'library',apiFetch,onRetry:plans=>prepared.push(...plans)}));});
  await settle();
  assert.match(document.querySelector('[role="status"]').textContent,/205 releases/);
  assert.ok(label('Filter tracker A'));
  await act(async()=>label('Filter tracker A').click());await settle();
  assert.match(document.querySelector('[role="status"]').textContent,/102 releases/);
  assert.ok(label('Remove tracker A'));
  await act(async()=>{const select=label('Tracker result');select.value='uploaded';select.dispatchEvent(new window.Event('change',{bubbles:true}));});await settle();
  assert.match(document.querySelector('[role="status"]').textContent,/103 releases/);
  await act(async()=>{const select=label('Category');select.value='TV';select.dispatchEvent(new window.Event('change',{bubbles:true}));});await settle();
  assert.match(document.querySelector('[role="status"]').textContent,/0 releases/);
  await act(async()=>button('Reset filters').click());await settle();
  assert.match(document.querySelector('[role="status"]').textContent,/205 releases/);
  await act(async()=>label('Filter tracker B').click());await settle();
  await act(async()=>button('Select all filtered').click());
  assert.match(button('Prepare retry').textContent,/205/);
  await act(async()=>button('Prepare retry').click());
  assert.equal(prepared.length,205);
  assert.ok(prepared.every(p=>p.trackers.join(',')==='B'));
  assert.equal(requests.filter(url=>url.endsWith('/retry-plan')).length,5);
  await act(async()=>label('Remove tracker B').click());await settle();
  assert.match(button('Prepare retry').textContent,/\(0\)/);
  await act(async()=>root.unmount());
});


test('remote workspace shows ETA and submits pause/resume/cancel/discard controls',async()=>{
  const transfer={id:'a'.repeat(32),name:'Dummy transfer',state:'copying',bytes_total:1000,bytes_sent:400,bytes_per_second:50,eta_seconds:12,can_control:true,can_discard:false,protocol:'rsync'};
  const actions=[];
  window.confirm=()=>true;
  const apiFetch=async(url,options)=>{
    if(options?.method==='POST'){
      const body=JSON.parse(options.body);actions.push({url,...body});
      if(body.action==='pause'){transfer.state='paused';transfer.eta_seconds=null;}
      if(body.action==='resume'){transfer.state='copying';transfer.eta_seconds=12;}
      if(body.action==='cancel'){transfer.state='interrupted';transfer.can_control=false;transfer.can_discard=true;transfer.eta_seconds=null;}
      if(body.action==='discard'){transfer.state='discarded';transfer.can_discard=false;}
    }
    return {ok:true,json:async()=>({backends:{dummy:{background_ready:true,transfers:[{...transfer}],jobs:{},operations:[]}}})};
  };
  const root=createRoot(document.getElementById('root'));
  await act(async()=>root.render(React.createElement(window.UANativeWorkspace,{workspace:'remote',apiFetch,onRetry:()=>{}})));
  await settle();
  assert.match(document.body.textContent,/ETA 0m 12s/);
  await act(async()=>button('Pause transfer').click());await settle();
  assert.ok(button('Resume transfer'));
  await act(async()=>button('Resume transfer').click());await settle();
  assert.ok(button('Pause transfer'));
  await act(async()=>button('Cancel transfer').click());await settle();
  assert.ok(button('Remove partial VPS data'));
  await act(async()=>button('Remove partial VPS data').click());await settle();
  assert.deepEqual(actions.map(a=>a.action),['pause','resume','cancel','discard']);
  assert.ok(actions.every(a=>a.stage==='a'.repeat(32)&&a.backend==='dummy'));
  assert.equal(actions[0].url,'/api/remote-upload/control');
  await act(async()=>root.unmount());
});


test('ready failed stage can return to upload form without a new transfer request',async()=>{
  const id='b'.repeat(32),reused=[];
  const transfer={id,name:'Existing copy',state:'ready',source:'/dummy/source.mkv',bytes_total:4,bytes_sent:4,can_reuse:true,trackers:['PTP'],return_after:3600,resume_args:'--remote-stage '+id};
  window.confirm=()=>true;
  const apiFetch=async(_url,options)=>{
    assert.notEqual(options?.method,'POST','Preparing reuse must not start a transfer');
    return {ok:true,json:async()=>({backends:{dummy:{background_ready:true,transfers:[transfer],jobs:{},operations:[]}}})};
  };
  const root=createRoot(document.getElementById('root'));
  await act(async()=>root.render(React.createElement(window.UANativeWorkspace,{workspace:'remote',apiFetch,onRetry:()=>{},onResume:(backend,stage)=>reused.push({backend,stage})})));
  await settle();
  await act(async()=>button('Use staged copy').click());
  assert.equal(reused.length,1);
  assert.equal(reused[0].backend,'dummy');assert.equal(reused[0].stage.id,id);
  await act(async()=>root.unmount());
});

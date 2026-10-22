const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(){this.value='';this.checked=false;this.children=[];this.textContent='';this.disabled=false;}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(){}
  get options(){return this.children;}
  get selectedOptions(){return this.children.filter(o=>o.selected);}
}
async function setup({failAt=0}={}){
  const ids=['query','mode','category','resolution','errors','trackers','message','rows','count','previous','next','filter','select-page','clear','select-all','import','retry'];
  const dom=Object.fromEntries(ids.map(id=>[id,new Element()]));dom.mode.value='missing';
  const calls=[]; let executes=0;
  const dataset=Array.from({length:205},(_,i)=>({id:String(i),release_name:i===0?'<img src=x onerror=alert(1)>':'Film '+i,category:'MOVIE',resolution:'2160p',successful_trackers:[],failed_trackers:['B'],status:'failed',attempts:1}));
  const fetch=async(url,options)=>{
    calls.push({url,options});
    if(url.startsWith('/api/upload-library?')){
      const p=new URLSearchParams(url.split('?')[1]);const offset=Number(p.get('offset'));
      return {ok:true,json:async()=>({rows:dataset.slice(offset,offset+100),total:dataset.length,trackers:['A','B']})};
    }
    if(url.endsWith('/retry-plan')){
      const data=JSON.parse(options.body);assert.ok(data.ids.length<=50);
      return {ok:true,json:async()=>({plans:data.ids.map(id=>({id,path:'/dummy/'+id,trackers:['B'],label:'Dummy'})),skipped:[]})};
    }
    if(url==='/api/execute'){
      executes++;
      return {ok:executes!==failAt,body:null};
    }
    throw Error('Unexpected route '+url);
  };
  const source=fs.readFileSync(path.join(__dirname,'../web_ui/static/js/upload_library.js'),'utf8');
  await vm.runInNewContext(source,{document:{getElementById:id=>dom[id],querySelector:()=>({content:'csrf-dummy'}),createElement:()=>new Element()},fetch,URLSearchParams,crypto:{randomUUID:()=>String(executes)},confirm:()=>true});
  return {dom,calls};
}

test('renders text safely; selection covers all pages and clear works',async()=>{
  const {dom}=await setup();
  assert.equal(dom.rows.children.length,100);
  assert.equal(dom.rows.children[0].children[1].textContent,'<img src=x onerror=alert(1)>');
  dom['select-page'].onclick();assert.match(dom.count.textContent,/100 selected/);
  await dom['select-all'].onclick();assert.match(dom.count.textContent,/205 selected/);
  dom.clear.onclick();assert.match(dom.count.textContent,/0 selected/);
});

test('bulk retry batches 205 IDs; target selection and CSRF propagated',async()=>{
  const {dom,calls}=await setup();dom.trackers.children[1].selected=true;
  await dom['select-all'].onclick();await dom.retry.onclick();
  const plans=calls.filter(c=>c.url.endsWith('/retry-plan'));
  assert.equal(plans.length,5);
  assert.equal(calls.filter(c=>c.url==='/api/execute').length,205);
  assert.equal(plans[0].options.headers['X-CSRF-Token'],'csrf-dummy');
  const execution=JSON.parse(calls.find(c=>c.url==='/api/execute').options.body);
  assert.equal(execution.args,'-tk B --unattended');assert.equal(execution.schedule,true);
  assert.match(dom.count.textContent,/0 selected/);
});

test('partial submission failure retains only unsubmitted selections',async()=>{
  const {dom,calls}=await setup({failAt:2});dom.trackers.children[1].selected=true;
  dom['select-page'].onclick();await dom.retry.onclick();
  assert.match(dom.count.textContent,/99 selected/);
  assert.equal(calls.filter(c=>c.url==='/api/execute').length,2);
  assert.match(dom.message.textContent,/rejected/);
  assert.equal(dom.retry.disabled,false);
});

test('filters are encoded and retries refuse empty target selection',async()=>{
  const {dom,calls}=await setup();dom.query.value='A&B';dom.category.value='MOVIE';dom.errors.checked=true;dom.trackers.children[1].selected=true;
  await dom['select-all'].onclick();
  const url=calls.filter(c=>c.url.startsWith('/api/upload-library?')).at(-1).url;
  const params=new URLSearchParams(url.split('?')[1]);assert.equal(params.get('q'),'A&B');assert.equal(params.get('tracker'),'B');assert.equal(params.get('errors'),'1');
  dom.trackers.children[1].selected=false;
  await dom.retry.onclick();assert.match(dom.message.textContent,/Select releases and target trackers/);
});

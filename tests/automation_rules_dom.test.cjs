const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const tick = () => new Promise(resolve => setTimeout(resolve,10));
test('visual rules edit literal conditions/actions, preview and save without executing',async()=>{
  const dom = new JSDOM(fs.readFileSync('web_ui/templates/automation_rules.html','utf8'),{runScripts:'outside-only',url:'http://localhost/automation-rules'});
  const w=dom.window,calls=[]; let schema={version:1,rules:[],overrides:{}};
  w.fetch=async(url,options)=>{
    calls.push({url,options}); let data;
    if(url.endsWith('/candidates')) data={candidates:[{id:'a'.repeat(64),label:'<img onerror=bad>'}]};
    else if(url.endsWith('/preview')) data={requires_confirmation:true,proposals:{requirements:['screenshot-review']}};
    else if(options?.method){schema=JSON.parse(options.body).schema;data={schema,revision:'next'};}
    else data={schema,revision:'initial',fields:['category','resolution'],operators:['equals','in','contains'],requirements:['screenshot-review'],references:{suggest_trackers:['A'],preset:['existing'],client_profile:['local']}};
    return {ok:true,json:async()=>data};
  };
  w.eval(fs.readFileSync('web_ui/static/js/automation_rules.js','utf8'));await tick();
  const $=id=>w.document.getElementById(id);
  assert.equal(w.document.querySelector('img'),null);
  $('add').onclick();
  const inputs=$('rules').querySelectorAll('input');
  inputs[0].value='Literal rule';inputs[0].oninput();
  inputs[3].value='MOVIE';inputs[3].oninput();
  await $('preview').onclick();
  const preview=JSON.parse(calls.at(-1).options.body);
  assert.equal(preview.schema.rules[0].name,'Literal rule');
  assert.equal(preview.schema.rules[0].conditions[0].value,'MOVIE');
  assert.match($('result').textContent,/requires_confirmation/);
  await $('save').onclick();
  assert.equal(calls.at(-1).url,'/api/automation-rules');
  assert.ok(calls.at(-1).options.headers['X-CSRF-Token']);
  assert.equal(calls.some(c=>/execute|transfer|submit/.test(c.url)),false);
  dom.window.close();
});

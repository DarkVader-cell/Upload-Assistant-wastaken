const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const parser=require('../web_ui/static/js/node_modules/@babel/parser');
const read=(name)=>fs.readFileSync(path.join(__dirname,'../web_ui/static/js',name),'utf8');

test('main app and native workspaces are valid JSX',()=>{
  for(const name of ['app.js','native_workspaces.js'])assert.ok(parser.parse(read(name),{sourceType:'script',plugins:['jsx']}));
});
test('native navigation and upload destination integrate without iframe',()=>{
  const app=read('app.js'),modules=read('native_workspaces.js');
  assert.match(app,/onWorkspace=\{setWorkspace\}/);
  assert.match(app,/Upload destination/);
  assert.match(app,/remote_backend: uploadDestination/);
  assert.match(app,/remote_trackers: uploadDestination/);
  assert.match(app,/setSelectedTrackers\(new Set\(plans.flatMap/);
  assert.match(modules,/apiFetch\(url/);
  assert.match(modules,/onRetry\(plans\)/);
  assert.doesNotMatch(modules,/<iframe/);
});

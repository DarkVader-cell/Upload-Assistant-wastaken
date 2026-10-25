const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

test('slot GUI retains per-torrent reasons, evidence and protected/context separation', () => {
  const scope = {window:{}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web_ui/static/js/run_gui_state.js'),'utf8'),scope);
  const api = scope.window.UARunGui;
  const state = api.reduceRunGuiEvent(api.createRunGuiState(),{type:'gui',data:{kind:'slot',tracker:'LUMINARR',verdict:'review',reason:'Size variance needs review',why:'Missing exact size',conflicts:[{id:'42',name:'Existing release',link:'https://luminarr.me/torrents/42',traits:'1080p; H.265',reason:'Rule 8.6.1.1: size ratio 1.1000 < 1.2000'}],protected_ids:['42'],requirements:['Provide size/comparison evidence'],related_releases:[{id:'7',name:'Other cut',link:'https://luminarr.me/torrents/7',reason:'Context only'}]}});
  const slot = Object.values(state.slots)[0];
  assert.equal(slot.conflicts[0].id,'42');
  assert.equal(slot.conflicts[0].protected,true);
  assert.match(slot.conflicts[0].reason,/1\.1000/);
  assert.equal(slot.conflicts[0].traits,'1080p; H.265');
  assert.equal(slot.requirements[0],'Provide size/comparison evidence');
  assert.equal(slot.relatedReleases[0].id,'7');
  assert.equal(slot.conflicts.length,1);
});

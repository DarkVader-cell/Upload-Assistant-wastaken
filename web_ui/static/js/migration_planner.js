/* Snapshot imports are data, never paths or executable commands. */
(() => {
  const $ = id => document.getElementById(id);
  let lastPlan = null, generation = 0;
  function invalidate() {lastPlan = null; generation++; $('export').disabled = true;}
  function error(e) {$('status').textContent = e.message;}
  async function api(url, body) {
    const response = await fetch(url, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content}, body:JSON.stringify(body)});
    const data = await response.json(); if (!response.ok) throw Error(data.error || 'Snapshot request failed'); return data;
  }
  $('snapshot').oninput = invalidate;
  $('example').onclick = async () => {try {invalidate(); $('snapshot').value = JSON.stringify(await api('/api/migration-planner/example'),null,2); $('status').textContent = 'Example loaded. Evidence deliberately incomplete; not live status.';} catch (e) {error(e);}};
  $('import').onchange = async e => {try {invalidate(); const file = e.target.files[0]; if (!file) return; if (file.size > 2097152) throw Error('Snapshot exceeds 2 MiB'); const value = JSON.parse(await file.text()); $('snapshot').value = JSON.stringify(value,null,2); $('status').textContent = 'Snapshot loaded locally. Preview to validate; nothing runs.';} catch (err) {error(err);}};
  $('preview').onclick = async () => {
    invalidate(); const current = generation;
    try {
      const data = await api('/api/migration-planner/preview',JSON.parse($('snapshot').value));
      if (current !== generation) return;
      lastPlan = data; $('export').disabled = false; $('status').textContent = data.notice;
      const summary = document.createElement('pre'); summary.textContent = JSON.stringify({source:data.source, observed_at:data.observed_at, age_seconds:data.age_seconds, blockers:data.blockers, destination:data.destination, unique_payloads:data.unique_payloads, duplicate_candidates_ignored:data.duplicate_candidates_ignored, additional_transfer_bytes:data.additional_transfer_bytes, verified_snapshot_reuse_bytes:data.verified_snapshot_reuse_bytes, available_after_reservations_bytes:data.available_after_reservations_bytes, shortage_bytes:data.shortage_bytes, estimated_transfer_seconds:data.estimated_transfer_seconds, estimate_kind:data.estimate_kind}, null, 2); $('summary').replaceChildren(summary); $('rows').replaceChildren();
      data.candidates.forEach(row => {const article = document.createElement('article'), title = document.createElement('h2'), evidence = document.createElement('pre'); title.textContent = row.label + ' — ' + (row.evidence_complete ? 'Evidence complete (planning only)' : 'Blocked / unknown evidence'); evidence.textContent = JSON.stringify(row,null,2); article.append(title,evidence); $('rows').append(article);});
    } catch (e) {error(e);}
  };
  $('export').onclick = () => {if (!lastPlan) return; const url = URL.createObjectURL(new Blob([JSON.stringify(lastPlan,null,2)],{type:'application/json'})); const link = document.createElement('a'); link.href = url; link.download = 'ua-readonly-plan-v1.json'; link.click(); URL.revokeObjectURL(url);};
})();

/* Slot decisions are version-bound. No group regeneration and no remote fetch. */
(() => {
  const $ = id => document.getElementById(id);
  const session = new URLSearchParams(location.search).get('session_id') || '';
  const query = '?session_id=' + encodeURIComponent(session);
  let version = 0, busy = false;
  async function api(url, body) {
    const response = await fetch(url, body ? {method:'POST', headers:{'Content-Type':'application/json', 'X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content}, body:JSON.stringify(body)} : {});
    const data = await response.json(); if (!response.ok) throw Error(data.error || 'Review request failed'); return data;
  }
  function error(e) {$('status').textContent = e.message;}
  async function load() {
    const generation = ++version;
    const data = await api('/api/screenshot-intelligence' + query);
    if (generation !== version) return;
    $('status').textContent = data.notice + (data.truncated ? ' Only the first 100 slots are analyzed.' : '');
    $('images').replaceChildren();
    data.images.forEach(row => {
      const article = document.createElement('article'); article.id = 'slot-' + row.id;
      const title = document.createElement('h2'); title.textContent = `Slot ${row.index + 1} · ${row.group} · ${row.decision}`;
      article.append(title);
      if (row.status === 'scored') {const img = document.createElement('img'); img.src = '/api/screenshot-intelligence/' + encodeURIComponent(row.id) + '/thumbnail' + query; img.alt = `Local slot ${row.index + 1}`; img.width = 192; article.append(img);}
      const info = document.createElement('pre'); info.textContent = JSON.stringify({status:row.status, reasons:row.reasons, brightness:row.brightness, detail:row.detail, edge_proxy:row.edge_proxy, duplicate_of:row.duplicate_of, text_or_credits:row.text_or_credits}, null, 2); article.append(info);
      row.alternatives.forEach(id => {const link = document.createElement('a'); link.href = '#slot-' + id; link.textContent = 'Compare ' + id.slice(-6) + ' '; article.append(link);});
      ['accepted','rejected','unreviewed'].forEach(decision => {
        const button = document.createElement('button'); button.textContent = decision; button.disabled = !row.version;
        button.onclick = async () => {if (busy) return; busy = true; try {await api('/api/screenshot-intelligence/decision' + query, {id:row.id, version:row.version, decision}); await load();} catch (e) {error(e);} finally {busy = false;}}; article.append(button);
      });
      const refill = document.createElement('button'); refill.textContent = 'Refill rejected slot'; refill.disabled = row.decision !== 'rejected';
      refill.onclick = async () => {
        if (busy || row.decision !== 'rejected' || !window.confirm('Capture one replacement for this rejected slot? Accepted slots and target count will not be changed.')) return;
        busy = true; refill.disabled = true;
        try {
          const current = await api('/api/screenshot-intelligence' + query);
          const slot = current.images.find(i => i.id === row.id);
          if (!slot || slot.decision !== 'rejected' || slot.version !== row.version) throw Error('Slot decision or image changed; refresh first');
          await api('/api/execution_screenshots/' + encodeURIComponent(row.id) + '/refill', {session_id:session});
          await load();
        } catch (e) {error(e);} finally {busy = false;}
      }; article.append(refill); $('images').append(article);
    });
  }
  $('refresh').onclick = () => load().catch(error);
  load().catch(error);
})();

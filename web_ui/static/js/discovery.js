/* Discovery never executes uploads. All untrusted evidence is rendered as text. */
(() => {
  const $ = id => document.getElementById(id);
  const selected = new Set();
  let offset = 0, plans = [], version = 0;
  const targets = () => Array.from(document.querySelectorAll('#trackers input:checked'), e => e.value);
  async function api(url, body) {
    const response = await fetch(url, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content}, body: JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Request failed');
    return data;
  }
  function message(error) { $('status').textContent = error.message; }
  function invalidate() { plans = []; $('queue').disabled = true; $('plan').textContent = ''; }
  async function load() {
    const generation = ++version;
    invalidate();
    const params = new URLSearchParams(new FormData($('filters')));
    targets().forEach(t => params.append('tracker', t));
    params.set('offset', offset); params.set('limit', 100);
    const data = await api('/api/discovery?' + params);
    if (generation !== version) return;
    $('status').textContent = `${data.total} candidates · snapshot ${data.updated_at ? new Date(data.updated_at * 1000).toLocaleString() : 'not loaded; refresh first'}${data.truncated ? ' · bounded to 5000 records' : ''}`;
    if (!$('trackers').querySelector('input')) {
      data.trackers.forEach(t => { const label = document.createElement('label'), input = document.createElement('input'); input.type = 'checkbox'; input.value = t; input.onchange = () => {selected.clear(); invalidate();}; label.append(input, document.createTextNode(t)); $('trackers').append(label); });
    }
    const previousFilters = new FormData($('filters'));
    $('metadata-filters').replaceChildren();
    Object.entries(data.facets).forEach(([field, values]) => { const label = document.createElement('label'), select = document.createElement('select'); select.name = field; select.append(new Option('All ' + field, '')); values.forEach(v => select.append(new Option(v, v))); select.value = previousFilters.get(field) || ''; label.append(field + ' ', select); $('metadata-filters').append(label); });
    $('rows').replaceChildren();
    data.rows.forEach(row => {
      const article = document.createElement('article'), label = document.createElement('label'), input = document.createElement('input'), evidence = document.createElement('pre');
      input.type = 'checkbox'; input.checked = selected.has(row.id); input.onchange = () => {input.checked ? selected.add(row.id) : selected.delete(row.id); invalidate();};
      label.append(input, document.createTextNode(row.release_name));
      evidence.textContent = JSON.stringify({metadata: Object.fromEntries(['category','resolution','codec','language','edition'].map(f => [f, row[f]])), evidence: row.evidence, blockers: row.blockers, work: row.estimated_work, ranking: row.ranking_reasons, targets: row.proposed_trackers}, null, 2);
      const details = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = row.preparation_ready ? 'Ready to prepare (verification still required)' : 'Review evidence / blockers'; details.append(summary, evidence); article.append(label, details); $('rows').append(article);
    });
    $('previous').disabled = offset === 0; $('next').disabled = offset + 100 >= data.total;
  }
  $('filters').onchange = () => {version++; selected.clear(); invalidate();};
  $('filters').onsubmit = e => {e.preventDefault(); offset = 0; selected.clear(); load().catch(message);};
  $('refresh').onclick = async () => {try {await api('/api/discovery/refresh', {}); offset = 0; selected.clear(); load().catch(message);} catch (e) {message(e);}};
  $('previous').onclick = () => {offset = Math.max(0, offset - 100); load().catch(message);};
  $('next').onclick = () => {offset += 100; load().catch(message);};
  $('preview').onclick = async () => {const generation = ++version; try {const data = await api('/api/discovery/preview', {ids: Array.from(selected), trackers: targets()}); if (generation !== version) return; plans = data.plans; $('plan').textContent = JSON.stringify(data, null, 2); $('queue').disabled = !plans.length;} catch (e) {message(e);}};
  $('queue').onclick = async () => {
    if (!plans.length || !window.confirm('Create a queue for reviewed preparation only? Nothing will run until you start it in Upload. Normal verification and approval remain required.')) return;
    $('queue').disabled = true;
    try {
      const data = await api('/api/save_queue', {items: plans.map(p => ({path: p.path, args: '-tk ' + p.trackers.join(',')}))});
      const link = document.createElement('a'); link.href = '/?review_queue=' + encodeURIComponent(data.path); link.textContent = 'Review this queue in Upload (not started)'; $('queue-result').replaceChildren(link);
    } catch (e) {message(e); $('queue').disabled = false;}
  };
  load().catch(message);
})();

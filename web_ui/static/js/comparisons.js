/* Isolated comparison UI: paths and labels are always text, never HTML. */
(() => {
  const $ = (id) => document.getElementById(id);
  const selected = [];
  let current = '';
  let timer;
  const report = (text) => { $('message').textContent = text; };
  async function api(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (window.UA_COMPARISON_CSRF && !headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', window.UA_COMPARISON_CSRF);
    const response = await fetch(url, { ...options, credentials: 'same-origin', headers });
    const data = await response.json();
    if (!response.ok || data.success === false) throw new Error(data.error || 'Request failed');
    return data;
  }
  function option(value, text) { const node = document.createElement('option'); node.value = value; node.textContent = text; return node; }
  function drawSources() {
    $('sources').replaceChildren();
    selected.forEach((item, i) => {
      const row = document.createElement('div'); row.className = 'source';
      const path = document.createElement('span'); path.textContent = item.path;
      const label = document.createElement('input'); label.value = item.label; label.maxLength = 80; label.title = 'Source label'; label.onchange = () => { item.label = label.value; };
      const offset = document.createElement('input'); offset.type = 'number'; offset.min = '0'; offset.max = '1000000'; offset.value = item.offset; offset.title = 'Trim offset (frames)'; offset.onchange = () => { item.offset = Number(offset.value); };
      const tone = document.createElement('select');
      [['auto','Auto HDR/DV'],['none','SDR / no tone map'],['hdr','HDR10 → SDR'],['hdr10plus','HDR10+ → SDR'],['dovi','Dolby Vision → SDR']].forEach(([v,t]) => tone.append(option(v,t)));
      tone.value = item.tonemap; tone.onchange = () => { item.tonemap = tone.value; };
      const remove = document.createElement('button'); remove.textContent = 'Remove'; remove.onclick = () => { selected.splice(i,1); drawSources(); };
      row.append(path,label,offset,tone,remove); $('sources').append(row);
    });
  }
  async function browse(path) {
    try {
      const data = await api(path ? '/api/browse?filter=video&path=' + encodeURIComponent(path) : '/api/browse_roots');
      current = path; $('location').textContent = path || 'Allowed browse roots'; $('files').replaceChildren();
      for (const item of data.items) {
        if (item.type !== 'folder' && !/\.(mkv|mp4|m2ts|avi|mov|vob|evo|mpg|mpeg)$/i.test(item.name)) continue;
        const button = document.createElement('button'); button.textContent = (item.type === 'folder' ? '📁 ' : '+ ') + item.name;
        button.onclick = () => {
          if (item.type === 'folder') { browse(item.path); return; }
          if (selected.length >= 4) { report('At most four sources per comparison.'); return; }
          if (selected.some((x) => x.path === item.path)) return;
          selected.push({path:item.path,label:'Source ' + (selected.length+1),offset:0,tonemap:'auto'}); drawSources();
        };
        $('files').append(button);
      }
    } catch (error) { report(error.message); }
  }
  $('home').onclick = () => browse('');
  $('up').onclick = () => { const parent = current.replace(/[\\/][^\\/]+[\\/]?$/, ''); browse(parent && parent !== current ? parent : ''); };
  $('roots').onchange = () => browse($('roots').value);
  async function poll(id) {
    try {
      const job = await api('/api/comparisons/' + id);
      report('Comparison job: ' + job.status);
      if (job.status === 'failed') { report(job.error); $('render').disabled = false; return; }
      if (job.status !== 'completed') { timer = setTimeout(() => poll(id), 2000); return; }
      $('render').disabled = false;
      const link = document.createElement('a'); link.href = '/api/comparisons/' + id + '/comparisons.zip'; link.textContent = 'Download all screenshots (ZIP)'; $('results').append(link);
      const grid = document.createElement('div'); grid.className = 'row';
      [...job.files].sort().forEach((name) => { const a = document.createElement('a'); a.href = '/api/comparisons/' + id + '/' + name; a.target = '_blank'; a.rel = 'noopener'; const image = document.createElement('img'); image.src = a.href; image.alt = name; image.loading = 'lazy'; a.append(image); grid.append(a); });
      $('results').append(grid);
    } catch (error) { report(error.message); $('render').disabled = false; }
  }
  $('render').onclick = async () => {
    if (selected.length < 2) { report('Select at least two videos.'); return; }
    const raw = $('frames').value.trim();
    if (raw && !/^\d+(\s*,\s*\d+){0,7}$/.test(raw)) { report('Use up to eight comma-separated nonnegative frame numbers.'); return; }
    clearTimeout(timer); $('render').disabled = true; $('results').replaceChildren(); report('Starting comparison…');
    try {
      const result = await api('/api/comparisons', {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':window.UA_COMPARISON_CSRF},body:JSON.stringify({sources:selected,count:Number($('count').value),frames:raw?raw.split(',').map(Number):[]})});
      poll(result.id);
    } catch (error) { report(error.message); $('render').disabled = false; }
  };
  api('/api/browse_roots').then((data) => { $('roots').append(option('','Choose root…')); data.items.forEach((x) => $('roots').append(option(x.path,x.name))); }).catch((e) => report(e.message));
  browse('');
})();

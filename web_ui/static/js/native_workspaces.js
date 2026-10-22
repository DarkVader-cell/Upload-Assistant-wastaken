/* Native workspaces share UA's theme, authenticated fetch and upload form. */
window.UANativeWorkspace = function UANativeWorkspace({workspace, apiFetch, onRetry}) {
  const {useState, useEffect, useRef} = React;
  const [data, setData] = useState({rows: [], trackers: [], total: 0, backends: {}});
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("missing");
  const [targets, setTargets] = useState([]);
  const [trackerSearch, setTrackerSearch] = useState("");
  const [category, setCategory] = useState("");
  const [resolution, setResolution] = useState("");
  const [errors, setErrors] = useState(false);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState(new Set());
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [resetCount, setResetCount] = useState(0);
  const version = useRef(0);
  const control = "rounded-lg border bg-transparent px-3 py-2 text-sm";
  const rows = data.rows || [];
  function params(start) {
    const p = new URLSearchParams({q: query, mode, category, resolution, errors: errors ? "1" : "0", offset: String(start), limit: "100"});
    targets.forEach(t => p.append("tracker", t));
    return p;
  }
  async function request(url, body) {
    const response = await apiFetch(url, body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Request failed");
    return result;
  }
  async function refresh(start = offset) {
    const generation = ++version.current;
    setLoading(true);
    try {
      const result = await request(workspace === "library" ? "/api/upload-library?" + params(start) : "/api/remote-upload");
      if (generation === version.current) setData(result);
    } catch (error) {
      if (generation === version.current) setMessage(error.message);
    } finally {
      if (generation === version.current) setLoading(false);
    }
  }
  function filter(setter, value) {
    version.current++;
    setLoading(true);
    setter(value);
    setOffset(0);
    setSelected(new Set());
    setMessage("");
  }
  useEffect(() => {
    const timer = setTimeout(() => refresh(), workspace === "library" ? 200 : 0);
    return () => {clearTimeout(timer); version.current++;};
  }, [workspace, query, mode, targets.join(","), category, resolution, errors, offset, resetCount]);
  useEffect(() => {
    if (workspace !== "remote") return;
    const timer = setInterval(() => {if (!document.hidden) refresh();}, 3000);
    return () => clearInterval(timer);
  }, [workspace]);
  function selectRows(values) {setSelected(previous => new Set([...previous, ...values.map(row => row.id)]));}
  async function selectAll() {
    setBusy(true);
    const generation = version.current;
    try {
      let total = 1;
      const p = params(0), values = [];
      for (let start = 0; start < total; start += 100) {
        p.set("offset", String(start));
        const result = await request("/api/upload-library?" + p);
        if (generation !== version.current) return;
        total = result.total;
        values.push(...result.rows);
      }
      selectRows(values);
    } catch (error) {setMessage(error.message);} finally {setBusy(false);}
  }
  async function retry() {
    if (!selected.size || !targets.length) {setMessage("Select releases and target trackers first"); return;}
    setBusy(true);
    const generation = version.current;
    try {
      const ids = Array.from(selected), plans = [];
      let skipped = 0;
      for (let index = 0; index < ids.length; index += 50) {
        const result = await request("/api/upload-library/retry-plan", {ids: ids.slice(index, index + 50), trackers: targets});
        if (generation !== version.current) return;
        plans.push(...result.plans);
        skipped += result.skipped.length;
      }
      if (plans.length) onRetry(plans);
      else setMessage(`${skipped} releases skipped: already successful or source unavailable`);
    } catch (error) {setMessage(error.message);} finally {setBusy(false);}
  }
  function reset() {
    version.current++;
    setQuery(""); setMode("missing"); setTargets([]); setCategory(""); setResolution(""); setErrors(false); setOffset(0); setSelected(new Set()); setTrackerSearch(""); setMessage("");
    setResetCount(previous => previous + 1);
  }
  return <section className="flex min-w-0 flex-1 flex-col overflow-auto p-6" aria-label={workspace === "library" ? "Upload Library" : "Remote uploads"}>
    <header className="mb-5 flex items-center justify-between border-b pb-4"><div><h1 className="text-xl font-bold">{workspace === "library" ? "Upload Library" : "Remote uploads"}</h1><p className="mt-1 text-sm opacity-70">{workspace === "library" ? "Choose filters to update results automatically. Prepare retries in the normal upload form." : "Remote staging, NVMe hashing, uploads, seeding and verified return."}</p></div><button className={control} onClick={() => refresh()}>Refresh</button></header>
    {message && <p role="alert" className="mb-4 rounded border p-3 text-sm">{message}</p>}
    {workspace === "library" ? <>
      <div className="flex min-h-0 flex-col gap-4 lg:flex-row">
        <aside className="w-full shrink-0 rounded-xl border p-4 lg:w-64" aria-label="Library filters">
          <div className="mb-3 flex justify-between"><strong>Filters</strong><button className="text-xs underline" onClick={reset}>Reset filters</button></div>
          <label className="mb-3 block text-sm">Search releases<input aria-label="Search releases" className={control + " mt-1 w-full"} value={query} onChange={e => filter(setQuery, e.target.value)} /></label>
          <label className="mb-3 block text-sm">Tracker result<select aria-label="Tracker result" className={control + " mt-1 w-full"} value={mode} onChange={e => filter(setMode, e.target.value)}><option value="missing">No recorded success</option><option value="uploaded">Uploaded</option><option value="failed">Failed</option><option value="unattempted">Never selected</option></select></label>
          <label className="mb-3 block text-sm">Category<select aria-label="Category" className={control + " mt-1 w-full"} value={category} onChange={e => filter(setCategory, e.target.value)}><option value="">All categories</option>{(data.facets?.category || []).map(value => <option key={value}>{value}</option>)}</select></label>
          <label className="mb-3 block text-sm">Resolution<select aria-label="Resolution" className={control + " mt-1 w-full"} value={resolution} onChange={e => filter(setResolution, e.target.value)}><option value="">All resolutions</option>{(data.facets?.resolution || []).map(value => <option key={value}>{value}</option>)}</select></label>
          <label className="mb-4 block text-sm"><input aria-label="Errors only" type="checkbox" checked={errors} onChange={e => filter(setErrors, e.target.checked)} /> Errors only</label>
          <fieldset disabled={busy}><legend className="mb-2 text-sm font-semibold">Trackers ({targets.length} selected)</legend>
            <input aria-label="Search trackers" className={control + " mb-2 w-full"} placeholder="Search trackers" value={trackerSearch} onChange={e => setTrackerSearch(e.target.value)} />
            <div className="mb-2 flex gap-3 text-xs"><button type="button" className="underline" onClick={() => filter(setTargets, data.trackers || [])}>All trackers</button><button type="button" className="underline" onClick={() => filter(setTargets, [])}>Clear trackers</button></div>
            <div className="max-h-80 overflow-auto">{(data.trackers || []).filter(t => t.toLowerCase().includes(trackerSearch.toLowerCase())).map(t => <label key={t} className="flex items-center gap-2 rounded px-1 py-2 text-sm hover:bg-white/5"><input aria-label={`Filter tracker ${t}`} type="checkbox" checked={targets.includes(t)} onChange={e => filter(setTargets, e.target.checked ? [...targets, t] : targets.filter(value => value !== t))} /><span className="min-w-0 flex-1 truncate">{t}</span><span className="text-xs opacity-60" title="Recorded successful uploads">{data.tracker_counts?.[t]?.uploaded || 0}</span></label>)}</div>
          </fieldset>
          <p className="mt-3 text-xs opacity-60">Multiple trackers match ANY selected tracker. Clear trackers to show all releases.</p>
        </aside>
        <div className="min-w-0 flex-1">
          <div className="mb-3 flex flex-wrap gap-2">{targets.map(t => <button className={control} key={t} aria-label={`Remove tracker ${t}`} onClick={() => filter(setTargets, targets.filter(value => value !== t))}>{t} ×</button>)}</div>
          <div className="mb-3 flex flex-wrap items-center gap-2"><button className={control} disabled={loading || busy} onClick={() => selectRows(rows)}>Select page</button><button className={control} disabled={loading || busy} onClick={selectAll}>Select all filtered</button><button className={control} onClick={() => setSelected(new Set())}>Clear selection</button><button className={control} disabled={loading || busy} onClick={retry}>Prepare retry ({selected.size})</button></div>
          <p role="status" className="mb-3 text-sm opacity-70">{loading ? "Updating results…" : `${data.total || 0} releases · ${selected.size} selected`}</p>
          <p className="mb-3 text-xs opacity-60">Missing means no local success record, not verified tracker absence. Successful targets are excluded from retries.</p>
          <div className="overflow-x-auto"><table className="w-full text-left text-sm" aria-label="Upload history"><thead><tr className="border-b"><th className="p-3"><input aria-label="Select all on page" type="checkbox" disabled={loading || busy || !rows.length} checked={rows.length > 0 && rows.every(row => selected.has(row.id))} onChange={e => e.target.checked ? selectRows(rows) : setSelected(previous => new Set([...previous].filter(id => !rows.some(row => row.id === id))))} /></th>{["Release", "Format", "Successful", "Failed", "Status"].map(label => <th key={label} className="p-3">{label}</th>)}</tr></thead><tbody>{rows.map(row => <tr key={row.id} className="border-b hover:bg-white/5"><td className="p-3"><input type="checkbox" aria-label={`Select ${row.release_name}`} checked={selected.has(row.id)} disabled={loading || busy} onChange={e => setSelected(previous => {const next = new Set(previous); e.target.checked ? next.add(row.id) : next.delete(row.id); return next;})} /></td><td className="p-3">{row.release_name}</td><td className="p-3">{[row.category, row.media_type, row.resolution].filter(Boolean).join(" / ")}</td><td className="p-3">{row.successful_trackers.join(", ")}</td><td className="p-3">{row.failed_trackers.join(", ")}</td><td className="p-3">{row.status} / {row.attempts} attempts</td></tr>)}</tbody></table></div>
          {!loading && !rows.length && <p className="p-5 text-sm">No releases match these filters. Reset filters or import retained history.</p>}
          <footer className="mt-4 flex flex-wrap items-center gap-3"><button className={control} disabled={loading || !offset} onClick={() => setOffset(Math.max(0, offset - 100))}>Previous</button><span>{Math.min(offset + 1, data.total || 0)}–{Math.min(offset + 100, data.total || 0)} of {data.total || 0}</span><button className={control} disabled={loading || offset + 100 >= data.total} onClick={() => setOffset(offset + 100)}>Next</button><button className={control} onClick={async () => {try {const result = await request("/api/upload-library/import", {}); setMessage(`Imported ${result.imported} retained snapshots`); refresh();} catch (error) {setMessage(error.message);}}}>Import history</button></footer>
        </div>
      </div>
    </> : <>
      <p className="mb-4 text-sm">Choose a remote destination in the Upload form. Local auxiliary files need separate staging and are rejected, not silently dropped.</p>
      {Object.entries(data.backends || {}).map(([name, backend]) => <article key={name} className="mb-4 rounded-xl border p-5"><header className="mb-3 flex justify-between"><h2 className="font-semibold">{name}</h2><button className={control} onClick={async () => {try {await request("/api/remote-upload", {backend: name, action: "tick"}); refresh();} catch (error) {setMessage(error.message);}}}>Process due returns</button></header>
        {!backend.background_ready && <p>SSH authentication requires setup.</p>}
        {(backend.transfers || []).map(transfer => <div key={transfer.id} className="my-3 rounded-lg border p-3"><p>{transfer.name} · {transfer.state}</p><progress className="my-2 w-full" max={transfer.bytes_total || 1} value={transfer.bytes_sent || 0} /><p className="text-xs opacity-70">{((transfer.bytes_sent || 0) / 1048576).toFixed(1)} / {((transfer.bytes_total || 0) / 1048576).toFixed(1)} MiB · {((transfer.bytes_per_second || 0) / 1048576).toFixed(1)} MiB/s</p></div>)}
        {Object.entries(backend.jobs || {}).map(([id, job]) => <div key={id} className="my-2 border-t pt-2 text-sm"><strong>{job.state}</strong> · {id}{Object.entries(job.torrents || {}).map(([hash, torrent]) => <p key={hash}>{hash.slice(0, 12)} · {torrent.state} · return {new Date(torrent.due * 1000).toLocaleString()}</p>)}</div>)}
        {(backend.operations || []).map(operation => <p key={operation.id} className="text-xs opacity-70">{operation.action}: {operation.state}</p>)}
      </article>)}
      {!Object.keys(data.backends || {}).length && <p>No remote backend configured on this UA host.</p>}
    </>}
  </section>;
};

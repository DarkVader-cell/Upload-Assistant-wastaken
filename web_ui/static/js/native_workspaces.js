/* Native workspaces share UA's React tree, theme, authenticated fetch and upload form. */
window.UANativeWorkspace = function UANativeWorkspace({workspace, apiFetch, onRetry}) {
  const {useState,useEffect}=React;
  const [data,setData]=useState({rows:[],trackers:[],total:0,backends:{}});
  const [query,setQuery]=useState("");
  const [mode,setMode]=useState("missing");
  const [targets,setTargets]=useState([]);
  const [category,setCategory]=useState("");
  const [resolution,setResolution]=useState("");
  const [errors,setErrors]=useState(false);
  const [offset,setOffset]=useState(0);
  const [selected,setSelected]=useState(new Set());
  const [message,setMessage]=useState("");
  const [busy,setBusy]=useState(false);
  const control="rounded-lg border bg-transparent px-3 py-2 text-sm";
  function params(start){const p=new URLSearchParams({q:query,mode,category,resolution,errors:errors?"1":"0",offset:String(start),limit:"100"});targets.forEach(t=>p.append("tracker",t));return p;}
  async function request(url,body){const response=await apiFetch(url,body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{});const result=await response.json();if(!response.ok)throw new Error(result.error || "Request failed");return result;}
  async function refresh(start=offset){try{setData(await request(workspace==="library"?"/api/upload-library?"+params(start):"/api/remote-upload"));}catch(error){setMessage(error.message);}}
  useEffect(()=>{setSelected(new Set());setOffset(0);refresh(0);},[workspace]);
  useEffect(()=>{if(workspace!=="remote")return;const timer=setInterval(()=>{if(!document.hidden)refresh();},3000);return()=>clearInterval(timer);},[workspace]);
  const rows=data.rows || [];
  function selectRows(values){setSelected(previous=>new Set([...previous,...values.map(row=>row.id)]));}
  async function selectAll(){setBusy(true);try{let total=1;const p=params(0);const values=[];for(let start=0;start<total;start+=100){p.set("offset",String(start));const result=await request("/api/upload-library?"+p);total=result.total;values.push(...result.rows);}selectRows(values);}catch(error){setMessage(error.message);}finally{setBusy(false);}}
  async function retry(){if(!selected.size||!targets.length){setMessage("Select releases and target trackers first");return;}setBusy(true);try{const ids=Array.from(selected),plans=[];let skipped=0;for(let index=0;index<ids.length;index+=50){const result=await request("/api/upload-library/retry-plan",{ids:ids.slice(index,index+50),trackers:targets});plans.push(...result.plans);skipped+=result.skipped.length;}if(plans.length)onRetry(plans);else setMessage(`${skipped} releases skipped: already successful or source unavailable`);}catch(error){setMessage(error.message);}finally{setBusy(false);}}
  return <section className="flex min-w-0 flex-1 flex-col overflow-auto p-6" aria-label={workspace==="library"?"Upload Library":"Remote uploads"}>
    <header className="mb-5 flex items-center justify-between border-b pb-4"><div><h1 className="text-xl font-bold">{workspace==="library"?"Upload Library":"Remote uploads"}</h1><p className="mt-1 text-sm opacity-70">{workspace==="library"?"Review previous uploads and prepare retries in the normal upload form.":"Remote staging, NVMe hashing, uploads, seeding and verified return."}</p></div><button className={control} onClick={()=>refresh()}>Refresh</button></header>
    {message&&<p role="status" className="mb-4 rounded border p-3 text-sm">{message}</p>}
    {workspace==="library"?<>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="text-sm">Search<input className={control+" block"} value={query} onChange={e=>setQuery(e.target.value)}/></label>
        <label className="text-sm">Trackers<select multiple className={control+" block min-w-40"} value={targets} onChange={e=>{setTargets(Array.from(e.target.selectedOptions).map(o=>o.value));setSelected(new Set());}}>{(data.trackers||[]).map(t=><option key={t}>{t}</option>)}</select></label>
        <label className="text-sm">Result<select className={control+" block"} value={mode} onChange={e=>setMode(e.target.value)}><option value="missing">No recorded success</option><option value="uploaded">Uploaded</option><option value="failed">Failed</option><option value="unattempted">Never selected</option></select></label>
        <label className="text-sm">Category<input className={control+" block w-28"} value={category} onChange={e=>setCategory(e.target.value)}/></label>
        <label className="text-sm">Resolution<input className={control+" block w-28"} value={resolution} onChange={e=>setResolution(e.target.value)}/></label>
        <label className="text-sm"><input type="checkbox" checked={errors} onChange={e=>setErrors(e.target.checked)}/> Errors only</label>
        <button className={control} onClick={()=>{setSelected(new Set());setOffset(0);refresh(0);}}>Apply filters</button>
        <button className={control} onClick={async()=>{try{const result=await request("/api/upload-library/import",{});setMessage(`Imported ${result.imported} retained snapshots`);refresh();}catch(error){setMessage(error.message);}}}>Import history</button>
      </div>
      <div className="mb-3 flex flex-wrap gap-2"><button className={control} onClick={()=>selectRows(rows)}>Select page</button><button className={control} disabled={busy} onClick={selectAll}>Select all filtered</button><button className={control} onClick={()=>setSelected(new Set())}>Clear</button><button className={control} disabled={busy} onClick={retry}>Prepare retry ({selected.size})</button></div>
      <p className="mb-3 text-xs opacity-60">Missing means no local success record, not confirmed tracker absence. Successful targets are excluded from retries.</p>
      <table className="w-full text-left text-sm"><thead><tr className="border-b">{["Select","Release","Format","Successful","Failed","Status"].map(label=><th key={label} className="p-3">{label}</th>)}</tr></thead><tbody>{rows.map(row=><tr key={row.id} className="border-b hover:bg-white/5"><td className="p-3"><input type="checkbox" aria-label={`Select ${row.release_name}`} checked={selected.has(row.id)} onChange={e=>setSelected(previous=>{const next=new Set(previous);e.target.checked?next.add(row.id):next.delete(row.id);return next;})}/></td><td className="p-3">{row.release_name}</td><td className="p-3">{[row.category,row.media_type,row.resolution].filter(Boolean).join(" / ")}</td><td className="p-3">{row.successful_trackers.join(", ")}</td><td className="p-3">{row.failed_trackers.join(", ")}</td><td className="p-3">{row.status} / {row.attempts} attempts</td></tr>)}</tbody></table>
      <footer className="mt-4 flex items-center gap-3"><button className={control} disabled={!offset} onClick={()=>{setOffset(offset-100);refresh(offset-100);}}>Previous</button><span>{Math.min(offset+1,data.total||0)}–{Math.min(offset+100,data.total||0)} of {data.total||0}</span><button className={control} disabled={offset+100>=data.total} onClick={()=>{setOffset(offset+100);refresh(offset+100);}}>Next</button></footer>
    </>:<>
      <p className="mb-4 text-sm">Choose a remote destination in the Upload form; release paths, selected trackers and supported metadata options are reused. Local-only auxiliary files need separate staging and are rejected, not silently dropped.</p>
      {Object.entries(data.backends||{}).map(([name,backend])=><article key={name} className="mb-4 rounded-xl border p-5"><header className="mb-3 flex justify-between"><h2 className="font-semibold">{name}</h2><button className={control} onClick={async()=>{try{await request("/api/remote-upload",{backend:name,action:"tick"});refresh();}catch(error){setMessage(error.message);}}}>Process due returns</button></header>
        {!backend.background_ready&&<p>SSH authentication requires setup.</p>}
        {(backend.transfers||[]).map(transfer=><div key={transfer.id} className="my-3 rounded-lg border p-3"><p>{transfer.name} · {transfer.state}</p><progress className="my-2 w-full" max={transfer.bytes_total||1} value={transfer.bytes_sent||0}/><p className="text-xs opacity-70">{((transfer.bytes_sent||0)/1048576).toFixed(1)} / {((transfer.bytes_total||0)/1048576).toFixed(1)} MiB · {((transfer.bytes_per_second||0)/1048576).toFixed(1)} MiB/s</p></div>)}
        {Object.entries(backend.jobs||{}).map(([id,job])=><div key={id} className="my-2 border-t pt-2 text-sm"><strong>{job.state}</strong> · {id}{Object.entries(job.torrents||{}).map(([hash,torrent])=><p key={hash}>{hash.slice(0,12)} · {torrent.state} · return {new Date(torrent.due*1000).toLocaleString()}</p>)}</div>)}
        {(backend.operations||[]).map(operation=><p key={operation.id} className="text-xs opacity-70">{operation.action}: {operation.state}</p>)}
      </article>)}
      {!Object.keys(data.backends||{}).length&&<p>No remote backend configured on this UA host.</p>}
    </>}
  </section>;
};

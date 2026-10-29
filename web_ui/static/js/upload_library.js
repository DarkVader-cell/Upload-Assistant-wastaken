"use strict";
(async () => {
  const el = (id) => document.getElementById(id);
  const selected = new Set();
  let rows = [], offset = 0, total = 0;
  const token = document.querySelector('meta[name="csrf-token"]').content;
  const headers = {"Content-Type":"application/json", "X-CSRF-Token":token};
  const message = (text) => { el("message").textContent = text; };
  const targets = () => Array.from(el("trackers").selectedOptions).map((o) => o.value);
  function params(start) {
    const p = new URLSearchParams({q:el("query").value, mode:el("mode").value, category:el("category").value, resolution:el("resolution").value, errors:el("errors").checked?"1":"0", offset:String(start), limit:"100"});
    targets().forEach((t) => p.append("tracker", t)); return p;
  }
  async function api(url, data) {
    const r = await fetch(url, data ? {method:"POST", headers, body:JSON.stringify(data)} : {});
    const body = await r.json(); if (!r.ok) throw new Error(body.error || "Request failed"); return body;
  }
  function render() {
    el("rows").replaceChildren(...rows.map((row) => {
      const tr = document.createElement("tr"), td = document.createElement("td"), box = document.createElement("input");
      box.type="checkbox"; box.checked=selected.has(row.id); box.setAttribute("aria-label", "Select " + row.release_name);
      box.onchange=() => { if(box.checked) selected.add(row.id); else selected.delete(row.id); message(selected.size+" selected"); };
      td.append(box); tr.append(td);
      [row.release_name, [row.category,row.media_type,row.resolution].filter(Boolean).join(" / "),row.successful_trackers.join(", "),row.failed_trackers.join(", "),row.status+" / "+row.attempts].forEach((value) => {const cell=document.createElement("td");cell.textContent=value;tr.append(cell);});
      return tr;
    }));
    el("count").textContent=`${total ? offset+1 : 0}–${Math.min(offset+100,total)} of ${total}; ${selected.size} selected`;
    el("previous").disabled=offset===0; el("next").disabled=offset+100>=total;
  }
  async function load() {
    try {
      const data=await api("/api/upload-library?"+params(offset)); rows=data.rows;total=data.total;
      if (!el("trackers").options.length) data.trackers.forEach((name)=>{const option=document.createElement("option");option.value=name;option.textContent=name;el("trackers").append(option);});
      render();
    } catch(e) {message(e.message);}
  }
  el("filter").onclick=()=>{selected.clear();offset=0;load();};
  el("previous").onclick=()=>{offset=Math.max(0,offset-100);load();};
  el("next").onclick=()=>{offset+=100;load();};
  el("select-page").onclick=()=>{rows.forEach((r)=>selected.add(r.id));render();};
  el("clear").onclick=()=>{selected.clear();render();};
  el("select-all").onclick=async()=>{
    try {const query=params(0);let matching=1;for(let i=0;i<matching;i+=100){query.set("offset",String(i));const data=await api("/api/upload-library?"+query);matching=data.total;data.rows.forEach((r)=>selected.add(r.id));}render();}catch(e){message(e.message);}
  };
  el("import").onclick=async()=>{try{const data=await api("/api/upload-library/import",{});message(`Imported ${data.imported} metadata records`);await load();}catch(e){message(e.message);}};
  el("retry").onclick=async()=>{
    if(!selected.size||!targets().length){message("Select releases and target trackers first");return;}
    if(!confirm(`Queue ${selected.size} releases for normal UA processing? Already successful tracker targets will be excluded.`))return;
    el("retry").disabled=true;
    try {
      const ids=Array.from(selected);let submitted=0,skipped=0;
      for(let i=0;i<ids.length;i+=50){
        const data=await api("/api/upload-library/retry-plan",{ids:ids.slice(i,i+50),trackers:targets()});skipped+=data.skipped.length;
        for(const plan of data.plans){
          // Existing execution endpoint owns concurrency, policy checks and session output.
          const response=await fetch("/api/execute",{method:"POST",headers,body:JSON.stringify({path:plan.path,args:"-tk "+plan.trackers.join(",")+" --unattended",session_id:"library-"+crypto.randomUUID(),label:plan.label,schedule:true})});
          if(!response.ok)throw new Error("Execution request rejected; inspect UA sessions before retrying");
          // Consume streams in background without accumulating sensitive logs in the DOM.
          if(response.body){const reader=response.body.getReader();(async()=>{try{while(!(await reader.read()).done){/* Drain without retaining session output. */} }catch(_error){message("A session stream disconnected; inspect UA sessions before retrying");}})();}
          submitted++;
          selected.delete(plan.id); // Do not resubmit accepted requests after a later batch fails.
          render();
        }
      }
      selected.clear();render();message(`${submitted} execution requests submitted; ${skipped} skipped. Check UA sessions for acceptance, queue limits and final results.`);
    } catch(e){message(e.message);}finally{el("retry").disabled=false;}
  };
  await load();
})();

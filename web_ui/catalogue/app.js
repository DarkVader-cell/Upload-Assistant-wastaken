'use strict';
(() => {
  const $=id=>document.getElementById(id);
  const trackers={HDB:'HDBits',PTP:'PassThePopcorn',ATH:'Aither',DT:'DesiTorrents'};
  const services={amazon:'Amazon Prime',netflix:'Netflix',appletv:'Apple TV+'};
  const regions={amazon:'GB',netflix:'US',appletv:'US'};
  const limits={daily_limit:['Movie / episode starts per UTC day',5,0],max_downloads_per_run:['Downloads per run',2,0],max_checks_per_run:['Titles checked per batch',20,1],pages_per_service:['New catalogue pages per service / batch',1,1],min_free_gib:['Minimum free space · GiB',50,0],timeout_seconds:['Download timeout · seconds',14400,1],max_candidate_age_hours:['Availability lifetime · hours',24,1],max_episodes_per_title:['New episodes per series scan',30,1],max_series_expansions_per_run:['Series expansions per run',2,1],series_refresh_minutes:['Series refresh · minutes',60,5],metadata_timeout_seconds:['Metadata timeout · seconds',180,1],slot_timeout_seconds:['Slot-check timeout · seconds',180,1],tracker_request_interval_seconds:['API gap per host · seconds',10,2],tracker_daily_api_limit:['Daily API requests per host',200,1],min_release_year:['Earliest release year · 0 any',0,0],max_release_year:['Latest release year · 0 current',0,0],discovery_start_offset:['API discovery depth · entries skipped',0,0],min_imdb_votes:['Minimum IMDb votes · 0 any',0,0],max_imdb_votes:['Maximum IMDb votes · 0 any',0,0],min_runtime_minutes:['Minimum reported runtime · minutes',0,0],max_runtime_minutes:['Maximum reported runtime · 0 any',0,0]};
  const discoveryKeys=new Set(['min_release_year','max_release_year','pages_per_service','discovery_start_offset','min_imdb_votes','max_imdb_votes','min_runtime_minutes','max_runtime_minutes']);
  let csrf='', current={}, initialised=false, refreshing=null, revision='', queueRevision='', queueKey='', queuePage=1;
  let generation=0, queueRequest=0, timer=null, debounce=null, busy=false, selectedJob=null;
  const pending=new Set(), rows=new Map();
  const node=(tag,text)=>{const element=document.createElement(tag);if(text!==undefined)element.textContent=text;return element;};
  function message(text,error=false){$('message').textContent=text;$('message').classList.toggle('error',error);}
  function signedIn(value){
    $('dashboard').hidden=!value;$('logout').hidden=!value;$('login-panel').hidden=value;
    if(!value){generation++;csrf='';initialised=false;revision='';queueKey='';clearTimeout(timer);if($('recheck-dialog').open)$('recheck-dialog').close();selectedJob=null;}
  }
  async function api(path,body){
    const options={credentials:'same-origin',cache:'no-store',headers:{}};
    if(body!==undefined){options.method='POST';options.headers={'Content-Type':'application/json','X-CSRF-Token':csrf};options.body=JSON.stringify(body);}
    const response=await fetch(`api/${path}`,options);
    if(response.status===401&&path!=='login')signedIn(false);
    if(!response.ok){let text=(await response.text()).slice(0,500);try{text=JSON.parse(text).error||text;}catch{}throw new Error(text||`Request failed (${response.status})`);}
    return response.json();
  }
  function field(text,id,type='text'){
    const label=node('label',text),input=node('input');input.id=id;input.type=type;label.append(input);return[label,input];
  }
  for(const[key,name]of Object.entries(trackers)){
    const[label]=field(name,`tracker-${key}`,'checkbox');label.className='inline';$('trackers').append(label);
  }
  for(const[key,name]of Object.entries(services)){
    const row=node('div');row.className='service';
    const[label]=field(name,`service-${key}`,'checkbox');label.className='inline';
    const[region,input]=field('Streaming/account region',`region-${key}`);input.maxLength=2;
    const[daily,count]=field('Download starts/day (not search)',`daily-${key}`,'number');count.min='0';
    const usage=node('div');usage.className='service-budget';usage.id=`usage-${key}`;
    row.append(label,region,daily,usage);$('services').append(row);
  }
  for(const[key,[text,,min]]of Object.entries(limits)){
    const[label,input]=field(text,key,'number');input.min=String(min);input.required=true;$(discoveryKeys.has(key)?'discovery-limits':'limits').append(label);
  }
  function renderSettings(config){
    $('countries').value=(config.origin_countries||[]).join(', ');
    $('original-languages').value=(config.original_languages||[]).join(', ');
    $('video-mode').value=config.video_mode||'saved';
    $('media-movie').checked=(config.media_types||['movie']).includes('movie');$('media-tv').checked=(config.media_types||[]).includes('tv');
    $('eligibility').value=config.eligibility||'absent_all';$('include-specials').checked=config.include_specials===true;
    $('selection-order').value=config.selection_order||'recent';$('exclude-keywords').value=(config.exclude_title_keywords||[]).join(', ');
    for(const key of Object.keys(trackers))$(`tracker-${key}`).checked=(config.trackers||[]).includes(key);
    for(const key of Object.keys(services)){
      const service=(config.services||{})[key];$(`service-${key}`).checked=Boolean(service);
      $(`region-${key}`).value=service?.region||regions[key];$(`daily-${key}`).value=service?.daily_limit??config.daily_limit??5;
    }
    for(const[key,[,fallback]]of Object.entries(limits))$(key).value=config[key]??fallback;
    $('allow-downloads').checked=config.allow_downloads===true;$('schedule-enabled').checked=config.schedule?.enabled===true;
    $('schedule-interval').value=config.schedule?.interval_minutes??60;$('schedule-mode').value=config.schedule?.mode||'plan';
    syncQuickSearch();refreshSearchContext().catch(()=>{});
  }
  function renderSearchScope(){const source=Object.keys(services).filter(key=>$(`service-${key}`).checked).map(key=>`${services[key]} ${$(`region-${key}`).value}`);$('search-scope').textContent=`Sources: ${source.join(', ')||'none selected'} · Film production: ${$('countries').value.trim()||'any country'} · Years: ${$('min_release_year').value||'any'}–${$('max_release_year').value||'current'} · IMDb votes: ${$('min_imdb_votes').value||0}–${Number($('max_imdb_votes').value)||'any'}. Production country is NOT your account/availability region.`;}
  function syncQuickSearch(){for(const key of Object.keys(services)){$(`quick-source-${key}`).checked=$(`service-${key}`).checked;$(`quick-region-${key}`).textContent=$(`region-${key}`).value;}$('search-production-country').value=$('countries').value;renderSearchScope();}
  async function refreshSearchContext(){const result=await api('search-context');const labels={title_year_votes_runtime_language_filters:'year/votes/runtime/language filters',disabled_service:'sources not selected',different_production_country_search:'entries found under another production-country search',availability_region_mismatch:'other streaming region',expired_catalogue_evidence:'expired availability evidence',unverified_prime_access:'Prime access not verified',already_decided_or_attempted:'already reviewed/attempted',retry_cooldown:'retry cooldown',media_type_mismatch:'different media type'};$('search-context').textContent=`Saved search: ${result.eligible} eligible of ${result.queue_total} queued. ${Object.entries(result.exclusions).map(([key,count])=>`${count} excluded: ${labels[key]||key}`).join(' · ')}${result.eligible===0?' — New discovery may find matches; an empty batch is not a service failure.':''}`;}
  for(const key of Object.keys(services))$(`quick-source-${key}`).onchange=()=>{$(`service-${key}`).checked=$(`quick-source-${key}`).checked;renderSearchScope();$('search-context').textContent='Source changes will be saved and applied when you click Find missing titles.';};
  $('search-production-country').oninput=()=>{$('countries').value=$('search-production-country').value;renderSearchScope();};
  $('search-any-production').onclick=()=>{$('countries').value='';$('search-production-country').value='';renderSearchScope();message('Production-country restriction cleared in the draft. Click Find missing titles to apply; streaming regions are unchanged.');};
  window.addEventListener('hashchange',()=>{if(location.hash==='#queue-section'){syncQuickSearch();refreshSearchContext().catch(()=>{});}});
  function renderControls(status){
    busy=status.busy;
    $('plan').disabled=busy||pending.has('plan');$('execute').disabled=busy||!current.allow_downloads||pending.has('execute');
    $('cancel').disabled=!busy||pending.has('cancel');$('save-settings').disabled=busy||pending.has('save-settings');
    $('logout').disabled=pending.has('logout');
    for(const button of document.querySelectorAll('.job-action'))button.disabled=busy;
    const configured=status.capabilities.metadata_adapter_configured;
    $('media-tv').disabled=!configured;for(const option of $('eligibility').options)option.disabled=option.value!=='absent_all'&&!configured;
    $('runtime-state').textContent=busy?'● Runner active':'● Runner idle';$('runtime-state').classList.toggle('running',busy);
    $('last-run').textContent=status.last_run?`Last run ${new Date(status.last_run.time*1000).toLocaleString()} · exit ${status.last_run.exit_code??'unknown'} · ${status.last_run.reported_jobs} jobs${status.last_run.error?' · '+status.last_run.error:''}`:'No runs yet';
    if(status.last_run?.selection){const selection=status.last_run.selection;$('search-outcome').textContent=status.last_run.reported_jobs===0&&selection.eligible===0?'Last batch completed with no matching titles. '+selection.message:`Last batch checked ${status.last_run.reported_jobs} titles; ${status.last_run.discovery?.map(item=>`${item.service}: ${item.catalogue_matches} catalogue matches`).join(' · ')||''}`;}
    $('next-run').textContent=status.next_run?`Next check: ${new Date(status.next_run*1000).toLocaleString()}`:'Schedule is paused.';
  }
  function metric(label,value,detail,limit){
    const item=node('div');item.className='metric';const title=node('span',label);title.className='metric-label';
    const count=node('div',String(value));count.className='metric-value';if(limit!==undefined)count.append(node('small',`/ ${limit}`));
    const description=node('span',detail);description.className='metric-detail';item.append(title,count,description);return item;
  }
  function renderOverview(status){
    const queue=status.queue,counts=queue.counts;
    $('summary').replaceChildren(
      metric('CATALOGUE QUEUE',queue.total,'Persistent across runs'),
      metric('CHECKED CANDIDATES',counts.ready||0,`${counts.unknown||0} API unknown · ${counts.unavailable||0} provider unavailable · ${counts.review||0} need review`),
      metric('COMPLETED',counts.succeeded||0,`${(counts.failed||0)+(counts.uncertain||0)} failed or uncertain`),
      metric('UTC STARTS TODAY',queue.starts_today,`Downloads: ${current.allow_downloads?'enabled':'disabled'} · Schedule: ${current.schedule?.enabled?'enabled':'paused'}`,current.daily_limit??5));
    for(const key of Object.keys(services)){
      const container=$(`usage-${key}`),config=(current.services||{})[key];container.replaceChildren();
      if(!config){container.append(node('span','Service disabled'));continue;}
      const used=queue.service_starts_today[key]||0,maximum=config.daily_limit??current.daily_limit??5;
      const progress=node('progress');progress.max=Math.max(1,maximum);progress.value=Math.min(used,maximum);
      progress.setAttribute('aria-label',`${services[key]} daily quota`);
      container.append(node('span',`${used} of ${maximum} starts used today`),progress);
    }
    const events=status.events.slice().reverse();
    $('events').replaceChildren(...(events.length?events.map(event=>{
      const row=node('li'),time=node('time',new Date(event.time).toLocaleTimeString());time.className='event-time';time.dateTime=event.time;
      row.append(time,node('span',event.message));return row;
    }):[node('li','No activity yet. Your first run will appear here.')]));
    const missing=[];if(!status.capabilities.existing_title_slots)missing.push('existing-title slots');if(!status.capabilities.tv_episodes)missing.push('TV episodes');
    $('capability-note').textContent=status.prime_inclusion_required?'Prime inclusion must be checked on the configured account/region. Rent/buy/add-ons are excluded; unverified access stays in review. Manual confirmation expires after 24 hours. Source quality/slots still need separate verification.':!status.capabilities.metadata_adapter_configured?'Metadata/slot adapter is not configured on this instance. Basic movie absence checks remain available.':missing.length?`Supported now: movies absent from all selected trackers. Still unavailable: ${missing.join(' and ')}. Live API and provider-ID validation is pending.`:'Movie/TV discovery and slot checks are available. Unknown inventories, trumps and evidence-required decisions are never assumed free. A slot finding is not upload approval; live API validation is pending.';
  }
  function renderQueue(data){
    $('queue-count').textContent=String(data.total);$('page-label').textContent=`Page ${data.page} of ${data.pages} · ${data.total} items`;
    $('page-prev').disabled=data.page<=1;$('page-next').disabled=data.page>=data.pages;
    $('queue-updated').textContent=`Updated ${new Date().toLocaleTimeString()}`;
    if(!data.jobs.length){
      rows.clear();const row=node('tr'),cell=node('td');cell.colSpan=4;cell.className='empty-state';
      cell.append(node('strong',$('queue-search').value?'No matching titles':'A little quiet in here.'),node('span','Run a discovery scan to find candidates, or adjust your filters.'));
      row.append(cell);$('queue').replaceChildren(row);return;
    }
    const keep=new Set(),ordered=[];
    for(const job of data.jobs){
      const key=job.key||job.imdb,signature=JSON.stringify(job);keep.add(key);let entry=rows.get(key);
      if(!entry||entry.signature!==signature){
        const row=node('tr'),title=node('td'),name=node('span',job.title||'Unknown title');name.className='row-title';
        const details=[job.imdb];if(job.year)details.push(String(job.year));if(job.episode)details.push(`S${String(job.season).padStart(2,'0')}E${String(job.episode).padStart(2,'0')}`);const meta=node('span',details.join(' · '));meta.className='row-meta';title.append(name,meta);
        const service=node('td'),serviceName=node('span',services[job.service]||job.service),dot=node('i');dot.className=`service-dot ${job.service}`;
        const serviceRow=node('span');serviceRow.className='service-name';serviceRow.append(dot,serviceName);const region=node('span',job.region||'');region.className='row-meta';service.append(serviceRow,region);
        const status=node('td'),badge=node('span',job.status);badge.className='job-status';if(/^[a-z_]+$/.test(job.status))badge.classList.add(job.status);status.append(badge);
        const decision=node('td');decision.className='decision-text';
        if(job.service==='amazon'){decision.append(node('small',job.source_access==='native_included'?'Prime subscription automatically verified (1h)':job.source_access==='manual_included'?'Manual note only; automatic account check still required':job.source_access==='rent_buy_or_addon'?'Rent/buy/add-on excluded':'Prime inclusion unverified'));const accessButton=node('button','Review Prime access');accessButton.className='button quiet';accessButton.onclick=()=>{sourceJob=job;$('source-review-title').textContent=`${job.title||job.imdb} · account region ${job.region}`;$('source-review-checked').checked=false;const item=String(job.provider_item||'');$('source-review-link').href=/^[A-Za-z0-9._-]{1,100}$/.test(item)?'https://www.primevideo.com/detail/'+encodeURIComponent(item):'https://www.primevideo.com/';$('source-review-dialog').showModal();};decision.append(accessButton);}
        const explanation=node('details'),summary=node('summary',({blocked:'Already present / blocked',unknown:'Verification incomplete',review:'Review required',unavailable:'Source unavailable',filtered:'Excluded by filters',pending:'Awaiting check',ready:'Metadata checked'})[job.status]||'View decision');explanation.append(summary,node('p',job.reason||'Awaiting verification'));const facts=[];if(Number.isInteger(job.imdb_votes))facts.push(`${job.imdb_votes.toLocaleString()} IMDb votes`);if(job.runtime_minutes)facts.push(`${job.runtime_minutes} min`);if(job.original_language)facts.push(`Original: ${job.original_language.toUpperCase()}`);if(facts.length)explanation.append(node('p',facts.join(' · ')));decision.append(explanation);
        if(['blocked','unknown','stale','review','filtered','unavailable','failed','uncertain'].includes(job.status)){
          const retry=node('button',job.started_day?'Verified retry…':'Recheck');retry.className='button quiet job-action';retry.disabled=busy;
          retry.addEventListener('click',()=>{selectedJob=job;$('recheck-description').textContent=`${job.title||job.imdb} · ${job.status}`;
            $('retry-confirm-label').hidden=!job.started_day;$('retry-confirm').checked=false;$('recheck-error').textContent='';$('recheck-dialog').showModal();});decision.append(retry);
        }
        row.append(title,service,status,decision);
        entry={signature,row};rows.set(key,entry);
      }
      ordered.push(entry.row);
    }
    for(const key of rows.keys())if(!keep.has(key))rows.delete(key);
    $('queue').replaceChildren(...ordered);
  }
  function queueFilters(){return{year_min:Number($('queue-year-min').value||0),year_max:Number($('queue-year-max').value||0),min_votes:Number($('queue-min-votes').value||0),language:$('queue-language').value.trim().toLowerCase(),access:$('queue-access').value,sort:$('queue-sort').value};}
  async function refreshQueue(force=false){
    const parameters=new URLSearchParams({page:String(queuePage),page_size:$('queue-size').value,status:$('queue-status').value,service:$('queue-service').value,q:$('queue-search').value.trim(),...queueFilters()});
    const key=`${queueRevision}:${parameters}`;if(!force&&key===queueKey)return;
    const request=++queueRequest,epoch=generation;const data=await api(`queue?${parameters}`);
    if(request!==queueRequest||epoch!==generation)return;
    if(queuePage>data.pages){queuePage=data.pages;return refreshQueue(true);}
    queueKey=key;renderQueue(data);
  }
  function armPoll(){
    clearTimeout(timer);if(document.hidden||$('dashboard').hidden)return;
    timer=setTimeout(()=>refresh().catch(error=>message(error.message,true)),busy?2500:12000);
  }
  async function refresh(force=false){
    if(refreshing){if(!force)return refreshing;await refreshing.catch(()=>{});return refresh(true);}
    const epoch=generation;
    refreshing=(async()=>{
      const status=await api('status?include_queue=0');if(epoch!==generation)return;
      csrf=status.csrf;current=status.settings;$('execute').hidden=status.discovery_only===true;signedIn(true);if(!initialised){renderSettings(current);initialised=true;presetList().catch(()=>{});}
      renderControls(status);
      if(revision!==status.revision){renderOverview(status);revision=status.revision;}
      queueRevision=status.queue.revision;await refreshQueue(force);
    })();
    try{return await refreshing;}finally{refreshing=null;armPoll();}
  }
  function action(id,fn){
    $(id).addEventListener('click',async()=>{
      if(pending.has(id))return;pending.add(id);$(id).disabled=true;
      try{await fn();}catch(error){message(error.message,true);}
      finally{pending.delete(id);if(['health','pause','logout'].includes(id))$(id).disabled=false;await refresh(true).catch(()=>{});}
    });
  }
  $('login-form').addEventListener('submit',async event=>{
    event.preventDefault();try{const result=await api('login',{password:$('password').value});csrf=result.csrf;$('password').value='';initialised=false;message('Signed in.');await refresh(true);}catch(error){message(error.message,true);}
  });
  action('logout',async()=>{await api('logout',{});signedIn(false);rows.clear();message('Signed out.');});
  action('plan',async()=>{const settings=searchDraft();if(!Object.keys(settings.services).length)throw new Error('Select at least one streaming source');await api('settings',{settings});await api('run',{mode:'plan',queue_only:$('queue-only').checked});initialised=false;message('Dry-run started with your saved search. Results will be saved automatically; no downloads.');});
  action('execute',async()=>{await api('run',{mode:'execute',queue_only:$('queue-only').checked,confirmation:'ENABLE DOWNLOADS'});message('Execution requested.');});
  action('cancel',async()=>{await api('cancel',{});initialised=false;message('Cancellation requested; schedule paused.');});
  action('pause',async()=>{await api('pause',{});initialised=false;message('Schedule paused. Any active run may finish.');});
  action('health',async()=>{const result=await api('cardinal-health',{});$('health-result').textContent=result.ok?`CardinalDL ${result.version} (${result.runtime}) · ${result.message}`:result.message;});
  function collectSettings(){
    const settings={video_mode:$('video-mode').value,original_languages:[...new Set($('original-languages').value.split(',').map(x=>x.trim().toLowerCase()).filter(Boolean))],origin_countries:$('countries').value.split(',').map(x=>x.trim().toUpperCase()).filter(Boolean),media_types:['movie','tv'].filter(type=>$(type==='movie'?'media-movie':'media-tv').checked),eligibility:$('eligibility').value,include_specials:$('include-specials').checked,selection_order:$('selection-order').value,exclude_title_keywords:$('exclude-keywords').value.split(',').map(value=>value.trim()).filter(Boolean),trackers:Object.keys(trackers).filter(key=>$(`tracker-${key}`).checked),services:{},allow_downloads:$('allow-downloads').checked,schedule:{enabled:$('schedule-enabled').checked,interval_minutes:Number($('schedule-interval').value),mode:$('schedule-mode').value}};
    for(const key of Object.keys(services))if($(`service-${key}`).checked)settings.services[key]={region:$(`region-${key}`).value.trim().toUpperCase(),daily_limit:Number($(`daily-${key}`).value)};
    for(const key of Object.keys(limits))settings[key]=Number($(key).value);
    return settings;
  }
  function searchDraft(){const all=collectSettings(),allowed=new Set(['services','trackers','origin_countries','original_languages','media_types','eligibility','include_specials','selection_order','min_release_year','max_release_year','min_imdb_votes','max_imdb_votes','min_runtime_minutes','max_runtime_minutes','exclude_title_keywords','video_mode','max_checks_per_run','pages_per_service','discovery_start_offset']);return Object.fromEntries(Object.entries(all).filter(([key])=>allowed.has(key)));}
  let namedPresets=[];
  async function presetList(){const data=await api('presets');namedPresets=data.presets;$('search-preset-list').replaceChildren(...namedPresets.map(p=>{const o=node('option',p.name);o.value=p.id;return o;}));}
  action('search-preset-save',async()=>{const all=collectSettings(),allowed=new Set(['services','trackers','origin_countries','original_languages','media_types','eligibility','include_specials','selection_order','min_release_year','max_release_year','min_imdb_votes','max_imdb_votes','min_runtime_minutes','max_runtime_minutes','exclude_title_keywords','video_mode','max_checks_per_run','pages_per_service','discovery_start_offset']);const settings=Object.fromEntries(Object.entries(all).filter(([key])=>allowed.has(key)));await api('presets',{name:$('search-preset-name').value,settings});await presetList();message('Named search preset saved. No scan or download started.');});
  action('search-preset-load',async()=>{if(!namedPresets.length)await presetList();const preset=namedPresets.find(p=>p.id===$('search-preset-list').value);if(!preset)throw new Error('Choose a saved search preset');renderSettings({...current,...preset.settings});message('Preset loaded into the form. Click Save search settings to apply it. No scan started.');});
  action('search-preset-refresh',presetList);
  action('search-preset-delete',async()=>{if(!$('search-preset-list').value)throw new Error('Select a preset');await api('presets',{delete:$('search-preset-list').value});await presetList();message('Preset deleted; active search settings are unchanged.');});
  $('settings-form').addEventListener('submit',async event=>{
    event.preventDefault();if(pending.has('save-settings'))return;pending.add('save-settings');$('save-settings').disabled=true;
    try{
      const settings=collectSettings();
      await api('settings',{settings,confirmation:settings.allow_downloads?'ENABLE DOWNLOADS':''});initialised=false;message('Settings saved and backed up on the dedicated server.');await refresh(true);
    }catch(error){message(error.message,true);}finally{pending.delete('save-settings');$('save-settings').disabled=busy;}
  });
  function discoveryPreset(rare){
    const values=rare?{min_release_year:1970,max_release_year:2015,min_imdb_votes:10,max_imdb_votes:5000,discovery_start_offset:0,min_runtime_minutes:30,max_runtime_minutes:0,pages_per_service:3}:{min_release_year:1960,max_release_year:2005,min_imdb_votes:0,max_imdb_votes:0,discovery_start_offset:0,min_runtime_minutes:40,max_runtime_minutes:0,pages_per_service:3};
    for(const[key,value]of Object.entries(values))$(key).value=String(value);
    $('selection-order').value=rare?'obscure':'oldest';
    message('Discovery preset staged only. Review regions/countries and limits, then save. No requests or downloads started.');
  }
  $('preset-rare').addEventListener('click',()=>discoveryPreset(true));$('preset-backcatalogue').addEventListener('click',()=>discoveryPreset(false));
  let sourceJob=null;
  $('source-review-close').onclick=()=>$('source-review-dialog').close();
  for(const [id,decision]of [['source-review-included','included'],['source-review-paid','paid'],['source-review-unknown','unknown']])action(id,async()=>{if(!sourceJob)throw new Error('Choose a title');await api('source-review',{key:sourceJob.key||sourceJob.imdb,region:sourceJob.region,decision,checked_in_account:$('source-review-checked').checked});$('source-review-dialog').close();queueKey='';await refresh(true);message('Manual source review saved. Tracker evidence still requires a fresh scan; no download started.');});
  $('close-recheck').addEventListener('click',()=>$('recheck-dialog').close());
  $('recheck-form').addEventListener('submit',async event=>{event.preventDefault();if(!selectedJob)return;
    try{await api('jobs/recheck',{job_key:selectedJob.key||selectedJob.imdb,confirmation:$('retry-confirm').checked?'VERIFIED NO PAYLOAD':''});$('recheck-dialog').close();message('Job queued for a fresh recheck. No API requests or downloads started.');queueKey='';await refresh(true);}catch(error){$('recheck-error').textContent=error.message;}});
  $('queue-go').addEventListener('click',()=>{const value=Number($('queue-jump').value);if(Number.isInteger(value)&&value>=1&&value<=1000000){queuePage=value;refreshQueue(true).catch(error=>message(error.message,true));}});
  for(const id of ['queue-status','queue-service','queue-size','queue-year-min','queue-year-max','queue-min-votes','queue-language','queue-access','queue-sort'])$(id).addEventListener('change',()=>{queuePage=1;refreshQueue(true).catch(error=>message(error.message,true));});
  $('queue-search').addEventListener('input',()=>{clearTimeout(debounce);debounce=setTimeout(()=>{queuePage=1;refreshQueue(true).catch(error=>message(error.message,true));},250);});
  $('page-prev').addEventListener('click',()=>{if(queuePage>1){queuePage--;refreshQueue(true).catch(error=>message(error.message,true));}});
  $('page-next').addEventListener('click',()=>{queuePage++;refreshQueue(true).catch(error=>message(error.message,true));});
  document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden&&!$('dashboard').hidden)refresh().catch(error=>message(error.message,true));});
  for(const link of document.querySelectorAll('.nav-item'))link.addEventListener('click',()=>{for(const other of document.querySelectorAll('.nav-item'))other.classList.toggle('active',other===link);});
  refresh().catch(()=>{});
})();

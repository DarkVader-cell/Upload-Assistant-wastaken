'use strict';
/** Read-only, version-pinned adapter for CardinalDL 3.10.16 listing mode.
 * Never modifies Cardinal files/profiles, never accepts a download argument.
 * Uses the installed CLI's own saved preferences and quality-selection helpers.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const Module = require('node:module');
const EXPECTED = '1963e0217e5dde2593312ba2b61fca089568c613a099d706a0f91ae8b7b3eeba';

function fail(message) { process.stderr.write(`Catalogue metadata refused: ${message}\n`); process.exit(2); }
const cli = path.resolve(process.argv[2] || 'src/cli.js');
const args = process.argv.slice(3);
const selfTest = args.length===1 && args[0]==='--self-test';
const allowed = new Map([['--service',1],['--configpath',1],['--listitem',1],['--season',1],['--jsonoutput',1],['--ua-episode-id',1],['--full',0],['--workers',1]]);
const options = {};
if(selfTest) Object.assign(options,{'--service':'netflix','--listitem':'fixture','--jsonoutput':'fixture'});
for (let i=0;!selfTest && i<args.length;i++) {
  const flag=args[i], count=allowed.get(flag);
  if (count===undefined || flag in options || (count && (i+1>=args.length || args[i+1].startsWith('--')))) fail('unsupported arguments');
  options[flag]=count ? args[++i] : true;
}
if (!options['--service'] || !options['--listitem'] || !options['--jsonoutput']) fail('listing with JSON output required');
if (!['amazon','netflix','appletv'].includes(options['--service'])) fail('unsupported service');
if (options['--workers'] && options['--workers']!=='1') fail('listing must be serial');
const source=fs.readFileSync(cli,'utf8');
if (crypto.createHash('sha256').update(source).digest('hex')!==EXPECTED) fail('CLI build changed; adapter validation required');
const home=path.dirname(cli);
if(selfTest) {
  const forbidden=()=>fail('network access forbidden in self-test');
  require('node:net').Socket.prototype.connect=forbidden;
  require('node:tls').connect=forbidden;
  require('node:dgram').createSocket=forbidden;
  for(const protocol of ['node:http','node:https']) { const transport=require(protocol); transport.request=forbidden; transport.get=forbidden; }
  globalThis.fetch=forbidden;
}
const formatter=require(path.join(home,'app/modules/listfmt.js'));
const quality=require(path.join(home,'app/modules/quality.js'));
const media=require(path.join(home,'shared/mediaQuality.js'));
const rawItems=new Map(), trackPlans=new Map();
globalThis.__uaCatalogueWantedEpisode=options['--ua-episode-id'] || null;
globalThis.__uaCatalogueCapture=(target,tracks)=>{
  // Cache only sanitized plans, never raw manifests/segments or signed URLs.
  trackPlans.set(String(target.id),{movie:makePlan(target,tracks,'movie'),episode:makePlan(target,tracks,'episode')});
};
globalThis.__uaCatalogueContext=null;
function providerErrorCode(error){
  return /No matching Playback Envelope was returned/i.test(String(error?.message||'')) ? 'playback_unavailable':null;
}
function emptyNetflixMetadata(url,request,result,requested){
  try {
    const target=new URL(String(url));
    const id=request?.params?.movieid ?? target.searchParams.get('movieid');
    return target.protocol==='https:' && target.hostname==='www.netflix.com' && target.pathname==='/nq/website/memberapi/release/metadata' && String(id)===String(requested) && result!==null && typeof result==='object' && !Array.isArray(result) && Object.keys(result).length===0;
  } catch {return false;}
}
function writeProviderFailure(code){
  if(!fs.existsSync(options['--jsonoutput']))fs.writeFileSync(options['--jsonoutput'],JSON.stringify({schema:1,cli_sha256:EXPECTED,service:options['--service'],requested:options['--listitem'],error:{code}}),{mode:0o600});
}
globalThis.__uaCatalogueProtect=service=>{
  if(!service) return;
  let titleUnavailable=false;
  if(options['--service']==='netflix' && typeof service.req?.fetch==='function'){
    const fetch=service.req.fetch;
    service.req.fetch=async function(url,request,...rest){
      const result=await fetch.call(this,url,request,...rest);
      if(emptyNetflixMetadata(url,request,result,options['--listitem']))titleUnavailable=true;
      return result;
    };
  }
  for(const method of ['item','episode']){
    if(typeof service[method]!=='function')continue;
    const original=service[method];
    service[method]=async function(...values){
      try{
        titleUnavailable=false;
        const result=await original.apply(this,values);
        if(!result && titleUnavailable)writeProviderFailure('title_unavailable');
        return result;
      }
      catch(error){
        // Only a fixed classifier is exported, never the provider error text,
        // playback envelopes, tokens, signed URLs, or account details.
        if(providerErrorCode(error)==='playback_unavailable')writeProviderFailure('playback_unavailable');
        throw error;
      }
    };
  }
};

function remember(value, depth=0, seen=new Set()) {
  if (!value || typeof value!=='object' || depth>8 || seen.has(value) || seen.size>20000) return;
  seen.add(value);
  if (value.id!==undefined && (value.title!==undefined || value.episode!==undefined)) rawItems.set(String(value.id),value);
  if (value instanceof Map) for (const child of value.values()) remember(child,depth+1,seen);
  else if (Array.isArray(value)) for(const child of value) remember(child,depth+1,seen);
  else for(const key of ['item','episodes','seasons']) remember(value[key],depth+1,seen);
}
for (const name of ['buildMovieJson','buildEpisodeJson','buildSeasonJson','buildSeriesJson']) {
  const original=formatter[name];
  if (typeof original!=='function') fail('listing serializer missing');
  formatter[name]=(...values)=> { for(const value of values) remember(value); return original(...values); };
}
function text(value) {
  return typeof value==='string' ? value.slice(0,500) : null;
}
function identifier(value) {
  if(value===null || value===undefined || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/.test(String(value))) fail('unsafe provider identifier');
  return String(value);
}
function number(value) {
  if(value===null || value==='' || typeof value==='boolean') return null;
  const n=Number(value); return Number.isFinite(n) && n>=0 ? n : null;
}
function languageSelection(requested, available) {
  if (!Array.isArray(requested) || !requested.length) return null;
  const values=requested.map(x=>String(x).split(':')[0].toUpperCase());
  if(values.includes('ALL')) return available;
  const canonical=Object.keys(formatter.buildMovieJson({id:'__ua_language_normalization__',title:'Language normalization',audios:values}).item?.audios || {});
  return available.filter(x=>canonical.includes(x.toUpperCase()));
}
function plan(id, kind) {
  return trackPlans.get(String(id))?.[kind] || {ok:false,reason:'Full quality metadata unavailable'};
}
function makePlan(raw, manifest, kind) {
  const context=globalThis.__uaCatalogueContext;
  const tracks=kind==='movie' ? raw?.resolutions : manifest;
  if (!context || !Array.isArray(tracks) || !tracks.length || !manifest?.length) return {ok:false,reason:'Full quality metadata unavailable'};
  let selected=media.selectVideoTrack(tracks,context.videoRequest,context.preferences);
  if (!selected.track) return {ok:false,reason:'Saved Cardinal profile has no matching video track'};
  if (kind==='movie') {
    const primary=media.parseVideoQualitySpec(quality.getAvailableQualities([selected.track])[0] || '');
    if (!primary?.height) return {ok:false,reason:'Movie resolution selection is unknown'};
    selected=media.selectVideoTrack(manifest,{...context.videoRequest,resolution:primary.height,exactResolution:true},context.preferences);
    if (!selected.track) return {ok:false,reason:'Selected movie resolution is absent from the manifest'};
    const actual=media.parseVideoQualitySpec(quality.getAvailableQualities([selected.track])[0] || '');
    if (primary.codec && primary.codec!==actual.codec || primary.range && primary.range!==actual.range) return {ok:false,reason:'Movie and manifest profile choices disagree'};
  }
  const descriptions=quality.getAvailableQualities([selected.track]);
  if (descriptions.length!==1 || typeof descriptions[0]!=='string') return {ok:false,reason:'Selected track is ambiguous'};
  const parsed=media.parseVideoQualitySpec(descriptions[0]);
  if (!parsed?.height || !parsed.codec) return {ok:false,reason:'Selected quality could not be normalized'};
  const rangeMap={sdr:[],dv:['DV'],'dv-hdr10':['DV','HDR10'],'dv-hdr10+':['DV','HDR10+'],hdr10:['HDR10'],'hdr10+':['HDR10+'],hlg:['HLG']};
  if (parsed.range && !(parsed.range in rangeMap)) return {ok:false,reason:'Unrecognized dynamic range'};
  return {ok:true,quality:descriptions[0],resolution:`${parsed.height}p`,codec:parsed.codec,
    video_width:number(selected.track.width),video_height:number(selected.track.height),
    hdr:rangeMap[parsed.range || 'sdr'],hybrid:Boolean(parsed.hybrid),container:context.outputFormat,profile_source:'Cardinal saved preferences',
    audio_requested:Array.isArray(context.dubs)?context.dubs:null,
    subtitle_requested:Array.isArray(context.subs)?context.subs:null};
}
function item(value,kind) {
  if (!value || value.id===undefined) return null;
  const raw=rawItems.get(String(value.id)) || value;
  const chosen={...plan(value.id,kind)};
  const audio=Object.keys(value.audios || {});
  const subs=Array.isArray(value.subtitles) ? value.subtitles.map(x=>String(x.code || '').toUpperCase()).filter(Boolean) : [];
  if (chosen.ok) {
    chosen.audio_languages=languageSelection(chosen.audio_requested,audio);
    chosen.subtitle_languages=languageSelection(chosen.subtitle_requested,subs);
    delete chosen.audio_requested; delete chosen.subtitle_requested;
  }
  return {id:identifier(value.id),title:text(value.title),kind,
    year:number(raw.year ?? raw.releaseYear ?? raw.originalReleaseYear),
    imdb_id:text(raw.imdb_id ?? raw.imdbId),
    episode:number(value.episode),is_special:value.is_special===true,
    plan:chosen};
}
const write=formatter.writeJsonOutput;
if (typeof write!=='function') fail('JSON writer missing');
formatter.writeJsonOutput=(destination,data)=> {
  // Whitelist metadata; never persist manifests, signed URLs, service tokens, or account settings.
  const root={schema:1,adapter:'cardinal-3.10.16',cli_sha256:EXPECTED,service:options['--service'],requested:options['--listitem'],selected_episode:options['--ua-episode-id'] || null};
  root.item=item(data.item,Array.isArray(data.seasons)?'series':'movie');
  root.episode=item(data.episode,'episode');
  root.seasons=(data.seasons || (data.season?[data.season]:[])).map(season=>({id:identifier(season.id),
    number:number(season.season),title:text(season.title),episodes:(season.episodes || []).map(x=>item(x,'episode')).filter(Boolean)}));
  if(options['--ua-episode-id']) for(const season of root.seasons) season.episodes=season.episodes.filter(episode=>episode.id===options['--ua-episode-id']);
  return write(destination,root);
};
function replaceOnce(text, anchor, replacement) {
  if (text.split(anchor).length!==2) fail('CLI instrumentation contract changed');
  return text.replace(anchor,replacement);
}
const begin=source.indexOf('async function fullList(mod, target) {');
const end=source.indexOf('async function fullListBatch',begin);
if (begin<0 || end<begin) fail('full-list contract changed');
let full=source.slice(begin,end);
full=replaceOnce(full,'async function fullList(mod, target) {','async function fullList(mod, target) {\n    if(globalThis.__uaCatalogueWantedEpisode && String(target.id)!==globalThis.__uaCatalogueWantedEpisode) return;');
const trackAnchor='const tracks = stream.video_tracks ?? (await xml?.getVideoTracks());';
full=replaceOnce(full,trackAnchor,trackAnchor+'\n        globalThis.__uaCatalogueCapture(target, tracks);');
let patched=source.slice(0,begin)+full+source.slice(end);
const serviceAnchor='const module = await (0, services_1.getService)(args.service);';
patched=replaceOnce(patched,serviceAnchor,serviceAnchor+'\n    globalThis.__uaCatalogueProtect(module);');
const prefAnchor='const captionModeRequests = args.dlsubs.map((code) => ({';
patched=replaceOnce(patched,prefAnchor,'globalThis.__uaCatalogueContext = {preferences, videoRequest, dubs:args.dublang, subs:args.dlsubs, outputFormat};\n    '+prefAnchor);
if(selfTest) {
  if(providerErrorCode(new Error('Amazon playback is unavailable for a fixture. No matching Playback Envelope was returned.'))!=='playback_unavailable' || providerErrorCode(new Error('Unrelated failure'))!==null) fail('provider error classification failed');
  const emptyUrl='https://www.netflix.com/nq/website/memberapi/release/metadata';
  if(!emptyNetflixMetadata(emptyUrl,{params:{movieid:'12345'}},{},'12345') || emptyNetflixMetadata(emptyUrl,{params:{movieid:'12345'}},null,'12345') || emptyNetflixMetadata(emptyUrl,{params:{movieid:'12345'}},{},'99999') || emptyNetflixMetadata(emptyUrl,{params:{movieid:'12345'}},{error:true},'12345'))fail('empty title classification contract failed');
  const preferences=require(path.join(home,'shared/qualityPreferences.js')).normalizeQualityPreferences({resolutionPreference:1080});
  globalThis.__uaCatalogueContext={preferences,videoRequest:{resolution:1080,exactResolution:true,allowHybrid:false},dubs:['EN'],subs:['EN'],outputFormat:'mkv'};
  const track={id:'fixture-quality',width:1920,height:1080,resolution:1080,codec:'h264',flags:['H264','SDR']};
  const target={id:'fixture',title:'Synthetic offline fixture',resolutions:[track],audios:['en']};
  rawItems.set('fixture',target);globalThis.__uaCatalogueCapture(target,[track]);
  const result=plan('fixture','movie');
  if(!result.ok || result.resolution!=='1080p' || result.codec!=='H264') fail('synthetic selection contract failed');
  const modeFixtures={sdr:'SDR',hdr10:'HDR10','hdr10+':'HDR10+',dv:'Dolby Vision','dv-hdr10':'DV/HDR10','dv-hdr10+':'DV/HDR10+',hlg:'HLG'};
  for(const [mode,range] of Object.entries(modeFixtures)) {
    const combined=mode.startsWith('dv-');
    const video={id:'fixture-'+mode,width:1920,height:1080,codec:'hevc',dynamicRange:range,generatedHybrid:combined};
    const raw={id:video.id,title:'Synthetic range fixture',resolutions:[video],audios:['en']};
    globalThis.__uaCatalogueContext.videoRequest={resolution:1080,exactResolution:true,ranges:media.VIDEO_RANGES_BY_FLAG[mode],allowHybrid:combined,fallback:false};
    const selected=makePlan(raw,[video],'movie');
    if(!selected.ok || selected.hdr.join(',')!==({sdr:[],hdr10:['HDR10'],'hdr10+':['HDR10+'],dv:['DV'],'dv-hdr10':['DV','HDR10'],'dv-hdr10+':['DV','HDR10+'],hlg:['HLG']}[mode]).join(','))fail('exact dynamic-range selection contract failed: '+mode);
    const wrong={...video,dynamicRange:mode==='sdr'?'HDR10':'SDR',generatedHybrid:false};
    if(makePlan({...raw,resolutions:[wrong]},[wrong],'movie').ok)fail('dynamic-range fallback was not rejected');
  }
  globalThis.__uaCatalogueContext.videoRequest={resolution:1080,exactResolution:true,allowHybrid:false};
  const normalized=item(formatter.buildMovieJson(target).item,'movie');
  if(!normalized.plan.ok || !normalized.plan.audio_languages?.includes('EN')) fail('language-selection contract failed');
  result.profile_source='synthetic fixture preferences';
  process.stdout.write(JSON.stringify({ok:true,cli_sha256:EXPECTED,selection:result,language_selection:normalized.plan.audio_languages,network_calls:0})+'\n');
  process.exit(0);
}
const cliArgs=[];
for(let i=0;i<args.length;i++) {if(args[i]==='--ua-episode-id'){i++;continue;}cliArgs.push(args[i]);}
process.argv=[process.execPath,cli,...cliArgs];
const compiled=new Module(cli,module);
compiled.filename=cli;
compiled.paths=Module._nodeModulePaths(home);
compiled._compile(patched,cli);

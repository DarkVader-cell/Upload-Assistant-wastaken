'use strict';
// Read-only native title-info adapter. Never request manifests, licenses or media.
const fs = require('node:fs');
const Module = require('node:module');
const path = require('node:path');
const crypto = require('node:crypto');
const hash = '1963e0217e5dde2593312ba2b61fca089568c613a099d706a0f91ae8b7b3eeba';
const safeEnum = x => typeof x === 'string' && /^[A-Za-z_]{1,48}$/.test(x) ? x : null;
const publicId = x => typeof x === 'string' && /^(amzn1\.dv\.gti\.[a-fA-F0-9-]{36}|[A-Z0-9]{10,26})$/.test(x) ? x : null;
function normalize(resource) {
  const pending = [...(resource.primaryActions || []), ...(resource.actions || []), ...(resource.adaptiveActions || [])];
  const actions = [];
  for (let i = 0; i < pending.length && i < 150; i++) {
    const action = pending[i];
    if (!action || typeof action !== 'object') continue;
    if (Array.isArray(action.childActions)) pending.push(...action.childActions.slice(0, 150));
    const metadata = action.navigationAction?.playbackMetadata || action.metadata;
    if (!metadata || metadata.metadataActionType !== 'Playback') continue;
    const clean = {metadataActionType: 'Playback', videoMaterialType: safeEnum(metadata.videoMaterialType), isTrailer: metadata.isTrailer === true, isUnopenedRental: metadata.isUnopenedRental === true, userEntitlementMetadata: {entitlementType: safeEnum(metadata.userEntitlementMetadata?.entitlementType), benefitType: (metadata.userEntitlementMetadata?.benefitType == null || metadata.userEntitlementMetadata.benefitType === '' || (Array.isArray(metadata.userEntitlementMetadata.benefitType) && metadata.userEntitlementMetadata.benefitType.length === 0)) ? null : (safeEnum(metadata.userEntitlementMetadata.benefitType) || 'UNRECOGNIZED')}, playbackExperienceMetadata: {playbackEnvelope: !!metadata.playbackExperienceMetadata?.playbackEnvelope}};
    // Native full Features own this key with value undefined. Do not turn that
    // legitimate omission into a fabricated cross-title identifier.
    if (metadata.playbackTitle !== undefined) clean.playbackTitle = publicId(metadata.playbackTitle) || 'UNRECOGNIZED';
    actions.push({metadata: clean});
  }
  return {imdbTconst: /^tt[0-9]{7,10}$/.test(resource.imdbTconst || '') ? resource.imdbTconst : null, gti: publicId(resource.gti), actions};
}
module.exports = {normalize};
if (require.main === module) {
  const [cli, requestFile, ...args] = process.argv.slice(2);
  const request = JSON.parse(fs.readFileSync(requestFile, 'utf8'));
  let source = fs.readFileSync(cli, 'utf8');
  if (crypto.createHash('sha256').update(source).digest('hex') !== hash) process.exit(42);
  const output = args[args.indexOf('--jsonoutput') + 1];
  function finish(resource, country, error) {
    const data = {schema: 1, cli_sha256: hash, service: 'amazon', requested: request.item, country: /^[A-Za-z]{2}$/.test(country || '') ? country.toUpperCase() : null, resource, error};
    fs.writeFileSync(output, JSON.stringify(data), {flag: 'wx', mode: 0o600});
    process.exit(0);
  }
  globalThis.__uaPrimeAccess = service => {
    if (!service || typeof service.itemAPI !== 'function' || !service.req || typeof service.req.fetch !== 'function') process.exit(42);
    const fetch = service.req.fetch;
    service.req.fetch = async function(url, ...rest) {
      let pathname;
      try { pathname = new URL(String(url)).pathname; } catch { throw new Error('Read-only access probe refused unknown request shape'); }
      if (/license|manifest|purchase|checkout|order|rent|buy|GetPlaybackResources|registerDevice|deregister|linkDevice/i.test(pathname)) throw new Error('Non-metadata request blocked');
      return fetch.call(this, url, ...rest);
    };
    const original = service.itemAPI;
    service.itemAPI = async function(...values) {
      const result = await original.apply(this, values);
      if (!result?.resource) finish(null, this.country, 'no_title_resource');
      finish(normalize(result.resource), this.country, null);
    };
  };
  const anchor = 'const module = await (0, services_1.getService)(args.service);';
  if (source.split(anchor).length !== 2) process.exit(42);
  source = source.replace(anchor, anchor + '\nglobalThis.__uaPrimeAccess(module);');
  process.argv = [process.execPath, cli, ...args];
  const compiled = new Module(cli, module);
  compiled.filename = cli;
  compiled.paths = Module._nodeModulePaths(path.dirname(cli));
  compiled._compile(source, cli);
}

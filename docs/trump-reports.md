# Aither/LST trump reports

UA supports opt-in trump reports on Aither and LST. In attended mode, existing
search matches can be selected for a **manual trump report**, even when the API
has not flagged them as trumpable or the basic duplicate filter removes them.
A slot-rule replacement recommendation also offers the report workflow.

A manual report option is not a claim that a torrent is eligible to be trumped.
Confirm the site rules, quality/source requirements and required comparison
images. The report confirmation defaults to **No**. If multiple existing
torrents are available, select the target explicitly; UA shows its name and ID.
Declining the report still allows the ordinary upload decision without a report.

Unattended runs do not silently authorize a report. Use attended confirmation
when you want to choose a target and provide evidence. Duplicate-check bypass
continues to bypass the interactive duplicate/trump prompts.

After confirmation, the existing workflow checks for prior reports and obtains
comparison evidence where required. LST asks for an additional report reason.
Report submission follows a successful upload, using the confirmed old torrent
ID and the new uploaded torrent ID. Failed uploads, revoked per-tracker intent,
invalid targets and self-reports are not submitted. Intent and reasons are
tracked separately for each site, so accepting one site's report does not
approve another site's report.

PTP's slot recommendations do not enable a PTP report-submission endpoint.

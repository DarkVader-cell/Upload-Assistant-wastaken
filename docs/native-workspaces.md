# Native Library and Remote workspaces

Library and Remote now live inside the existing React upload interface, sharing
UA's theme, navigation rail, authenticated API helper and upload form. Legacy
`/upload-library` and `/remote-upload` links redirect to the corresponding main
workspace. Mobile layouts have matching workspace navigation.

The normal Upload form has a destination selector. Local execution is unchanged.
For a configured remote destination, select the file using the existing browser,
choose explicit trackers and set the remote seed interval. Supported metadata
arguments (edition, IDs, source/type/resolution, year, tag, screenshots and common
boolean flags) are forwarded as quoted argv, not shell fragments. Remote jobs
run unattended: policy reviews are not bypassed. The Remote workspace displays
transfer bytes, MiB/s, operations, jobs and return deadlines.

Local auxiliary paths (description files, custom screenshots and other files)
are **not** silently forwarded to a machine that cannot access them. Unsupported
options are rejected until an explicit auxiliary-file staging mechanism exists.
Remote staging currently accepts one release per job/backend operation; a
multi-item remote submission is refused before copying anything.

Library retains search, tracker/status/category/resolution filters, paging,
select page/all filtered, metadata import and retry preparation. Prepare retry
loads server-validated paths and only missing tracker targets into the existing
Upload form. Choose local or remote destination and review normal UA options
before executing. Library preparation does not itself upload anything.

Known scope: remote jobs use persisted remote operation status, rather than the
local interactive terminal's screenshot/prompt stream. Local-only features are
not claimed to work remotely. This integration does not transplant local files
referenced by arbitrary CLI flags.

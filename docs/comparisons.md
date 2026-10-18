# Local video comparisons

Open **Comparisons** in the WebUI navigation (or `/comparisons`). This separate
page renders matched frame numbers from two to four server-side videos using
Squash's `multi_comps.vpy`; it does not upload screenshots or interact with any
tracker or torrent client.

1. Browse an allowed root and select two to four video files.
2. Set source labels and, if needed, a frame trim offset for each source.
3. Choose automatic frame positions (1–8) or explicit comma-separated frame numbers.
4. Leave tone mapping on Auto for detected HDR/Dolby Vision, or explicitly select
   SDR, HDR10, HDR10+, or Dolby Vision conversion.
5. Click **Generate comparisons**. Preview the results and download the ZIP.

The upstream script normalizes to 24000/1001 fps. It does **not** automatically
align different editions, cuts, opening logos, or variable-frame-rate sources.
Always inspect scene alignment; use offsets/exact frames to correct it.
Automatic HLG conversion is rejected because this script has no native HLG
mode. Dolby Vision/FEL metadata handling depends on source/plugin support;
missing metadata is an error, not a silent SDR conversion. The initial UI does
not expose EL baking, telecine correction, crop/border or arbitrary Python code.

## Dedicated installation

Use Python 3.12+ on Linux with glibc 2.28+ and FFmpeg/ffprobe available:

```bash
UA_COMPARISON_BOOTSTRAP_PYTHON=/path/to/python3.14 bash scripts/install-comparisons.sh
```

This installs a separate virtualenv at `~/.local/share/ua-comparisons/venv` and an
independent upstream source checkout at a pinned revision. It does not modify
system Python or UA's upload dependencies. The upstream script is GPL-3.0;
its source and license remain in that independent checkout, not bundled into UA.
The adapter verifies the pinned script's SHA-256 before loading it. It replaces
only configuration, the desktop output-registration helper, and source index
cache locations in memory; the upstream checkout is not edited.
The desktop Qt/vspreview application is not required for headless export.

Set these environment variables on the UA service and restart only UA:

```ini
UA_COMPARISON_PYTHON=/home/USER/.local/share/ua-comparisons/venv/bin/python
UA_COMPARISON_SCRIPT=/home/USER/.local/share/ua-comparisons/upstream/video/multi_comps.vpy
```

Containers and other instances without that separate runtime show a setup
notice rather than attempting an upload or substituting a different renderer.
VapourSynth plugin wheels include LSMASHSource, SubText, FillBorders, vivtc and
vs-placebo. The script's optional extra processing modes are not all enabled by
the initial WebUI. GPU/Vulkan/software-renderer capabilities must be verified
for HDR conversion on each host.

The same pinned checkout also contains `video/check_idr.py`; its `rich`, `av`
and FFmpeg requirements are installed. It remains a separate CLI tool, for example:

```bash
~/.local/share/ua-comparisons/venv/bin/python \
  ~/.local/share/ua-comparisons/upstream/video/check_idr.py /path/stream.h264 --frame 1000
```

## Resource and security limits

- Requires a logged-in WebUI session; mutations require CSRF and same-origin validation.
- Source paths must resolve within UA's configured browse roots.
- One comparison job at a time; up to four sources and eight frames per source.
- Maximum source resolution 4096×2160; rendering uses two VapourSynth threads,
  a 256 MiB frame cache, and a 30-minute subprocess timeout.
- Results live under the private UA state directory `tmp/comparisons/<job-id>/`.
  The ZIP includes images and labels/frame numbers, not source paths or logs.
- Rendering is local only. You decide which results to share or upload later.
- Job listing is in-memory and resets when UA restarts. Completed files remain
  on disk for manual cleanup; do not delete a job folder while it is rendering.
- Detailed errors are in the job's private `render.log`; API errors are sanitized.

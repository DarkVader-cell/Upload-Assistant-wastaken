#!/usr/bin/env bash
# Dedicated-host installer. No system Python packages or torrent services change.
set -euo pipefail
umask 022
root="${UA_COMPARISON_ROOT:-$HOME/.local/share/ua-comparisons}"
python="${UA_COMPARISON_BOOTSTRAP_PYTHON:-python3}"
revision=52aa470ad8018d30fe598f783e4d33c33e33fcf6
"$python" -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12+ is required"'
mkdir -p "$root"
if [[ ! -d "$root/upstream/.git" ]]; then
  git clone https://github.com/9Oc/Squash-P2P-Scriptorium.git "$root/upstream"
fi
[[ -z "$(git -C "$root/upstream" status --porcelain)" ]] || { echo 'Upstream checkout has local modifications; refusing overwrite' >&2; exit 1; }
git -C "$root/upstream" fetch origin "$revision"
git -C "$root/upstream" checkout --detach "$revision"
if [[ ! -x "$root/venv/bin/python" ]]; then "$python" -m venv "$root/venv"; fi
"$root/venv/bin/python" -m pip install --only-binary=:all: \
 'VapourSynth==81' 'vapoursynth-lsmas==1310.0.0.0' \
 'vapoursynth-subtext==7.0' 'vapoursynth-fillborders==4.0' \
 'vapoursynth-vivtc==2.0' 'vs-placebo==2.0.4' \
 'vstools==3.4.5' 'awsmfunc==1.3.5' 'pillow==13.0.0' 'numpy==2.5.4' \
 'rich==15.0.0' 'av==19.0.1' 'vsutil==0.8.0'
"$root/venv/bin/python" -m pip check
"$root/venv/bin/python" -m pip freeze > "$root/requirements.lock.txt"
"$root/venv/bin/python" - <<'PY'
import vapoursynth as vs
import vstools, awsmfunc, av
from awsmfunc.types.placebo import PlaceboColorSpace
core = vs.core
for name in ('lsmas', 'sub', 'fb', 'vivtc', 'placebo'):
    if not hasattr(core, name):
        raise SystemExit('Missing VapourSynth plugin: ' + name)
print('Comparison runtime imports/plugins OK')
PY
printf '\nConfigure the UA service with:\nUA_COMPARISON_PYTHON=%s/venv/bin/python\nUA_COMPARISON_SCRIPT=%s/upstream/video/multi_comps.vpy\n' "$root" "$root"

#!/usr/bin/env python3
"""Headless adapter for an independently installed Squash multi_comps.vpy.

The upstream GPL script is not bundled or copied into UA. Configuration is
supplied as data, never user Python. Rendering does not upload or seed anything.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def render(config_path: Path, script_path: Path) -> None:
    import numpy as np
    import vapoursynth as vs
    from PIL import Image

    config = json.loads(config_path.read_text())
    core = vs.core
    core.num_threads = 2
    core.max_cache_size = 256
    script_bytes = script_path.read_bytes()
    if hashlib.sha256(script_bytes).hexdigest() != "6d3a25b5072bdc763a0cc3fbf4244a4b67904057b527b4974e214831f888e51f":
        raise ValueError("Comparison script does not match the pinned reviewed revision")
    script = ast.parse(script_bytes.decode("utf-8"), str(script_path))

    class SourceCache(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module == "vstools":
                # New vstools no longer exports the desktop preview helper.
                node.names = [alias for alias in node.names if alias.name != "set_output"]
            return node

        def visit_Call(self, node):
            self.generic_visit(node)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "LWLibavSource":
                node.func = ast.copy_location(ast.Name(id="__ua_lwsource", ctx=ast.Load()), node.func)
            return node

    script = ast.fix_missing_locations(SourceCache().visit(script))
    # Replace only upstream configuration assignments. No path/label is code.
    targets = {"clips_config", "src_min", "src_max"}
    script.body = [n for n in script.body if not (
        isinstance(n, (ast.Assign, ast.AnnAssign)) and any(
            isinstance(t, ast.Name) and t.id in targets
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
        )
    )]
    def load_source(path):
        cache = config_path.parent / (hashlib.sha256(str(path).encode()).hexdigest() + ".lwi")
        return core.lsmas.LWLibavSource(path, cachefile=str(cache), threads=2)

    def set_output(clip, **_kwargs):
        # Headless equivalent: preserve each processed clip in VS's output registry.
        clip.set_output(len(vs.get_outputs()))

    ns = {"__name__": "__ua_comparison__", "__file__": str(script_path), "__ua_lwsource": load_source, "set_output": set_output}
    # Marker classes live before the config block. Execute that prefix first.
    split = next(i for i, n in enumerate(script.body) if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Tuple) and any(isinstance(x, ast.Name) and x.id == "fpsnum" for x in t.elts)
        for t in n.targets
    ))
    exec(compile(ast.Module(body=script.body[:split], type_ignores=[]), str(script_path), "exec"), ns)  # noqa: S102 - SHA256-pinned upstream code; user settings remain data.
    clips = []
    for item in config["sources"]:
        executable = shutil.which("ffprobe")
        if executable is None:
            raise ValueError("ffprobe is not installed")
        probe = subprocess.run([executable, "-v", "error", "-select_streams", "v:0", "-show_streams", "-of", "json", item["path"]], capture_output=True, text=True, timeout=30, check=True)  # noqa: S603 - fixed argv, prevalidated local file, no shell.
        stream = json.loads(probe.stdout)["streams"][0]
        if int(stream.get("width", 0)) * int(stream.get("height", 0)) > 4096 * 2160:
            raise ValueError("Comparison sources must be at most 4096x2160")
        if item["tonemap"] == "auto":
            side = str(stream.get("side_data_list", [])).lower()
            item["tonemap"] = "dovi" if "dovi" in side or "dolby vision" in side else "hdr" if stream.get("color_transfer") in {"smpte2084", "arib-std-b67"} else "none"
            if stream.get("color_transfer") == "arib-std-b67":
                raise ValueError("HLG automatic tone mapping is not supported by this upstream script; choose a supported conversion explicitly")
        entry = [item["path"], item["label"] + " (Comparison)", ns["Engine"].LSMASH]
        if item["offset"]:
            entry.append(item["offset"])
        if item["tonemap"] != "none":
            entry.append(ns[{"hdr": "HDR", "hdr10plus": "HDR10Plus", "dovi": "DOVI"}[item["tonemap"]]])
        clips.append(tuple(entry))
    ns.update(clips_config=clips, src_min=None, src_max=None)
    vs.clear_outputs()
    exec(compile(ast.Module(body=script.body[split:], type_ignores=[]), str(script_path), "exec"), ns)  # noqa: S102 - pinned upstream processing; no user code.
    outputs = [value.clip if hasattr(value, "clip") else value for _, value in sorted(vs.get_outputs().items())]
    if len(outputs) != len(clips):
        raise ValueError("Upstream script did not produce one output per source")
    length = min(c.num_frames for c in outputs)
    if length < 2:
        raise ValueError("Sources have no overlapping usable frames after offsets")
    frames = config.get("frames") or [max(0, min(length - 1, round(length * (i + 1) / (config["count"] + 1)))) for i in range(config["count"])]
    if any(i >= length for i in frames):
        raise ValueError("A selected frame exceeds the shortest prepared source")
    directory = config_path.parent
    manifest = {"frames": frames, "sources": config["sources"], "files": [], "upstream": str(script_path)}
    for source_index, clip in enumerate(outputs):
        if clip.width * clip.height > 4096 * 2160:
            raise ValueError("Comparison sources must be at most 4096x2160")
        options = {"format": vs.RGB24}
        if clip.format.color_family == vs.YUV:
            with clip.get_frame(frames[0]) as first:
                if int(first.props.get("_Matrix", 2)) == 2:
                    options["matrix_in_s"] = "709" if clip.height >= 720 else "170m"
        rgb = core.resize.Bicubic(clip, **options)
        for index, frame_number in enumerate(frames):
            label = re.sub(r"[^A-Za-z0-9._-]+", "-", config["sources"][source_index]["label"]).strip(".-")[:48] or "Source"
            # Existing UA comparison importers use frame-source-label.png.
            name = f"{index + 1:03d}-{source_index + 1:02d}-{label}.png"
            with rgb.get_frame(frame_number) as frame:
                pixels = np.stack([np.asarray(frame[p]) for p in range(3)], axis=2)
                Image.fromarray(pixels, "RGB").save(directory / name)
            manifest["files"].append({"name": name, "source": source_index, "frame": frame_number})
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Comparison rendering completed")


if __name__ == "__main__":
    os.umask(0o077)
    if len(sys.argv) != 3:
        raise SystemExit("Usage: render-comparisons.py CONFIG_JSON MULTI_COMPS_VPY")
    render(Path(sys.argv[1]), Path(sys.argv[2]))

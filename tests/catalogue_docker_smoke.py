"""Dedicated-only, no-download Docker/CLI supervision test.

Checks real Cardinal --version, then synthetic Node children for EOF/timeout.
Does not call streaming or tracker APIs or signal the existing Cardinal server.
"""

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.catalogue_runner import DOCKER_SUPERVISOR, download  # noqa: E402 -- standalone dedicated test bootstrap
from src.catalogue_web import Dashboard  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    docker = config["cardinal_docker"]
    container = docker["container"]
    health = asyncio.run(Dashboard(args.config, Path("/unused/auth")).health())
    if not health["ok"]:
        raise RuntimeError("Actual dedicated Cardinal CLI version check failed")
    binary = shutil.which("docker")
    if not binary:
        raise RuntimeError("Docker executable missing")
    base = [
        binary,
        "exec",
        "--interactive",
        "--user",
        docker.get("user", "node"),
        "--workdir",
        docker.get("workdir", "/app/.output"),
        container,
        "node",
        "-e",
        DOCKER_SUPERVISOR,
    ]

    def command(tag, seconds):
        return [*base, str(seconds), "-e", f"process.title={json.dumps(tag)};setInterval(()=>{{}},1000)"]

    def remaining(tag):
        source = """const fs=require('fs');const tag=process.argv[1];let count=0;
for(const id of fs.readdirSync('/proc')){if(!/^\\d+$/.test(id)||Number(id)===process.pid)continue;
try{if(fs.readFileSync('/proc/'+id+'/cmdline','utf8').split('\\0')[0]===tag)count++;}catch(_){}}
console.log(count);"""
        out = subprocess.check_output([binary, "exec", container, "node", "-e", source, tag], timeout=15)  # noqa: S603 -- fixed probe, own UUID marker
        return int(out)

    tag = "ua-catalogue-probe-" + uuid.uuid4().hex[:10]
    result = download(command(tag, 1), timeout=8)
    if result != "uncertain" or remaining(tag):
        raise RuntimeError("Container-side timeout did not cleanly stop its synthetic child")
    tag = "ua-catalogue-probe-" + uuid.uuid4().hex[:10]
    child = subprocess.Popen(command(tag, 30), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603 -- synthetic child only
    try:
        # Closing stdin must cancel only the synthetic child, with no PID guesses.
        child.stdin.close()
        code = child.wait(timeout=15)
        if code != 124 or remaining(tag):
            raise RuntimeError("Container-side EOF cancellation failed")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    tag = "ua-catalogue-probe-" + uuid.uuid4().hex[:10]
    if download(command(tag, 30), timeout=1) != "uncertain" or remaining(tag):
        raise RuntimeError("Host cancellation left a container child behind")
    print(f"Dedicated Docker smoke passed: CardinalDL {health['version']}; synthetic timeout, EOF, and host cancellation cleanup passed")


if __name__ == "__main__":
    main()

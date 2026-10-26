#!/usr/bin/env python3
"""Run a saved, credential-file-based portable installer profile safely."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.installer_profile import DEFAULT_IMAGE, display_command, install_arguments, installation_lock, load_profile, write_launcher


def output(arguments):
    # Only Docker inspection/compose argv is accepted; no shell or credential values.
    if arguments[0] != "docker":
        raise ValueError("Unexpected installer inspection executable")
    executable = shutil.which("docker")
    if executable is None:
        raise FileNotFoundError("Docker is required")
    return subprocess.check_output([executable, *arguments[1:]], text=True, stderr=subprocess.PIPE).strip()  # noqa: S603


def compose(profile):
    root = Path(profile["install_dir"])
    return ["docker", "compose", "--env-file", str(root / ".env"), "-f", str(root / "docker-compose.yml")]


def refuse_live_instance(profile):
    """Never rewrite settings beneath a running instance or active upload."""
    root = Path(profile["install_dir"])
    if profile["mode"] == "docker" and (root / "docker-compose.yml").is_file() and output([*compose(profile), "ps", "-q", "upload-assistant"]):
        raise ValueError("Existing instance is running. Stop it during an idle maintenance window before reinstalling/syncing settings.")
    if profile["mode"] == "standalone" and (root / "app").is_dir():
        for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
            try:
                args = cmdline.read_bytes().split(b"\0")
                cwd = (cmdline.parent / "cwd").resolve()
                scripts = [Path(a.decode(errors="replace")) for a in args if Path(a.decode(errors="replace")).name == "upload.py"]
                app = (root / "app").resolve()
                if scripts and (cwd.is_relative_to(app) or any(p.is_absolute() and p.resolve().is_relative_to(app) for p in scripts)):
                    raise ValueError("A native UA process is using this instance; stop it during idle maintenance before reinstalling.")
            except (OSError, RuntimeError):
                continue


def pinned_image(profile):
    image = profile.get("image", DEFAULT_IMAGE)
    executable = shutil.which("docker")
    if executable is None:
        raise FileNotFoundError("Docker is required")
    subprocess.run([executable, "pull", image], check=True)  # noqa: S603 - validated reference, no shell
    details = json.loads(output(["docker", "image", "inspect", image]))[0]
    labels = (details.get("Config") or {}).get("Labels") or {}
    if profile.get("revision") and labels.get("org.opencontainers.image.revision") != profile["revision"]:
        raise ValueError("Published image does not match the requested revision; no configuration changed")
    repository = image.split("@", 1)[0]
    if repository.rfind(":") > repository.rfind("/"):
        repository = repository.rsplit(":", 1)[0]
    digests = [value for value in details.get("RepoDigests", []) if value.startswith(repository + "@sha256:")]
    if not digests:
        raise ValueError("No immutable digest for the requested image")
    return digests[0]


def wait_healthy(profile):
    for _ in range(90):
        ids = output([*compose(profile), "ps", "-q", "upload-assistant"]).splitlines()
        if len(ids) == 1:
            state = json.loads(output(["docker", "inspect", ids[0]]))[0]["State"]
            if state.get("Health", {}).get("Status") == "healthy":
                return
            if state.get("Status") in {"dead", "exited"}:
                break
        time.sleep(2)
    raise ValueError("Instance did not become healthy; inspect its private logs before use")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Install/import/start; otherwise show the non-secret plan only")
    parser.add_argument("--write-launcher", type=Path, help="Create an executable .desktop shortcut, without running installation")
    args = parser.parse_args()
    try:
        profile = load_profile(args.profile)
        installer = Path(__file__).with_name("install-instance.sh")
        if args.write_launcher:
            if args.apply:
                raise ValueError("Create a launcher or apply the profile, not both")
            write_launcher(args.profile.expanduser(), args.write_launcher.expanduser(), Path(__file__).resolve())
            print("Private terminal launcher created. It contains file references, not credentials.")
            return 0
        if not args.apply:
            print(display_command(install_arguments(profile, installer)))
            print("Plan only. Use --apply or the saved launcher to install.")
            return 0
        if not sys.platform.startswith("linux"):
            raise ValueError("Automatic installer currently supports Linux; use platform-specific documentation elsewhere")
        with installation_lock(profile):
            refuse_live_instance(profile)
            image = pinned_image(profile) if profile["mode"] == "docker" else None
            # Recheck after the pull, immediately before the installer can write.
            refuse_live_instance(profile)
            subprocess.run(install_arguments(profile, installer, image=image), check=True)  # noqa: S603 - validated profile, fixed installer, no shell
            if profile["mode"] == "docker" and profile.get("start", True):
                wait_healthy(profile)
        print("Configured instance installed. Host paths/client mappings and per-host WebUI login remain local.")
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, KeyError, IndexError):
        # Do not echo config parse/decryption errors or captured child output.
        print(
            "Installation refused or failed. Check the profile, private file permissions, revision pin and idle-instance requirements. No secret values are printed.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Validated, secret-free saved arguments for the portable instance installer."""

from __future__ import annotations

import json
import os
import shlex
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_IMAGE = "ghcr.io/darkvader-cell/upload-assistant-wastaken:latest"
VALUE_FLAGS = {
    "install_dir": "--install-dir",
    "browse_root": "--browse-root",
    "webui_port": "--webui-port",
    "image": "--image",
    "repo_url": "--repo-url",
    "import_bundle": "--import-bundle",
    "bundle_passphrase_file": "--bundle-passphrase-file",
    "prowlarr_url": "--prowlarr-url",
    "prowlarr_api_key_file": "--prowlarr-api-key-file",
}
BOOL_FLAGS = {"install_dependencies": "--install-dependencies", "bundle_overwrite": "--bundle-overwrite"}
PATHS = {"install_dir", "browse_root", "import_bundle", "bundle_passphrase_file", "prowlarr_api_key_file"}
ALLOWED = set(VALUE_FLAGS) | set(BOOL_FLAGS) | {"version", "mode", "start", "revision"}


def load_profile(path: Path) -> dict:
    """Profiles contain paths/options, never raw passwords, tokens or key values."""
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Profile must be a small regular JSON file, not a symlink")
    if path.stat().st_mode & 0o022 or path.stat().st_uid != os.getuid():
        raise ValueError("Profile must be owned by you and not writable by other users")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) - ALLOWED:
        raise ValueError("Unknown profile fields; raw credentials are not accepted")
    if type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("Unsupported installer profile version")
    if data.get("mode", "docker") not in {"docker", "standalone"}:
        raise ValueError("Mode must be docker or standalone")
    result = {"mode": "docker", "start": True, **data}
    for key, value in result.items():
        if key in {*BOOL_FLAGS, "start"}:
            if type(value) is not bool:
                raise ValueError("Installer switches must be booleans")
        elif key != "version":
            if not isinstance(value, (str, int)) or isinstance(value, bool):
                raise ValueError("Invalid installer option type")
            if any(c in str(value) for c in "\r\n\x00"):
                raise ValueError("Installer options cannot contain control characters")
    for key in PATHS:
        if key in result:
            value = Path(str(result[key])).expanduser()
            result[key] = str((path.parent / value).absolute() if not value.is_absolute() else value)
    if not result.get("browse_root") or not result.get("install_dir"):
        raise ValueError("Select an install directory and an existing media browse root")
    install = Path(result["install_dir"]).resolve()
    browse = Path(result["browse_root"]).resolve()
    if not browse.is_dir():
        raise ValueError("Browse root must already exist")
    if install == Path("/") or install == Path.home() or install.is_relative_to(browse) or browse.is_relative_to(install):
        raise ValueError("Installation/state and payload trees must not overlap")
    if Path(result["install_dir"]).is_symlink():
        raise ValueError("Install directory cannot be a symlink")
    if install.exists() and install.stat().st_uid != os.getuid():
        raise ValueError("Install directory must be owned by you")
    for key in ["repo_url", "prowlarr_url"]:
        if result.get(key):
            url = urlsplit(str(result[key]))
            if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("URLs must be HTTP(S), without embedded credentials")
            if key == "repo_url" and url.scheme != "https":
                raise ValueError("Repository URL must use HTTPS")
    port = str(result.get("webui_port", 5000))
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("Invalid WebUI port")
    if result.get("bundle_passphrase_file") and not result.get("import_bundle"):
        raise ValueError("Bundle passphrase requires an encrypted bundle")
    if result.get("bundle_overwrite") and not result.get("import_bundle"):
        raise ValueError("Bundle overwrite requires an encrypted bundle")
    for key in ["bundle_passphrase_file", "prowlarr_api_key_file"]:
        if result.get(key):
            private = Path(result[key])
            if private.is_symlink() or not private.is_file() or private.stat().st_uid != os.getuid() or private.stat().st_mode & 0o077:
                raise ValueError("Credential/passphrase files must be regular, private, and owned by you")
    if result.get("revision"):
        rev = str(result["revision"])
        if result["mode"] != "docker" or len(rev) != 40 or any(c not in "0123456789abcdef" for c in rev):
            raise ValueError("Docker revision pins require a full lowercase commit SHA")
    image = str(result.get("image", DEFAULT_IMAGE))
    if not image or any(c.isspace() for c in image) or "://" in image or image.startswith("-") or ("@" in image and "@sha256:" not in image):
        raise ValueError("Invalid container image reference")
    return result


@contextmanager
def installation_lock(profile: dict):
    """Double-clicks must not start two writers for the same instance."""
    import fcntl

    root = Path(profile["install_dir"])
    root.parent.mkdir(parents=True, exist_ok=True)
    path = root.with_name("." + root.name + ".installer.lock")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(fd).st_uid != os.getuid():
            raise ValueError("Installer lock must be owned by you")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another installer is already managing this instance") from None
        yield
    finally:
        os.close(fd)


def install_arguments(profile: dict, installer: Path, *, image: str | None = None) -> list[str]:
    args = ["bash", str(installer), "--mode", profile["mode"]]
    for key, flag in VALUE_FLAGS.items():
        value = image if key == "image" and image else profile.get(key)
        if value is not None:
            args.extend([flag, str(value)])
    for key, flag in BOOL_FLAGS.items():
        if profile.get(key):
            args.append(flag)
    if not profile.get("start", True):
        args.append("--no-start")
    return args


def write_launcher(profile: Path, target: Path, entrypoint: Path) -> None:
    """A terminal launcher can securely prompt sudo or a bundle passphrase."""
    if any(c in str(value) for value in [profile, target, entrypoint] for c in "\r\n\x00"):
        raise ValueError("Launcher paths cannot contain control characters")
    if target.exists() or target.is_symlink():
        raise ValueError("Refusing to overwrite an existing launcher")
    target.parent.mkdir(parents=True, exist_ok=True)

    def quote(value):
        text = str(value).replace("%", "%%")
        for old, new in [("\\", "\\\\"), ('"', '\\"'), ("$", "\\$"), ("`", "\\`")]:
            text = text.replace(old, new)
        return '"' + text + '"'

    command = " ".join(quote(v) for v in [sys.executable, entrypoint, "--profile", profile.absolute(), "--apply"])
    content = "[Desktop Entry]\nType=Application\nName=Install configured Upload Assistant instance\nTerminal=true\nIcon=system-software-install\nExec=" + command + "\n"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRWXU)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(content)


def display_command(arguments: list[str]) -> str:
    """Arguments contain only public options and file REFERENCES, not secret values."""
    return shlex.join(arguments)

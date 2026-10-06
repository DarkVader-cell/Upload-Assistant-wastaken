#!/usr/bin/env python3
"""Export/import encrypted settings; never accept passphrases in command arguments."""
import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config_bundle import MAX_BUNDLE_BYTES, decrypt_settings, encrypt_settings, import_settings, portable_settings, read_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "import"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--sections", nargs="+", default=["DEFAULT", "TRACKERS"])
    parser.add_argument("--passphrase-file", type=Path, help="Private file; otherwise prompt securely")
    parser.add_argument("--overwrite", action="store_true", help="Explicitly replace existing selected settings during import")
    args = parser.parse_args()
    try:
        if args.passphrase_file:
            if args.passphrase_file.stat().st_mode & 0o077:
                raise ValueError("Passphrase file must have mode 0600 or stricter")
            password = args.passphrase_file.read_text().rstrip("\r\n")
        else:
            password = getpass.getpass("Bundle passphrase (12+ characters): ")
            if args.action == "export" and password != getpass.getpass("Confirm passphrase: "):
                raise ValueError("Passphrases do not match")
        if args.action == "export":
            encrypted = encrypt_settings(portable_settings(read_config(args.config), args.sections), password)
            fd = os.open(args.bundle, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(encrypted)
            print("Encrypted bundle exported. Local paths, runtime state, and cookie files excluded.")
        else:
            with args.bundle.open("rb") as handle:
                encrypted = handle.read(MAX_BUNDLE_BYTES + 1)
            backup = import_settings(args.config, decrypt_settings(encrypted, password), args.overwrite)
            print(f"Imported selected settings; private backup: {backup.name}")
        return 0
    except Exception:
        # Parse/decryption exceptions may contain secret values; do not echo them.
        print("Bundle operation failed. Check permissions, configuration literals, passphrase, and bundle integrity.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

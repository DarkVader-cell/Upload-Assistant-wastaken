# One-click configured client installation

Use a saved profile to install a **new Linux instance** with selected shared
configuration and API/image-host keys. No secrets go into the profile or desktop
shortcut. The existing portable installer and encrypted bundle implementation
remain the installation/import backend.

## Prepare selected shared settings once

Export from the explicitly chosen source instance:

```bash
uv run python scripts/config-bundle.py export \
  --config /path/to/source/data/config.py \
  --bundle /private/shared-settings.ua-bundle \
  --sections DEFAULT TRACKERS
```

It prompts securely for a 12+ character passphrase. For unattended installation,
keep that passphrase in a separate user-owned file with mode `0600`. Transfer the
encrypted bundle and passphrase separately through authenticated SSH or another
private channel; never put either in Git or a public URL.

`DEFAULT`/`TRACKERS` include selected portable settings, metadata/image-host
keys and tracker credentials. They do **not** copy media, torrents, caches,
submission acknowledgements, browser-cookie files, WebUI authentication/session
identity, SSH private keys, or machine-local paths. Torrent-client profiles are
not exported in this recommended selection. Configure destination clients,
storage paths, mount mappings and WebUI login locally.

## Save the profile on the destination

Copy `data/installer-profile.example.json` to a private, user-owned file, e.g.
`~/.config/ua-instance-setup/new-instance.json`. Edit the media root, instance
directory, port and bundle/passphrase file references. The media directory must
exist; it must not overlap the installation/state directory.

```bash
chmod 600 ~/.config/ua-instance-setup/new-instance.json
python3 scripts/one-click-install.py \
  --profile ~/.config/ua-instance-setup/new-instance.json
```

This only prints the non-secret plan. Install with:

```bash
python3 scripts/one-click-install.py \
  --profile ~/.config/ua-instance-setup/new-instance.json --apply
```

Docker mode pulls the selected image, optionally checks its OCI revision label,
then pins the installation to the resolved immutable digest. Set `revision` to
an exact 40-character commit SHA to require that revision. It checks container
health before reporting success. Dependency installation is optional via
`install_dependencies: true` and supports Debian/Ubuntu with root/sudo; Docker
access is never granted silently.

Create the actual one-click terminal shortcut:

```bash
python3 scripts/one-click-install.py \
  --profile ~/.config/ua-instance-setup/new-instance.json \
  --write-launcher ~/.local/share/applications/ua-install-configured.desktop
```

The launcher uses the current Python executable and checkout path; regenerate
it if either moves. It prompts in a terminal for sudo or a bundle passphrase
when necessary. Some desktop environments require explicitly trusting the new
launcher before clicking it.

## Updating shared configuration

This is explicit **one-way import**, not background or bidirectional syncing.
Export a fresh encrypted bundle when the authoritative source settings change.
An import fills missing values by default. `bundle_overwrite: true` explicitly
replaces existing selected **portable** values (for example, rotating tracker
API keys), while excluded host paths remain untouched. Each import keeps a
private timestamped config backup.

The one-click installer refuses to rewrite a **running** existing instance,
even if it appears idle. Stop that instance during an idle maintenance window
before reinstalling/importing. Do not use this new-instance installer to
restructure an existing manually installed server or a shared Compose stack.
Use its existing guarded update procedure instead. Application updates do not
reset submission journals or authorize replaying ambiguous tracker POSTs.

`mode: standalone` delegates to the user-space seedbox installer and creates
`run-ua.sh`; it does not install/restart an existing systemd service or create a
Windows installation. Native Python selection remains the seedbox installer's
policy; the optional `revision` pin is Docker-only.

See [portable installation](instance-installer.md) and
[encrypted bundles](config-bundles.md) for the supported import boundaries.

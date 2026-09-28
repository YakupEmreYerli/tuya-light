# Tuya Light — notes for coding agents

Control Tuya Wi-Fi bulbs over the LAN from three front ends that share one core: a KDE Plasma 6 panel widget, the
`tuya-light` command, and an MCP server. User docs are in `README.md`; the "why it is like this" list is in
`CONTRIBUTING.md`. Read both before changing code.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e './backend[test]'
.venv/bin/pytest backend                       # fake bulb, no hardware needed
./install.sh                                   # pipx command + widget for this user
systemctl --user restart plasma-plasmashell    # after a widget change: QML and translations load once
tools/preview.py /tmp/shots                    # popup rendered off-screen, one PNG per state
tools/preview.py /tmp/shots --config configScenes configAppearance   # settings tabs
tools/update-translations.sh && tools/build-translations.sh          # after changing i18n() text
shellcheck install.sh tools/*.sh
```

## Layout

- `backend/src/tuya_light/` — `light.py` (one bulb, human units in, Tuya units inside), `scenes.py` (scene store),
  `config.py` (device list, private atomic writes), `cli.py`, `mcp_server.py`, `setup.py` (cloud key fetch).
- `plasma/contents/ui/` — `main.qml`, `Backend.qml` (runs the CLI, one light command at a time), `FullRepresentation`,
  `CompactRepresentation`, `ColorWheel`, `SceneInfo`, and four settings tabs `config*.qml`.
- `po/` translations, `tools/` previews, banner and translation scripts, `docs/` logo and images.

## Rules

- Never open windows on the desktop to check the UI: render with `tools/preview.py` (off-screen) and look at the PNGs.
  It needs the system PySide6 (`/usr/bin/python3`), not a pip one.
- Never write to a real bulb to "try" a change; tests use `FakeBulb`. Reading state is fine.
- New widget settings go through the `cfg` property, not `Plasmoid.configuration` directly, so previews keep working.
  Only `configGeneral.qml` declares `cfg_backendCommand` / `cfg_device`.
- Every command that changes a light prints the resulting state; the widget depends on it.
- User-visible strings: `i18n()` in QML, then update and translate `po/tr.po` (keep it at 100 %).
- Commits in English, `feat:` / `fix:` / `docs:` / `ci:` / `chore:`, the why in the body. Push once when a piece of
  work is done, and watch CI (`gh run watch --exit-status`).
- No `rm -rf` in commands, even for temporary directories.

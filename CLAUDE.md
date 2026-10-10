# Tuya Light — notes for coding agents

Control Tuya Wi-Fi bulbs from four front ends that share one core: a KDE Plasma 6 panel widget, the `tuya-light`
command, an MCP server and a phone page (`tuya-light serve`). The core reaches bulbs over the LAN (default) or,
opt-in, through Tuya's cloud OpenAPI. User docs are in `README.md`; the "why it is like this" list is in
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
.venv/bin/python tools/web-preview.py --lights 2                     # phone page, pretend bulbs, 127.0.0.1:8893
tools/web-icons.sh                                                   # after changing docs/brand/logo.svg
docker build . && docker compose --profile home --profile cloud config --quiet
```

## Layout

- `backend/src/tuya_light/` — `light.py` (`BaseLight` + local `Light`, human units in, Tuya units inside),
  `cloud.py` (`CloudLight`, credentials, call-sparing session), `backend.py` (`open_light`, transport precedence),
  `worker.py` (one command at a time per bulb, latest wins, debounce), `web.py` (phone page server, auth, systemd
  unit), `static/` (the page, no build step), `shared.py` (scenes/favourites/names shared between linked
  installs), `scenes.py`, `config.py`, `cli.py`, `mcp_server.py`, `setup.py`.
- `Dockerfile`, `compose.yaml` — the server in a container (profiles `home` local, `cloud` cloud).
- `plasma/contents/ui/` — `main.qml`, `Backend.qml` (runs the CLI, one light command at a time), `FullRepresentation`,
  `CompactRepresentation`, `ColorWheel`, `SceneInfo`, and four settings tabs `config*.qml`.
- `po/` translations, `tools/` previews, banner and translation scripts, `docs/` logo and images.

## Rules

- Never open windows on the desktop to check the UI: render with `tools/preview.py` (off-screen) and look at the PNGs.
  It needs the system PySide6 (`/usr/bin/python3`), not a pip one.
- Never write to a real bulb to "try" a change; tests use `FakeBulb` and `FakeCloud`. Reading state is fine.
- Never call the real Tuya cloud from tests or to "try" something; it spends the owner's monthly allowance.
- Don't install or start the `tuya-light-serve` service on the dev machine; look at the page with
  `tools/web-preview.py` (pretend bulbs, temporary config) and a browser at phone size, with the safe areas set
  through `--safe-top` / `--safe-bottom` on the root element (the page's CSP blocks injected style tags).
- Don't `tuya-light link` the dev machine to anything real; `test_shared.py` covers sync with two fake installs.
- New widget settings go through the `cfg` property, not `Plasmoid.configuration` directly, so previews keep working.
  Only `configGeneral.qml` declares `cfg_backendCommand` / `cfg_device`.
- Every command that changes a light prints the resulting state; the widget depends on it.
- User-visible strings: `i18n()` in QML, then update and translate `po/tr.po` (keep it at 100 %).
- Commits in English, `feat:` / `fix:` / `docs:` / `ci:` / `chore:`, the why in the body. Push once when a piece of
  work is done, and watch CI (`gh run watch --exit-status`).
- No `rm -rf` in commands, even for temporary directories.

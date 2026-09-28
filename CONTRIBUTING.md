# Contributing

Thanks for helping. Issues and pull requests are both welcome; for anything larger than a fix, open an issue first so we can agree on the shape.

## Set up

```bash
git clone https://github.com/YakupEmreYerli/tuya-light.git && cd tuya-light
python3 -m venv .venv && .venv/bin/pip install -e './backend[test]'
.venv/bin/pytest backend
```

The tests use a fake bulb, so they run without hardware. To try your change on a real bulb and in the panel, run `./install.sh`; it reinstalls the command and upgrades the widget. Plasma caches QML, so after a widget change reopen the popup, or restart Plasma: `systemctl --user restart plasma-plasmashell`.

## Before sending

```bash
.venv/bin/pytest backend
shellcheck install.sh tools/*.sh
tools/preview.py /tmp/shots        # renders the popup off-screen; look at the PNGs
```

`tools/preview.py` needs the system PySide6 (the same Qt as Plasma), not one from pip, which ships its own Qt and cannot load Plasma's QML modules.

## Things worth knowing

- **Human units outside, Tuya units inside.** Everything the CLI, MCP server and widget see is 0-100 (hue 0-360). The raw ranges (10-1000 or 25-255, hex colour strings) never leave `backend/src/tuya_light/light.py`. `decode_dps` handles both bulb generations; if you add a layout, add a test with a real sample.
- **Bulbs push partial updates.** Right after a write, a bulb sends only the data points that changed, and that packet can arrive in place of the status reply. `Light._raw_status` merges replies until the switch point is there. Don't "simplify" that loop away.
- **One command at a time from the widget.** `Backend.qml` keeps at most one pending command and replaces it with newer ones. Sending every slider step would queue dozens of TCP sessions against a device that handles one at a time.
- **Every command prints the state afterwards.** The widget relies on this to avoid a second call; keep it true for new commands.
- **No shell interpolation of user input in QML.** Device names go through `_quote()` in `Backend.qml`.

## Translations

Strings live in the QML as `i18n("...")`. After changing them:

```bash
tools/update-translations.sh      # refreshes po/tuya-light.pot and merges into po/*.po
```

To add a language, copy `po/tuya-light.pot` to `po/<lang>.po`, translate, and run `tools/build-translations.sh` (install.sh does this too).

## Style

- Python: standard library style, type hints, no new runtime dependencies without a reason.
- QML: follow KDE's conventions (Kirigami units for sizes, `PlasmaComponents3` controls, no hard-coded colours except the light colours themselves).
- Commits: `feat:`, `fix:`, `docs:`, `test:`, `chore:`, imperative, with the *why* in the body.

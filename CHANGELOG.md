# Changelog

## Unreleased

- Phone page: `tuya-light serve` runs a small web server with a one-screen page for a phone (on/off, brightness, warm to cool, colours, scenes), light and dark, installable on the iPhone's Home Screen. Pair a phone with `serve --pair` (link and QR code per address, home network and Tailscale), lock phones out with `serve --rotate-key`. A random key becomes an HttpOnly, SameSite=Strict cookie; the server checks the host name and the origin and never serves device keys.
- `serve --install-service` / `--remove-service`: a systemd user service that starts the page at login and restarts it on failure; `./install.sh --web` sets it up and restarts it after upgrades.
- Cloud backend: control bulbs through Tuya's IoT Platform OpenAPI with your own Access ID, Secret and region (`TUYA_ACCESS_ID`, `TUYA_ACCESS_SECRET`, `TUYA_REGION`, or `cloud.json`), for servers away from the bulbs. Choose per device (`"transport"` in `devices.json`), per process (`TUYA_LIGHT_TRANSPORT`) or per run (`--transport`). `setup --cloud` saves the device list for it. It logs in once per process, works out the state after a command, debounces drags and polls sparingly.
- Commands sent from long-running front ends go one at a time per bulb, and a newer one replaces a waiting one, as the widget already did.
- `serve --trust-proxy` and `--allow-host` for running behind a reverse proxy.
- `Dockerfile` (non-root) and `compose.yaml` with a home-server (local, host network) and a cloud-server profile; CI builds the image.
- New optional extra `web` (QR codes for pairing).

## 0.1.0 — 2026-09-28

First release.

- `tuya-light` command: state, on/off/toggle, colour (name, hex, HSV), white, brightness, temperature, six scenes, `--json` output.
- `tuya-light setup`: fetches local keys from the Tuya cloud once and finds the bulbs on the LAN.
- Your own scenes: `scene-save` (from a colour, a white tone, or the light as it is), `scene-remove`, `scene-hide`/`scene-show`, `scene-reset`; built-in scenes can be edited and restored. Stored in `scenes.json`, shared by every front end.
- `tuya-light mcp`: MCP server with twelve tools for AI assistants, including saving the current light as a scene.
- KDE Plasma 6 widget: colour wheel, brightness and white temperature sliders, favourite colours, scenes, several bulbs.
- Widget settings in four tabs: popup sections and their order, wheel size, scene columns, favourite colours, panel icon (shape, tint, dimming, brightness label); left click, middle click and scroll wheel actions; a scene editor; device and connection test.
- Both Tuya bulb generations (data points 1-5 and 20-24).
- English and Turkish.

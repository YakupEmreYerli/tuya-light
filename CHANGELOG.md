# Changelog

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

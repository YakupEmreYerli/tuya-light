# Security

## Reporting

Please report security problems privately, not in a public issue: use GitHub's **Report a vulnerability** button on the Security tab of this repository. You will get an answer within a week.

## What is sensitive here

- **Local keys.** Anyone with a bulb's local key and access to your network can control it. `tuya-light setup` writes them to `~/.config/tuya-light/devices.json` through a fresh temporary file that is owner-only (0600) from creation, then renames it into place. A key file written by another tool (such as tinytuya's wizard) is tightened to 0600 the first time tuya-light reads it. Scenes (`scenes.json`) are written the same way.
- **Tuya cloud credentials.** For local control the Access ID and Secret are used during `setup` only and are never written to disk. Pass them through `TUYA_ACCESS_ID` / `TUYA_ACCESS_SECRET` (the older `TUYA_API_KEY` / `TUYA_API_SECRET` work too) or type them at the prompt (the secret prompt does not echo). The cloud backend needs them for every command: they are read from the environment first, and only if typed at `setup --cloud` saved to `cloud.json` (0600). They are kept out of error messages, logs, the systemd unit and everything the phone page serves.
- **The phone page's pairing key.** `web.key` (0600) next to `devices.json`. Whoever has the pairing link can control your lights from wherever the server is reachable. The key becomes an HttpOnly, SameSite=Strict cookie; `tuya-light serve --rotate-key` invalidates it at once. Query strings are never logged.

## By design

- In local mode (the default), after setup no traffic goes to the cloud: the CLI, MCP server, widget and phone page talk to bulbs on the local network (TCP 6668) only. The cloud backend is opt-in and sends every command through Tuya's servers.
- The MCP server speaks stdio only; it does not open a network port.
- `tuya-light serve` opens one (8892, all interfaces by default). Every API call needs the pairing cookie; it only answers to this computer's own addresses and names (against DNS rebinding); changes need a same-origin JSON request, and there is no CORS. It serves a fixed list of page files and never `devices.json`, keys or credentials. On the home network it is plain HTTP, as the bulbs' own protocol is. It trusts `X-Forwarded-*` headers only with `--trust-proxy`; on a server reachable from the internet, put it behind a reverse proxy that does its own authentication.
- The widget runs the configured backend command through the shell; device names are single-quoted before they reach it.

## Out of scope

The Tuya protocol itself and bulb firmware. Report those to Tuya.

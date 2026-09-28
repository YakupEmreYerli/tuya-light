# Security

## Reporting

Please report security problems privately, not in a public issue: use GitHub's **Report a vulnerability** button on the Security tab of this repository. You will get an answer within a week.

## What is sensitive here

- **Local keys.** Anyone with a bulb's local key and access to your network can control it. `tuya-light setup` writes them to `~/.config/tuya-light/devices.json` through a fresh temporary file that is owner-only (0600) from creation, then renames it into place. A key file written by another tool (such as tinytuya's wizard) is tightened to 0600 the first time tuya-light reads it. Scenes (`scenes.json`) are written the same way.
- **Tuya cloud credentials.** The Access ID and Secret are used during `setup` only and are never written to disk. Pass them through `TUYA_API_KEY` / `TUYA_API_SECRET` or type them at the prompt (the secret prompt does not echo).

## By design

- After setup, no traffic goes to the cloud: the CLI, MCP server and widget talk to bulbs on the local network (TCP 6668) only.
- The MCP server speaks stdio only; it does not open a network port.
- The widget runs the configured backend command through the shell; device names are single-quoted before they reach it.

## Out of scope

The Tuya protocol itself and bulb firmware. Report those to Tuya.

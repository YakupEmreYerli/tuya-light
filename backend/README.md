# tuya-light

Control Tuya Wi-Fi bulbs over your local network, or through Tuya's cloud API:
a command-line tool, an MCP server for AI assistants, a page for your phone,
and the backend of a KDE Plasma 6 panel widget.

```bash
pipx install 'tuya-light[mcp,web] @ git+https://github.com/YakupEmreYerli/tuya-light#subdirectory=backend'
tuya-light setup          # fetch your bulbs' local keys once
tuya-light colour purple
tuya-light scene movie
tuya-light mcp            # MCP server on stdio
tuya-light serve          # the phone page; pair with `tuya-light serve --pair`
tuya-light setup --cloud  # or: control the bulbs through Tuya's cloud API from anywhere
```

Extras: `mcp` for the MCP server, `web` for QR codes when pairing a phone (the
page itself needs only the standard library).

Full documentation, the widget and screenshots:
https://github.com/YakupEmreYerli/tuya-light

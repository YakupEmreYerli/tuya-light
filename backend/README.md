# tuya-light

Control Tuya Wi-Fi bulbs over your local network: a command-line tool, an MCP
server for AI assistants, and the backend of a KDE Plasma 6 panel widget.

```bash
pipx install 'tuya-light[mcp] @ git+https://github.com/YakupEmreYerli/tuya-light#subdirectory=backend'
tuya-light setup          # fetch your bulbs' local keys once
tuya-light colour purple
tuya-light scene movie
tuya-light mcp            # MCP server on stdio
```

Full documentation, the widget and screenshots:
https://github.com/YakupEmreYerli/tuya-light

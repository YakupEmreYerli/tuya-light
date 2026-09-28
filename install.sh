#!/bin/sh
# Installs everything for the current user, no root needed:
#   - the tuya-light command (CLI + MCP server) with pipx
#   - the Plasma widget with kpackagetool6
# Usage: ./install.sh [--no-widget] [--no-mcp]
set -eu
root=$(cd "$(dirname "$0")" && pwd)
widget=1
extra="[mcp]"
for arg in "$@"; do
    case "$arg" in
        --no-widget) widget=0 ;;
        --no-mcp) extra="" ;;
        -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

if ! command -v pipx >/dev/null 2>&1; then
    echo "pipx is needed: install it with your package manager (e.g. pacman -S python-pipx)." >&2
    exit 1
fi

echo "==> Installing the tuya-light command"
# --force upgrades in place; if pipx cannot rebuild the existing venv, start
# clean. A failed build never removes a working install.
if ! pipx install --force "$root/backend$extra"; then
    pipx uninstall tuya-light >/dev/null 2>&1 || true
    pipx install "$root/backend$extra"
fi

if [ "$widget" = 1 ]; then
    if ! command -v kpackagetool6 >/dev/null 2>&1; then
        echo "kpackagetool6 not found: is this KDE Plasma 6? Skipping the widget." >&2
    else
        echo "==> Installing the Plasma widget"
        if command -v msgfmt >/dev/null 2>&1; then
            "$root/tools/build-translations.sh"
        fi
        kpackagetool6 --type Plasma/Applet --upgrade "$root/plasma" 2>/dev/null \
            || kpackagetool6 --type Plasma/Applet --install "$root/plasma"
    fi
fi

cat <<'EOF'

Done. Next:
  1. tuya-light setup          fetch your bulbs' local keys (once)
  2. tuya-light state          check that your bulb answers
  3. Right-click the panel → Add or Manage Widgets → "Tuya Light"
EOF

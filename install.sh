#!/bin/sh
# Installs everything for the current user, no root needed:
#   - the tuya-light command (CLI + MCP server) with pipx
#   - the Plasma widget with kpackagetool6
#   - with --web: the phone page, as a user service that starts at login
# Usage: ./install.sh [--no-widget] [--no-mcp] [--web]
set -eu
root=$(cd "$(dirname "$0")" && pwd)
widget=1
mcp=1
web=0
for arg in "$@"; do
    case "$arg" in
        --no-widget) widget=0 ;;
        --no-mcp) mcp=0 ;;
        --web) web=1 ;;
        -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

# A phone page installed earlier keeps its extra through upgrades.
unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/tuya-light-serve.service"
web_extra=$web
[ -e "$unit" ] && web_extra=1
extras=""
[ "$mcp" = 1 ] && extras="mcp"
[ "$web_extra" = 1 ] && extras="${extras:+$extras,}web"
extra=""
[ -n "$extras" ] && extra="[$extras]"

if ! command -v pipx >/dev/null 2>&1; then
    echo "pipx is needed: install it with your package manager (e.g. pacman -S python-pipx)." >&2
    exit 1
fi

echo "==> Installing the tuya-light command"
# --force upgrades in place. If pipx cannot rebuild the existing venv, start
# clean, but only after proving the package builds, so a broken checkout
# never takes a working install down with it.
if ! pipx install --force "$root/backend$extra"; then
    check=$(mktemp -d)
    trap 'rm -rf "$check"' EXIT
    if ! python3 -m pip wheel --quiet --no-deps --wheel-dir "$check" "$root/backend" >/dev/null 2>&1; then
        echo "The package does not build; your current tuya-light is left as it was." >&2
        exit 1
    fi
    pipx uninstall tuya-light >/dev/null 2>&1 || true
    pipx install "$root/backend$extra"
fi
command_status="installed"
bin=$(command -v tuya-light 2>/dev/null || echo "$(pipx environment --value PIPX_BIN_DIR)/tuya-light")
if ! command -v tuya-light >/dev/null 2>&1; then
    command_status="installed, but not on your PATH: run 'pipx ensurepath' and open a new terminal"
fi

web_status="not installed (./install.sh --web)"
if [ "$web" = 1 ]; then
    echo "==> Installing the phone page service"
    if "$bin" serve --install-service; then
        web_status="running at login; pair a phone with: tuya-light serve --pair"
    else
        web_status="NOT installed: see the message above"
    fi
elif [ -e "$unit" ]; then
    if systemctl --user try-restart tuya-light-serve.service 2>/dev/null; then
        web_status="restarted with the new version"
    else
        web_status="installed (could not restart it: systemctl --user restart tuya-light-serve)"
    fi
fi

widget_status="skipped (--no-widget)"
if [ "$widget" = 1 ]; then
    if ! command -v kpackagetool6 >/dev/null 2>&1; then
        widget_status="NOT installed: kpackagetool6 not found (needs KDE Plasma 6)"
    else
        echo "==> Installing the Plasma widget"
        if command -v msgfmt >/dev/null 2>&1; then
            "$root/tools/build-translations.sh"
        fi
        if kpackagetool6 --type Plasma/Applet --upgrade "$root/plasma" 2>/dev/null \
            || kpackagetool6 --type Plasma/Applet --install "$root/plasma"; then
            widget_status="installed (after an upgrade, restart Plasma once: systemctl --user restart plasma-plasmashell)"
        else
            widget_status="NOT installed: kpackagetool6 failed"
        fi
    fi
fi

cat <<EOF

tuya-light command: $command_status
Plasma widget:      $widget_status
Phone page:         $web_status

Next:
  1. tuya-light setup          fetch your bulbs' local keys (once)
  2. tuya-light state          check that your bulb answers
  3. Right-click the panel → Add or Manage Widgets → "Tuya Light"
EOF

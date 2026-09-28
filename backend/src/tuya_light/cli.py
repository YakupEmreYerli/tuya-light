"""tuya-light: command-line front end, also the widget's backend.

Every command that touches a bulb prints the bulb's state afterwards, as
one line of JSON with --json, so a caller never needs a second round-trip.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, config
from .light import SCENES, Light, LightError, State

NAMED_COLOURS = {
    "red": 0, "orange": 30, "yellow": 55, "green": 120, "cyan": 180,
    "blue": 230, "purple": 275, "pink": 320,
}


def _hex_to_hsv(text: str) -> tuple[float, float, float]:
    import colorsys

    t = text.lstrip("#")
    if len(t) != 6:
        raise ValueError
    r, g, b = (int(t[i : i + 2], 16) / 255 for i in (0, 2, 4))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return h * 360, s * 100, v * 100


def _parse_colour(text: str) -> tuple[float, float, float]:
    if text in NAMED_COLOURS:
        return NAMED_COLOURS[text], 100, 100
    try:
        return _hex_to_hsv(text)
    except ValueError:
        raise SystemExit(f"tuya-light: not a colour: {text!r} (a name or #rrggbb)") from None


def _print_state(state: State, as_json: bool) -> None:
    if as_json:
        print(json.dumps(state.to_json()))
        return
    if not state.online:
        print(f"{state.name}: offline ({state.error})")
        return
    if not state.on:
        print(f"{state.name}: off")
    elif state.mode == "colour":
        print(f"{state.name}: on, colour hue {state.hue}° sat {state.saturation}% "
              f"value {state.value}%")
    else:
        print(f"{state.name}: on, white {state.brightness}% temperature {state.temperature}%")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tuya-light", description=__doc__.splitlines()[0])
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-d", "--device", help="device id or name (default: the first one)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="fetch local keys from the Tuya cloud (once)")
    s.add_argument("--region", default="eu", choices=sorted(config_regions()))
    s.add_argument("--device-id", help="id of any one device on the account")
    s.add_argument("--all", action="store_true", help="keep non-light devices too")

    sub.add_parser("mcp", help="run the MCP server on stdio (for AI assistants)")
    sub.add_parser("devices", help="list configured devices")
    sub.add_parser("scenes", help="list built-in scenes")
    sub.add_parser("state", help="show the current state")
    sub.add_parser("on")
    sub.add_parser("off")
    sub.add_parser("toggle")

    c = sub.add_parser("colour", aliases=["color"], help="a name, #rrggbb, or H S V")
    c.add_argument("spec", nargs="+")

    w = sub.add_parser("white", help="white light: brightness and temperature, 0-100")
    w.add_argument("brightness", type=float)
    w.add_argument("temperature", type=float, nargs="?", default=None,
                   help="0 warm .. 100 cool (default: keep)")

    b = sub.add_parser("brightness", help="0-100, keeps the current mode and colour")
    b.add_argument("percent", type=float)

    t = sub.add_parser("temperature", help="0 warm .. 100 cool, switches to white")
    t.add_argument("percent", type=float)

    sc = sub.add_parser("scene", help="apply a built-in scene")
    sc.add_argument("name", choices=list(SCENES))
    return p


def config_regions():
    from .setup import REGIONS

    return REGIONS


def run(args: argparse.Namespace) -> int:
    if args.cmd == "setup":
        from .setup import run as setup_run

        return setup_run(args.region, args.all, args.device_id)

    if args.cmd == "mcp":
        from .mcp_server import run as mcp_run

        return mcp_run()

    if args.cmd == "scenes":
        rows = [{"name": k, "label": v.label, "mode": v.mode} for k, v in SCENES.items()]
        print(json.dumps(rows) if args.json else "\n".join(r["name"] for r in rows))
        return 0

    devices = config.load()
    if args.cmd == "devices":
        rows = [{"id": d.id, "name": d.name, "ip": d.ip} for d in devices]
        print(json.dumps(rows) if args.json else
              "\n".join(f"{d.name}\t{d.id}\t{d.ip or '-'}" for d in devices))
        return 0

    light = Light(config.pick(devices, args.device))
    try:
        if args.cmd == "on":
            light.power(True)
        elif args.cmd == "off":
            light.power(False)
        elif args.cmd == "toggle":
            light.toggle()
        elif args.cmd in ("colour", "color"):
            if len(args.spec) == 3:
                light.colour(*(float(x) for x in args.spec))
            elif len(args.spec) == 1:
                light.colour(*_parse_colour(args.spec[0]))
            else:
                raise SystemExit("tuya-light: colour takes a name, #rrggbb, or H S V")
        elif args.cmd == "white":
            temp = args.temperature
            if temp is None:
                temp = light.state().temperature
            light.white(args.brightness, temp)
        elif args.cmd == "brightness":
            light.brightness(args.percent)
        elif args.cmd == "temperature":
            light.temperature(args.percent)
        elif args.cmd == "scene":
            light.scene(args.name)
        state = light.state()
    except LightError as err:
        state = State(id=light.device.id, name=light.device.name, online=False, error=str(err))
    finally:
        light.close()

    _print_state(state, args.json)
    return 0 if state.online else 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except config.ConfigError as err:
        if args.json:
            print(json.dumps({"online": False, "error": str(err), "config": True}))
        else:
            print(f"tuya-light: {err}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())

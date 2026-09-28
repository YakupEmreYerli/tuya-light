"""MCP server: the same controls as the CLI, as tools an AI assistant can call.

Run with `tuya-light mcp` (stdio). Every tool that changes a light returns the
light's state afterwards, so the assistant can confirm what happened.
"""

from __future__ import annotations

from typing import Literal

from . import config
from .cli import NAMED_COLOURS, _hex_to_hsv
from .light import SCENES, Light, LightError, State

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    try:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP
    except ImportError:  # pragma: no cover - exercised only without the extra
        FastMCP = None

INSTRUCTIONS = (
    "Controls Tuya Wi-Fi lights on the user's local network. Brightness, "
    "saturation and colour temperature are 0-100; hue is 0-360 (0 red, 120 "
    "green, 240 blue). Temperature 0 is warm, 100 is cool. If the user has "
    "several lights, call list_devices first and pass `device`; otherwise it "
    "can be left out. Every change returns the new state."
)

SceneName = Literal["relax", "reading", "focus", "movie", "night", "party"]


def _with_light(device: str | None, action) -> dict:
    light = Light(config.pick(config.load(), device))
    try:
        action(light)
        state = light.state()
    except LightError as err:
        state = State(id=light.device.id, name=light.device.name, online=False, error=str(err))
    finally:
        light.close()
    return state.to_json()


def build_server():
    if FastMCP is None:
        raise SystemExit(
            "tuya-light: the MCP server needs the `mcp` package: "
            "pipx install 'tuya-light[mcp]' (or pip install mcp)"
        )
    server = FastMCP("tuya-light", instructions=INSTRUCTIONS)

    @server.tool()
    def list_devices() -> list[dict]:
        """List the configured lights (id, name, IP)."""
        return [{"id": d.id, "name": d.name, "ip": d.ip} for d in config.load()]

    @server.tool()
    def list_scenes() -> list[dict]:
        """List the built-in scenes."""
        return [{"name": k, "label": v.label, "mode": v.mode} for k, v in SCENES.items()]

    @server.tool()
    def get_state(device: str | None = None) -> dict:
        """Read a light's current state: on/off, mode, brightness, colour."""
        return _with_light(device, lambda light: None)

    @server.tool()
    def turn_on(device: str | None = None) -> dict:
        """Switch a light on."""
        return _with_light(device, lambda light: light.power(True))

    @server.tool()
    def turn_off(device: str | None = None) -> dict:
        """Switch a light off."""
        return _with_light(device, lambda light: light.power(False))

    @server.tool()
    def toggle(device: str | None = None) -> dict:
        """Switch a light on if it is off, off if it is on."""
        return _with_light(device, lambda light: light.toggle())

    @server.tool()
    def set_colour(
        hue: float | None = None,
        saturation: float = 100,
        brightness: float = 100,
        colour: str | None = None,
        device: str | None = None,
    ) -> dict:
        """Set a coloured light. Give either `colour` (a name such as red, orange,
        yellow, green, cyan, blue, purple, pink, or #rrggbb) or `hue` (0-360) with
        `saturation` (0-100). `brightness` is 0-100."""
        if colour:
            if colour.lower() in NAMED_COLOURS:
                h, s = NAMED_COLOURS[colour.lower()], 100
            else:
                try:
                    h, s, _ = _hex_to_hsv(colour)
                except ValueError:
                    raise ValueError(f"not a colour: {colour!r}") from None
        elif hue is not None:
            h, s = hue, saturation
        else:
            raise ValueError("give `colour` or `hue`")
        return _with_light(device, lambda light: light.colour(h, s, brightness))

    @server.tool()
    def set_white(brightness: float, temperature: float | None = None,
                  device: str | None = None) -> dict:
        """Set white light. `brightness` 0-100; `temperature` 0 (warm) to 100
        (cool), left out to keep the current one."""

        def act(light: Light):
            temp = light.state().temperature if temperature is None else temperature
            light.white(brightness, temp)

        return _with_light(device, act)

    @server.tool()
    def set_brightness(brightness: float, device: str | None = None) -> dict:
        """Dim or brighten (0-100) without changing the colour or white tone."""
        return _with_light(device, lambda light: light.brightness(brightness))

    @server.tool()
    def apply_scene(scene: SceneName, device: str | None = None) -> dict:
        """Apply a built-in scene: relax (warm, soft), reading (bright neutral),
        focus (bright cool), movie (dim deep blue), night (very dim amber),
        party (bright magenta)."""
        return _with_light(device, lambda light: light.scene(scene))

    return server


def run() -> int:
    build_server().run()
    return 0

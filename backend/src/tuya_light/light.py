"""Talking to one bulb: read its state, change it, report back.

Everything the outside world sees is in human units: brightness, colour
temperature, saturation and value are 0-100, hue is 0-360. The raw Tuya
ranges (10-1000, 0-255, hex colour strings) stay inside this module.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import tinytuya

from . import scenes as scene_store
from .config import Device


class LightError(Exception):
    pass


@dataclass
class State:
    id: str
    name: str
    online: bool
    on: bool = False
    mode: str = "white"
    brightness: int = 0
    temperature: int = 0
    hue: int = 0
    saturation: int = 0
    value: int = 0
    error: str | None = None

    def to_json(self) -> dict:
        return asdict(self)


def _clamp(x: float, lo: int, hi: int) -> int:
    x = float(x)
    if not math.isfinite(x):
        raise LightError(f"not a usable number: {x}")
    return int(max(lo, min(hi, round(x))))


# Two data-point layouts cover practically every Tuya bulb:
#   type A (older): switch 1, mode 2, brightness 3 (25-255), temp 4 (0-255),
#                   colour 5 as "rrggbb0hhhssvv"
#   type B (newer): switch 20, mode 21, brightness 22 (10-1000), temp 23 (0-1000),
#                   colour 24 as "hhhhssssvvvv"
_LAYOUTS = {
    "B": {"switch": "20", "mode": "21", "bright": "22", "temp": "23", "colour": "24", "max": 1000},
    "A": {"switch": "1", "mode": "2", "bright": "3", "temp": "4", "colour": "5", "max": 255},
}


def decode_dps(dps: dict) -> dict | None:
    """Raw data points -> State fields in human units, or None if unknown."""
    kind = "B" if "20" in dps else ("A" if "1" in dps else None)
    if kind is None:
        return None
    lay = _LAYOUTS[kind]
    top = lay["max"]
    out = {"on": bool(dps.get(lay["switch"]))}
    mode = str(dps.get(lay["mode"]) or "white")
    out["mode"] = "colour" if mode == "colour" else ("scene" if mode.startswith("scene") else "white")
    if lay["bright"] in dps:
        out["brightness"] = _clamp(int(dps[lay["bright"]]) / top * 100, 0, 100)
    if lay["temp"] in dps:
        out["temperature"] = _clamp(int(dps[lay["temp"]]) / top * 100, 0, 100)
    colour = str(dps.get(lay["colour"]) or "")
    try:
        if kind == "B" and len(colour) == 12:
            h, s, v = (int(colour[i : i + 4], 16) for i in (0, 4, 8))
            out.update(hue=h % 361, saturation=_clamp(s / 10, 0, 100), value=_clamp(v / 10, 0, 100))
        elif kind == "A" and len(colour) == 14:
            h, s, v = int(colour[7:10], 16), int(colour[10:12], 16), int(colour[12:14], 16)
            out.update(hue=h % 361, saturation=_clamp(s / 2.55, 0, 100), value=_clamp(v / 2.55, 0, 100))
    except ValueError:
        pass
    return out


class Light:
    def __init__(self, device: Device, timeout: float = 3.0):
        self.device = device
        self.bulb = tinytuya.BulbDevice(
            device.id,
            device.ip or "Auto",
            device.key,
            version=device.version,
            connection_timeout=timeout,
        )
        self.bulb.set_socketPersistent(True)
        self.bulb.set_socketRetryLimit(1)

    # -- reading ---------------------------------------------------------

    def _raw_status(self) -> dict:
        # Right after a write, bulbs push a partial update (only the data points
        # that changed) and it can arrive in place of the status reply. Merge
        # replies until the switch point is there.
        merged: dict = {}
        for _ in range(3):
            data = self.bulb.status()
            if not isinstance(data, dict) or "Error" in data:
                if merged:
                    break
                reason = data.get("Error", "no answer") if isinstance(data, dict) else "no answer"
                raise LightError(str(reason))
            merged.update(data.get("dps") or {})
            if "20" in merged or "1" in merged:
                break
        return {"dps": merged}

    def state(self) -> State:
        base = State(id=self.device.id, name=self.device.name, online=False)
        try:
            raw = self._raw_status()
        except LightError as err:
            base.error = str(err)
            return base
        decoded = decode_dps(raw.get("dps", {}))
        if decoded is None:
            base.error = f"unrecognised bulb data points: {sorted(raw.get('dps', {}))}"
            return base
        base.online = True
        for field, value in decoded.items():
            setattr(base, field, value)
        return base

    # -- writing ---------------------------------------------------------

    def _check(self, result) -> None:
        if isinstance(result, dict) and result.get("Error"):
            raise LightError(str(result["Error"]))

    def _min_brightness(self) -> int:
        """Lowest percentage the bulb accepts: older bulbs start at 25/255 (10 %),
        newer ones at 10/1000 (1 %). tinytuya raises below it."""
        dpset = getattr(self.bulb, "dpset", None) or {}
        low, high = dpset.get("value_min"), dpset.get("value_max")
        if isinstance(low, (int, float)) and isinstance(high, (int, float)) and high > 0 and low > 0:
            return max(1, math.ceil(low * 100 / high))
        return 1

    def power(self, on: bool) -> None:
        self._check(self.bulb.turn_on() if on else self.bulb.turn_off())

    def toggle(self) -> None:
        self.power(not self.state().on)

    def colour(self, hue: float, saturation: float, value: float) -> None:
        h = (_clamp(hue, -100_000, 100_000) % 360) / 360.0
        s = _clamp(saturation, 0, 100) / 100.0
        v = max(1, _clamp(value, 0, 100)) / 100.0
        self._ensure_on()
        try:
            self._check(self.bulb.set_hsv(h, s, v))
        except ValueError as err:
            raise LightError(str(err)) from None

    def white(self, brightness: float, temperature: float) -> None:
        bright = _clamp(brightness, 0, 100)
        temp = _clamp(temperature, 0, 100)
        self._ensure_on()
        try:
            self._check(self.bulb.set_white_percentage(max(self._min_brightness(), bright), temp))
        except ValueError as err:
            raise LightError(str(err)) from None

    def brightness(self, percent: float) -> None:
        """Dim without changing mode: white stays white, colour keeps its hue."""
        now = self.state()
        if now.mode == "colour":
            self.colour(now.hue, now.saturation, percent)
        else:
            self.white(percent, now.temperature)

    def temperature(self, percent: float) -> None:
        now = self.state()
        bright = now.brightness if now.mode == "white" else max(now.value, 1)
        self.white(bright, percent)

    def scene(self, name: str) -> None:
        self.apply(scene_store.get(name))

    def apply(self, sc: "scene_store.Scene") -> None:
        if sc.mode == "white":
            self.white(sc.brightness, sc.temperature)
        else:
            self.colour(sc.hue, sc.saturation, sc.brightness)

    def _ensure_on(self) -> None:
        self._check(self.bulb.turn_on())

    def close(self) -> None:
        try:
            self.bulb.close()
        except Exception:
            pass

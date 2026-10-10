"""The cloud transport: Tuya's IoT Platform OpenAPI, through tinytuya.Cloud.

For a computer that is not on the bulb's network (a rented server, say).
Commands go from here to Tuya's servers and on to the bulb, so they need
the internet, your own cloud project's Access ID and Secret, and an active
IoT Core plan on the Tuya developer platform. Local mode needs none of this.

The free plan has a monthly allowance of API calls, so this module spends
them carefully:

- One login token per process, one instruction-set lookup per bulb.
- After a command, the state is worked out from what was sent instead of
  being read back (the cloud often answers with the old values for a moment
  anyway); a state read reuses a reading younger than two seconds.
- A relative change (brightness, temperature) starts from a reading up to a
  minute old instead of asking again.
- Whether the bulb is connected is checked at most once a minute.

Credentials come from TUYA_ACCESS_ID, TUYA_ACCESS_SECRET and TUYA_REGION
(environment first, so containers work), else from cloud.json next to
devices.json (0600). They are never printed, logged or served.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import ConfigError, Device, _secure, config_path, write_private
from .light import BaseLight, LightError, State, _clamp

REGIONS = {
    "eu": "Central Europe",
    "us": "Western America",
    "us-e": "Eastern America",
    "cn": "China",
    "in": "India",
    "weu": "Western Europe",
}

ENV_ID = ("TUYA_ACCESS_ID", "TUYA_API_KEY")          # the second names are what
ENV_SECRET = ("TUYA_ACCESS_SECRET", "TUYA_API_SECRET")  # `setup` always accepted
ENV_REGION = ("TUYA_REGION",)


# -- credentials ---------------------------------------------------------------


@dataclass(frozen=True)
class Credentials:
    access_id: str
    access_secret: str = field(repr=False)
    region: str
    source: str = field(default="", compare=False)


def credentials_path() -> Path:
    return config_path().with_name("cloud.json")


def load_credentials(path: Path | None = None) -> Credentials:
    """Environment first, then cloud.json; each value on its own."""
    path = path or credentials_path()
    saved: dict = {}
    if path.exists():
        _secure(path, "your Tuya cloud secret")
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
            raise ConfigError(f"cannot read {path}: {err}") from None
        if not isinstance(saved, dict):
            raise ConfigError(f"{path} must contain a JSON object")

    sources = set()

    def pick(names: tuple[str, ...], key: str) -> str:
        for name in names:
            value = (os.environ.get(name) or "").strip()
            if value:
                sources.add("environment")
                return value
        value = str(saved.get(key) or "").strip()
        if value:
            sources.add(str(path))
        return value

    access_id = pick(ENV_ID, "access_id")
    secret = pick(ENV_SECRET, "access_secret")
    region = pick(ENV_REGION, "region").lower()
    missing = [name for name, value in (("TUYA_ACCESS_ID", access_id),
                                        ("TUYA_ACCESS_SECRET", secret),
                                        ("TUYA_REGION", region)) if not value]
    if missing:
        raise ConfigError(f"the cloud transport needs {', '.join(missing)} (environment) or "
                          f"{path}; run `tuya-light setup --cloud`")
    if region not in REGIONS:
        raise ConfigError(f"unknown Tuya region {region!r}; use one of {', '.join(REGIONS)}")
    return Credentials(access_id, secret, region, " and ".join(sorted(sources)))


def save_credentials(access_id: str, secret: str, region: str, path: Path | None = None) -> Path:
    path = path or credentials_path()
    write_private(path, json.dumps({"access_id": access_id, "access_secret": secret,
                                    "region": region}, indent=2) + "\n")
    return path


# -- Tuya's standard instruction set for lights --------------------------------
#
# Newer bulbs use the _v2 codes (brightness 10-1000, colour s/v 0-1000), older
# ones the plain codes (brightness 25-255, colour s/v 0-255). The real ranges
# come from the bulb's instruction set; these are the fallbacks.

SWITCH_CODES = ("switch_led", "led_switch")
BRIGHT_CODES = ("bright_value_v2", "bright_value")
TEMP_CODES = ("temp_value_v2", "temp_value")
COLOUR_CODES = ("colour_data_v2", "colour_data")
DEFAULT_RANGES = {
    "bright_value_v2": (10, 1000), "bright_value": (25, 255),
    "temp_value_v2": (0, 1000), "temp_value": (0, 255),
    "colour_data_v2": (0, 1000), "colour_data": (0, 255),
}


@dataclass(frozen=True)
class Spec:
    """Which codes a bulb uses and their raw ranges."""

    switch: str
    bright: str | None = None
    temp: str | None = None
    colour: str | None = None
    work_mode: bool = True
    ranges: dict = field(default_factory=dict, compare=False)  # code -> (min, max)

    def range(self, code: str) -> tuple[int, int]:
        return self.ranges.get(code) or DEFAULT_RANGES.get(code) or (0, 1000)


def _json(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        out = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return out if isinstance(out, dict) else {}


def _first(codes, options: tuple[str, ...]) -> str | None:
    return next((c for c in options if c in codes), None)


def spec_from_codes(codes, ranges: dict | None = None) -> Spec | None:
    switch = _first(codes, SWITCH_CODES)
    if switch is None:
        return None
    return Spec(switch=switch, bright=_first(codes, BRIGHT_CODES), temp=_first(codes, TEMP_CODES),
                colour=_first(codes, COLOUR_CODES), work_mode="work_mode" in codes,
                ranges=ranges or {})


def spec_from_functions(result: dict) -> Spec | None:
    """`getfunctions` answer -> Spec, with the bulb's own ranges."""
    functions = (result or {}).get("functions") or []
    ranges: dict = {}
    codes = []
    for fn in functions:
        if not isinstance(fn, dict) or not fn.get("code"):
            continue
        code = fn["code"]
        codes.append(code)
        values = _json(fn.get("values"))
        try:
            if "max" in values:
                ranges[code] = (int(values.get("min", 0)), int(values["max"]))
            elif isinstance(values.get("v"), dict):  # colour: use v (s has the same range)
                ranges[code] = (int(values["v"].get("min", 0)), int(values["v"]["max"]))
        except (TypeError, ValueError, KeyError):
            pass
    return spec_from_codes(codes, ranges)


def _percent(raw, top: int) -> int:
    try:
        return _clamp(float(raw) / top * 100, 0, 100) if top > 0 else 0
    except (TypeError, ValueError, LightError):
        return 0


def _raw(percent: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(_clamp(percent, 0, 100) / 100 * hi))))


def decode_status(codes: dict, spec: Spec) -> dict:
    """Cloud status (code -> value) -> State fields in human units."""
    out = {"on": bool(codes.get(spec.switch))}
    mode = str(codes.get("work_mode") or "white")
    out["mode"] = "colour" if mode == "colour" else ("scene" if mode.startswith("scene") else "white")
    if spec.bright and spec.bright in codes:
        out["brightness"] = _percent(codes[spec.bright], spec.range(spec.bright)[1])
    if spec.temp and spec.temp in codes:
        out["temperature"] = _percent(codes[spec.temp], spec.range(spec.temp)[1])
    if spec.colour and spec.colour in codes:
        hsv = _json(codes[spec.colour])
        top = spec.range(spec.colour)[1]
        try:
            out["hue"] = int(hsv.get("h", 0)) % 361
        except (TypeError, ValueError):
            pass
        out["saturation"] = _percent(hsv.get("s", 0), top)
        out["value"] = _percent(hsv.get("v", 0), top)
    return out


# -- one account, shared by every bulb on it ----------------------------------


def _reason(answer) -> str:
    """tinytuya's error dict -> the part worth showing."""
    text = str(answer.get("Payload") or answer.get("Error") or answer)
    if "Tuya Cloud:" in text:
        text = text.split("Tuya Cloud:", 1)[1].strip().strip("'\"")
    return f"Tuya cloud: {text}"


class CloudSession:
    STATUS_FRESH = 2.0
    ONLINE_EVERY = 60.0

    def __init__(self, creds: Credentials, *, timeout: float = 10.0,
                 client_factory: Callable | None = None) -> None:
        self.creds = creds
        self.timeout = timeout
        self.calls = 0  # API requests made, for tests and curiosity
        self._client_factory = client_factory
        self._client = None
        self._lock = threading.RLock()
        self._specs: dict[str, Spec] = {}
        self._status: dict[str, tuple[dict, float]] = {}
        self._online: dict[str, tuple[bool, float]] = {}

    def _redact(self, text: str) -> str:
        for secret in (self.creds.access_secret, getattr(self._client, "token", None)):
            if secret:
                text = text.replace(str(secret), "***")
        return text

    def _run(self, func, *args):
        """Call into tinytuya with a deadline (its requests have none)."""
        box: dict = {}

        def target():
            try:
                box["value"] = func(*args)
            except Exception as err:  # network errors and the like
                box["error"] = err

        worker = threading.Thread(target=target, daemon=True)
        worker.start()
        worker.join(self.timeout)
        if worker.is_alive():
            raise LightError("the Tuya cloud did not answer in time")
        if "error" in box:
            err = box["error"]
            raise LightError(self._redact(f"Tuya cloud request failed: {type(err).__name__}: {err}"))
        return box.get("value")

    def _cloud(self):
        if self._client is None:
            factory = self._client_factory
            if factory is None:
                import tinytuya

                factory = tinytuya.Cloud
            creds = self.creds
            self.calls += 1  # the login token
            client = self._run(lambda: factory(apiRegion=creds.region, apiKey=creds.access_id,
                                               apiSecret=creds.access_secret))
            if getattr(client, "error", None) or not getattr(client, "token", None):
                raise LightError(self._redact(f"Tuya cloud login failed: {_reason(client.error or {})}"))
            self._client = client
        return self._client

    def call(self, method: str, *args):
        with self._lock:
            client = self._cloud()
            self.calls += 1
            answer = self._run(getattr(client, method), *args)
        if answer is None:
            raise LightError("no answer from the Tuya cloud")
        if isinstance(answer, dict) and (answer.get("Error") or answer.get("success") is False):
            raise LightError(self._redact(_reason(answer if answer.get("Error") else
                                                  {"Payload": answer.get("msg")})))
        return answer

    def status(self, dev_id: str, max_age: float = STATUS_FRESH) -> dict:
        cached = self._status.get(dev_id)
        if cached and time.monotonic() - cached[1] < max_age:
            return cached[0]
        answer = self.call("getstatus", dev_id)
        items = answer.get("result") if isinstance(answer, dict) else None
        if not isinstance(items, list):
            raise LightError("Tuya cloud: unexpected status answer")
        codes = {i["code"]: i.get("value") for i in items if isinstance(i, dict) and "code" in i}
        self._status[dev_id] = (codes, time.monotonic())
        return codes

    def spec(self, dev_id: str) -> Spec:
        found = self._specs.get(dev_id)
        if found is not None:
            return found
        try:
            found = spec_from_functions(self.call("getfunctions", dev_id).get("result"))
        except LightError:
            found = None
        if found is None:  # no instruction set: go by the codes the status uses
            found = spec_from_codes(self.status(dev_id, 60.0))
        if found is None:
            raise LightError("Tuya cloud: this device has no light switch code")
        self._specs[dev_id] = found
        return found

    def online(self, dev_id: str) -> bool:
        cached = self._online.get(dev_id)
        if cached and time.monotonic() - cached[1] < self.ONLINE_EVERY:
            return cached[0]
        try:
            answer = self.call("getconnectstatus", dev_id)
        except LightError:
            answer = True  # a project without this permission still has a working status
        on = answer if isinstance(answer, bool) else True
        self._online[dev_id] = (on, time.monotonic())
        return on

    def send(self, dev_id: str, commands: list[dict]) -> None:
        self.call("sendcommand", dev_id, {"commands": commands})
        # The cloud may still report the old values for a moment; what was
        # just accepted is the better answer to the next state read.
        codes = dict(self._status.get(dev_id, ({}, 0))[0])
        codes.update({c["code"]: c["value"] for c in commands})
        self._status[dev_id] = (codes, time.monotonic())
        if dev_id in self._online:
            self._online[dev_id] = (True, self._online[dev_id][1])


_sessions: dict[Credentials, CloudSession] = {}
_sessions_lock = threading.Lock()


def session_for(creds: Credentials) -> CloudSession:
    with _sessions_lock:
        found = _sessions.get(creds)
        if found is None:
            found = _sessions[creds] = CloudSession(creds)
        return found


# -- the light -------------------------------------------------------------------


class CloudLight(BaseLight):
    """A bulb reached through Tuya's OpenAPI."""

    transport = "cloud"
    LOOSE = 60.0  # how old a reading a relative change may start from

    def __init__(self, device: Device, session: CloudSession | None = None) -> None:
        self.device = device
        self.session = session or session_for(load_credentials())

    def state(self, max_age: float = CloudSession.STATUS_FRESH) -> State:
        base = State(id=self.device.id, name=self.device.name, online=False)
        try:
            codes = self.session.status(self.device.id, max_age)
            spec = self.session.spec(self.device.id)
            if not self.session.online(self.device.id):
                base.error = "the light is not connected to the Tuya cloud"
                return base
        except LightError as err:
            base.error = str(err)
            return base
        base.online = True
        for name, value in decode_status(codes, spec).items():
            setattr(base, name, value)
        return base

    def _current(self) -> State:
        now = self.state(max_age=self.LOOSE)
        if not now.online:
            raise LightError(now.error or "the light did not answer")
        return now

    def _send(self, commands: list[tuple[str, object]]) -> None:
        self.session.send(self.device.id, [{"code": c, "value": v} for c, v in commands if c])

    def power(self, on: bool) -> None:
        self._send([(self.session.spec(self.device.id).switch, bool(on))])

    def white(self, brightness: float, temperature: float) -> None:
        spec = self.session.spec(self.device.id)
        if spec.bright is None:
            raise LightError("this light has no brightness code")
        commands = [(spec.switch, True)]
        if spec.work_mode:
            commands.append(("work_mode", "white"))
        commands.append((spec.bright, _raw(brightness, *spec.range(spec.bright))))
        if spec.temp is not None:
            commands.append((spec.temp, _raw(temperature, *spec.range(spec.temp))))
        self._send(commands)

    def colour(self, hue: float, saturation: float, value: float) -> None:
        spec = self.session.spec(self.device.id)
        if spec.colour is None:
            raise LightError("this light has no colour code")
        top = spec.range(spec.colour)[1]
        hsv = {"h": _clamp(hue, -100_000, 100_000) % 360,
               "s": _raw(saturation, 0, top),
               "v": _raw(max(1, _clamp(value, 0, 100)), 1, top)}
        commands = [(spec.switch, True)]
        if spec.work_mode:
            commands.append(("work_mode", "colour"))
        # Sent as a JSON string, as the cloud reports it.
        commands.append((spec.colour, json.dumps(hsv, separators=(",", ":"))))
        self._send(commands)

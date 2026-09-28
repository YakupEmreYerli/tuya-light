"""Device list: where it lives and how it is read and written.

The file is a JSON list in the same shape tinytuya's own wizard writes
(``id``, ``name``, ``key``, optionally ``ip`` and ``version``), so a
``devices.json`` produced by ``python -m tinytuya wizard`` works as is.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

# Tuya product categories that are lights (dj = bulb, dd = strip, xdd = ceiling,
# fwd = ambient, dc = string, tgq/tgkg = dimmers).
LIGHT_CATEGORIES = {"dj", "dd", "xdd", "fwd", "dc", "tgq", "tgkg", "tyndj", "gyd"}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    key: str
    ip: str | None = None
    version: float = 3.3

    @classmethod
    def from_json(cls, raw: dict) -> "Device":
        try:
            dev_id, key = raw["id"], raw["key"]
        except KeyError as missing:
            raise ConfigError(f"device entry is missing {missing}") from None
        if not key:
            raise ConfigError(f"device {dev_id} has no local key")
        version = raw.get("version") or raw.get("ver") or 3.3
        return cls(
            id=dev_id,
            name=raw.get("name") or dev_id,
            key=key,
            ip=raw.get("ip") or None,
            version=float(version),
        )

    def to_json(self) -> dict:
        out = {"id": self.id, "name": self.name, "key": self.key, "version": self.version}
        if self.ip:
            out["ip"] = self.ip
        return out


def config_path() -> Path:
    override = os.environ.get("TUYA_LIGHT_CONFIG")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "tuya-light" / "devices.json"


def load(path: Path | None = None) -> list[Device]:
    path = path or config_path()
    if not path.exists():
        raise ConfigError(f"no device list at {path}; run `tuya-light setup` first")
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as err:
        raise ConfigError(f"{path} is not valid JSON: {err}") from None
    if not isinstance(raw, list):
        raise ConfigError(f"{path} must contain a JSON list of devices")
    return [Device.from_json(entry) for entry in raw]


def save(devices: list[Device], path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    # The file holds local keys: owner-only from the first byte.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump([d.to_json() for d in devices], fh, indent=2)
        fh.write("\n")
    tmp.replace(path)
    return path


def pick(devices: list[Device], wanted: str | None) -> Device:
    if not devices:
        raise ConfigError("the device list is empty")
    if wanted is None:
        return devices[0]
    for dev in devices:
        if wanted in (dev.id, dev.name):
            return dev
    raise ConfigError(f"no device with id or name {wanted!r}")

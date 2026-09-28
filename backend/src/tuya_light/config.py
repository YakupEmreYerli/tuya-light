"""Device list: where it lives and how it is read and written.

The file is a JSON list in the same shape tinytuya's own wizard writes
(``id``, ``name``, ``key``, optionally ``ip`` and ``version``), so a
``devices.json`` produced by ``python -m tinytuya wizard`` works as is.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
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
        try:
            version = float(raw.get("version") or raw.get("ver") or 3.3)
        except (TypeError, ValueError):
            raise ConfigError(f"device {dev_id}: version must be a number like 3.3") from None
        if not 3.1 <= version <= 3.5:
            raise ConfigError(f"device {dev_id}: unsupported protocol version {version}")
        return cls(
            id=dev_id,
            name=raw.get("name") or dev_id,
            key=key,
            ip=raw.get("ip") or None,
            version=version,
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


def _secure(path: Path) -> None:
    """Local keys must not be readable by others. A file we did not write (say,
    tinytuya's wizard output) may be 0644; tighten it and say so."""
    st = path.stat()
    if st.st_uid == os.getuid() and st.st_mode & 0o077:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        print(f"tuya-light: {path} was readable by others; it holds local keys, "
              "so its permissions are now 0600", file=sys.stderr)


def load(path: Path | None = None) -> list[Device]:
    path = path or config_path()
    if not path.exists():
        raise ConfigError(f"no device list at {path}; run `tuya-light setup` first")
    try:
        _secure(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ConfigError(f"{path} is not valid JSON: {err}") from None
    except (OSError, UnicodeDecodeError) as err:
        raise ConfigError(f"cannot read {path}: {err}") from None
    if not isinstance(raw, list) or not all(isinstance(e, dict) for e in raw):
        raise ConfigError(f"{path} must contain a JSON list of devices")
    return [Device.from_json(entry) for entry in raw]


def write_private(path: Path, text: str, mode: int = 0o600) -> None:
    """Atomic write: a fresh temp file (0600 from creation, never reused),
    flushed to disk, then renamed over the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save(devices: list[Device], path: Path | None = None) -> Path:
    path = path or config_path()
    write_private(path, json.dumps([d.to_json() for d in devices], indent=2) + "\n")
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

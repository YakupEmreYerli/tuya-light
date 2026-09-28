"""Scenes: six built in, any number of your own, one file shared by all fronts.

``scenes.json`` next to ``devices.json`` holds only what differs from the
built-ins: new scenes, edited built-ins, and built-ins marked hidden. The CLI,
the MCP server and the widget all read and write it through this module, so a
scene made in the widget is there for ``tuya-light scene`` and for an AI
assistant too.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .config import ConfigError, config_path


@dataclass(frozen=True)
class Scene:
    name: str  # stable key used on the command line
    label: str  # what people see
    mode: str  # "white" or "colour"
    brightness: int = 100  # white: brightness; colour: value
    temperature: int = 0  # white only, 0 warm .. 100 cool
    hue: int = 0  # colour only, 0-360
    saturation: int = 100  # colour only
    builtin: bool = False
    hidden: bool = False

    def to_json(self) -> dict:
        return asdict(self)


BUILTIN: tuple[Scene, ...] = (
    Scene("relax", "Relax", "white", brightness=45, temperature=0, builtin=True),
    Scene("reading", "Reading", "white", brightness=100, temperature=55, builtin=True),
    Scene("focus", "Focus", "white", brightness=100, temperature=100, builtin=True),
    Scene("movie", "Movie", "colour", brightness=18, hue=255, saturation=85, builtin=True),
    Scene("night", "Night", "colour", brightness=6, hue=25, saturation=100, builtin=True),
    Scene("party", "Party", "colour", brightness=100, hue=320, saturation=100, builtin=True),
)
_BUILTIN_BY_NAME = {s.name: s for s in BUILTIN}
_FIELDS = {"label", "mode", "brightness", "temperature", "hue", "saturation", "hidden"}


def scenes_path() -> Path:
    override = os.environ.get("TUYA_LIGHT_SCENES")
    return Path(override) if override else config_path().with_name("scenes.json")


def slug(label: str) -> str:
    """'Kitap Okuma' -> 'kitap-okuma'; Turkish letters fold to ASCII."""
    table = str.maketrans("ıİşŞğĞçÇöÖüÜ", "iIsSgGcCoOuU")
    text = unicodedata.normalize("NFKD", label.translate(table))
    text = text.encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "scene"


def _clamp(v, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(float(v)))))


def _clean(raw: dict) -> dict:
    out = {k: raw[k] for k in _FIELDS if k in raw}
    if "mode" in out and out["mode"] not in ("white", "colour"):
        raise ConfigError(f"scene mode must be white or colour, not {out['mode']!r}")
    for key, hi in (("brightness", 100), ("temperature", 100), ("saturation", 100), ("hue", 360)):
        if key in out:
            out[key] = _clamp(out[key], 0, hi)
    if "hidden" in out:
        out["hidden"] = bool(out["hidden"])
    return out


def _read_overrides(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as err:
        raise ConfigError(f"{path} is not valid JSON: {err}") from None
    if not isinstance(data, list):
        raise ConfigError(f"{path} must contain a JSON list of scenes")
    return [d for d in data if isinstance(d, dict) and d.get("name")]


def _write_overrides(entries: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def load(include_hidden: bool = False, path: Path | None = None) -> list[Scene]:
    path = path or scenes_path()
    merged: dict[str, Scene] = {s.name: s for s in BUILTIN}
    for raw in _read_overrides(path):
        name = str(raw["name"])
        base = merged.get(name) or Scene(name, name, "white")
        merged[name] = replace(base, **_clean(raw))
    scenes = list(merged.values())
    return scenes if include_hidden else [s for s in scenes if not s.hidden]


def get(name: str, path: Path | None = None) -> Scene:
    for s in load(include_hidden=True, path=path):
        if s.name == name or s.label.lower() == name.lower():
            return s
    known = ", ".join(s.name for s in load(path=path))
    raise ConfigError(f"no scene {name!r}; known: {known}")


def save(label: str, mode: str, *, name: str | None = None, brightness: float = 100,
         temperature: float = 0, hue: float = 0, saturation: float = 100,
         path: Path | None = None) -> Scene:
    """Create a scene, or overwrite one (built-in or not) with the same name."""
    path = path or scenes_path()
    key = name or slug(label)
    entry = {"name": key, **_clean({
        "label": label, "mode": mode, "brightness": brightness, "temperature": temperature,
        "hue": hue, "saturation": saturation, "hidden": False,
    })}
    entries = [e for e in _read_overrides(path) if e["name"] != key]
    entries.append(entry)
    _write_overrides(entries, path)
    return get(key, path)


def set_hidden(name: str, hidden: bool, path: Path | None = None) -> Scene:
    path = path or scenes_path()
    scene = get(name, path)
    entries = _read_overrides(path)
    for e in entries:
        if e["name"] == scene.name:
            e["hidden"] = hidden
            break
    else:
        entries.append({"name": scene.name, "hidden": hidden})
    _write_overrides(entries, path)
    return get(scene.name, path)


def remove(name: str, path: Path | None = None) -> str:
    """Delete your own scene; a built-in one is hidden instead (restore with reset)."""
    path = path or scenes_path()
    scene = get(name, path)
    if scene.builtin:
        set_hidden(scene.name, True, path)
        return "hidden"
    _write_overrides([e for e in _read_overrides(path) if e["name"] != scene.name], path)
    return "removed"


def reset(name: str | None = None, path: Path | None = None) -> None:
    """Restore one built-in scene (or all of them) to its original form."""
    path = path or scenes_path()
    if name is None:
        keep = [e for e in _read_overrides(path) if e["name"] not in _BUILTIN_BY_NAME]
    else:
        keep = [e for e in _read_overrides(path) if e["name"] != name]
    _write_overrides(keep, path)

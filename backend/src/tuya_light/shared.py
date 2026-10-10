"""Settings shared between installs: scenes, favourite colours, device names.

Every install keeps them in its own files (scenes.json, settings.json) and
everything reads those, so it all keeps working offline. When someone has
several installs (the PC with the widget, a box at home, a cloud server),
one of them, the one running `tuya-light serve`, holds the shared copy and
the others are linked to it once:

    tuya-light link 'https://lights.example.com/?key=...'

A linked install then syncs by itself: right after a change, and before it
shows scenes, favourites or devices (at most once a minute). Sync goes item
by item (one scene, the favourites list, one device's name): each side sends
what changed since the last sync, and when both sides changed the same item,
the later edit wins. Per-device layout (popup size, wheel size, columns)
stays in each widget's own settings.

The link (address, pairing key, extra headers for an authenticating proxy)
is kept in link.json, readable only by you. None of it is ever printed.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import scenes as scene_store
from .config import ConfigError, _secure, config_path, write_private

PULL_EVERY = 60.0  # seconds between automatic syncs before a read
RETRY_AFTER = 60.0  # after a failed sync, don't try again on every command
TIMEOUT = 5.0
MAX_ITEMS = 500

_HEX = re.compile(r"#[0-9a-f]{6}")


class SyncError(Exception):
    pass


# -- the local files -------------------------------------------------------------


def settings_path() -> Path:
    override = os.environ.get("TUYA_LIGHT_SETTINGS")
    return Path(override) if override else config_path().with_name("settings.json")


def link_path() -> Path:
    return config_path().with_name("link.json")


def hub_path() -> Path:
    return config_path().with_name("hub.json")


def _lock():
    return scene_store._locked(scene_store.scenes_path())


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ConfigError(f"cannot read {path}: {err}") from None
    return data if isinstance(data, type(default)) else default


def read_settings() -> dict:
    return _read_json(settings_path(), {})


def _write_settings(data: dict) -> None:
    write_private(settings_path(), json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def colour(text: str) -> str:
    value = str(text).strip().lower()
    if not value.startswith("#"):
        value = "#" + value
    if not _HEX.fullmatch(value):
        raise ConfigError(f"not a colour: {text!r} (use #rrggbb)")
    return value


def favourites() -> list[str] | None:
    """The shared favourite colours, or None if nobody has chosen any yet."""
    found = read_settings().get("favourite_colours")
    if not isinstance(found, list):
        return None
    return [c for c in found if isinstance(c, str) and _HEX.fullmatch(c)]


def set_favourites(colours: list[str], if_unset: bool = False) -> list[str] | None:
    """Replace the favourites. With if_unset, only when none were ever chosen:
    how the widget hands over the colours it used to keep to itself."""
    cleaned = [colour(c) for c in colours]
    with _lock():
        data = read_settings()
        if if_unset and isinstance(data.get("favourite_colours"), list):
            return favourites()
        data["favourite_colours"] = cleaned
        _write_settings(data)
    return cleaned


def device_names() -> dict[str, str]:
    found = read_settings().get("device_names")
    if not isinstance(found, dict):
        return {}
    return {str(k): v for k, v in found.items() if isinstance(v, str) and v.strip()}


def set_device_name(dev_id: str, name: str | None) -> None:
    with _lock():
        data = read_settings()
        names = device_names()
        if name and name.strip():
            names[dev_id] = name.strip()[:64]
        else:
            names.pop(dev_id, None)
        if names:
            data["device_names"] = names
        else:
            data.pop("device_names", None)
        _write_settings(data)


# -- items: what syncs -----------------------------------------------------------
#
#   scene:<name>  one entry of scenes.json (a new scene, an edited or hidden
#                 built-in); gone = no change from the built-in / deleted
#   favourites    the list of favourite colours
#   name:<id>     a device's display name


def read_items() -> dict:
    items: dict = {}
    for entry in scene_store._read_overrides(scene_store.scenes_path()):
        items[f"scene:{entry['name']}"] = entry
    found = favourites()
    if found is not None:
        items["favourites"] = found
    for dev_id, name in sorted(device_names().items()):
        items[f"name:{dev_id}"] = name
    return items


def _valid(key, value):
    """An item as received from elsewhere, cleaned, or None to drop it."""
    if not isinstance(key, str) or value is None:
        return None
    try:
        if key.startswith("scene:") and isinstance(value, dict):
            name = key[len("scene:"):]
            if not name or value.get("name") != name:
                return None
            return {"name": name, **scene_store._clean(value)}
        if key == "favourites" and isinstance(value, list):
            return [colour(c) for c in value][:64]
        if key.startswith("name:") and isinstance(value, str) and value.strip():
            return value.strip()[:64]
    except ConfigError:
        return None
    return None


def write_items(items: dict) -> None:
    """Make the local files hold exactly these items (callers hold the lock)."""
    scenes = [v for k, v in items.items() if k.startswith("scene:")]
    scene_store._write_overrides(scenes, scene_store.scenes_path())
    data = read_settings()
    if "favourites" in items:
        data["favourite_colours"] = items["favourites"]
    else:
        data.pop("favourite_colours", None)
    names = {k[len("name:"):]: v for k, v in items.items() if k.startswith("name:")}
    if names:
        data["device_names"] = names
    else:
        data.pop("device_names", None)
    if data or settings_path().exists():
        _write_settings(data)


def _stamp(key: str) -> float:
    """When an item last changed here: its file's modification time."""
    path = scene_store.scenes_path() if key.startswith("scene:") else settings_path()
    try:
        return path.stat().st_mtime
    except OSError:
        return time.time()


def _changed(current: dict, before: dict) -> list[dict]:
    keys = list(current) + [k for k in before if k not in current]
    return [{"key": k, "value": current.get(k), "stamp": _stamp(k)}
            for k in keys if current.get(k) != before.get(k)]


# -- the shared copy (the install that runs `serve`) -------------------------------


def hub_sync(base: int, changes: list) -> dict:
    """Merge a linked install's changes into the shared copy and return it.

    Each item remembers the revision it last changed at and when it was
    edited. A change from a linked install wins unless this side changed the
    same item after `base` (the revision that install last saw) and that
    edit is the later one.
    """
    if link_path().exists():
        raise SyncError("this install is itself linked to another one; "
                        "link to that one instead")
    if not isinstance(base, int) or base < 0 or not isinstance(changes, list):
        raise SyncError("malformed sync request")
    if len(changes) > MAX_ITEMS:
        raise SyncError("too many changes in one request")
    with _lock():
        state = _read_json(hub_path(), {})
        rev = int(state.get("rev", 0))
        meta: dict = state.get("items") if isinstance(state.get("items"), dict) else {}

        # Edits made right here (CLI, MCP, widget on this machine) since last time.
        current = read_items()
        for change in _changed(current, {k: m.get("value") for k, m in meta.items()}):
            rev += 1
            meta[change["key"]] = {"value": change["value"], "rev": rev, "stamp": change["stamp"]}

        applied = 0
        for change in changes:
            if not isinstance(change, dict):
                continue
            key = change.get("key")
            value = _valid(key, change.get("value"))
            if value is None and change.get("value") is not None:
                continue  # not something we know how to store
            try:
                stamp = float(change.get("stamp", 0))
            except (TypeError, ValueError):
                stamp = 0.0
            mine = meta.get(key)
            if mine is not None:
                if mine.get("value") == value:
                    continue
                if mine.get("rev", 0) > base and mine.get("stamp", 0) > stamp:
                    continue  # both changed it; this side's edit is the later one
            rev += 1
            meta[key] = {"value": value, "rev": rev, "stamp": stamp}
            applied += 1

        values = {k: m["value"] for k, m in meta.items() if m.get("value") is not None}
        if applied:
            write_items(values)
        write_private(hub_path(), json.dumps({"rev": rev, "items": meta}, ensure_ascii=False) + "\n")
    return {"rev": rev, "items": values}


# -- a linked install --------------------------------------------------------------


def parse_headers(lines) -> dict[str, str]:
    headers = {}
    for line in lines or []:
        name, sep, value = str(line).partition(":")
        name, value = name.strip(), value.strip()
        if not sep or not name or not value or not re.fullmatch(r"[A-Za-z0-9-]+", name):
            raise ConfigError(f"a header looks like 'Name: value', not {str(line)[:40]!r}")
        headers[name] = value
    return headers


def _env_headers() -> dict[str, str]:
    # For containers: TUYA_LIGHT_LINK_HEADERS="CF-Access-Client-Id: ...; CF-Access-Client-Secret: ..."
    raw = os.environ.get("TUYA_LIGHT_LINK_HEADERS", "")
    return parse_headers([p for p in re.split(r"[;\n]", raw) if p.strip()])


def load_link() -> dict | None:
    path = link_path()
    if not path.exists():
        return None
    _secure(path, "the pairing key of the install it is linked to")
    data = _read_json(path, {})
    return data if data.get("url") and data.get("key") else None


def _save_link(data: dict) -> None:
    write_private(link_path(), json.dumps(data, indent=2, ensure_ascii=False) + "\n")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a redirect here is a login page, never the answer


def _post(link: dict, path: str, body: dict, timeout: float = TIMEOUT) -> dict:
    headers = {**(link.get("headers") or {}), **_env_headers(),
               "Authorization": f"Bearer {link['key']}", "Content-Type": "application/json",
               "Accept": "application/json"}
    request = urllib.request.Request(link["url"].rstrip("/") + path, method="POST",
                                     data=json.dumps(body).encode(), headers=headers)
    opener = urllib.request.build_opener(_NoRedirect)
    host = urlsplit(link["url"]).netloc
    try:
        with opener.open(request, timeout=timeout) as answer:
            raw = answer.read(4_000_000)
    except urllib.error.HTTPError as err:
        try:
            detail = json.loads(err.read(20_000) or b"{}")
        except ValueError:
            detail = None
        if 300 <= err.code < 400:
            raise SyncError(f"{host} answered with a redirect, most likely to a login page: an "
                            "authenticating proxy is in front of it; give its service-token "
                            "headers with --header") from None
        if isinstance(detail, dict) and detail.get("error"):
            if err.code == 401:
                raise SyncError(f"{host} did not accept the key; pair again with a fresh link "
                                "from `tuya-light serve --pair` there") from None
            raise SyncError(f"{host}: {detail['error']}") from None
        if err.code in (401, 403):
            raise SyncError(f"{host} refused the request ({err.code}); if a proxy guards it, "
                            "check its service-token headers") from None
        raise SyncError(f"{host} answered {err.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as err:
        reason = getattr(err, "reason", err)
        raise SyncError(f"cannot reach {host}: {reason}") from None
    try:
        data = json.loads(raw)
    except ValueError:
        raise SyncError(f"{host} did not answer with tuya-light's data") from None
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        raise SyncError(f"{host} did not answer with tuya-light's data")
    return data


def _run(link: dict, timeout: float = TIMEOUT) -> dict:
    """One sync, with the lock held around reading, sending and writing."""
    with _lock():
        current = read_items()
        changes = _changed(current, link.get("snapshot") or {})
        answer = _post(link, "/api/sync", {"base": int(link.get("base", 0)), "changes": changes},
                       timeout)
        items = {}
        for key, value in list(answer["items"].items())[:MAX_ITEMS]:
            cleaned = _valid(key, value)
            if cleaned is not None:
                items[key] = cleaned
        pulled = sum(1 for k in set(items) | set(current) if items.get(k) != current.get(k))
        write_items(items)
        link.update(base=int(answer.get("rev", 0)), snapshot=items, synced_at=time.time(),
                    failed_at=None, error=None)
        _save_link(link)
    return {"pushed": len(changes), "pulled": pulled, "rev": link["base"],
            "server": urlsplit(link["url"]).netloc}


def link(url: str, headers: dict[str, str], replace_local: bool = False,
         timeout: float = TIMEOUT) -> dict:
    """Link this install to the one at `url` (its pairing link) and sync once.
    Nothing is saved unless that first sync works."""
    parts = urlsplit(url.strip())
    key = (parse_qs(parts.query).get("key") or [""])[0]
    if parts.scheme not in ("http", "https") or not parts.netloc or not key:
        raise ConfigError("give the pairing link that `tuya-light serve --pair` prints "
                          "on the other install (it ends in ?key=...)")
    data = {"url": f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}", "key": key,
            "headers": headers, "base": 0,
            # Taking the other side's copy: nothing here counts as a change.
            "snapshot": read_items() if replace_local else {}}
    return _run(data, timeout)


def unlink() -> bool:
    path = link_path()
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


def sync(timeout: float = TIMEOUT) -> dict:
    found = load_link()
    if found is None:
        raise ConfigError("this install is not linked to another one; "
                          "see `tuya-light link --help`")
    try:
        return _run(found, timeout)
    except SyncError as err:
        found.update(failed_at=time.time(), error=str(err))
        _save_link(found)
        raise


def status() -> dict:
    found = load_link()
    if found is None:
        return {"linked": False}
    dirty = bool(_changed(read_items(), found.get("snapshot") or {}))
    return {"linked": True, "server": urlsplit(found["url"]).netloc,
            "synced_at": found.get("synced_at"), "pending": dirty, "error": found.get("error")}


def maybe_sync(force: bool = False, quiet: bool = False) -> None:
    """Called around commands that show or change shared settings. Never fails:
    when the other install can't be reached, the local copy is used and the
    change goes up next time."""
    try:
        found = load_link()
    except ConfigError:
        return
    if found is None:
        return
    now = time.time()
    failed = found.get("failed_at") or 0
    if not force:
        if now - (found.get("synced_at") or 0) < PULL_EVERY:
            return
        if now - failed < RETRY_AFTER:
            return
    try:
        _run(found, timeout=3.0 if not force else TIMEOUT)
    except (SyncError, ConfigError) as err:
        found.update(failed_at=now, error=str(err))
        try:
            _save_link(found)
        except OSError:
            pass
        if not quiet:
            print(f"tuya-light: shared settings not synced ({err}); using the local copy",
                  file=sys.stderr)

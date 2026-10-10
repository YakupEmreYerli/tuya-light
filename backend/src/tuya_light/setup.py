"""One-time setup: fetch local keys from the Tuya cloud, find bulbs on the LAN.

For the local transport the cloud is only needed here. Once the keys are
saved, every command talks to the bulbs directly and keeps working after the
Tuya developer trial ends.

With --cloud (a server away from the bulbs) the devices are saved for the
cloud transport instead, without a LAN scan, and typed-in credentials are
kept in cloud.json (0600) because every command needs them.
"""

from __future__ import annotations

import getpass
import os
import sys

import tinytuya

from .cloud import ENV_ID, ENV_SECRET, REGIONS, save_credentials
from .config import LIGHT_CATEGORIES, Device, save


def _ask(prompt: str, secret: bool = False) -> str:
    if secret:
        return getpass.getpass(prompt).strip()
    return input(prompt).strip()


def fetch_from_cloud(region: str, api_key: str, api_secret: str, any_device_id: str) -> list[dict]:
    cloud = tinytuya.Cloud(
        apiRegion=region, apiKey=api_key, apiSecret=api_secret, apiDeviceID=any_device_id
    )
    if getattr(cloud, "error", None):
        raise SystemExit(f"tuya-light: cloud login failed: {cloud.error}")
    devices = cloud.getdevices(verbose=False)
    if isinstance(devices, dict):
        payload = devices.get("Payload") or devices.get("Error") or devices
        raise SystemExit(f"tuya-light: cloud refused the request: {payload}")
    return devices


def scan_lan(seconds: int = 12) -> dict[str, dict]:
    print(f"Scanning the local network for {seconds} s...", file=sys.stderr)
    found = tinytuya.deviceScan(verbose=False, maxretry=seconds, color=False, poll=False)
    return {info.get("gwId") or info.get("id"): info for info in found.values()}


def _env(names: tuple[str, ...]) -> str:
    return next((os.environ[n].strip() for n in names if os.environ.get(n, "").strip()), "")


def run(region: str | None, include_all: bool, any_device_id: str | None,
        cloud: bool = False) -> int:
    region = (region or os.environ.get("TUYA_REGION") or "eu").strip().lower()
    if region not in REGIONS:
        raise SystemExit(f"tuya-light: unknown region {region!r}; use one of {', '.join(REGIONS)}")
    from_env = bool(_env(ENV_ID) and _env(ENV_SECRET))
    api_key = _env(ENV_ID) or _ask("Tuya Access ID: ")
    api_secret = _env(ENV_SECRET) or _ask("Tuya Access Secret: ", secret=True)
    any_device_id = any_device_id or _ask(
        "Device ID of any one of your devices (Tuya IoT platform, Devices tab): "
    )

    cloud_devices = fetch_from_cloud(region, api_key, api_secret, any_device_id)
    lan = {} if cloud else scan_lan()

    devices: list[Device] = []
    for raw in cloud_devices:
        if not include_all and raw.get("category") not in LIGHT_CATEGORIES:
            continue
        if cloud:
            raw = dict(raw, transport="cloud", ip=None)
        else:
            seen = lan.get(raw["id"], {})
            raw = dict(raw, ip=seen.get("ip"), version=seen.get("version") or raw.get("version"))
            if not raw.get("key"):
                print(f"  skipped {raw.get('name')}: the cloud returned no local key",
                      file=sys.stderr)
                continue
        dev = Device.from_json(raw)
        devices.append(dev)
        where = ("through the Tuya cloud" if cloud else
                 dev.ip or "not seen on the LAN (will search each time)")
        print(f"  {dev.name}: {where}", file=sys.stderr)

    if not devices:
        print("tuya-light: no lights found on this account", file=sys.stderr)
        return 1
    path = save(devices)
    print(f"Saved {len(devices)} device(s) to {path}", file=sys.stderr)
    if cloud and not from_env:
        where = save_credentials(api_key, api_secret, region)
        print(f"Saved the Access ID, Secret and region to {where} (readable only by you); "
              "the cloud transport needs them for every command.", file=sys.stderr)
    elif cloud:
        print("The credentials came from the environment and were not saved: keep "
              "TUYA_ACCESS_ID, TUYA_ACCESS_SECRET and TUYA_REGION set wherever tuya-light runs.",
              file=sys.stderr)
    return 0

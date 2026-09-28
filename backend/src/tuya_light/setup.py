"""One-time setup: fetch local keys from the Tuya cloud, find bulbs on the LAN.

The cloud is only needed here. Once the keys are saved, every command talks
to the bulbs directly and keeps working after the Tuya developer trial ends.
"""

from __future__ import annotations

import getpass
import os
import sys

import tinytuya

from .config import LIGHT_CATEGORIES, Device, save

REGIONS = {
    "eu": "Central Europe",
    "us": "Western America",
    "us-e": "Eastern America",
    "cn": "China",
    "in": "India",
    "weu": "Western Europe",
}


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


def run(region: str, include_all: bool, any_device_id: str | None) -> int:
    api_key = os.environ.get("TUYA_API_KEY") or _ask("Tuya Access ID: ")
    api_secret = os.environ.get("TUYA_API_SECRET") or _ask("Tuya Access Secret: ", secret=True)
    any_device_id = any_device_id or _ask(
        "Device ID of any one of your devices (Tuya IoT platform, Devices tab): "
    )

    cloud_devices = fetch_from_cloud(region, api_key, api_secret, any_device_id)
    lan = scan_lan()

    devices: list[Device] = []
    for raw in cloud_devices:
        if not include_all and raw.get("category") not in LIGHT_CATEGORIES:
            continue
        seen = lan.get(raw["id"], {})
        raw = dict(raw, ip=seen.get("ip"), version=seen.get("version") or raw.get("version"))
        if not raw.get("key"):
            print(f"  skipped {raw.get('name')}: the cloud returned no local key", file=sys.stderr)
            continue
        dev = Device.from_json(raw)
        devices.append(dev)
        where = dev.ip or "not seen on the LAN (will search each time)"
        print(f"  {dev.name}: {where}", file=sys.stderr)

    if not devices:
        print("tuya-light: no lights found on this account", file=sys.stderr)
        return 1
    path = save(devices)
    print(f"Saved {len(devices)} device(s) to {path}", file=sys.stderr)
    return 0

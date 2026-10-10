"""Which transport reaches a bulb, and opening it.

- ``local`` (the default): straight to the bulb on the LAN with its local key
  (light.Light). No cloud involved.
- ``cloud``: through Tuya's IoT Platform OpenAPI with your own Access ID and
  Secret (cloud.CloudLight), for a server that is not on the bulb's network.

Precedence, strongest first: ``tuya-light --transport``, the device's
``"transport"`` in devices.json, ``TUYA_LIGHT_TRANSPORT``, then local.
"""

from __future__ import annotations

from .config import TRANSPORTS, ConfigError, Device, default_transport
from .light import BaseLight, Light

# Set by the command line's --transport for the whole process.
override: str | None = None


def transport_for(device: Device, forced: str | None = None) -> str:
    kind = forced or override or device.transport or default_transport()
    if kind not in TRANSPORTS:
        raise ConfigError(f"transport must be local or cloud, not {kind!r}")
    return kind


def open_light(device: Device, *, timeout: float = 3.0, transport: str | None = None) -> BaseLight:
    if transport_for(device, transport) == "cloud":
        from .cloud import CloudLight

        return CloudLight(device)
    if not device.key:
        raise ConfigError(f"{device.name} has no local key: run `tuya-light setup`, "
                          "or use the cloud transport")
    return Light(device, timeout=timeout)

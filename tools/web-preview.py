#!/usr/bin/env python3
"""Run the phone page against pretend bulbs, to work on the page without
hardware and without touching your own configuration.

    .venv/bin/python tools/web-preview.py [--port 8893] [--lights 2] [--offline] [--cloud]

Prints a pairing link for this computer. The device list, scenes and key live
in a temporary directory that is deleted on exit; no real bulb and no real
Tuya cloud is contacted (--cloud uses a pretend one).
"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))

import tinytuya  # noqa: E402

from tuya_light import light as light_module  # noqa: E402
from tuya_light import web  # noqa: E402

NAMES = ["Desk lamp", "Hall", "Bedroom"]


class PretendBulb:
    """Answers like a newer (data points 20-24) bulb, a little slowly."""

    def __init__(self, offline: bool) -> None:
        self.on, self.mode = True, "white"
        self.bright, self.temp = 450, 200
        self.hsv = (0.75, 0.8, 0.7)
        self.offline = offline

    def set_socketPersistent(self, *_): pass
    def set_socketRetryLimit(self, *_): pass
    def close(self): pass

    def _wait(self):
        time.sleep(0.12)
        return {"Error": "Network Error: Device Unreachable"} if self.offline else {}

    def status(self):
        err = self._wait()
        if err:
            return err
        h, s, v = self.hsv
        return {"dps": {"20": self.on, "21": self.mode, "22": self.bright, "23": self.temp,
                        "24": "%04x%04x%04x" % (round(h * 360), round(s * 1000), round(v * 1000))}}

    def turn_on(self):
        self.on = True
        return self._wait()

    def turn_off(self):
        self.on = False
        return self._wait()

    def set_hsv(self, h, s, v):
        self.mode, self.hsv = "colour", (h, s, v)
        return self._wait()

    def set_white_percentage(self, b, t):
        self.mode, self.bright, self.temp = "white", round(b * 10), round(t * 10)
        return self._wait()


class PretendCloud:
    """Answers like tinytuya.Cloud for one v2 bulb."""

    def __init__(self, **kw):
        self.token, self.error = "pretend", None
        self.dps = {"switch_led": True, "work_mode": "white", "bright_value_v2": 450,
                    "temp_value_v2": 200, "colour_data_v2": '{"h":275,"s":800,"v":700}'}

    def getstatus(self, dev):
        time.sleep(0.3)
        return {"success": True, "result": [{"code": c, "value": v} for c, v in self.dps.items()]}

    def getfunctions(self, dev):
        return {"success": True, "result": {"functions": [{"code": c} for c in self.dps]}}

    def getconnectstatus(self, dev):
        return True

    def sendcommand(self, dev, commands):
        time.sleep(0.3)
        self.dps.update({c["code"]: c["value"] for c in commands["commands"]})
        return {"success": True, "result": True}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8893)
    p.add_argument("--lights", type=int, default=1, choices=(1, 2, 3))
    p.add_argument("--offline", action="store_true", help="the bulbs never answer")
    p.add_argument("--cloud", action="store_true", help="reach the bulbs through a pretend cloud")
    args = p.parse_args()

    with tempfile.TemporaryDirectory(prefix="tuya-light-preview-") as tmp:
        devices = [{"id": f"pretend{i}", "name": NAMES[i], "key": "not-a-real-key",
                    "ip": "192.0.2.10"} for i in range(args.lights)]
        if args.cloud:
            for d in devices:
                d["transport"] = "cloud"
            os.environ.update(TUYA_ACCESS_ID="pretend", TUYA_ACCESS_SECRET="pretend",
                              TUYA_REGION="eu")
            tinytuya.Cloud = PretendCloud
        Path(tmp, "devices.json").write_text(json.dumps(devices))
        Path(tmp, "devices.json").chmod(0o600)
        os.environ["TUYA_LIGHT_CONFIG"] = str(Path(tmp, "devices.json"))
        os.environ["TUYA_LIGHT_SCENES"] = str(Path(tmp, "scenes.json"))
        bulbs = {d["id"]: PretendBulb(args.offline) for d in devices}
        light_module.tinytuya.BulbDevice = lambda dev_id, *a, **kw: bulbs[dev_id]

        keys = web.KeyStore(Path(tmp, "web.key"))
        server = web.PhoneServer((args.host, args.port), keys=keys, bad_key_delay=0.2)
        print(f"Pair:  http://{args.host}:{args.port}/?key={keys.get()}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

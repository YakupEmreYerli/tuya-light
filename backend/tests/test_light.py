import json

import pytest

from tuya_light import cli, config
from tuya_light import scenes as scene_store
from tuya_light.config import ConfigError
from tuya_light.light import Light


class FakeBulb:
    """Stands in for tinytuya.BulbDevice: records writes, answers reads."""

    def __init__(self, *a, **kw):
        self.calls = []
        self.on = True
        self.mode = "white"
        self.bright = 50
        self.temp = 30
        self.hsv = (0.5, 1.0, 0.8)
        self.fail = None

    def set_socketPersistent(self, *_): pass
    def set_socketRetryLimit(self, *_): pass
    def close(self): pass

    def status(self):
        if self.fail:
            return {"Error": self.fail}
        h, sat, val = self.hsv
        return {"dps": {
            "20": self.on, "21": self.mode,
            "22": int(self.bright * 10), "23": int(self.temp * 10),
            "24": "%04x%04x%04x" % (round(h * 360), round(sat * 1000), round(val * 1000)),
        }}

    def turn_on(self):
        self.calls.append(("on",)); self.on = True; return {}

    def turn_off(self):
        self.calls.append(("off",)); self.on = False; return {}

    def set_hsv(self, h, s, v):
        self.calls.append(("hsv", round(h, 3), round(s, 3), round(v, 3)))
        self.mode, self.hsv = "colour", (h, s, v)
        return {}

    def set_white_percentage(self, b, t):
        self.calls.append(("white", b, t))
        self.mode, self.bright, self.temp = "white", b, t
        return {}


@pytest.fixture(autouse=True)
def isolated_scenes(tmp_path, monkeypatch):
    monkeypatch.setenv("TUYA_LIGHT_SCENES", str(tmp_path / "scenes.json"))


@pytest.fixture
def fake(monkeypatch):
    bulb = FakeBulb()
    monkeypatch.setattr("tuya_light.light.tinytuya.BulbDevice", lambda *a, **kw: bulb)
    return bulb


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "devices.json"
    path.write_text(json.dumps([
        {"id": "abc123", "name": "Desk", "key": "k1", "ip": "10.0.0.5", "version": "3.5"},
        {"id": "def456", "name": "Hall", "key": "k2"},
    ]))
    monkeypatch.setenv("TUYA_LIGHT_CONFIG", str(path))
    return path


def dev():
    return config.Device(id="abc123", name="Desk", key="k1", ip="10.0.0.5", version=3.5)


def test_config_reads_wizard_format(cfg):
    devices = config.load()
    assert [d.name for d in devices] == ["Desk", "Hall"]
    assert devices[0].version == 3.5 and devices[1].ip is None


def test_config_pick_by_name_and_default(cfg):
    devices = config.load()
    assert config.pick(devices, None).id == "abc123"
    assert config.pick(devices, "Hall").id == "def456"
    with pytest.raises(config.ConfigError):
        config.pick(devices, "Kitchen")


def test_config_missing_key_is_an_error():
    with pytest.raises(config.ConfigError):
        config.Device.from_json({"id": "x", "key": ""})


def test_save_is_owner_only(tmp_path):
    path = config.save([dev()], tmp_path / "d" / "devices.json")
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert config.load(path)[0].key == "k1"


def test_state_in_human_units(fake):
    fake.mode, fake.hsv = "colour", (0.75, 0.5, 0.2)
    s = Light(dev()).state()
    assert (s.online, s.on, s.mode, s.hue, s.saturation, s.value) == (True, True, "colour", 270, 50, 20)


def test_offline_state_carries_the_reason(fake):
    fake.fail = "Network Error: Device Unreachable"
    s = Light(dev()).state()
    assert not s.online and "Unreachable" in s.error


def test_colour_turns_on_and_clamps(fake):
    fake.on = False
    Light(dev()).colour(390, 150, 0)
    assert fake.calls == [("on",), ("hsv", 0.083, 1.0, 0.01)]


def test_brightness_keeps_colour_mode(fake):
    fake.mode, fake.hsv = "colour", (0.5, 1.0, 0.8)
    Light(dev()).brightness(30)
    assert fake.calls[-1] == ("hsv", 0.5, 1.0, 0.3)


def test_brightness_keeps_white_temperature(fake):
    Light(dev()).brightness(70)
    assert fake.calls[-1] == ("white", 70, 30)


def test_toggle(fake):
    Light(dev()).toggle()
    assert fake.calls == [("off",)]


def test_every_scene_applies(fake):
    light = Light(dev())
    for sc in scene_store.BUILTIN:
        light.scene(sc.name)
    assert len([c for c in fake.calls if c[0] in ("hsv", "white")]) == len(scene_store.BUILTIN)
    with pytest.raises(ConfigError):
        light.scene("disco")


def test_cli_prints_state_after_command(fake, cfg, capsys):
    assert cli.main(["--json", "colour", "#ff0000"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "colour" and out["hue"] == 0 and out["saturation"] == 100


def test_cli_named_colour_and_device_flag(fake, cfg, capsys):
    assert cli.main(["--json", "-d", "Desk", "colour", "purple"]) == 0
    assert json.loads(capsys.readouterr().out)["hue"] == 275


def test_cli_offline_exit_code(fake, cfg, capsys):
    fake.fail = "timeout"
    assert cli.main(["--json", "state"]) == 2
    assert json.loads(capsys.readouterr().out)["online"] is False


def test_cli_without_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TUYA_LIGHT_CONFIG", str(tmp_path / "none.json"))
    assert cli.main(["--json", "state"]) == 3
    assert json.loads(capsys.readouterr().out)["config"] is True


def test_decode_type_a_layout():
    from tuya_light.light import decode_dps
    out = decode_dps({"1": True, "2": "colour", "3": 255, "4": 0, "5": "ff00000000ffff"})
    assert out["on"] and out["mode"] == "colour" and out["brightness"] == 100
    assert (out["hue"], out["saturation"], out["value"]) == (0, 100, 100)


def test_decode_real_bulb_sample():
    from tuya_light.light import decode_dps
    out = decode_dps({"20": True, "21": "white", "22": 10, "23": 78, "24": "011003e803e8"})
    assert (out["brightness"], out["temperature"], out["hue"], out["saturation"]) == (1, 8, 272, 100)


def test_unknown_layout_is_offline(fake, monkeypatch):
    monkeypatch.setattr(fake, "status", lambda: {"dps": {"101": 1}})
    s = Light(dev()).state()
    assert not s.online and "unrecognised" in s.error


def test_partial_push_is_merged_with_next_reply(fake, monkeypatch):
    replies = iter([{"dps": {"23": 78}}, {"dps": {"20": True, "21": "white", "22": 500}}])
    monkeypatch.setattr(fake, "status", lambda: next(replies))
    s = Light(dev()).state()
    assert s.online and s.brightness == 50 and s.temperature == 8

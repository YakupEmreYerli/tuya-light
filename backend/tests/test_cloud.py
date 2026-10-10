import json
import threading
import time

import pytest

from tuya_light import backend, cli, cloud, config, web
from tuya_light.cloud import CloudLight, CloudSession, Credentials
from tuya_light.config import ConfigError, Device
from tuya_light.light import Light
from tuya_light.worker import LightWorker

from test_light import FakeBulb  # noqa: E402

SECRET = "good-secret-0123456789"
CLOUD_ERR = "Error Response from Tuya Cloud"

V2_FUNCTIONS = [
    {"code": "switch_led", "type": "Boolean", "values": "{}"},
    {"code": "work_mode", "type": "Enum", "values": '{"range":["white","colour","scene","music"]}'},
    {"code": "bright_value_v2", "type": "Integer", "values": '{"min":10,"max":1000,"scale":0,"step":1}'},
    {"code": "temp_value_v2", "type": "Integer", "values": '{"min":0,"max":1000,"scale":0,"step":1}'},
    {"code": "colour_data_v2", "type": "Json",
     "values": '{"h":{"min":0,"scale":0,"unit":"","max":360,"step":1},'
               '"s":{"min":0,"scale":0,"unit":"","max":1000,"step":1},'
               '"v":{"min":0,"scale":0,"unit":"","max":1000,"step":1}}'},
    {"code": "scene_data_v2", "type": "Json", "values": "{}"},
]


class FakeCloud:
    """Stands in for tinytuya.Cloud: answers like Tuya's OpenAPI, records calls."""

    made = []

    def __init__(self, apiRegion=None, apiKey=None, apiSecret=None, **kw):
        FakeCloud.made.append(self)
        self.region = apiRegion
        self.token = "token-abc" if apiSecret == SECRET else None
        self.error = None if self.token else {
            "Error": "Unable to Get Cloud Token", "Err": "911",
            "Payload": "Cloud _gettoken() failed: 'sign invalid'"}
        self.calls = []
        self.online = True
        self.functions = V2_FUNCTIONS
        self.fail = None
        self.dps = {"switch_led": True, "work_mode": "white", "bright_value_v2": 450,
                    "temp_value_v2": 200, "colour_data_v2": '{"h":275,"s":900,"v":400}',
                    "scene_data_v2": '{"scene_num":1}'}

    def _error(self, msg):
        return {"Error": CLOUD_ERR, "Err": "913", "Payload": f"Error from Tuya Cloud: {msg!r}"}

    def getstatus(self, dev):
        self.calls.append(("getstatus", dev))
        if self.fail:
            return self._error(self.fail)
        return {"result": [{"code": c, "value": v} for c, v in self.dps.items()], "success": True}

    def getfunctions(self, dev):
        self.calls.append(("getfunctions", dev))
        if self.functions is None:
            return self._error("permission deny")
        return {"result": {"category": "dj", "functions": self.functions}, "success": True}

    def getconnectstatus(self, dev):
        self.calls.append(("getconnectstatus", dev))
        return self.online

    def sendcommand(self, dev, commands):
        self.calls.append(("sendcommand", dev, commands["commands"]))
        if self.fail:
            return self._error(self.fail)
        for c in commands["commands"]:
            self.dps[c["code"]] = c["value"]
        return {"result": True, "success": True, "t": 1}

    def count(self, name):
        return sum(1 for c in self.calls if c[0] == name)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name in ("TUYA_ACCESS_ID", "TUYA_ACCESS_SECRET", "TUYA_REGION", "TUYA_API_KEY",
                 "TUYA_API_SECRET", "TUYA_LIGHT_TRANSPORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TUYA_LIGHT_CONFIG", str(tmp_path / "devices.json"))
    monkeypatch.setenv("TUYA_LIGHT_SCENES", str(tmp_path / "scenes.json"))
    monkeypatch.setattr(web, "tailscale_name", lambda: None)
    monkeypatch.setattr(backend, "override", None)
    cloud._sessions.clear()
    FakeCloud.made.clear()
    monkeypatch.setattr("tinytuya.Cloud", FakeCloud)
    yield
    cloud._sessions.clear()


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("TUYA_ACCESS_ID", "id-1")
    monkeypatch.setenv("TUYA_ACCESS_SECRET", SECRET)
    monkeypatch.setenv("TUYA_REGION", "eu")


def dev(transport="cloud"):
    return Device(id="bf01", name="Desk", key="", transport=transport)


def fake() -> FakeCloud:
    return FakeCloud.made[-1]


# -- credentials and transport choice ------------------------------------------


def test_credentials_environment_wins_over_file(tmp_path, monkeypatch):
    path = cloud.save_credentials("file-id", "file-secret", "us", tmp_path / "cloud.json")
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    c = cloud.load_credentials(path)
    assert (c.access_id, c.access_secret, c.region) == ("file-id", "file-secret", "us")
    monkeypatch.setenv("TUYA_ACCESS_SECRET", "env-secret")
    monkeypatch.setenv("TUYA_REGION", "EU")
    c = cloud.load_credentials(path)
    assert (c.access_id, c.access_secret, c.region) == ("file-id", "env-secret", "eu")
    monkeypatch.setenv("TUYA_API_KEY", "old-name-id")  # what `setup` always accepted
    assert cloud.load_credentials(path).access_id == "old-name-id"


def test_credentials_missing_or_wrong(tmp_path, monkeypatch):
    with pytest.raises(ConfigError, match="TUYA_ACCESS_ID, TUYA_ACCESS_SECRET, TUYA_REGION"):
        cloud.load_credentials(tmp_path / "none.json")
    monkeypatch.setenv("TUYA_ACCESS_ID", "x")
    monkeypatch.setenv("TUYA_ACCESS_SECRET", "y")
    monkeypatch.setenv("TUYA_REGION", "mars")
    with pytest.raises(ConfigError, match="unknown Tuya region"):
        cloud.load_credentials(tmp_path / "none.json")


def test_loose_credentials_file_is_tightened(tmp_path, capsys):
    path = tmp_path / "cloud.json"
    path.write_text(json.dumps({"access_id": "a", "access_secret": "b", "region": "eu"}))
    path.chmod(0o644)
    cloud.load_credentials(path)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert "cloud secret" in capsys.readouterr().err


def test_secret_stays_out_of_repr():
    c = Credentials("id-1", SECRET, "eu")
    assert SECRET not in repr(c) and "id-1" in repr(c)


def test_transport_precedence(monkeypatch):
    plain = Device(id="a", name="A", key="k")
    assert backend.transport_for(plain) == "local"
    monkeypatch.setenv("TUYA_LIGHT_TRANSPORT", "cloud")
    assert backend.transport_for(plain) == "cloud"
    assert backend.transport_for(Device(id="a", name="A", key="k", transport="local")) == "local"
    monkeypatch.setattr(backend, "override", "local")  # tuya-light --transport local
    assert backend.transport_for(dev()) == "local"
    monkeypatch.setenv("TUYA_LIGHT_TRANSPORT", "carrier-pigeon")
    monkeypatch.setattr(backend, "override", None)
    with pytest.raises(ConfigError):
        backend.transport_for(plain)


def test_cloud_device_needs_no_local_key(monkeypatch):
    d = Device.from_json({"id": "bf01", "name": "Desk", "transport": "cloud"})
    assert d.transport == "cloud" and d.key == ""
    assert d.to_json()["transport"] == "cloud"
    with pytest.raises(ConfigError):
        Device.from_json({"id": "bf01", "key": ""})  # local still needs one
    monkeypatch.setenv("TUYA_LIGHT_TRANSPORT", "cloud")
    assert Device.from_json({"id": "bf01"}).key == ""
    with pytest.raises(ConfigError):
        Device.from_json({"id": "bf01", "transport": "bluetooth"})


def test_open_light_picks_the_transport(creds, monkeypatch):
    monkeypatch.setattr("tuya_light.light.tinytuya.BulbDevice", lambda *a, **kw: FakeBulb())
    assert isinstance(backend.open_light(dev()), CloudLight)
    assert isinstance(backend.open_light(Device(id="a", name="A", key="k")), Light)
    with pytest.raises(ConfigError, match="no local key"):
        backend.open_light(dev(transport="local"))


# -- value mapping -------------------------------------------------------------


def test_state_in_human_units(creds):
    light = CloudLight(dev())
    s = light.state()
    assert (s.online, s.on, s.mode, s.brightness, s.temperature) == (True, True, "white", 45, 20)
    assert (s.hue, s.saturation, s.value) == (275, 90, 40)


def test_older_bulb_ranges_come_from_its_instruction_set(creds):
    light = CloudLight(dev())
    light.session._cloud()
    f = fake()
    f.functions = [
        {"code": "switch_led", "type": "Boolean", "values": "{}"},
        {"code": "work_mode", "type": "Enum", "values": "{}"},
        {"code": "bright_value", "type": "Integer", "values": '{"min":25,"max":255}'},
        {"code": "temp_value", "type": "Integer", "values": '{"min":0,"max":255}'},
        {"code": "colour_data", "type": "Json",
         "values": '{"h":{"min":0,"max":360},"s":{"min":0,"max":255},"v":{"min":0,"max":255}}'},
    ]
    f.dps = {"switch_led": True, "work_mode": "colour", "bright_value": 255, "temp_value": 0,
             "colour_data": {"h": 120, "s": 255, "v": 128}}
    s = light.state()
    assert (s.mode, s.brightness, s.hue, s.saturation, s.value) == ("colour", 100, 120, 100, 50)
    light.white(3, 50)
    assert f.calls[-1][2] == [{"code": "switch_led", "value": True},
                              {"code": "work_mode", "value": "white"},
                              {"code": "bright_value", "value": 25},  # the bulb's floor
                              {"code": "temp_value", "value": 128}]


def test_commands_use_the_cloud_codes(creds):
    light = CloudLight(dev())
    light.white(45, 20)
    f = fake()
    assert f.calls[-1] == ("sendcommand", "bf01", [
        {"code": "switch_led", "value": True}, {"code": "work_mode", "value": "white"},
        {"code": "bright_value_v2", "value": 450}, {"code": "temp_value_v2", "value": 200}])
    light.colour(390, 150, 40)
    assert f.calls[-1][2][-1] == {"code": "colour_data_v2", "value": '{"h":30,"s":1000,"v":400}'}
    light.power(False)
    assert f.calls[-1][2] == [{"code": "switch_led", "value": False}]
    assert light.state().on is False


def test_scenes_are_sent_as_commands(creds):
    light = CloudLight(dev())
    light.scene("night")  # built-in: colour, hue 25, brightness 6
    assert fake().calls[-1][2][-1] == {"code": "colour_data_v2", "value": '{"h":25,"s":1000,"v":60}'}
    light.scene("reading")
    assert {"code": "bright_value_v2", "value": 1000} in fake().calls[-1][2]


# -- spending API calls carefully ----------------------------------------------


def test_state_after_a_command_costs_no_extra_read(creds):
    light = CloudLight(dev())
    light.state()
    f = fake()
    reads = f.count("getstatus")
    light.colour(200, 80, 50)
    s = light.state()
    assert (s.mode, s.hue, s.value) == ("colour", 200, 50)
    assert f.count("getstatus") == reads  # worked out from what was sent


def test_relative_change_reuses_a_recent_reading(creds, monkeypatch):
    light = CloudLight(dev())
    light.state()
    f = fake()
    # two seconds later a plain state read asks again, a relative change doesn't
    now = time.monotonic()
    monkeypatch.setattr(cloud.time, "monotonic", lambda: now + 10)
    light.brightness(30)
    assert f.count("getstatus") == 1
    assert f.calls[-1][2][-2:] == [{"code": "bright_value_v2", "value": 300},
                                   {"code": "temp_value_v2", "value": 200}]
    light.state()
    assert f.count("getstatus") == 1  # the command refreshed the reading
    monkeypatch.setattr(cloud.time, "monotonic", lambda: now + 20)
    light.state()
    assert f.count("getstatus") == 2


def test_one_login_and_one_instruction_set_per_process(creds):
    for _ in range(3):
        light = backend.open_light(dev())
        light.state()
        light.power(True)
        light.close()
    assert len(FakeCloud.made) == 1
    assert fake().count("getfunctions") == 1
    assert fake().count("getconnectstatus") == 1  # at most once a minute


def test_offline_bulb_and_cloud_errors(creds):
    light = CloudLight(dev())
    light.session._cloud()
    fake().online = False
    s = light.state()
    assert not s.online and "not connected" in s.error
    fake().fail = "device is offline"
    with pytest.raises(cloud.LightError, match="Tuya cloud: device is offline"):
        light.power(True)


def test_instruction_set_falls_back_to_status_codes(creds):
    light = CloudLight(dev())
    light.session._cloud()
    fake().functions = None  # e.g. "permission deny"
    assert light.state().brightness == 45
    light.white(50, 50)
    assert {"code": "bright_value_v2", "value": 500} in fake().calls[-1][2]


def test_login_failure_and_secrets_never_in_messages(monkeypatch):
    monkeypatch.setenv("TUYA_ACCESS_ID", "id-1")
    monkeypatch.setenv("TUYA_ACCESS_SECRET", "wrong-secret-xyz")
    monkeypatch.setenv("TUYA_REGION", "eu")
    s = CloudLight(dev()).state()
    assert not s.online and "sign invalid" in s.error and "wrong-secret-xyz" not in s.error

    def leaky(*a, **kw):
        raise RuntimeError("boom with wrong-secret-xyz inside")

    session = CloudSession(Credentials("id-1", "wrong-secret-xyz", "eu"), client_factory=leaky)
    with pytest.raises(cloud.LightError) as err:
        session.status("bf01")
    assert "wrong-secret-xyz" not in str(err.value) and "***" in str(err.value)


def test_slow_cloud_gives_up_instead_of_hanging(creds):
    def slow(**kw):
        time.sleep(1)

    session = CloudSession(Credentials("id-1", SECRET, "eu"), timeout=0.1, client_factory=slow)
    with pytest.raises(cloud.LightError, match="in time"):
        session.status("bf01")


# -- debounce --------------------------------------------------------------------


def test_cloud_worker_sends_only_where_a_drag_stops(creds):
    worker = LightWorker(dev(), settle=0.15, linger=0.05)
    tickets = []
    for value in (10, 20, 30, 40, 50):
        tickets.append(worker.submit(lambda light, v=value: light.brightness(v)))
        time.sleep(0.02)
    states = [t.wait(5) for t in tickets]
    sends = [c for c in fake().calls if c[0] == "sendcommand"]
    assert len(sends) == 1 and {"code": "bright_value_v2", "value": 500} in sends[0][2]
    assert all(s.brightness == 50 for s in states)
    worker.stop()


def test_debounce_never_waits_forever(creds):
    worker = LightWorker(dev(), settle=0.1, linger=0.05)
    stop = time.monotonic() + 0.8
    value = 1
    while time.monotonic() < stop:  # a finger that never rests
        worker.submit(lambda light, v=value: light.brightness(v))
        value += 1
        time.sleep(0.03)
    worker.read().wait(5)
    assert sum(1 for c in fake().calls if c[0] == "sendcommand") >= 2
    worker.stop()


# -- the command line and the phone page over the cloud --------------------------


def write_devices(tmp_path, entries):
    path = tmp_path / "devices.json"
    path.write_text(json.dumps(entries))
    path.chmod(0o600)


def test_cli_transport_flag(creds, tmp_path, capsys):
    write_devices(tmp_path, [{"id": "bf01", "name": "Desk", "key": "k"}])
    assert cli.main(["--transport", "cloud", "--json", "brightness", "30"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["brightness"] == 30 and out["online"]
    assert any(c[0] == "sendcommand" for c in fake().calls)


def test_cli_cloud_error_exit_codes(tmp_path, capsys, monkeypatch):
    write_devices(tmp_path, [{"id": "bf01", "name": "Desk", "transport": "cloud"}])
    assert cli.main(["--json", "state"]) == 3  # no credentials: a setup problem
    out = json.loads(capsys.readouterr().out)
    assert out["config"] is True and "TUYA_ACCESS_ID" in out["error"]
    monkeypatch.setenv("TUYA_ACCESS_ID", "id-1")
    monkeypatch.setenv("TUYA_ACCESS_SECRET", SECRET)
    monkeypatch.setenv("TUYA_REGION", "eu")
    CloudLight(dev()).session._cloud()
    fake().fail = "device is offline"
    assert cli.main(["--json", "on"]) == 2  # the light did not answer
    assert "device is offline" in json.loads(capsys.readouterr().out)["error"]


def test_setup_cloud_saves_devices_and_typed_credentials(tmp_path, monkeypatch, capsys):
    from tuya_light import setup

    monkeypatch.setattr(setup, "fetch_from_cloud", lambda *a: [
        {"id": "bf01", "name": "Desk", "key": "lk", "category": "dj"},
        {"id": "sw01", "name": "Plug", "key": "pk", "category": "cz"}])
    monkeypatch.setattr(setup, "scan_lan", lambda: pytest.fail("no LAN scan in cloud mode"))
    answers = iter(["typed-id", "typed-secret", "bf01"])
    monkeypatch.setattr(setup, "_ask", lambda prompt, secret=False: next(answers))
    assert cli.main(["setup", "--cloud", "--region", "weu"]) == 0
    saved = json.loads((tmp_path / "devices.json").read_text())
    assert saved == [{"id": "bf01", "name": "Desk", "key": "lk", "version": 3.3,
                      "transport": "cloud"}]
    creds_file = tmp_path / "cloud.json"
    assert oct(creds_file.stat().st_mode & 0o777) == "0o600"
    assert json.loads(creds_file.read_text())["region"] == "weu"
    assert "typed-secret" not in capsys.readouterr().err


def test_setup_cloud_keeps_environment_credentials_off_disk(creds, tmp_path, monkeypatch):
    from tuya_light import setup

    monkeypatch.setattr(setup, "fetch_from_cloud", lambda *a: [
        {"id": "bf01", "name": "Desk", "key": "", "category": "dj"}])
    monkeypatch.setattr(setup, "_ask", lambda prompt, secret=False: "bf01")
    assert cli.main(["setup", "--cloud"]) == 0
    assert not (tmp_path / "cloud.json").exists()


def test_page_learns_the_transport_and_polls_cloud_lights_slowly(creds, tmp_path):
    import http.client

    write_devices(tmp_path, [{"id": "bf01", "name": "Desk", "transport": "cloud"},
                             {"id": "ab01", "name": "Hall", "key": "k"}])
    server = web.PhoneServer(("127.0.0.1", 0), keys=web.KeyStore(tmp_path / "web.key"),
                             linger=0.05, bad_key_delay=0, log=lambda line: None, cloud_poll=45)
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    port = server.server_address[1]
    key = server.keys.get()

    seen = []

    def get(path):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", path, headers={"Host": f"127.0.0.1:{port}",
                                           "Cookie": f"{web.COOKIE}={key}"})
        raw = conn.getresponse().read()
        seen.append(raw)
        return json.loads(raw)

    try:
        devices = get("/api/devices")["devices"]
        assert [d["transport"] for d in devices] == ["cloud", "local"]
        state = get("/api/state?device=Desk")
        assert (state["transport"], state["poll"], state["brightness"]) == ("cloud", 45, 45)
        before = len(fake().calls)
        get("/api/state?device=Desk")  # a second phone right after: no new API call
        assert len(fake().calls) == before
        get("/api/scenes")
        assert not any(SECRET.encode() in raw or b"token-abc" in raw for raw in seen)
    finally:
        server.shutdown()
        server.server_close()

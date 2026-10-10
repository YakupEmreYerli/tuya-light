import http.client
import json
import threading
import time

import pytest

from tuya_light import cli, web
from tuya_light import scenes as scene_store
from tuya_light.config import Device
from tuya_light.light import Light, State
from tuya_light.worker import LightWorker

from test_light import FakeBulb  # noqa: E402

LOCAL_KEYS = ("k1-secret-local-key", "k2-secret-local-key")


@pytest.fixture(autouse=True)
def quiet_network(monkeypatch):
    # Never ask the real Tailscale or network stack during tests.
    monkeypatch.setattr(web, "tailscale_name", lambda: None)


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "devices.json"
    cfg.write_text(json.dumps([
        {"id": "abc123", "name": "Desk", "key": LOCAL_KEYS[0], "ip": "10.0.0.5"},
        {"id": "def456", "name": "Hall", "key": LOCAL_KEYS[1], "ip": "10.0.0.6"},
    ]))
    cfg.chmod(0o600)
    monkeypatch.setenv("TUYA_LIGHT_CONFIG", str(cfg))
    monkeypatch.setenv("TUYA_LIGHT_SCENES", str(tmp_path / "scenes.json"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    bulbs = {}

    def make(dev_id, *a, **kw):
        return bulbs.setdefault(dev_id, FakeBulb())

    monkeypatch.setattr("tuya_light.light.tinytuya.BulbDevice", make)
    return tmp_path, bulbs


class Client:
    def __init__(self, server):
        self.server = server
        self.port = server.server_address[1]
        self.host = f"127.0.0.1:{self.port}"
        self.key = server.keys.get()

    def request(self, method, path, body=None, *, cookie=True, headers=None, origin=True,
                ctype="application/json"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = {"Host": self.host}
        if cookie:
            hdrs["Cookie"] = f"{web.COOKIE}={self.key if cookie is True else cookie}"
        if method == "POST":
            if origin:
                hdrs["Origin"] = f"http://{self.host}" if origin is True else origin
            if ctype:
                hdrs["Content-Type"] = ctype
        hdrs.update(headers or {})
        data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
        conn.request(method, path, body=data, headers=hdrs)
        res = conn.getresponse()
        raw = res.read()
        conn.close()
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = raw
        return res, payload

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, {} if body is None else body, **kw)


@pytest.fixture
def client(env):
    tmp, _ = env
    logs = []
    server = web.PhoneServer(("127.0.0.1", 0), keys=web.KeyStore(tmp / "web.key"), linger=0.05,
                             bad_key_delay=0, log=logs.append, allow_hosts=("pc.lan",))
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    c = Client(server)
    c.logs = logs
    yield c
    server.shutdown()
    server.server_close()


def bulb(env, dev_id="abc123"):
    return env[1][dev_id]


# -- pages and pairing --------------------------------------------------------


def test_page_is_served_without_a_key_and_carries_no_secret(client):
    res, body = client.get("/", cookie=False)
    assert res.status == 200 and res.getheader("Content-Type").startswith("text/html")
    assert client.key.encode() not in body
    assert "frame-ancestors 'none'" in res.getheader("Content-Security-Policy")
    assert res.getheader("X-Content-Type-Options") == "nosniff"
    for path in ("/app.js", "/app.css", "/sw.js", "/apple-touch-icon.png", "/icon.svg"):
        assert client.get(path, cookie=False)[0].status == 200, path


def test_api_needs_the_key(client, env):
    assert client.get("/api/state", cookie=False)[0].status == 401
    assert client.get("/api/state", cookie="wrong")[0].status == 401
    res, state = client.get("/api/state")
    assert res.status == 200 and state["online"] and state["name"] == "Desk"
    assert res.getheader("Cache-Control") == "no-store"


def test_pairing_link_sets_a_strict_cookie_and_cleans_the_address(client):
    res, _ = client.get(f"/?key={client.key}", cookie=False)
    assert res.status == 303 and res.getheader("Location") == "/"
    cookie = res.getheader("Set-Cookie")
    assert cookie.startswith(f"{web.COOKIE}={client.key};")
    for part in ("HttpOnly", "SameSite=Strict", "Path=/", f"Max-Age={web.COOKIE_MAX_AGE}"):
        assert part in cookie
    # the cookie as the phone would send it back
    value = cookie.split(";")[0].split("=", 1)[1]
    assert client.get("/api/state", cookie=value)[0].status == 200


def test_wrong_pairing_link_sets_no_cookie(client):
    res, _ = client.get("/?key=guess", cookie=False)
    assert res.status == 303 and res.getheader("Location") == "/#bad-key"
    assert res.getheader("Set-Cookie") is None


def test_key_never_reaches_the_log(client):
    client.get(f"/?key={client.key}", cookie=False, headers={"Host": "evil.example"})
    client.get("/api/state", cookie=False)
    assert client.logs, "refused requests are logged"
    assert not any(client.key in line for line in client.logs)


def test_manifest_pairs_the_home_screen_app_only_for_a_paired_phone(client):
    res, manifest = client.get("/manifest.webmanifest", cookie=False)
    assert res.status == 200 and manifest["start_url"] == "/" and manifest["display"] == "standalone"
    res, manifest = client.get("/manifest.webmanifest")
    assert manifest["start_url"] == f"/?key={client.key}"
    assert res.getheader("Cache-Control") == "no-store"


def test_key_file_is_private_and_rotation_locks_phones_out(client, env):
    tmp, _ = env
    path = tmp / "web.key"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    old = client.key
    time.sleep(0.01)
    new = web.KeyStore(path).rotate()  # as `serve --rotate-key` does, from another process
    assert new != old
    assert client.get("/api/state", cookie=old)[0].status == 401
    assert client.get("/api/state", cookie=new)[0].status == 200


# -- host and origin ----------------------------------------------------------


def test_foreign_host_name_is_refused(client):
    # DNS rebinding: a page on evil.example that resolves to this computer.
    res, body = client.get("/api/state", headers={"Host": f"evil.example:{client.port}"})
    assert res.status == 403 and "--allow-host" in body["error"]
    assert client.post("/api/power", {"on": False}, headers={"Host": "evil.example"},
                       origin="http://evil.example")[0].status == 403
    assert client.get(f"/?key={client.key}", cookie=False,
                      headers={"Host": "evil.example"})[0].status == 403


def test_own_names_and_addresses_are_accepted(client):
    for host in (f"localhost:{client.port}", f"192.168.1.20:{client.port}", "[fd7a::1]:8892",
                 f"pc.lan:{client.port}"):
        assert client.get("/api/state", headers={"Host": host})[0].status == 200, host


def test_changes_need_the_page_s_own_origin(client, env):
    assert client.post("/api/power", {"on": False}, origin=None)[0].status == 403
    assert client.post("/api/power", {"on": False}, origin="http://evil.example")[0].status == 403
    assert client.post("/api/power", {"on": False}, origin="null")[0].status == 403
    assert client.post("/api/power", {"on": False},
                       headers={"Sec-Fetch-Site": "cross-site"})[0].status == 403
    assert "abc123" not in env[1]  # the bulb was never contacted
    res, state = client.post("/api/power", {"on": False}, headers={"Sec-Fetch-Site": "same-origin"})
    assert res.status == 200 and state["on"] is False


def test_another_app_on_this_machine_cannot_post(client):
    # localhost:3000 and localhost:<port> share cookies (same site), not origin
    res, _ = client.post("/api/power", {"on": False}, headers={"Host": f"localhost:{client.port}"},
                         origin="http://localhost:3000")
    assert res.status == 403


def test_changes_must_be_json(client, env):
    res, _ = client.post("/api/power", b"on=false", ctype="application/x-www-form-urlencoded")
    assert res.status == 415
    res, _ = client.post("/api/power", b"on=false", ctype="text/plain")
    assert res.status == 415


def test_no_cors_preflight(client):
    res, _ = client.request("OPTIONS", "/api/power", cookie=False,
                            headers={"Origin": "http://evil.example",
                                     "Access-Control-Request-Method": "POST"})
    assert res.status == 405 and res.getheader("Access-Control-Allow-Origin") is None


# -- controls -----------------------------------------------------------------


def test_power_toggle_brightness_temperature(client, env):
    res, state = client.post("/api/power", {"on": False})
    assert state["on"] is False and state["latest"] is True
    _, state = client.post("/api/toggle")
    assert state["on"] is True
    _, state = client.post("/api/brightness", {"value": 30})
    assert state["brightness"] == 30 and bulb(env).calls[-1] == ("white", 30, 30)
    _, state = client.post("/api/temperature", {"value": 80})
    assert state["mode"] == "white" and state["temperature"] == 80


def test_colour_by_hue_or_hex_keeps_brightness(client, env):
    client.post("/api/brightness", {"value": 40})
    _, state = client.post("/api/colour", {"hue": 275, "saturation": 90})
    assert state["mode"] == "colour" and state["hue"] == 275 and state["value"] == 40
    _, state = client.post("/api/color", {"hex": "#ff0000", "value": 70})
    assert (state["hue"], state["saturation"], state["value"]) == (0, 100, 70)


def test_bad_values_are_refused(client, env):
    for path, body in (("/api/brightness", {"value": "bright"}), ("/api/brightness", {}),
                       ("/api/brightness", {"value": True}), ("/api/power", {"on": "yes"}),
                       ("/api/colour", {"hex": "red"}), ("/api/colour", {"hue": 10}),
                       ("/api/scene", {"name": 5})):
        assert client.post(path, body)[0].status == 400, (path, body)
    assert client.post("/api/brightness", b'{"value": NaN}')[0].status == 400
    assert client.post("/api/brightness", b"[1, 2]")[0].status == 400
    assert client.post("/api/brightness", b"{not json")[0].status == 400
    assert client.post("/api/brightness", b"x" * (web.MAX_BODY + 1))[0].status == 413
    assert client.post("/api/disco", {})[0].status == 404
    assert "abc123" not in env[1] or env[1]["abc123"].calls == []


def test_scenes_are_listed_and_applied(client, env):
    scene_store.save("Evening", "colour", hue=30, saturation=80, brightness=35)
    scene_store.remove("party")  # hidden built-ins stay off the phone too
    res, scenes = client.get("/api/scenes")
    names = [s["name"] for s in scenes]
    assert res.status == 200 and "evening" in names and "party" not in names
    _, state = client.post("/api/scene", {"name": "night"})
    assert state["mode"] == "colour" and state["value"] == 6
    _, state = client.post("/api/scene", {"name": "Evening"})
    assert (state["hue"], state["value"]) == (30, 35)
    res, body = client.post("/api/scene", {"name": "disco"})
    assert res.status == 404 and "disco" in body["error"]


def test_device_is_chosen_by_id_or_name(client, env):
    _, state = client.get("/api/state?device=Hall")
    assert state["id"] == "def456"
    client.post("/api/power?device=def456", {"on": False})
    assert env[1]["def456"].calls == [("off",)]
    assert client.get("/api/state?device=Kitchen")[0].status == 404


def test_offline_light_is_reported_not_an_error(client, env):
    client.get("/api/state")
    bulb(env).fail = "Network Error: Device Unreachable"
    time.sleep(web.STATE_MAX_AGE + 0.05)
    res, state = client.get("/api/state")
    assert res.status == 200 and state["online"] is False and "Unreachable" in state["error"]


def test_missing_device_list_says_run_setup(client, monkeypatch, tmp_path):
    monkeypatch.setenv("TUYA_LIGHT_CONFIG", str(tmp_path / "none.json"))
    res, body = client.get("/api/state")
    assert res.status == 503 and body["config"] is True
    assert client.get("/api/devices")[0].status == 503


def test_local_keys_never_leave_the_server(client, env):
    res, devices = client.get("/api/devices")
    assert devices["devices"] == [{"id": "abc123", "name": "Desk", "transport": "local"},
                                  {"id": "def456", "name": "Hall", "transport": "local"}]
    seen = []
    for path in ("/api/devices", "/api/state", "/api/scenes", "/manifest.webmanifest", "/",
                 "/devices.json", "/../devices.json", "/static/../../devices.json",
                 "/%2e%2e/devices.json", "/web.key", "/static/index.html"):
        res, body = client.get(path)
        seen.append(body if isinstance(body, bytes) else json.dumps(body).encode())
        if "devices.json" in path or "web.key" in path or path.startswith("/static"):
            assert res.status == 404, path
    for key in LOCAL_KEYS:
        assert not any(key.encode() in body for body in seen)


def test_cli_serve_pair_prints_a_link_per_address(env, monkeypatch, capsys):
    monkeypatch.setattr(web, "local_addresses",
                        lambda: [("Tailscale", "100.101.102.103"), ("Home network (eth0)", "192.168.1.9")])
    assert cli.main(["--json", "serve", "--pair", "--port", "9000"]) == 0
    links = json.loads(capsys.readouterr().out)
    key = web.KeyStore().get()
    assert [link["url"] for link in links] == [f"http://100.101.102.103:9000/?key={key}",
                                               f"http://192.168.1.9:9000/?key={key}"]
    assert cli.main(["serve", "--pair", "--url", "https://pc.example.ts.net/"]) == 0
    out = capsys.readouterr().out
    assert f"https://pc.example.ts.net/?key={key}" in out


def test_cli_rotate_key(env, capsys):
    first = web.KeyStore().get()
    assert cli.main(["serve", "--rotate-key"]) == 0
    assert web.KeyStore().get() != first


def test_addresses_skip_bridges_and_vpn_tunnels():
    sample = [
        {"ifname": "lo", "addr_info": [{"family": "inet", "local": "127.0.0.1"}]},
        {"ifname": "eno1", "addr_info": [{"family": "inet", "local": "192.168.1.125"}]},
        {"ifname": "virbr0", "addr_info": [{"family": "inet", "local": "192.168.122.1"}]},
        {"ifname": "tailscale0", "addr_info": [{"family": "inet", "local": "100.77.1.2"}]},
        {"ifname": "docker0", "addr_info": [{"family": "inet", "local": "172.17.0.1"}]},
        {"ifname": "CloudflareWARP", "addr_info": [{"family": "inet", "local": "172.16.0.2"}]},
    ]
    found = web.parse_addresses(sample, is_physical=lambda name: name == "eno1")
    assert found == [("Tailscale", "100.77.1.2"), ("Home network (eno1)", "192.168.1.125")]


# -- the systemd user service -------------------------------------------------


def test_install_and_remove_service(env, monkeypatch, capsys):
    tmp, _ = env
    calls = []

    def run(cmd, **kw):
        calls.append(cmd[2:])
        return __import__("subprocess").CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(web.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(web, "_command", lambda: ["/opt/tuya light/bin/tuya-light"])
    monkeypatch.setenv("TUYA_ACCESS_SECRET", "cloud-secret-value")
    monkeypatch.setenv("TUYA_REGION", "eu")
    opts = web.Options(port=9000, allow_hosts=("pc.lan",), device="Desk", trust_proxy=True)
    assert web.install_service(opts, run=run) == 0
    unit = (tmp / "xdg" / "systemd" / "user" / web.SERVICE).read_text()
    assert ('ExecStart="/opt/tuya light/bin/tuya-light" -d Desk serve --host 0.0.0.0 --port 9000 '
            "--allow-host pc.lan --trust-proxy") in unit
    assert "Restart=on-failure" in unit and "WantedBy=default.target" in unit
    assert f"Environment=TUYA_LIGHT_CONFIG={tmp}/devices.json" in unit
    assert "Environment=TUYA_REGION=eu" in unit
    assert "cloud-secret-value" not in unit  # unit files are world-readable
    assert calls == [["daemon-reload"], ["enable", web.SERVICE], ["restart", web.SERVICE]]
    assert "disable --now" in capsys.readouterr().out

    calls.clear()
    assert web.remove_service(run=run) == 0
    assert not (tmp / "xdg" / "systemd" / "user" / web.SERVICE).exists()
    assert calls == [["disable", "--now", web.SERVICE], ["daemon-reload"]]


def test_unit_quoting_escapes_systemd_specifiers():
    assert web._sd_quote("/home/a%b/x") == "/home/a%%b/x"
    assert web._sd_quote('say "hi"') == '"say \\"hi\\""'


# -- one bulb, one command at a time ------------------------------------------


class SlowBulb(FakeBulb):
    def __init__(self):
        super().__init__()
        self.gate = threading.Event()
        self.started = threading.Event()

    def set_white_percentage(self, b, t):
        self.started.set()
        self.gate.wait(5)
        return super().set_white_percentage(b, t)


def test_newer_command_replaces_the_waiting_one(monkeypatch):
    slow = SlowBulb()
    monkeypatch.setattr("tuya_light.light.tinytuya.BulbDevice", lambda *a, **kw: slow)
    worker = LightWorker(Device(id="x", name="Desk", key="k"), linger=0.05)
    first = worker.submit(lambda light: light.white(10, 0))
    assert slow.started.wait(2)
    second = worker.submit(lambda light: light.white(20, 0))   # waits...
    third = worker.submit(lambda light: light.white(30, 0))    # ...and is replaced
    slow.gate.set()
    assert first.wait(5).brightness == 10 and first.latest is False
    assert third.wait(5).brightness == 30 and third.latest is True
    assert second.wait(5).brightness == 30  # the dropped caller gets the newer result
    assert [c for c in slow.calls if c[0] == "white"] == [("white", 10, 0), ("white", 30, 0)]
    worker.stop()


def test_reads_share_one_bulb_round_trip(monkeypatch):
    fake = FakeBulb()
    reads = []
    original = fake.status
    monkeypatch.setattr(fake, "status", lambda: reads.append(1) or original())
    monkeypatch.setattr("tuya_light.light.tinytuya.BulbDevice", lambda *a, **kw: fake)
    worker = LightWorker(Device(id="x", name="Desk", key="k"), linger=0.05)
    assert worker.read(max_age=5).wait(5).online
    assert worker.read(max_age=5).wait(5).online
    assert len(reads) == 1
    worker.stop()


def test_worker_survives_a_failing_bulb(monkeypatch):
    def boom(*a, **kw):
        raise OSError("no route to host")

    worker = LightWorker(Device(id="x", name="Desk", key="k"), linger=0.05, light_factory=boom)
    state = worker.read().wait(5)
    assert isinstance(state, State) and not state.online
    fake = FakeBulb()
    monkeypatch.setattr("tuya_light.light.tinytuya.BulbDevice", lambda *a, **kw: fake)
    worker._light_factory = Light
    assert worker.read().wait(5).online
    worker.stop()


def test_bulb_is_let_go_after_a_read_and_kept_briefly_after_a_change(monkeypatch):
    fake = FakeBulb()
    closed = []
    monkeypatch.setattr(fake, "close", lambda: closed.append(time.monotonic()))
    monkeypatch.setattr("tuya_light.light.tinytuya.BulbDevice", lambda *a, **kw: fake)
    worker = LightWorker(Device(id="x", name="Desk", key="k"), linger=0.3)
    worker.read().wait(5)
    time.sleep(0.05)
    assert len(closed) == 1  # right away, not after the pause
    done = time.monotonic()
    worker.submit(lambda light: light.power(False)).wait(5)
    time.sleep(0.1)
    assert len(closed) == 1  # still connected: the next drag value may follow
    time.sleep(0.4)
    assert len(closed) == 2 and closed[1] - done >= 0.3
    worker.stop()


# -- behind a reverse proxy -----------------------------------------------------


@pytest.fixture
def proxied(env):
    tmp, _ = env
    server = web.PhoneServer(("127.0.0.1", 0), keys=web.KeyStore(tmp / "web.key"), linger=0.05,
                             bad_key_delay=0, log=lambda line: None, trust_proxy=True,
                             allow_hosts=("light.example.com",))
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    yield Client(server)
    server.shutdown()
    server.server_close()


def test_forwarded_headers_are_ignored_unless_trusted(client):
    res, _ = client.get(f"/?key={client.key}", cookie=False,
                        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "evil.example"})
    assert res.status == 303 and "Secure" not in res.getheader("Set-Cookie")


def test_trusted_proxy_gives_host_scheme_and_secure_cookie(proxied):
    fwd = {"Host": "127.0.0.1:8892", "X-Forwarded-Host": "light.example.com",
           "X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.9"}
    res, _ = proxied.get(f"/?key={proxied.key}", cookie=False, headers=fwd)
    assert res.status == 303 and "; Secure" in res.getheader("Set-Cookie")
    res, state = proxied.post("/api/power", {"on": False}, headers=fwd,
                              origin="https://light.example.com")
    assert res.status == 200 and state["on"] is False
    # the origin must match what the proxy says the page is
    assert proxied.post("/api/power", {"on": True}, headers=fwd,
                        origin="http://127.0.0.1:8892")[0].status == 403
    bad = dict(fwd, **{"X-Forwarded-Host": "evil.example"})
    assert proxied.get("/api/state", headers=bad)[0].status == 403

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tuya_light import cli, config, shared, web
from tuya_light import scenes as store
from tuya_light.config import ConfigError


@pytest.fixture
def two(tmp_path, monkeypatch):
    """Two installs in one process: `hub` (runs serve) and `pc` (linked to it).
    Their paths come from the environment, so `use()` switches between them,
    and the network between them is a direct call into the hub."""
    dirs = {"hub": tmp_path / "hub", "pc": tmp_path / "pc"}
    for d in dirs.values():
        d.mkdir()
        (d / "devices.json").write_text(json.dumps([{"id": "bf01", "name": "Desk", "key": "k"}]))
        (d / "devices.json").chmod(0o600)
    monkeypatch.setattr(web, "tailscale_name", lambda: None)

    def use(name):
        monkeypatch.setenv("TUYA_LIGHT_CONFIG", str(dirs[name] / "devices.json"))
        monkeypatch.setenv("TUYA_LIGHT_SCENES", str(dirs[name] / "scenes.json"))
        monkeypatch.setenv("TUYA_LIGHT_SETTINGS", str(dirs[name] / "settings.json"))

    calls = []

    def network(link, path, body, timeout=5.0):
        calls.append(json.loads(json.dumps(body)))
        use("hub")
        try:
            answer = json.loads(json.dumps(shared.hub_sync(body["base"], body["changes"])))
        finally:
            use("pc")
        return answer

    monkeypatch.setattr(shared, "_post", network)
    use("pc")

    class Two:
        pass

    t = Two()
    t.use, t.dirs, t.calls = use, dirs, calls
    return t


def touch(path, when):
    os.utime(path, (when, when))


def link(two, **kw):
    return shared.link("https://lights.example.com/?key=secret-key-123", {}, **kw)


# -- linking and the sync rules -------------------------------------------------


def test_first_link_takes_this_installs_customisations_up(two):
    store.save("Cinema", "colour", name="movie", hue=200, brightness=12)  # relabelled built-in
    for name in ("focus", "night", "party", "reading"):
        store.set_hidden(name, True)
    shared.set_favourites(["#FF0000", "00ff00"])
    result = link(two)
    assert result["pushed"] == 6 and result["server"] == "lights.example.com"
    two.use("hub")
    names = [s.name for s in store.load()]
    assert names == ["relax", "movie"]  # the four hidden ones stay hidden on the hub
    assert store.get("movie").label == "Cinema"
    assert shared.favourites() == ["#ff0000", "#00ff00"]
    two.use("pc")
    assert oct(shared.link_path().stat().st_mode & 0o777) == "0o600"


def test_changes_flow_both_ways(two):
    link(two)
    store.save("Reading nook", "white", temperature=30, brightness=80)
    shared.sync()
    two.use("hub")
    assert store.get("reading-nook").brightness == 80
    shared.set_device_name("bf01", "Desk lamp")  # an edit made on the hub itself
    store.save("Sunset", "colour", hue=18, brightness=70)
    two.use("pc")
    shared.sync()
    assert [d.name for d in config.load()] == ["Desk lamp"]
    assert [s.name for s in store.load()][-2:] == ["reading-nook", "sunset"]  # the hub's order


def test_both_changed_the_same_scene_later_edit_wins(two):
    link(two)
    store.save("Evening", "white", temperature=10)
    shared.sync()
    two.use("hub")
    store.save("Evening", "white", temperature=90)
    touch(store.scenes_path(), time.time() + 100)  # the hub's edit is the later one
    two.use("pc")
    store.save("Evening", "white", temperature=40)
    touch(store.scenes_path(), time.time())
    shared.sync()
    assert store.get("evening").temperature == 90
    # and the other way round
    store.save("Evening", "white", temperature=55)
    touch(store.scenes_path(), time.time() + 500)
    two.use("hub")
    store.save("Evening", "white", temperature=5)
    touch(store.scenes_path(), time.time() + 200)
    two.use("pc")
    shared.sync()
    assert store.get("evening").temperature == 55
    two.use("hub")
    assert store.get("evening").temperature == 55


def test_different_items_never_conflict(two):
    link(two)
    store.save("Mine", "white", temperature=20)
    two.use("hub")
    store.save("Theirs", "colour", hue=100)
    touch(store.scenes_path(), time.time() + 100)
    two.use("pc")
    shared.sync()
    assert {"mine", "theirs"} <= {s.name for s in store.load()}


def test_deletes_and_resets_travel(two):
    store.save("Temp", "white")
    store.set_hidden("party", True)
    link(two)
    two.use("hub")
    store.remove("temp")
    store.reset("party")
    two.use("pc")
    shared.sync()
    names = [s.name for s in store.load()]
    assert "temp" not in names and "party" in names


def test_replace_local_takes_the_other_copy(two):
    two.use("hub")
    store.save("Hub scene", "white")
    two.use("pc")
    store.save("Pc scene", "white")
    link(two, replace_local=True)
    names = {s.name for s in store.load(include_hidden=True)}
    assert "hub-scene" in names and "pc-scene" not in names


def test_offline_works_from_the_local_copy_and_sends_later(two, monkeypatch, capsys):
    link(two)
    good = shared._post

    def down(*a, **kw):
        raise shared.SyncError("cannot reach lights.example.com: timed out")

    monkeypatch.setattr(shared, "_post", down)
    store.save("Offline edit", "white", brightness=33)
    shared.maybe_sync(force=True)  # never raises
    assert "using the local copy" in capsys.readouterr().err
    assert store.get("offline-edit").brightness == 33
    assert shared.status()["pending"] is True
    # a failed attempt is not retried on every command, even when a read is due
    found = shared.load_link()
    found["synced_at"] = 0
    shared._save_link(found)
    tried = []
    monkeypatch.setattr(shared, "_post", lambda *a, **kw: tried.append(1) or down())
    shared.maybe_sync()
    assert tried == []
    # back online: the edit goes up
    monkeypatch.setattr(shared, "_post", good)
    shared.sync()
    two.use("hub")
    assert store.get("offline-edit").brightness == 33


def test_reads_sync_at_most_once_a_minute(two):
    link(two)
    before = len(two.calls)
    shared.maybe_sync()
    assert len(two.calls) == before  # synced just now
    found = shared.load_link()
    found["synced_at"] = time.time() - shared.PULL_EVERY - 1
    shared._save_link(found)
    shared.maybe_sync()
    assert len(two.calls) == before + 1


def test_cli_commands_sync_around_reads_and_writes(two, capsys):
    link(two)
    before = len(two.calls)
    assert cli.main(["--json", "scene-save", "Late", "--white", "20"]) == 0
    assert len(two.calls) == before + 1  # sent right away
    two.use("hub")
    assert store.get("late").temperature == 20
    store.save("From hub", "white")
    two.use("pc")
    found = shared.load_link()
    found["synced_at"] = 0
    shared._save_link(found)
    capsys.readouterr()
    assert cli.main(["--json", "scenes"]) == 0
    assert "from-hub" in [s["name"] for s in json.loads(capsys.readouterr().out)]


def test_hub_refuses_to_be_a_hub_when_linked(two):
    link(two)
    with pytest.raises(shared.SyncError, match="linked to another"):
        shared.hub_sync(0, [])


def test_bad_items_are_dropped_both_ways(two):
    two.use("hub")
    answer = shared.hub_sync(0, [
        {"key": "scene:x", "value": {"name": "y", "mode": "white"}, "stamp": 1},  # name mismatch
        {"key": "favourites", "value": ["red"], "stamp": 1},                      # not #rrggbb
        {"key": "evil", "value": "x", "stamp": 1},
        {"key": "name:bf01", "value": "Desk lamp", "stamp": 1},
    ])
    assert answer["items"] == {"name:bf01": "Desk lamp"}


# -- favourites ------------------------------------------------------------------


def test_widget_hands_its_favourites_over_once(two, capsys):
    assert shared.favourites() is None
    assert cli.main(["--json", "favourites-set", "--if-unset", "#ff0000", "blue"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first[0] == "#ff0000" and first[1].startswith("#00") and first[1].endswith("ff")
    # set elsewhere since: a second hand-over changes nothing
    assert cli.main(["--json", "favourites-set", "--if-unset", "#123456"]) == 0
    assert json.loads(capsys.readouterr().out) == first
    assert cli.main(["--json", "favourites-set"]) == 0  # chosen: none
    assert json.loads(capsys.readouterr().out) == []
    assert cli.main(["--json", "favourites"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    with pytest.raises(ConfigError):
        shared.set_favourites(["#12345"])


def test_rename_and_names_on_the_phone_page(two, capsys):
    assert cli.main(["--json", "rename", "Desk", "Reading lamp"]) == 0
    assert json.loads(capsys.readouterr().out) == {"id": "bf01", "name": "Reading lamp"}
    assert config.pick(config.load(), "Reading lamp").id == "bf01"
    assert cli.main(["--json", "rename", "bf01"]) == 0  # back to its own name
    assert json.loads(capsys.readouterr().out)["name"] == "Desk"


# -- talking to a server behind a proxy ------------------------------------------


class Stub:
    """A stand-in for the other install (or the proxy in front of it)."""

    def __init__(self, status=200, body=None, location=None):
        seen = self.seen = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append({k.lower(): v for k, v in self.headers.items()})
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                data = json.dumps(stub.body).encode() if stub.body is not None else b"<html>login</html>"
                self.send_response(stub.status)
                if stub.location:
                    self.send_header("Location", stub.location)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.status, self.body, self.location = status, body, location
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/?key=the-pairing-key"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def pc(tmp_path, monkeypatch):
    monkeypatch.setenv("TUYA_LIGHT_CONFIG", str(tmp_path / "devices.json"))
    monkeypatch.setenv("TUYA_LIGHT_SCENES", str(tmp_path / "scenes.json"))
    monkeypatch.setenv("TUYA_LIGHT_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.delenv("TUYA_LIGHT_LINK_HEADERS", raising=False)
    return tmp_path


def test_proxy_headers_are_sent_kept_private_and_never_shown(pc, monkeypatch, capsys):
    stub = Stub(body={"rev": 1, "items": {}})
    try:
        assert cli.main(["link", stub.url, "--header", "CF-Access-Client-Id: id.access",
                         "--header", "CF-Access-Client-Secret: very-secret-value"]) == 0
        out = capsys.readouterr()
        assert "very-secret-value" not in out.out + out.err and "the-pairing-key" not in out.out
        sent = stub.seen[-1]
        assert sent["cf-access-client-id"] == "id.access"
        assert sent["cf-access-client-secret"] == "very-secret-value"
        assert sent["authorization"] == "Bearer the-pairing-key"
        saved = shared.link_path()
        assert oct(saved.stat().st_mode & 0o777) == "0o600"
        assert json.loads(saved.read_text())["headers"]["CF-Access-Client-Secret"] == "very-secret-value"
        # containers: the environment adds or overrides headers
        monkeypatch.setenv("TUYA_LIGHT_LINK_HEADERS",
                           "CF-Access-Client-Secret: from-env; X-Extra: 1")
        shared.sync()
        assert stub.seen[-1]["cf-access-client-secret"] == "from-env"
        assert stub.seen[-1]["x-extra"] == "1"
        assert cli.main(["--json", "sync", "--status"]) == 0
        status = capsys.readouterr().out
        assert "from-env" not in status and "very-secret-value" not in status
    finally:
        stub.close()


def test_a_login_redirect_means_proxy_headers_are_missing(pc, capsys):
    stub = Stub(status=302, location="https://team.example.com/cdn-cgi/access/login")
    try:
        assert cli.main(["link", stub.url]) == 3
        err = capsys.readouterr().err
        assert "redirect" in err and "--header" in err
        assert not shared.link_path().exists()  # nothing saved when the first sync fails
    finally:
        stub.close()


def test_refusals_are_explained(pc):
    for status, body, words in ((401, {"error": "this phone is not paired"}, "did not accept the key"),
                                (403, None, "service-token headers"),
                                (409, {"error": "this install is itself linked"}, "itself linked")):
        stub = Stub(status=status, body=body)
        try:
            with pytest.raises(shared.SyncError, match=words):
                shared.link(stub.url, {})
        finally:
            stub.close()


def test_unreachable_and_bad_links(pc):
    with pytest.raises(ConfigError, match="pairing link"):
        shared.link("https://lights.example.com/", {})
    with pytest.raises(shared.SyncError, match="cannot reach"):
        shared.link("http://127.0.0.1:9/?key=k", {}, timeout=1)
    with pytest.raises(ConfigError):
        shared.parse_headers(["no colon here"])
    with pytest.raises(ConfigError):
        shared.parse_headers(["Bad Name: x"])

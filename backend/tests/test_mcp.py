import asyncio
import json

import pytest

pytest.importorskip("mcp")

from tuya_light.mcp_server import build_server  # noqa: E402

from test_light import FakeBulb  # noqa: E402


@pytest.fixture
def server(tmp_path, monkeypatch):
    path = tmp_path / "devices.json"
    path.write_text(json.dumps([{"id": "abc", "name": "Desk", "key": "k", "ip": "10.0.0.5"}]))
    monkeypatch.setenv("TUYA_LIGHT_CONFIG", str(path))
    bulb = FakeBulb()
    monkeypatch.setattr("tuya_light.light.tinytuya.BulbDevice", lambda *a, **kw: bulb)
    return build_server(), bulb


def call(server, name, **args):
    result = asyncio.run(server.call_tool(name, args))
    # mcp 2.x: CallToolResult; mcp 1.x: (content, structured) or content alone.
    if hasattr(result, "content"):
        assert not getattr(result, "isError", False), result.content[0].text
        content = result.content
    else:
        content = result[0] if isinstance(result, tuple) else result
    return json.loads(content[0].text)


def test_tools_are_listed(server):
    srv, _ = server
    names = {t.name for t in asyncio.run(srv.list_tools())}
    assert {"get_state", "turn_on", "turn_off", "toggle", "set_colour", "set_white",
            "set_brightness", "apply_scene", "list_devices", "list_scenes"} <= names


def test_set_colour_by_name_returns_state(server):
    srv, bulb = server
    state = call(srv, "set_colour", colour="blue", brightness=40)
    assert state["mode"] == "colour" and state["hue"] == 230 and state["value"] == 40


def test_set_white_keeps_temperature(server):
    srv, bulb = server
    call(srv, "set_white", brightness=80)
    assert bulb.calls[-1] == ("white", 80, 30)


def test_scene_and_device_by_name(server):
    srv, bulb = server
    state = call(srv, "apply_scene", scene="night", device="Desk")
    assert state["mode"] == "colour" and state["value"] == 6


def test_save_scene_from_current_light_then_apply(server, tmp_path, monkeypatch):
    monkeypatch.setenv("TUYA_LIGHT_SCENES", str(tmp_path / "scenes.json"))
    srv, bulb = server
    bulb.mode, bulb.hsv = "colour", (0.5, 1.0, 0.4)
    saved = call(srv, "save_scene", label="Evening")
    assert (saved["name"], saved["mode"], saved["hue"], saved["brightness"]) == ("evening", "colour", 180, 40)
    names = [s["name"] for s in call_list(srv, "list_scenes")]
    assert "evening" in names
    state = call(srv, "apply_scene", scene="Evening")
    assert state["hue"] == 180
    assert call(srv, "remove_scene", scene="evening")["result"] == "removed"


def call_list(server, name, **args):
    result = asyncio.run(server.call_tool(name, args))
    if hasattr(result, "structuredContent") and result.structuredContent:
        data = result.structuredContent
        return data.get("result", data)
    content = result.content if hasattr(result, "content") else (result[0] if isinstance(result, tuple) else result)
    return [json.loads(c.text) for c in content]

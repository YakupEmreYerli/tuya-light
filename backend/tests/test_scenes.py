import json

import pytest

from tuya_light import cli
from tuya_light import scenes as store
from tuya_light.config import ConfigError

from test_light import FakeBulb  # noqa: F401  (fixtures below reuse its shape)


@pytest.fixture(autouse=True)
def scenes_file(tmp_path, monkeypatch):
    path = tmp_path / "scenes.json"
    monkeypatch.setenv("TUYA_LIGHT_SCENES", str(path))
    return path


def test_builtins_without_a_file():
    assert [s.name for s in store.load()] == ["relax", "reading", "focus", "movie", "night", "party"]


def test_slug_folds_turkish():
    assert store.slug("Kitap Okuma Işığı") == "kitap-okuma-isigi"
    assert store.slug("  !!  ") == "scene"


def test_save_new_scene_and_find_by_label(scenes_file):
    store.save("Kitap", "white", brightness=80, temperature=30)
    sc = store.get("kitap")
    assert (sc.label, sc.mode, sc.brightness, sc.temperature, sc.builtin) == ("Kitap", "white", 80, 30, False)
    assert store.get("KITAP").name == "kitap"
    # only the difference is stored
    assert json.loads(scenes_file.read_text()) == [{
        "name": "kitap", "label": "Kitap", "mode": "white", "brightness": 80,
        "temperature": 30, "hue": 0, "saturation": 100, "hidden": False}]


def test_values_are_clamped():
    sc = store.save("Loud", "colour", hue=400, saturation=-5, brightness=150)
    assert (sc.hue, sc.saturation, sc.brightness) == (360, 0, 100)


def test_edit_builtin_then_reset():
    store.save("Cinema", "colour", name="movie", hue=200, brightness=10)
    sc = store.get("movie")
    assert sc.builtin and sc.label == "Cinema" and sc.hue == 200
    store.reset("movie")
    assert store.get("movie").label == "Movie"


def test_remove_hides_builtin_and_deletes_own():
    store.save("Mine", "white")
    assert store.remove("mine") == "removed"
    with pytest.raises(ConfigError):
        store.get("mine")
    assert store.remove("party") == "hidden"
    assert "party" not in [s.name for s in store.load()]
    assert store.get("party").hidden
    store.set_hidden("party", False)
    assert "party" in [s.name for s in store.load()]


def test_bad_mode_is_refused():
    with pytest.raises(ConfigError):
        store.save("X", "disco")


def test_cli_scene_save_list_and_remove(capsys):
    assert cli.main(["--json", "scene-save", "Akşam", "--colour", "orange", "--brightness", "40"]) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["name"] == "aksam" and saved["hue"] == 30 and saved["brightness"] == 40
    assert cli.main(["--json", "scenes"]) == 0
    names = [s["name"] for s in json.loads(capsys.readouterr().out)]
    assert names[-1] == "aksam"
    assert cli.main(["scene-remove", "aksam"]) == 0


def test_cli_scene_save_white_and_hue_sat(capsys):
    cli.main(["--json", "scene-save", "Warm", "--white", "10"])
    assert json.loads(capsys.readouterr().out)["temperature"] == 10
    cli.main(["--json", "scene-save", "Teal", "--colour", "180 60"])
    out = json.loads(capsys.readouterr().out)
    assert (out["hue"], out["saturation"]) == (180, 60)

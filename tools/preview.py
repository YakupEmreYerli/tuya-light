#!/usr/bin/python3
"""Render the widget's popup to PNG files without opening a window.

The popup is drawn off-screen (QT_QPA_PLATFORM=offscreen) against a fake
backend, once per state, so screenshots never depend on a real bulb and never
steal focus on the desktop. Needs the system PySide6 (same Qt as Plasma).

    tools/preview.py OUTDIR [--scale 2] [--dark|--light]
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "plasma" / "contents" / "ui"

STATES = {
    "colour": {"online": True, "on": True, "mode": "colour", "name": "Desk lamp",
               "hue": 275, "saturation": 85, "value": 70, "brightness": 70, "temperature": 20},
    "white": {"online": True, "on": True, "mode": "white", "name": "Desk lamp",
              "hue": 30, "saturation": 60, "value": 100, "brightness": 45, "temperature": 12},
    "offline": {"online": False, "name": "Desk lamp", "error": "Network Error: Device Unreachable"},
    "setup": {"config": True},
}

SCENES = [
    {"name": "relax", "label": "Relax", "mode": "white", "brightness": 45, "temperature": 0, "hue": 0, "saturation": 100, "builtin": True, "hidden": False},
    {"name": "reading", "label": "Reading", "mode": "white", "brightness": 100, "temperature": 55, "hue": 0, "saturation": 100, "builtin": True, "hidden": False},
    {"name": "focus", "label": "Focus", "mode": "white", "brightness": 100, "temperature": 100, "hue": 0, "saturation": 100, "builtin": True, "hidden": False},
    {"name": "movie", "label": "Movie", "mode": "colour", "brightness": 18, "temperature": 0, "hue": 255, "saturation": 85, "builtin": True, "hidden": False},
    {"name": "night", "label": "Night", "mode": "colour", "brightness": 6, "temperature": 0, "hue": 25, "saturation": 100, "builtin": True, "hidden": False},
    {"name": "sunset", "label": "Sunset", "mode": "colour", "brightness": 70, "temperature": 0, "hue": 18, "saturation": 90, "builtin": False, "hidden": False},
]

CONFIG = {
    "sections": ["wheel", "brightness", "temperature", "scenes"],
    "wheelSize": 12, "sceneColumns": 3,
    "favoriteColours": ["#ff3b30", "#ff9500", "#ffcc00", "#34c759", "#00c7be", "#0a84ff", "#8e5cff", "#ff2d92"],
    "iconStyle": "bulb", "tintIcon": True, "dimWhenOff": True, "showPercent": False,
    "leftClick": "popup", "middleClick": "toggle", "wheelAction": "brightness", "wheelStep": 5,
}

# The popup sits on Plasma's own dialog frame (dialogs/background from the
# current Plasma theme), so corners, border and shadow match the real thing.
WRAPPER = """
import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.ksvg as KSvg
import "file://%(ui)s" as Ui

Item {
    id: stage
    width: frame.width + 2 * pad
    height: frame.height + 2 * pad
    readonly property int pad: Kirigami.Units.gridUnit

    QtObject {
        id: fake
        property var light: previewState.config ? ({}) : previewState
        property var devices: previewDevices
        property var scenes: previewScenes
        property var allScenes: previewScenes
        property bool busy: false
        property bool loaded: !previewState.config
        property bool needsSetup: previewState.config === true
        property bool missingBackend: false
        property string error: previewState.config ? "no device list" : (previewState.error || "")
        property string device: ""
        readonly property bool online: loaded && light.online === true
        function send(args) {}
        function refresh() {}
        function listDevices() {}
        function listScenes() {}
        function quote(s) { return "'" + s + "'" }
    }
    QtObject {
        id: fakeRoot
        property bool expanded: true
        function reload() {}
        function selectDevice(id) {}
    }

    KSvg.FrameSvgItem {
        id: frame
        x: stage.pad
        y: stage.pad
        imagePath: "dialogs/background"
        width: popup.Layout.preferredWidth + margins.left + margins.right
        height: Math.max(popup.Layout.preferredHeight, Kirigami.Units.gridUnit * 16) + margins.top + margins.bottom

        Ui.FullRepresentation {
            id: popup
            anchors.fill: parent
            anchors.leftMargin: frame.margins.left
            anchors.rightMargin: frame.margins.right
            anchors.topMargin: frame.margins.top
            anchors.bottomMargin: frame.margins.bottom
            backend: fake
            root: fakeRoot
            cfg: previewConfig
        }
    }
}
"""


# A settings page on a plain window background, the way the widget's
# configuration dialog shows it.
CONFIG_WRAPPER = """
import QtQuick
import org.kde.kirigami as Kirigami

Rectangle {
    width: Kirigami.Units.gridUnit * 34
    height: Kirigami.Units.gridUnit * 28
    color: Kirigami.Theme.backgroundColor
    Kirigami.Theme.colorSet: Kirigami.Theme.Window
    Loader {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.largeSpacing
        source: "file://%(ui)s/%(page)s.qml"
        onLoaded: {
            // What Plasma's config dialog does: fill every cfg_ property it declares.
            for (const key in previewConfig) {
                if (("cfg_" + key) in item) item["cfg_" + key] = previewConfig[key]
            }
        }
    }
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir", type=Path)
    ap.add_argument("--scale", default="2")
    ap.add_argument("--states", nargs="*", default=list(STATES))
    ap.add_argument("--devices", type=int, default=1, help="how many devices to pretend")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=JSON",
                    help="override a widget setting, e.g. --set 'sections=[\"brightness\",\"scenes\"]'")
    ap.add_argument("--suffix", default="", help="added to output file names")
    ap.add_argument("--config", nargs="*", default=None, metavar="PAGE",
                    help="render settings pages instead (configAppearance, configBehaviour, ...)")
    args = ap.parse_args()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QPA_PLATFORMTHEME", "kde")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    os.environ["QT_FORCE_STDERR_LOGGING"] = "1"  # QML errors to the terminal, not the journal
    os.environ["QT_SCALE_FACTOR"] = args.scale

    from PySide6.QtCore import QObject, QTimer, QUrl, Slot
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtQuick import QQuickView

    class Ki18n(QObject):
        """Stands in for KLocalizedContext: English text, %1..%n filled in."""

        @staticmethod
        def _fill(text, *subs):
            for i, sub in enumerate(subs, 1):
                if isinstance(sub, float) and sub.is_integer():
                    sub = int(sub)
                text = text.replace(f"%{i}", str(sub))
            return text

        @Slot(str, result=str)
        @Slot(str, "QVariant", result=str)
        @Slot(str, "QVariant", "QVariant", result=str)
        def i18n(self, text, *subs):
            return self._fill(text, *subs)

        @Slot(str, str, result=str)
        @Slot(str, str, "QVariant", result=str)
        def i18nc(self, _ctx, text, *subs):
            return self._fill(text, *subs)

        @Slot(str, str, "QVariant", result=str)
        def i18np(self, one, many, n):
            return self._fill(one if int(n) == 1 else many, n)

        @Slot(str, str, result=str)
        @Slot(str, str, "QVariant", result=str)
        def i18nd(self, _domain, text, *subs):
            return self._fill(text, *subs)

    app = QGuiApplication(sys.argv)
    args.outdir.mkdir(parents=True, exist_ok=True)
    wrapper = args.outdir / ".preview.qml"
    wrapper.write_text(WRAPPER % {"ui": UI})
    ki18n = Ki18n()
    devices = [{"id": f"d{i}", "name": n} for i, n in
               enumerate(["Desk lamp", "Ceiling", "Hall"][: args.devices])]

    import json as _json
    cfg = dict(CONFIG)
    for item in args.set:
        key, _, value = item.partition("=")
        cfg[key] = _json.loads(value)

    queue = list(args.states) if args.config is None else ["config:" + p for p in args.config]
    failures = []

    def render_next():
        if not queue:
            wrapper.unlink(missing_ok=True)
            app.exit(1 if failures else 0)
            return
        name = queue.pop(0)
        view = QQuickView()
        view.setColor(QColor(0, 0, 0, 0))
        ctx = view.rootContext()
        ctx.setContextObject(ki18n)
        ctx.setContextProperty("previewState", STATES.get(name, {}))
        ctx.setContextProperty("previewDevices", devices)
        ctx.setContextProperty("previewScenes", SCENES)
        ctx.setContextProperty("previewConfig", cfg)
        source = wrapper
        if name.startswith("config:"):
            source = args.outdir / ".config-preview.qml"
            source.write_text(CONFIG_WRAPPER % {"ui": UI, "page": name[7:]})
            name = name[7:]
        view.setSource(QUrl.fromLocalFile(str(source)))
        if view.status() != QQuickView.Status.Ready:
            for err in view.errors():
                print(err.toString(), file=sys.stderr)
            failures.append(name)
            QTimer.singleShot(0, render_next)
            return
        view.show()

        def fit():
            root = view.rootObject()
            view.resize(int(root.width()), int(root.height()))
            QTimer.singleShot(400, grab)

        def grab():
            out = args.outdir / f"{name}{args.suffix}.png"
            view.grabWindow().save(str(out))
            print(out)
            view.close()
            view.deleteLater()
            render_next()

        QTimer.singleShot(2500 if name in (args.config or []) else 700, fit)

    QTimer.singleShot(0, render_next)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

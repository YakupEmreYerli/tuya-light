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

WRAPPER = """
import QtQuick
import org.kde.kirigami as Kirigami
import "file://%(ui)s" as Ui

Rectangle {
    id: stage
    width: Kirigami.Units.gridUnit * 18
    height: Kirigami.Units.gridUnit * 24
    color: Kirigami.Theme.backgroundColor
    Kirigami.Theme.colorSet: Kirigami.Theme.View

    QtObject {
        id: fake
        property var light: previewState.config ? ({}) : previewState
        property var devices: previewDevices
        property bool busy: false
        property bool loaded: !previewState.config
        property bool needsSetup: previewState.config === true
        property bool missingBackend: false
        property string error: previewState.config ? "no device list" : (previewState.error || "")
        property string device: ""
        readonly property bool online: loaded && light.online === true
        function send(args) { console.log("send", args) }
        function refresh() {}
        function listDevices() {}
    }
    QtObject {
        id: fakeRoot
        property bool expanded: true
        function reload() {}
        function selectDevice(id) {}
    }

    Ui.FullRepresentation {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.largeSpacing
        backend: fake
        root: fakeRoot
    }
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir", type=Path)
    ap.add_argument("--scale", default="2")
    ap.add_argument("--states", nargs="*", default=list(STATES))
    ap.add_argument("--devices", type=int, default=1, help="how many devices to pretend")
    args = ap.parse_args()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QPA_PLATFORMTHEME", "kde")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    os.environ["QT_SCALE_FACTOR"] = args.scale

    from PySide6.QtCore import QObject, QTimer, QUrl, Slot
    from PySide6.QtGui import QGuiApplication
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

    queue = list(args.states)
    failures = []

    def render_next():
        if not queue:
            wrapper.unlink(missing_ok=True)
            app.exit(1 if failures else 0)
            return
        name = queue.pop(0)
        view = QQuickView()
        ctx = view.rootContext()
        ctx.setContextObject(ki18n)
        ctx.setContextProperty("previewState", STATES[name])
        ctx.setContextProperty("previewDevices", devices)
        view.setSource(QUrl.fromLocalFile(str(wrapper)))
        if view.status() != QQuickView.Status.Ready:
            for err in view.errors():
                print(err.toString(), file=sys.stderr)
            failures.append(name)
            QTimer.singleShot(0, render_next)
            return
        view.show()

        def grab():
            out = args.outdir / f"{name}.png"
            view.grabWindow().save(str(out))
            print(out)
            view.close()
            view.deleteLater()
            render_next()

        QTimer.singleShot(900, grab)

    QTimer.singleShot(0, render_next)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

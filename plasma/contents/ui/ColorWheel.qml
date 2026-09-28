/*
    SPDX-FileCopyrightText: 2026 Yakup Emre Yerli
    SPDX-License-Identifier: GPL-2.0-or-later
*/

// Hue around the circle, saturation from the centre out. Hue 0 (red) sits at
// three o'clock and runs clockwise, the same way the knob is placed, so the
// drawing and the picking can never disagree.

import QtQuick
import org.kde.kirigami as Kirigami

Item {
    id: wheel

    property real hue: 0          // 0-360
    property real saturation: 0   // 0-100
    property bool dimmed: false

    signal picked(real hue, real saturation)   // while dragging
    signal released(real hue, real saturation) // on release

    implicitWidth: Kirigami.Units.gridUnit * 11
    implicitHeight: implicitWidth

    readonly property real radius: Math.min(width, height) / 2
    readonly property real ring: radius - Kirigami.Units.smallSpacing

    Canvas {
        id: canvas
        anchors.fill: parent
        opacity: wheel.dimmed ? 0.45 : 1
        Behavior on opacity { NumberAnimation { duration: Kirigami.Units.shortDuration } }
        renderStrategy: Canvas.Cooperative
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()

        onPaint: {
            const ctx = getContext("2d")
            const cx = width / 2, cy = height / 2, r = wheel.ring
            ctx.reset()
            for (let h = 0; h < 360; h += 1) {
                ctx.beginPath()
                ctx.moveTo(cx, cy)
                ctx.arc(cx, cy, r, (h - 0.6) * Math.PI / 180, (h + 1.2) * Math.PI / 180, false)
                ctx.closePath()
                ctx.fillStyle = Qt.hsla(h / 360, 1, 0.5, 1)
                ctx.fill()
            }
            const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r)
            g.addColorStop(0, "white")
            g.addColorStop(1, Qt.rgba(1, 1, 1, 0))
            ctx.beginPath()
            ctx.arc(cx, cy, r, 0, 2 * Math.PI)
            ctx.fillStyle = g
            ctx.fill()
        }
    }

    Rectangle {
        id: knob
        readonly property real dist: wheel.ring * Math.min(1, wheel.saturation / 100)
        readonly property real angle: wheel.hue * Math.PI / 180
        width: Kirigami.Units.gridUnit * 1.2
        height: width
        radius: width / 2
        x: wheel.width / 2 + Math.cos(angle) * dist - width / 2
        y: wheel.height / 2 + Math.sin(angle) * dist - height / 2
        color: Qt.hsva(wheel.hue / 360, wheel.saturation / 100, 1, 1)
        border.width: 3
        border.color: "white"
        visible: !wheel.dimmed

        Rectangle {
            anchors.fill: parent
            anchors.margins: -1
            radius: width / 2
            color: "transparent"
            border.width: 1
            border.color: Qt.rgba(0, 0, 0, 0.35)
        }
    }

    MouseArea {
        anchors.fill: parent
        preventStealing: true

        function pick(mx, my) {
            const dx = mx - wheel.width / 2, dy = my - wheel.height / 2
            let h = Math.atan2(dy, dx) * 180 / Math.PI
            if (h < 0) {
                h += 360
            }
            const s = Math.min(100, Math.sqrt(dx * dx + dy * dy) / wheel.ring * 100)
            wheel.hue = Math.round(h)
            wheel.saturation = Math.round(s)
        }

        onPressed: mouse => { pick(mouse.x, mouse.y); wheel.picked(wheel.hue, wheel.saturation) }
        onPositionChanged: mouse => {
            if (pressed) {
                pick(mouse.x, mouse.y)
                wheel.picked(wheel.hue, wheel.saturation)
            }
        }
        onReleased: wheel.released(wheel.hue, wheel.saturation)
    }
}

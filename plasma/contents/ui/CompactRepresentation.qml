/*
    SPDX-FileCopyrightText: 2026 Yakup Emre Yerli
    SPDX-License-Identifier: GPL-2.0-or-later
*/

// Panel icon. What clicks and the wheel do, and how it looks, come from the
// Behaviour and Appearance settings.

import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PC3

MouseArea {
    id: compact

    required property var backend
    required property var root
    required property var cfg

    readonly property var light: backend.light
    readonly property bool isOn: backend.online && light.on === true
    readonly property int level: light.mode === "colour" ? (light.value || 0) : (light.brightness || 0)

    SceneInfo { id: sceneInfo }

    readonly property color lightColour: {
        if (!isOn || !cfg.tintIcon) {
            return Kirigami.Theme.textColor
        }
        if (light.mode === "colour") {
            return Qt.hsva((light.hue || 0) / 360, Math.max(0.35, (light.saturation || 0) / 100), 1, 1)
        }
        return sceneInfo.whiteColour(light.temperature || 0)
    }

    readonly property string iconFile: ({
        bulb: "tuya-light-symbolic.svg",
        "bulb-filled": "tuya-light-bulb-filled-symbolic.svg",
        lamp: "tuya-light-lamp-symbolic.svg",
        star: "tuya-light-star-symbolic.svg",
    })[cfg.iconStyle] || "tuya-light-symbolic.svg"

    Layout.minimumWidth: row.implicitWidth
    Layout.preferredWidth: row.implicitWidth

    acceptedButtons: Qt.LeftButton | Qt.MiddleButton
    hoverEnabled: true

    function act(action, scene) {
        if (action === "popup") {
            root.expanded = !wasExpanded
        } else if (action === "toggle") {
            backend.send("toggle")
        } else if (action === "scene" && scene) {
            backend.send("scene " + backend.quote(scene))
        }
    }

    property bool wasExpanded: false
    onPressed: mouse => { wasExpanded = root.expanded }
    onClicked: mouse => {
        if (mouse.button === Qt.MiddleButton) {
            act(cfg.middleClick, cfg.middleScene)
        } else {
            act(cfg.leftClick, cfg.leftScene)
        }
    }

    property real wheelDelta: 0
    onWheel: wheel => {
        if (!backend.online || cfg.wheelAction === "none") {
            return
        }
        wheelDelta += wheel.angleDelta.y * (cfg.invertWheel ? -1 : 1)
        const steps = Math.trunc(wheelDelta / 120)
        if (steps === 0) {
            return
        }
        wheelDelta -= steps * 120
        const step = steps * cfg.wheelStep
        const clamp = v => Math.max(1, Math.min(100, v))
        if (cfg.wheelAction === "temperature") {
            backend.send("temperature " + Math.max(0, Math.min(100, (light.temperature || 0) + step)))
        } else if (cfg.wheelAction === "hue") {
            const h = (((light.hue || 0) + step * 3) % 360 + 360) % 360
            backend.send("colour %1 %2 %3".arg(h).arg(Math.max(light.saturation || 0, 60)).arg(Math.max(level, 5)))
        } else {
            backend.send("brightness " + clamp(level + step))
        }
    }

    RowLayout {
        id: row
        anchors.fill: parent
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Icon {
            Layout.fillHeight: true
            Layout.preferredWidth: height
            source: Qt.resolvedUrl("../icons/" + compact.iconFile)
            isMask: true
            color: compact.lightColour
            opacity: !compact.backend.online ? 0.5 : (!compact.isOn && compact.cfg.dimWhenOff ? 0.55 : 1)
            active: compact.containsMouse
            Behavior on color { ColorAnimation { duration: Kirigami.Units.longDuration } }
        }

        PC3.Label {
            visible: compact.cfg.showPercent && compact.backend.online
            text: compact.isOn ? i18nc("percentage", "%1%", compact.level) : i18n("Off")
            font.features: { "tnum": 1 }
            Layout.rightMargin: Kirigami.Units.smallSpacing
        }
    }
}

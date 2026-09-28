/*
    SPDX-FileCopyrightText: 2026 Yakup Emre Yerli
    SPDX-License-Identifier: GPL-2.0-or-later
*/

// Panel icon: a bulb that takes the light's colour while it is on.
// Click opens the popup, middle-click switches the light, the wheel dims it.

import QtQuick
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid

MouseArea {
    id: compact

    required property var backend
    required property var root

    readonly property var light: backend.light
    readonly property bool isOn: backend.online && light.on === true

    readonly property color lightColour: {
        if (!isOn) {
            return Kirigami.Theme.textColor
        }
        if (light.mode === "colour") {
            return Qt.hsva((light.hue || 0) / 360, Math.max(0.35, (light.saturation || 0) / 100), 1, 1)
        }
        // White: blend from warm amber to cool white along the temperature.
        const t = (light.temperature || 0) / 100
        return Qt.rgba(1, 0.78 + 0.2 * t, 0.45 + 0.55 * t, 1)
    }

    acceptedButtons: Qt.LeftButton | Qt.MiddleButton
    hoverEnabled: true

    property bool wasExpanded: false
    onPressed: mouse => { wasExpanded = root.expanded }
    onClicked: mouse => {
        if (mouse.button === Qt.MiddleButton) {
            backend.send("toggle")
        } else {
            root.expanded = !wasExpanded
        }
    }

    property real wheelDelta: 0
    onWheel: wheel => {
        if (!backend.online) {
            return
        }
        wheelDelta += wheel.angleDelta.y
        const steps = Math.trunc(wheelDelta / 120)
        if (steps === 0) {
            return
        }
        wheelDelta -= steps * 120
        const current = light.mode === "colour" ? (light.value || 0) : (light.brightness || 0)
        const next = Math.max(1, Math.min(100, current + steps * Plasmoid.configuration.wheelStep))
        backend.send("brightness " + next)
    }

    Kirigami.Icon {
        id: icon
        anchors.fill: parent
        source: Qt.resolvedUrl("../icons/tuya-light-symbolic.svg")
        isMask: true
        color: compact.lightColour
        opacity: compact.backend.online ? 1 : 0.5
        active: compact.containsMouse
        Behavior on color { ColorAnimation { duration: Kirigami.Units.longDuration } }
    }
}

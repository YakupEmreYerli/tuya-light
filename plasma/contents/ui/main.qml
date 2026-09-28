/*
    SPDX-FileCopyrightText: 2026 Yakup Emre Yerli
    SPDX-License-Identifier: GPL-2.0-or-later
*/

import QtQuick
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore

PlasmoidItem {
    id: main

    Backend {
        id: tuya
        command: Plasmoid.configuration.backendCommand || "tuya-light"
        device: Plasmoid.configuration.device
    }

    function reload() {
        tuya.listDevices()
        tuya.refresh()
    }

    function selectDevice(id) {
        Plasmoid.configuration.device = id
        tuya.refresh()
    }

    Plasmoid.icon: Qt.resolvedUrl("../icons/tuya-light-symbolic.svg")
    Plasmoid.status: tuya.online && tuya.light.on
        ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus

    toolTipMainText: tuya.light.name || i18n("Tuya Light")
    toolTipSubText: {
        if (tuya.needsSetup) return i18n("Not set up yet")
        if (!tuya.online) return i18n("Not reachable")
        if (!tuya.light.on) return i18n("Off")
        if (tuya.light.mode === "colour") return i18n("On, colour, %1%", tuya.light.value)
        return i18n("On, white, %1%", tuya.light.brightness)
    }

    compactRepresentation: CompactRepresentation {
        backend: tuya
        root: main
    }

    fullRepresentation: FullRepresentation {
        backend: tuya
        root: main
    }

    onExpandedChanged: if (main.expanded) reload()

    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            text: tuya.light.on ? i18n("Turn off") : i18n("Turn on")
            icon.name: "system-shutdown"
            enabled: tuya.online
            onTriggered: tuya.send(tuya.light.on ? "off" : "on")
        },
        PlasmaCore.Action {
            text: i18n("Refresh")
            icon.name: "view-refresh"
            onTriggered: main.reload()
        }
    ]

    Timer {
        interval: Math.max(10, Plasmoid.configuration.refreshSeconds) * 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: {
            if (tuya.devices.length === 0) tuya.listDevices()
            tuya.refresh()
        }
    }
}

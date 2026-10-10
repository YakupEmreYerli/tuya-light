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
        tuya.listScenes()
        tuya.listFavourites()
        tuya.refresh()
    }

    // Favourite colours live in the backend, shared with linked installs. The
    // widget's own setting mirrors them, so its editor and popup work as before:
    // edits there are sent to the backend, changes from elsewhere come back.
    readonly property var defaultFavourites: ["#ff3b30", "#ff9500", "#ffcc00", "#34c759",
                                              "#00c7be", "#0a84ff", "#8e5cff", "#ff2d92"]

    function plainColours(list) {
        return Array.from(list || []).map(c => {
            const t = String(c).toLowerCase()
            return t.length === 9 ? "#" + t.slice(3) : t   // #aarrggbb -> #rrggbb
        })
    }

    function sameColours(a, b) {
        return JSON.stringify(plainColours(a)) === JSON.stringify(plainColours(b))
    }

    function mirrorFavourites() {
        if (!tuya.favouritesKnown) {
            return
        }
        const mine = Plasmoid.configuration.favoriteColours
        if (tuya.favourites === null) {
            // None chosen anywhere yet: hand over colours customised here, once.
            if (!sameColours(mine, defaultFavourites)) {
                tuya.setFavourites(plainColours(mine), true)
            }
        } else if (!sameColours(tuya.favourites, mine)) {
            Plasmoid.configuration.favoriteColours = tuya.favourites
        }
    }

    Connections {
        target: tuya
        function onFavouritesChanged() { main.mirrorFavourites() }
        function onFavouritesKnownChanged() { main.mirrorFavourites() }
    }

    Connections {
        target: Plasmoid.configuration
        function onFavoriteColoursChanged() {
            if (tuya.favouritesKnown && tuya.favourites !== null
                    && !main.sameColours(tuya.favourites, Plasmoid.configuration.favoriteColours)) {
                tuya.setFavourites(main.plainColours(Plasmoid.configuration.favoriteColours), false)
            }
        }
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
        cfg: Plasmoid.configuration
    }

    fullRepresentation: FullRepresentation {
        backend: tuya
        root: main
        cfg: Plasmoid.configuration
    }

    onExpandedChanged: if (main.expanded) reload()

    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            text: i18n("Show controls")
            icon.name: "color-picker"
            visible: Plasmoid.configuration.leftClick !== "popup"
            onTriggered: main.expanded = true
        },
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
            if (tuya.allScenes.length === 0) tuya.listScenes()
            if (!tuya.favouritesKnown) tuya.listFavourites()
            tuya.refresh()
        }
    }
}

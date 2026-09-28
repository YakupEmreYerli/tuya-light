/*
    SPDX-FileCopyrightText: 2026 Yakup Emre Yerli
    SPDX-License-Identifier: GPL-2.0-or-later
*/

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PC3
import org.kde.plasma.extras as PlasmaExtras

PlasmaExtras.Representation {
    id: full

    required property var backend
    required property var root

    readonly property var light: backend.light
    readonly property bool isOn: backend.online && light.on === true
    readonly property bool colourMode: light.mode === "colour"

    Layout.minimumWidth: Kirigami.Units.gridUnit * 16
    Layout.minimumHeight: Kirigami.Units.gridUnit * 22
    Layout.preferredWidth: Kirigami.Units.gridUnit * 17
    collapseMarginsHint: true

    // Values shown while a drag is in flight, so the controls don't jump back
    // to the last reported state between commands.
    property real shownHue: light.hue || 0
    property real shownSat: light.saturation || 0
    property real shownBrightness: colourMode ? (light.value || 0) : (light.brightness || 0)
    property real shownTemp: light.temperature || 0

    Connections {
        target: full.backend
        function onLightChanged() {
            console.log('TLDBG light', JSON.stringify(full.light), full.shownBrightness, brightnessSlider.value, tempSlider.value)
            if (!wheel.pressed) {
                full.shownHue = full.light.hue || 0
                full.shownSat = full.light.saturation || 0
            }
            if (!brightnessSlider.pressed) {
                full.shownBrightness = full.colourMode ? (full.light.value || 0) : (full.light.brightness || 0)
            }
            if (!tempSlider.pressed) {
                full.shownTemp = full.light.temperature || 0
            }
        }
    }

    header: PlasmaExtras.PlasmoidHeading {
        RowLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            PC3.ComboBox {
                id: devicePicker
                Layout.fillWidth: true
                visible: full.backend.devices.length > 1
                model: full.backend.devices.map(d => d.name)
                currentIndex: Math.max(0, full.backend.devices.findIndex(
                    d => d.id === full.backend.device || d.name === full.backend.device))
                onActivated: index => full.root.selectDevice(full.backend.devices[index].id)
            }

            Kirigami.Heading {
                Layout.fillWidth: true
                visible: !devicePicker.visible
                level: 3
                text: full.light.name || i18n("Light")
                elide: Text.ElideRight
            }

            PC3.BusyIndicator {
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Layout.preferredWidth
                running: full.backend.busy
                visible: running
            }

            PC3.Switch {
                id: power
                enabled: full.backend.online
                checked: full.isOn
                onToggled: full.backend.send(checked ? "on" : "off")
                PC3.ToolTip.text: checked ? i18n("Turn off") : i18n("Turn on")
                PC3.ToolTip.visible: hovered
                PC3.ToolTip.delay: Kirigami.Units.toolTipDelay
            }
        }
    }

    // Setup, missing backend, or an unreachable bulb: one clear message.
    PlasmaExtras.PlaceholderMessage {
        anchors.centerIn: parent
        width: parent.width - Kirigami.Units.gridUnit * 2
        visible: !full.backend.online && (full.backend.error.length > 0 || full.backend.needsSetup)
        iconName: full.backend.needsSetup || full.backend.missingBackend ? "configure" : "network-disconnect"
        text: full.backend.missingBackend ? i18n("Backend not installed")
            : full.backend.needsSetup ? i18n("No lights set up yet")
            : i18n("The light is not answering")
        explanation: full.backend.missingBackend
            ? i18n("Install the tuya-light command (see the README), or set its path in the widget settings.")
            : full.backend.needsSetup
            ? i18n("Run “tuya-light setup” in a terminal once to fetch your bulbs' local keys.")
            : i18n("Is it switched on at the wall and on the same network?\n%1", full.backend.error)
        helpfulAction: QQC2.Action {
            icon.name: "view-refresh"
            text: i18n("Try again")
            onTriggered: full.root.reload()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.largeSpacing
        visible: full.backend.online

        ColorWheel {
            id: wheel
            property bool pressed: false
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: Math.min(full.width - Kirigami.Units.gridUnit * 2, Kirigami.Units.gridUnit * 12)
            Layout.preferredHeight: Layout.preferredWidth
            hue: full.shownHue
            saturation: full.shownSat
            dimmed: !full.isOn || !full.colourMode
            onPicked: (h, s) => {
                pressed = true
                full.shownHue = h
                full.shownSat = s
                full.backend.send("colour %1 %2 %3".arg(h).arg(s).arg(Math.max(full.shownBrightness, 5)))
            }
            onReleased: (h, s) => {
                pressed = false
                full.backend.send("colour %1 %2 %3".arg(h).arg(s).arg(Math.max(full.shownBrightness, 5)))
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 3
            columnSpacing: Kirigami.Units.smallSpacing
            rowSpacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: "brightness-high-symbolic"
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Layout.preferredWidth
            }
            PC3.Slider {
                id: brightnessSlider
                Layout.fillWidth: true
                from: 1
                to: 100
                stepSize: 1
                value: full.shownBrightness
                enabled: full.isOn
                onMoved: {
                    full.shownBrightness = value
                    full.backend.send("brightness " + Math.round(value))
                }
                onPressedChanged: if (!pressed) full.backend.send("brightness " + Math.round(value))
                Accessible.name: i18n("Brightness")
            }
            PC3.Label {
                text: i18nc("percentage", "%1%", Math.round(brightnessSlider.value))
                Layout.minimumWidth: Kirigami.Units.gridUnit * 2
                horizontalAlignment: Text.AlignRight
                font.features: { "tnum": 1 }
                opacity: full.isOn ? 1 : 0.5
            }

            Kirigami.Icon {
                source: "color-picker-grey-symbolic"
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Layout.preferredWidth
            }
            PC3.Slider {
                id: tempSlider
                Layout.fillWidth: true
                from: 0
                to: 100
                stepSize: 1
                value: full.shownTemp
                enabled: full.isOn
                onMoved: {
                    full.shownTemp = value
                    full.backend.send("temperature " + Math.round(value))
                }
                onPressedChanged: if (!pressed) full.backend.send("temperature " + Math.round(value))
                Accessible.name: i18n("White temperature")

                background: Rectangle {
                    x: tempSlider.leftPadding
                    y: tempSlider.topPadding + tempSlider.availableHeight / 2 - height / 2
                    width: tempSlider.availableWidth
                    height: Kirigami.Units.smallSpacing * 1.5
                    radius: height / 2
                    opacity: tempSlider.enabled ? 1 : 0.4
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: "#ffb45c" }
                        GradientStop { position: 0.5; color: "#fff4e0" }
                        GradientStop { position: 1; color: "#cfe3ff" }
                    }
                }
            }
            PC3.Label {
                text: full.colourMode ? "–" : (tempSlider.value < 34 ? i18n("Warm") : tempSlider.value > 66 ? i18n("Cool") : i18n("Neutral"))
                Layout.minimumWidth: Kirigami.Units.gridUnit * 2
                horizontalAlignment: Text.AlignRight
                opacity: full.isOn ? 1 : 0.5
            }
        }

        Kirigami.Separator { Layout.fillWidth: true }

        GridLayout {
            Layout.fillWidth: true
            columns: 3
            columnSpacing: Kirigami.Units.smallSpacing
            rowSpacing: Kirigami.Units.smallSpacing

            Repeater {
                model: [
                    { key: "relax", label: i18n("Relax"), swatch: "#ffb45c" },
                    { key: "reading", label: i18n("Reading"), swatch: "#fff1d6" },
                    { key: "focus", label: i18n("Focus"), swatch: "#dcebff" },
                    { key: "movie", label: i18n("Movie"), swatch: "#3a1fb8" },
                    { key: "night", label: i18n("Night"), swatch: "#b3470d" },
                    { key: "party", label: i18n("Party"), swatch: "#ff2fa8" },
                ]

                delegate: PC3.Button {
                    required property var modelData
                    Layout.fillWidth: true
                    text: modelData.label
                    enabled: full.backend.online
                    onClicked: full.backend.send("scene " + modelData.key)

                    contentItem: RowLayout {
                        spacing: Kirigami.Units.smallSpacing
                        Rectangle {
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 0.6
                            Layout.preferredHeight: Layout.preferredWidth
                            radius: width / 2
                            color: modelData.swatch
                            border.width: 1
                            border.color: Qt.rgba(0, 0, 0, 0.2)
                        }
                        PC3.Label {
                            Layout.fillWidth: true
                            text: modelData.label
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}

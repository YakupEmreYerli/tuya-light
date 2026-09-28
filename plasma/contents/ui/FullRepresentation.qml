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
    required property var cfg      // Plasmoid.configuration, or a stand-in in previews

    readonly property var light: backend.light
    readonly property bool isOn: backend.online && light.on === true
    readonly property bool colourMode: light.mode === "colour"
    readonly property var sections: (cfg.sections || []).filter(s => knownSections.indexOf(s) >= 0)
    readonly property var knownSections: ["wheel", "brightness", "temperature", "favorites", "scenes"]

    SceneInfo { id: sceneInfo }

    Layout.minimumWidth: Kirigami.Units.gridUnit * 16
    Layout.preferredWidth: Math.max(Kirigami.Units.gridUnit * 17, cfg.wheelSize * Kirigami.Units.gridUnit + Kirigami.Units.gridUnit * 3)
    Layout.preferredHeight: header.implicitHeight + body.implicitHeight + Kirigami.Units.largeSpacing * 3
    Layout.minimumHeight: Layout.preferredHeight
    collapseMarginsHint: true

    // Values shown while a drag is in flight, so the controls don't jump back
    // to the last reported state between commands.
    property real shownHue: light.hue || 0
    property real shownSat: light.saturation || 0
    property real shownBrightness: colourMode ? (light.value || 0) : (light.brightness || 0)
    property real shownTemp: light.temperature || 0
    property bool dragging: false

    Connections {
        target: full.backend
        function onLightChanged() {
            // Mid-drag, or an in-between answer while the final value is still
            // queued: keep showing what the user chose.
            if (full.dragging || !full.backend.latest) {
                return
            }
            full.shownHue = full.light.hue || 0
            full.shownSat = full.light.saturation || 0
            full.shownBrightness = full.colourMode ? (full.light.value || 0) : (full.light.brightness || 0)
            full.shownTemp = full.light.temperature || 0
        }
    }

    function sendColour(h, s) {
        full.backend.send("colour %1 %2 %3".arg(Math.round(h)).arg(Math.round(s)).arg(Math.max(Math.round(full.shownBrightness), 5)))
    }

    header: PlasmaExtras.PlasmoidHeading {
        id: header
        leftPadding: Kirigami.Units.largeSpacing
        rightPadding: Kirigami.Units.largeSpacing

        contentItem: RowLayout {
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
        id: body
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.largeSpacing
        visible: full.backend.online

        Repeater {
            model: full.sections
            delegate: Loader {
                required property string modelData
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignHCenter
                sourceComponent: ({
                    wheel: wheelSection,
                    brightness: brightnessSection,
                    temperature: temperatureSection,
                    favorites: favoritesSection,
                    scenes: scenesSection,
                })[modelData]
            }
        }

        PC3.Label {
            Layout.fillWidth: true
            visible: full.sections.length === 0
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            opacity: 0.7
            text: i18n("Every section is hidden. Turn some on in the widget's Appearance settings.")
        }
    }

    Component {
        id: wheelSection
        Item {
            implicitHeight: wheel.height
            ColorWheel {
                id: wheel
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(full.width - Kirigami.Units.gridUnit * 2, full.cfg.wheelSize * Kirigami.Units.gridUnit)
                height: width
                hue: full.shownHue
                saturation: full.shownSat
                dimmed: !full.isOn || !full.colourMode
                onPicked: (h, s) => {
                    full.dragging = true
                    full.shownHue = h
                    full.shownSat = s
                    full.sendColour(h, s)
                }
                onReleased: (h, s) => {
                    full.dragging = false
                    full.sendColour(h, s)
                }
            }
        }
    }

    Component {
        id: brightnessSection
        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Icon {
                source: "brightness-high-symbolic"
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Layout.preferredWidth
            }
            PC3.Slider {
                id: slider
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
                onPressedChanged: {
                    full.dragging = pressed
                    if (!pressed) full.backend.send("brightness " + Math.round(value))
                }
                Accessible.name: i18n("Brightness")
            }
            PC3.Label {
                text: i18nc("percentage", "%1%", Math.round(slider.value))
                Layout.minimumWidth: Kirigami.Units.gridUnit * 2.5
                horizontalAlignment: Text.AlignRight
                font.features: { "tnum": 1 }
                opacity: full.isOn ? 1 : 0.5
            }
        }
    }

    Component {
        id: temperatureSection
        RowLayout {
            spacing: Kirigami.Units.smallSpacing
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
                onPressedChanged: {
                    full.dragging = pressed
                    if (!pressed) full.backend.send("temperature " + Math.round(value))
                }
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
                        GradientStop { position: 0; color: sceneInfo.whiteColour(0) }
                        GradientStop { position: 0.5; color: sceneInfo.whiteColour(50) }
                        GradientStop { position: 1; color: sceneInfo.whiteColour(100) }
                    }
                }
            }
            PC3.Label {
                text: full.colourMode ? "–" : (tempSlider.value < 34 ? i18n("Warm") : tempSlider.value > 66 ? i18n("Cool") : i18n("Neutral"))
                Layout.minimumWidth: Kirigami.Units.gridUnit * 2.5
                horizontalAlignment: Text.AlignRight
                opacity: full.isOn ? 1 : 0.5
            }
        }
    }

    Component {
        id: favoritesSection
        Flow {
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                model: full.cfg.favoriteColours || []
                delegate: QQC2.AbstractButton {
                    id: swatch
                    required property string modelData
                    readonly property color c: modelData
                    width: Kirigami.Units.gridUnit * 1.6
                    height: width
                    enabled: full.backend.online
                    hoverEnabled: true
                    onClicked: {
                        full.shownHue = c.hsvHue * 360
                        full.shownSat = c.hsvSaturation * 100
                        full.sendColour(full.shownHue, full.shownSat)
                    }
                    background: Rectangle {
                        radius: width / 2
                        color: swatch.c
                        border.width: swatch.hovered ? 2 : 1
                        border.color: swatch.hovered ? Kirigami.Theme.highlightColor : Qt.rgba(1, 1, 1, 0.25)
                    }
                    Accessible.name: modelData
                }
            }
        }
    }

    Component {
        id: scenesSection
        GridLayout {
            columns: Math.max(1, full.cfg.sceneColumns)
            columnSpacing: Kirigami.Units.smallSpacing
            rowSpacing: Kirigami.Units.smallSpacing

            Repeater {
                model: full.backend.scenes
                delegate: PC3.Button {
                    id: sceneButton
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1   // equal columns
                    enabled: full.backend.online
                    text: sceneInfo.label(modelData)
                    onClicked: full.backend.send("scene " + full.backend.quote(modelData.name))
                    PC3.ToolTip.text: sceneInfo.describe(modelData)
                    PC3.ToolTip.visible: hovered
                    PC3.ToolTip.delay: Kirigami.Units.toolTipDelay

                    contentItem: RowLayout {
                        spacing: Kirigami.Units.smallSpacing
                        Rectangle {
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 0.6
                            Layout.preferredHeight: Layout.preferredWidth
                            radius: width / 2
                            color: sceneInfo.colour(sceneButton.modelData)
                            border.width: 1
                            border.color: Qt.rgba(0, 0, 0, 0.2)
                        }
                        PC3.Label {
                            Layout.fillWidth: true
                            text: sceneButton.text
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }
    }
}

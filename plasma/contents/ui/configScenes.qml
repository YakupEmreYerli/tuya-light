/*
    SPDX-FileCopyrightText: 2026 Yakup Emre Yerli
    SPDX-License-Identifier: GPL-2.0-or-later
*/

// Scenes live in the tuya-light backend (scenes.json), not in the widget's
// settings, so the command line and AI assistants see the same list. Edits
// here are saved at once; Apply/OK are not needed for them.

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

KCM.ScrollViewKCM {
    id: page

    property string cfg_backendCommand: "tuya-light"
    property string cfg_device: ""

    Backend {
        id: backend
        command: page.cfg_backendCommand || "tuya-light"
        device: page.cfg_device
        Component.onCompleted: { listScenes(); refresh() }
    }
    SceneInfo { id: sceneInfo }

    property string message: ""

    function run(args) {
        backend.call(args, (ok, answer, err) => {
            page.message = ok ? "" : (err || i18n("The change could not be saved."))
            backend.listScenes()
        })
    }

    header: ColumnLayout {
        spacing: Kirigami.Units.smallSpacing
        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: i18n("Scenes are shared with the tuya-light command and its MCP server. Changes here are saved immediately.")
        }
        Kirigami.InlineMessage {
            Layout.fillWidth: true
            type: Kirigami.MessageType.Error
            text: page.message
            visible: text.length > 0
        }
    }

    view: ListView {
        id: list
        model: backend.allScenes
        clip: true

        delegate: QQC2.ItemDelegate {
            id: row
            required property var modelData
            width: ListView.view.width
            opacity: modelData.hidden ? 0.55 : 1
            onClicked: editor.openFor(modelData)

            contentItem: RowLayout {
                spacing: Kirigami.Units.largeSpacing
                Rectangle {
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 1.4
                    Layout.preferredHeight: Layout.preferredWidth
                    radius: width / 2
                    color: sceneInfo.colour(row.modelData)
                    border.width: 1
                    border.color: Qt.rgba(0, 0, 0, 0.25)
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    QQC2.Label {
                        Layout.fillWidth: true
                        text: sceneInfo.label(row.modelData)
                        elide: Text.ElideRight
                    }
                    QQC2.Label {
                        Layout.fillWidth: true
                        font: Kirigami.Theme.smallFont
                        opacity: 0.7
                        elide: Text.ElideRight
                        text: {
                            const bits = [sceneInfo.describe(row.modelData)]
                            if (row.modelData.builtin) bits.push(i18n("built in"))
                            if (row.modelData.hidden) bits.push(i18n("hidden"))
                            return bits.join(" · ")
                        }
                    }
                }
                QQC2.ToolButton {
                    icon.name: "media-playback-start"
                    enabled: backend.online
                    onClicked: backend.send("scene " + backend.quote(row.modelData.name))
                    QQC2.ToolTip.text: i18n("Try on the light")
                    QQC2.ToolTip.visible: hovered
                }
                QQC2.ToolButton {
                    icon.name: "document-edit"
                    onClicked: editor.openFor(row.modelData)
                    QQC2.ToolTip.text: i18n("Edit")
                    QQC2.ToolTip.visible: hovered
                }
                QQC2.ToolButton {
                    icon.name: row.modelData.hidden ? "view-visible" : "view-hidden"
                    onClicked: page.run((row.modelData.hidden ? "scene-show " : "scene-hide ") + backend.quote(row.modelData.name))
                    QQC2.ToolTip.text: row.modelData.hidden ? i18n("Show in the popup") : i18n("Hide from the popup")
                    QQC2.ToolTip.visible: hovered
                }
                QQC2.ToolButton {
                    visible: !row.modelData.builtin
                    icon.name: "edit-delete"
                    onClicked: page.run("scene-remove " + backend.quote(row.modelData.name))
                    QQC2.ToolTip.text: i18n("Delete")
                    QQC2.ToolTip.visible: hovered
                }
                QQC2.ToolButton {
                    visible: row.modelData.builtin
                    icon.name: "edit-undo"
                    onClicked: page.run("scene-reset " + backend.quote(row.modelData.name))
                    QQC2.ToolTip.text: i18n("Restore the original")
                    QQC2.ToolTip.visible: hovered
                }
            }
        }
    }

    footer: RowLayout {
        QQC2.Button {
            text: i18n("New scene…")
            icon.name: "list-add"
            onClicked: editor.openFor(null)
        }
        QQC2.Button {
            text: i18n("Save the light as a scene…")
            icon.name: "document-save"
            enabled: backend.online
            onClicked: { editor.openFor(null); editor.takeFromLight() }
        }
        Item { Layout.fillWidth: true }
        QQC2.Button {
            text: i18n("Restore built-in scenes")
            icon.name: "edit-undo"
            onClicked: page.run("scene-reset")
        }
    }

    Kirigami.Dialog {
        id: editor
        title: key.length ? i18n("Edit scene") : i18n("New scene")
        padding: Kirigami.Units.largeSpacing
        preferredWidth: Kirigami.Units.gridUnit * 22
        standardButtons: Kirigami.Dialog.NoButton

        property string key: ""
        property string mode: "colour"
        property real hue: 30
        property real saturation: 100
        property real brightness: 100
        property real temperature: 30

        function openFor(scene) {
            if (scene) {
                key = scene.name
                nameField.text = sceneInfo.label(scene)
                mode = scene.mode
                hue = scene.hue
                saturation = scene.saturation
                brightness = scene.brightness
                temperature = scene.temperature
            } else {
                key = ""
                nameField.text = ""
                mode = "colour"; hue = 30; saturation = 100; brightness = 100; temperature = 30
            }
            open()
            nameField.forceActiveFocus()
        }

        function takeFromLight() {
            const l = backend.light
            if (!l.online) return
            mode = l.mode === "colour" ? "colour" : "white"
            hue = l.hue; saturation = l.saturation; temperature = l.temperature
            brightness = mode === "colour" ? l.value : l.brightness
        }

        function tryIt() {
            if (mode === "colour") {
                backend.send("colour %1 %2 %3".arg(Math.round(hue)).arg(Math.round(saturation)).arg(Math.max(1, Math.round(brightness))))
            } else {
                backend.send("white %1 %2".arg(Math.max(1, Math.round(brightness))).arg(Math.round(temperature)))
            }
        }

        function save() {
            const label = nameField.text.trim()
            if (!label.length) return
            let args = "scene-save " + backend.quote(label)
            if (key.length) args += " --name " + backend.quote(key)
            if (mode === "colour") {
                args += " --colour " + backend.quote(Math.round(hue) + " " + Math.round(saturation))
            } else {
                args += " --white " + Math.round(temperature)
            }
            args += " --brightness " + Math.round(brightness)
            page.run(args)
            close()
        }

        ColumnLayout {
            spacing: Kirigami.Units.largeSpacing

            Kirigami.FormLayout {
                Layout.fillWidth: true
                QQC2.TextField {
                    id: nameField
                    Kirigami.FormData.label: i18n("Name:")
                    placeholderText: i18n("e.g. Reading nook")
                    onAccepted: editor.save()
                }
                RowLayout {
                    Kirigami.FormData.label: i18n("Light:")
                    QQC2.RadioButton {
                        text: i18n("Colour")
                        checked: editor.mode === "colour"
                        onToggled: if (checked) editor.mode = "colour"
                    }
                    QQC2.RadioButton {
                        text: i18n("White")
                        checked: editor.mode === "white"
                        onToggled: if (checked) editor.mode = "white"
                    }
                }
            }

            ColorWheel {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: Kirigami.Units.gridUnit * 9
                Layout.preferredHeight: Layout.preferredWidth
                visible: editor.mode === "colour"
                hue: editor.hue
                saturation: editor.saturation
                onPicked: (h, s) => { editor.hue = h; editor.saturation = s }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 3
                QQC2.Label { text: i18n("Brightness") }
                QQC2.Slider {
                    Layout.fillWidth: true
                    from: 1; to: 100; stepSize: 1
                    value: editor.brightness
                    onMoved: editor.brightness = value
                }
                QQC2.Label { text: i18nc("percentage", "%1%", Math.round(editor.brightness)); Layout.minimumWidth: Kirigami.Units.gridUnit * 2 }

                QQC2.Label { text: i18n("Warm – cool"); visible: editor.mode === "white" }
                QQC2.Slider {
                    Layout.fillWidth: true
                    visible: editor.mode === "white"
                    from: 0; to: 100; stepSize: 1
                    value: editor.temperature
                    onMoved: editor.temperature = value
                }
                Rectangle {
                    visible: editor.mode === "white"
                    Layout.preferredWidth: Kirigami.Units.gridUnit
                    Layout.preferredHeight: Layout.preferredWidth
                    radius: width / 2
                    color: sceneInfo.whiteColour(editor.temperature)
                }
            }

            RowLayout {
                Layout.fillWidth: true
                QQC2.Button {
                    text: i18n("Take from the light")
                    icon.name: "color-picker"
                    enabled: backend.online
                    onClicked: editor.takeFromLight()
                }
                QQC2.Button {
                    text: i18n("Try on the light")
                    icon.name: "media-playback-start"
                    enabled: backend.online
                    onClicked: editor.tryIt()
                }
                Item { Layout.fillWidth: true }
                QQC2.Button {
                    text: i18n("Cancel")
                    onClicked: editor.close()
                }
                QQC2.Button {
                    text: i18n("Save")
                    icon.name: "document-save"
                    highlighted: true
                    enabled: nameField.text.trim().length > 0
                    onClicked: editor.save()
                }
            }
        }
    }
}

/*
    SPDX-FileCopyrightText: 2026 Yakup Emre Yerli
    SPDX-License-Identifier: GPL-2.0-or-later
*/

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Dialogs
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

KCM.SimpleKCM {
    id: page

    property var cfg_sections: []
    property alias cfg_wheelSize: wheelSize.value
    property alias cfg_sceneColumns: columns.value
    property var cfg_favoriteColours: []
    property string cfg_iconStyle: "bulb"
    property alias cfg_tintIcon: tint.checked
    property alias cfg_dimWhenOff: dim.checked
    property alias cfg_showPercent: percent.checked

    readonly property var sectionNames: ({
        wheel: i18n("Colour wheel"),
        brightness: i18n("Brightness slider"),
        temperature: i18n("White temperature slider"),
        favorites: i18n("Favourite colours"),
        scenes: i18n("Scenes"),
    })

    // Every known section once: the shown ones in their order, then the hidden ones.
    function rows() {
        const shown = (cfg_sections || []).filter(k => sectionNames[k] !== undefined)
        const hidden = Object.keys(sectionNames).filter(k => shown.indexOf(k) < 0)
        return shown.map(k => ({ key: k, on: true })).concat(hidden.map(k => ({ key: k, on: false })))
    }
    property var order: rows()

    function commit(list) {
        order = list
        cfg_sections = list.filter(r => r.on).map(r => r.key)
    }
    function move(i, d) {
        const list = order.slice()
        const j = i + d
        if (j < 0 || j >= list.length) return
        const t = list[i]; list[i] = list[j]; list[j] = t
        commit(list)
    }
    function setOn(i, on) {
        const list = order.slice()
        list[i] = { key: list[i].key, on: on }
        commit(list)
    }

    Kirigami.FormLayout {
        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Popup")
        }

        ColumnLayout {
            Kirigami.FormData.label: i18n("Sections:")
            Kirigami.FormData.labelAlignment: Qt.AlignTop
            spacing: 0

            Repeater {
                model: page.order
                delegate: RowLayout {
                    required property var modelData
                    required property int index
                    spacing: Kirigami.Units.smallSpacing
                    QQC2.CheckBox {
                        Layout.minimumWidth: Kirigami.Units.gridUnit * 12
                        text: page.sectionNames[modelData.key]
                        checked: modelData.on
                        onToggled: page.setOn(index, checked)
                    }
                    QQC2.ToolButton {
                        icon.name: "arrow-up"
                        enabled: index > 0
                        onClicked: page.move(index, -1)
                        QQC2.ToolTip.text: i18n("Move up")
                        QQC2.ToolTip.visible: hovered
                    }
                    QQC2.ToolButton {
                        icon.name: "arrow-down"
                        enabled: index < page.order.length - 1
                        onClicked: page.move(index, 1)
                        QQC2.ToolTip.text: i18n("Move down")
                        QQC2.ToolTip.visible: hovered
                    }
                }
            }
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Colour wheel size:")
            QQC2.Slider {
                id: wheelSize
                from: 7
                to: 18
                stepSize: 1
                Layout.preferredWidth: Kirigami.Units.gridUnit * 10
            }
            QQC2.Label {
                text: wheelSize.value <= 9 ? i18n("Small") : wheelSize.value <= 12 ? i18n("Medium")
                    : wheelSize.value <= 15 ? i18n("Large") : i18n("Very large")
            }
        }

        QQC2.SpinBox {
            id: columns
            Kirigami.FormData.label: i18n("Scene columns:")
            from: 1
            to: 4
        }

        Flow {
            Kirigami.FormData.label: i18n("Favourite colours:")
            Layout.preferredWidth: Kirigami.Units.gridUnit * 16
            spacing: Kirigami.Units.smallSpacing

            Repeater {
                model: page.cfg_favoriteColours
                delegate: QQC2.AbstractButton {
                    id: fav
                    required property string modelData
                    required property int index
                    width: Kirigami.Units.gridUnit * 1.8
                    height: width
                    hoverEnabled: true
                    onClicked: {
                        const list = page.cfg_favoriteColours.slice()
                        list.splice(index, 1)
                        page.cfg_favoriteColours = list
                    }
                    background: Rectangle {
                        radius: width / 2
                        color: fav.modelData
                        border.width: 1
                        border.color: Qt.rgba(0, 0, 0, 0.3)
                    }
                    Kirigami.Icon {
                        anchors.centerIn: parent
                        width: parent.width * 0.6
                        height: width
                        source: "edit-delete-remove"
                        visible: fav.hovered
                    }
                    QQC2.ToolTip.text: i18n("Remove %1", fav.modelData)
                    QQC2.ToolTip.visible: hovered
                }
            }
            QQC2.ToolButton {
                icon.name: "list-add"
                onClicked: colourDialog.open()
                QQC2.ToolTip.text: i18n("Add a colour")
                QQC2.ToolTip.visible: hovered
            }
        }
        QQC2.Label {
            text: i18n("Click a colour to remove it. Turn on “Favourite colours” above to show them.")
            opacity: 0.7
            font: Kirigami.Theme.smallFont
            wrapMode: Text.Wrap
            Layout.maximumWidth: Kirigami.Units.gridUnit * 18
        }

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Panel icon")
        }

        RowLayout {
            Kirigami.FormData.label: i18n("Icon:")
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                model: [
                    { key: "bulb", file: "tuya-light-symbolic.svg", name: i18n("Bulb") },
                    { key: "bulb-filled", file: "tuya-light-bulb-filled-symbolic.svg", name: i18n("Filled bulb") },
                    { key: "lamp", file: "tuya-light-lamp-symbolic.svg", name: i18n("Lamp") },
                    { key: "star", file: "tuya-light-star-symbolic.svg", name: i18n("Star") },
                ]
                delegate: QQC2.ToolButton {
                    id: iconChoice
                    required property var modelData
                    checkable: true
                    checked: page.cfg_iconStyle === modelData.key
                    onClicked: page.cfg_iconStyle = modelData.key
                    implicitWidth: Kirigami.Units.iconSizes.medium + Kirigami.Units.largeSpacing * 2
                    implicitHeight: implicitWidth
                    contentItem: Kirigami.Icon {
                        source: Qt.resolvedUrl("../icons/" + iconChoice.modelData.file)
                        isMask: true
                        color: Kirigami.Theme.textColor
                        implicitWidth: Kirigami.Units.iconSizes.medium
                        implicitHeight: implicitWidth
                    }
                    QQC2.ToolTip.text: modelData.name
                    QQC2.ToolTip.visible: hovered
                    Accessible.name: modelData.name
                }
            }
        }
        QQC2.CheckBox {
            id: tint
            text: i18n("Take the light's colour")
        }
        QQC2.CheckBox {
            id: dim
            text: i18n("Fade the icon while the light is off")
        }
        QQC2.CheckBox {
            id: percent
            text: i18n("Show the brightness next to the icon")
        }
    }

    ColorDialog {
        id: colourDialog
        title: i18n("Add a favourite colour")
        onAccepted: {
            const hex = selectedColor.toString()
            if (page.cfg_favoriteColours.indexOf(hex) < 0) {
                page.cfg_favoriteColours = page.cfg_favoriteColours.concat([hex])
            }
        }
    }
}

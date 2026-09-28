/*
    SPDX-FileCopyrightText: 2026 Yakup Emre Yerli
    SPDX-License-Identifier: GPL-2.0-or-later
*/

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kde.plasma.plasmoid

KCM.SimpleKCM {
    id: page

    property string cfg_leftClick: "popup"
    property string cfg_leftScene: ""
    property string cfg_middleClick: "toggle"
    property string cfg_middleScene: ""
    property string cfg_wheelAction: "brightness"
    property alias cfg_wheelStep: step.value
    property alias cfg_invertWheel: invert.checked
    // Read, never declared as cfg_: only the Device tab owns these settings, so
    // applying this tab can never write an older value over them.
    readonly property var saved: Plasmoid.configuration

    Backend {
        id: backend
        command: (page.saved && page.saved.backendCommand) || "tuya-light"
        Component.onCompleted: listScenes()
    }
    SceneInfo { id: sceneInfo }

    readonly property var clickActions: [
        { key: "popup", text: i18n("Open the controls") },
        { key: "toggle", text: i18n("Switch the light on or off") },
        { key: "scene", text: i18n("Apply a scene") },
        { key: "none", text: i18n("Nothing") },
    ]
    readonly property var wheelActions: [
        { key: "brightness", text: i18n("Brightness") },
        { key: "temperature", text: i18n("White temperature") },
        { key: "hue", text: i18n("Colour (turn the wheel)") },
        { key: "none", text: i18n("Nothing") },
    ]
    readonly property var sceneChoices: backend.scenes.map(s => ({ key: s.name, text: sceneInfo.label(s) }))

    function indexOf(list, key) {
        return Math.max(0, list.findIndex(x => x.key === key))
    }

    Kirigami.FormLayout {
        QQC2.ComboBox {
            Kirigami.FormData.label: i18n("Left click:")
            model: page.clickActions
            textRole: "text"
            currentIndex: page.indexOf(page.clickActions, page.cfg_leftClick)
            onActivated: page.cfg_leftClick = page.clickActions[currentIndex].key
        }
        QQC2.ComboBox {
            Kirigami.FormData.label: i18n("Scene:")
            visible: page.cfg_leftClick === "scene"
            model: page.sceneChoices
            textRole: "text"
            currentIndex: page.indexOf(page.sceneChoices, page.cfg_leftScene)
            onActivated: page.cfg_leftScene = page.sceneChoices[currentIndex].key
            Component.onCompleted: if (!page.cfg_leftScene && page.sceneChoices.length) page.cfg_leftScene = page.sceneChoices[0].key
        }

        QQC2.ComboBox {
            Kirigami.FormData.label: i18n("Middle click:")
            model: page.clickActions
            textRole: "text"
            currentIndex: page.indexOf(page.clickActions, page.cfg_middleClick)
            onActivated: page.cfg_middleClick = page.clickActions[currentIndex].key
        }
        QQC2.ComboBox {
            Kirigami.FormData.label: i18n("Scene:")
            visible: page.cfg_middleClick === "scene"
            model: page.sceneChoices
            textRole: "text"
            currentIndex: page.indexOf(page.sceneChoices, page.cfg_middleScene)
            onActivated: page.cfg_middleScene = page.sceneChoices[currentIndex].key
        }

        Item { Kirigami.FormData.isSection: true }

        QQC2.ComboBox {
            Kirigami.FormData.label: i18n("Scroll wheel:")
            model: page.wheelActions
            textRole: "text"
            currentIndex: page.indexOf(page.wheelActions, page.cfg_wheelAction)
            onActivated: page.cfg_wheelAction = page.wheelActions[currentIndex].key
        }
        QQC2.SpinBox {
            id: step
            Kirigami.FormData.label: i18n("Step per notch:")
            enabled: page.cfg_wheelAction !== "none"
            from: 1
            to: 25
            textFromValue: (v) => page.cfg_wheelAction === "hue" ? i18n("%1°", v * 3) : i18nc("percentage", "%1%", v)
            valueFromText: (t) => parseInt(t)
        }
        QQC2.CheckBox {
            id: invert
            enabled: page.cfg_wheelAction !== "none"
            text: i18n("Reverse the direction")
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 20
            wrapMode: Text.Wrap
            opacity: 0.7
            font: Kirigami.Theme.smallFont
            text: i18n("If the left click no longer opens the controls, they are in the icon's right-click menu.")
            visible: page.cfg_leftClick !== "popup"
        }
    }
}

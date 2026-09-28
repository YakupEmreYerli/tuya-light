/*
    SPDX-FileCopyrightText: 2026 Yakup Emre Yerli
    SPDX-License-Identifier: GPL-2.0-or-later
*/

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

KCM.SimpleKCM {
    property alias cfg_backendCommand: command.text
    property alias cfg_device: device.text
    property alias cfg_refreshSeconds: refresh.value
    property alias cfg_wheelStep: step.value

    Kirigami.FormLayout {
        QQC2.TextField {
            id: command
            Kirigami.FormData.label: i18n("Backend command:")
            placeholderText: "tuya-light"
        }
        QQC2.TextField {
            id: device
            Kirigami.FormData.label: i18n("Device:")
            placeholderText: i18n("First in the list")
        }
        QQC2.SpinBox {
            id: refresh
            Kirigami.FormData.label: i18n("Check the light every:")
            from: 10
            to: 3600
            textFromValue: (v) => i18np("%1 second", "%1 seconds", v)
            valueFromText: (t) => parseInt(t)
        }
        QQC2.SpinBox {
            id: step
            Kirigami.FormData.label: i18n("Scroll step:")
            from: 1
            to: 25
            textFromValue: (v) => i18nc("percentage", "%1%", v)
            valueFromText: (t) => parseInt(t)
        }
        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 22
            wrapMode: Text.Wrap
            text: i18n("Middle-click the panel icon to switch the light, scroll over it to dim.")
        }
    }
}

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
    id: page

    property alias cfg_backendCommand: command.text
    property alias cfg_device: device.text
    property alias cfg_refreshSeconds: refresh.value

    Backend {
        id: backend
        command: command.text || "tuya-light"
        device: device.text
        Component.onCompleted: listDevices()
    }

    Kirigami.FormLayout {
        QQC2.ComboBox {
            Kirigami.FormData.label: i18n("Light:")
            visible: backend.devices.length > 0
            model: [i18n("First in the list")].concat(backend.devices.map(d => d.name))
            currentIndex: Math.max(0, backend.devices.findIndex(d => d.id === device.text || d.name === device.text) + 1)
            onActivated: device.text = currentIndex === 0 ? "" : backend.devices[currentIndex - 1].id
        }
        QQC2.TextField {
            id: device
            visible: backend.devices.length === 0
            Kirigami.FormData.label: i18n("Light:")
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

        Item { Kirigami.FormData.isSection: true }

        QQC2.TextField {
            id: command
            Kirigami.FormData.label: i18n("Backend command:")
            placeholderText: "tuya-light"
        }

        RowLayout {
            QQC2.Button {
                text: i18n("Test the connection")
                icon.name: "network-connect"
                onClicked: {
                    result.text = i18n("Asking the light…")
                    backend.call("state", (ok, answer, err) => {
                        if (answer && answer.online) {
                            result.text = i18n("%1 answered: %2", answer.name, answer.on ? i18n("on") : i18n("off"))
                        } else if (answer && answer.config) {
                            result.text = i18n("No lights set up yet: run “tuya-light setup” in a terminal.")
                        } else {
                            result.text = (answer && answer.error) || err || i18n("The tuya-light command was not found.")
                        }
                        backend.listDevices()
                    })
                }
            }
        }
        QQC2.Label {
            id: result
            Layout.maximumWidth: Kirigami.Units.gridUnit * 20
            wrapMode: Text.Wrap
        }
    }
}

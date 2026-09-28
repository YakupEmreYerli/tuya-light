import QtQuick
import org.kde.plasma.configuration

ConfigModel {
    ConfigCategory {
        name: i18n("Appearance")
        icon: "preferences-desktop-color"
        source: "configAppearance.qml"
    }
    ConfigCategory {
        name: i18n("Behaviour")
        icon: "input-mouse"
        source: "configBehaviour.qml"
    }
    ConfigCategory {
        name: i18n("Scenes")
        icon: "games-config-theme"
        source: "configScenes.qml"
    }
    ConfigCategory {
        name: i18n("Device")
        icon: "network-wireless"
        source: "configGeneral.qml"
    }
}

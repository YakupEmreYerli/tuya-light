/*
    SPDX-FileCopyrightText: 2026 Yakup Emre Yerli
    SPDX-License-Identifier: GPL-2.0-or-later
*/

// How a scene looks and is called on screen, shared by the popup and settings.

import QtQuick

QtObject {
    // Built-in scenes keep their translated name until the user renames them.
    readonly property var builtinLabels: ({
        relax: ["Relax", i18n("Relax")],
        reading: ["Reading", i18n("Reading")],
        focus: ["Focus", i18n("Focus")],
        movie: ["Movie", i18n("Movie")],
        night: ["Night", i18n("Night")],
        party: ["Party", i18n("Party")],
    })

    function label(scene) {
        const b = scene.builtin ? builtinLabels[scene.name] : undefined
        return b && scene.label === b[0] ? b[1] : scene.label
    }

    // White light: amber at 0, near-white in the middle, pale blue at 100.
    function whiteColour(temperature) {
        const t = Math.max(0, Math.min(100, temperature)) / 100
        if (t < 0.5) {
            const k = t / 0.5
            return Qt.rgba(1, 0.71 + 0.25 * k, 0.36 + 0.52 * k, 1)
        }
        const k = (t - 0.5) / 0.5
        return Qt.rgba(1 - 0.19 * k, 0.96 - 0.07 * k, 0.88 + 0.12 * k, 1)
    }

    function colour(scene) {
        if (scene.mode === "colour") {
            return Qt.hsva((scene.hue % 360) / 360, scene.saturation / 100,
                           0.45 + 0.55 * scene.brightness / 100, 1)
        }
        return whiteColour(scene.temperature)
    }

    function describe(scene) {
        if (scene.mode === "colour") {
            return i18n("Colour, %1%", scene.brightness)
        }
        const t = scene.temperature
        const tone = t < 34 ? i18n("warm") : t > 66 ? i18n("cool") : i18n("neutral")
        return i18n("White, %1, %2%", tone, scene.brightness)
    }
}

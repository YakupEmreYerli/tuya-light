/*
    SPDX-FileCopyrightText: 2026 Yakup Emre Yerli
    SPDX-License-Identifier: GPL-2.0-or-later
*/

// Runs the `tuya-light` command-line backend and keeps the last known state.
// One command at a time: while one runs, newer writes replace each other, so
// dragging a slider sends the first and the last value, not every step.

import QtQuick
import org.kde.plasma.plasma5support as P5Support

Item {
    id: backend

    property string command: "tuya-light"
    property string device: ""

    property var light: ({})
    property var devices: []
    property bool busy: false
    property bool loaded: false
    property bool needsSetup: false
    property bool missingBackend: false
    property string error: ""

    readonly property bool online: loaded && light.online === true

    property string _pending: ""
    property var _kinds: ({})

    function _quote(s) {
        return "'" + String(s).replace(/'/g, "'\\''") + "'"
    }

    function _base() {
        let c = command + " --json"
        if (device.length > 0) {
            c += " -d " + _quote(device)
        }
        return c
    }

    function send(args) {
        const cmd = _base() + " " + args
        if (busy) {
            _pending = cmd
            return
        }
        _run(cmd, "state")
    }

    function refresh() {
        if (!busy) {
            send("state")
        }
    }

    function listDevices() {
        _run(command + " --json devices", "devices")
    }

    function _run(cmd, kind) {
        if (kind === "state") {
            busy = true
        }
        // A unique shell comment makes every call a new source, so an
        // identical command issued twice still runs twice.
        const src = cmd + " #" + Date.now() + Math.random().toString(36).slice(2, 6)
        _kinds[src] = kind
        exec.connectSource(src)
    }

    function _finish(source, data) {
        const kind = _kinds[source]
        delete _kinds[source]
        exec.disconnectSource(source)

        const code = data["exit code"]
        const out = String(data["stdout"] || "").trim()
        missingBackend = code === 127
        let parsed = null
        try {
            parsed = out.length ? JSON.parse(out.split("\n").pop()) : null
        } catch (e) {
            parsed = null
        }

        if (kind === "devices") {
            devices = Array.isArray(parsed) ? parsed : []
            return
        }

        busy = false
        if (missingBackend) {
            error = i18n("The tuya-light command was not found.")
        } else if (parsed && parsed.config) {
            needsSetup = true
            error = parsed.error || ""
        } else if (parsed) {
            needsSetup = false
            light = parsed
            loaded = true
            error = parsed.online ? "" : (parsed.error || i18n("The light did not answer."))
        } else {
            error = String(data["stderr"] || "").trim() || i18n("Unexpected answer from tuya-light.")
        }

        if (_pending.length > 0) {
            const next = _pending
            _pending = ""
            _run(next, "state")
        }
    }

    P5Support.DataSource {
        id: exec
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => backend._finish(source, data)
    }
}

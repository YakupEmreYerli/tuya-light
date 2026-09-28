/*
    SPDX-FileCopyrightText: 2026 Yakup Emre Yerli
    SPDX-License-Identifier: GPL-2.0-or-later
*/

// Runs the `tuya-light` command-line backend and keeps the last known state.
// Light commands go one at a time: while one runs, newer ones replace each
// other, so dragging a slider sends the first and the last value, not every
// step. Scene edits and lists run alongside, each with its own callback.

import QtQuick
import org.kde.plasma.plasma5support as P5Support

Item {
    id: backend

    property string command: "tuya-light"
    property string device: ""

    property var light: ({})
    property var devices: []
    property var scenes: []        // visible scenes, as `tuya-light scenes --json`
    property var allScenes: []     // including hidden ones
    property bool busy: false
    property bool loaded: false
    property bool needsSetup: false
    property bool missingBackend: false
    property string error: ""

    readonly property bool online: loaded && light.online === true

    property string _pending: ""
    property var _jobs: ({})

    function quote(s) {
        return "'" + String(s).replace(/'/g, "'\\''") + "'"
    }

    function _base() {
        let c = command + " --json"
        if (device.length > 0) {
            c += " -d " + quote(device)
        }
        return c
    }

    // A light command; its answer becomes the new `light`.
    function send(args) {
        const cmd = _base() + " " + args
        if (busy) {
            _pending = cmd
            return
        }
        _run(cmd, { kind: "state" })
    }

    function refresh() {
        if (!busy) {
            send("state")
        }
    }

    function listDevices() {
        _run(command + " --json devices", { kind: "devices" })
    }

    function listScenes() {
        _run(command + " --json scenes --all", { kind: "scenes" })
    }

    // Anything else (scene edits): callback(ok, parsedJson, stderr).
    function call(args, callback) {
        _run(_base() + " " + args, { kind: "call", callback: callback })
    }

    function _run(cmd, job) {
        if (job.kind === "state") {
            busy = true
        }
        // A unique shell comment makes every call a new source, so an
        // identical command issued twice still runs twice.
        const src = cmd + " #" + Date.now() + Math.random().toString(36).slice(2, 6)
        _jobs[src] = job
        exec.connectSource(src)
    }

    function _parse(out) {
        try {
            return out.length ? JSON.parse(out.split("\n").pop()) : null
        } catch (e) {
            return null
        }
    }

    function _finish(source, data) {
        const job = _jobs[source] || { kind: "call" }
        delete _jobs[source]
        exec.disconnectSource(source)

        const code = data["exit code"]
        const out = String(data["stdout"] || "").trim()
        const err = String(data["stderr"] || "").trim()
        const parsed = _parse(out)
        if (code === 127) {
            missingBackend = true
        }

        if (job.kind === "devices") {
            devices = Array.isArray(parsed) ? parsed : []
            return
        }
        if (job.kind === "scenes") {
            if (Array.isArray(parsed)) {
                allScenes = parsed
                scenes = parsed.filter(s => !s.hidden)
            }
            return
        }
        if (job.kind === "call") {
            if (job.callback) {
                job.callback(code === 0, parsed, err)
            }
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
            missingBackend = false
            light = parsed
            loaded = true
            error = parsed.online ? "" : (parsed.error || i18n("The light did not answer."))
        } else {
            error = err || i18n("Unexpected answer from tuya-light.")
        }

        if (_pending.length > 0) {
            const next = _pending
            _pending = ""
            _run(next, { kind: "state" })
        }
    }

    P5Support.DataSource {
        id: exec
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => backend._finish(source, data)
    }
}

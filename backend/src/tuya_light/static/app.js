/*
    SPDX-FileCopyrightText: 2026 Yakup Emre Yerli
    SPDX-License-Identifier: GPL-2.0-or-later
*/

// The phone page. It talks to `tuya-light serve` and keeps the widget's
// rules: one light command at a time, a newer command replaces one that is
// still waiting, and the controls never jump back to an answer that is
// already out of date.
//
// A light reached through the Tuya cloud costs an API call per request, so
// for those the page sends a slider's value only where the drag stops, asks
// for the state less often (the server says how often), and stops asking
// after five quiet minutes until the page is touched or shown again.

const POLL_MS = 4000
const IDLE_MS = 5 * 60 * 1000
const RETRY_MS = 5000
const POLL_TIMEOUT_MS = 12000
const SEND_TIMEOUT_MS = 25000

// The widget's default favourites, without yellow and teal, so that seven
// targets fit a phone's width at 44 points each.
const SWATCHES = [
    ['red', '#ff3b30'], ['orange', '#ff9500'], ['green', '#34c759'],
    ['blue', '#0a84ff'], ['purple', '#8e5cff'], ['pink', '#ff2d92'],
]

const STRINGS = {
    en: {
        light: 'Light',
        off: 'Off',
        tapToTurnOn: 'Tap to turn on',
        brightnessIs: 'Brightness %1',
        brightness: 'Brightness',
        white: 'White light',
        warm: 'Warm', neutral: 'Neutral', cool: 'Cool',
        warmWhite: 'warm white', neutralWhite: 'neutral white', coolWhite: 'cool white',
        effect: 'Light effect',
        effectDetail: 'Set in the Tuya app',
        pale: 'pale %1',
        colours: 'Colours',
        moreColours: 'More colours',
        scenes: 'Scenes',
        connecting: 'Connecting…',
        viaCloud: 'Through the Tuya cloud',
        pcTitle: "Can't reach your computer",
        pcText: 'Is it switched on and awake? This phone has to be on your home Wi-Fi, or connected to Tailscale.',
        bulbTitle: 'The light is not answering',
        bulbText: 'Is it switched on at the wall and on the same network as the computer?',
        unpairedTitle: 'This phone is not paired yet',
        unpairedText: 'On the computer, run `tuya-light serve --pair` and open the link it shows on this phone.',
        badKeyTitle: 'That pairing link no longer works',
        badKeyText: 'The key has been changed. Run `tuya-light serve --pair` on the computer for a new link. If this is the Home Screen app, delete it and add it again from the new link.',
        setupTitle: 'No lights set up yet',
        setupText: 'On the computer, run `tuya-light setup` once to fetch your bulbs’ local keys.',
        refusedTitle: 'The computer turned this page away',
        errorTitle: 'Something went wrong on the computer',
        tryAgain: 'Try again',
        addHint: 'To keep this on your Home Screen, tap Share, then Add to Home Screen.',
        dismiss: 'Close',
        names: {
            red: 'red', orange: 'orange', yellow: 'yellow', green: 'green',
            cyan: 'cyan', blue: 'blue', purple: 'purple', pink: 'pink',
        },
        builtins: {
            relax: 'Relax', reading: 'Reading', focus: 'Focus',
            movie: 'Movie', night: 'Night', party: 'Party',
        },
    },
    tr: {
        light: 'Işık',
        off: 'Kapalı',
        tapToTurnOn: 'Açmak için dokunun',
        brightnessIs: 'Parlaklık %1',
        brightness: 'Parlaklık',
        white: 'Beyaz ışık',
        warm: 'Sıcak', neutral: 'Nötr', cool: 'Soğuk',
        warmWhite: 'sıcak beyaz', neutralWhite: 'nötr beyaz', coolWhite: 'soğuk beyaz',
        effect: 'Işık efekti',
        effectDetail: 'Tuya uygulamasından ayarlandı',
        pale: 'açık %1',
        colours: 'Renkler',
        moreColours: 'Başka bir renk',
        scenes: 'Sahneler',
        connecting: 'Bağlanıyor…',
        viaCloud: 'Tuya bulutu üzerinden',
        pcTitle: 'Bilgisayara ulaşılamıyor',
        pcText: 'Bilgisayar açık ve uyanık mı? Telefon evdeki Wi-Fi’a ya da Tailscale’e bağlı olmalı.',
        bulbTitle: 'Işık cevap vermiyor',
        bulbText: 'Anahtardan açık mı, bilgisayarla aynı ağda mı?',
        unpairedTitle: 'Bu telefon henüz eşleşmedi',
        unpairedText: 'Bilgisayarda `tuya-light serve --pair` komutunu çalıştırın, gösterdiği bağlantıyı bu telefonda açın.',
        badKeyTitle: 'Bu eşleştirme bağlantısı artık geçmiyor',
        badKeyText: 'Anahtar değişmiş. Bilgisayarda `tuya-light serve --pair` ile yeni bağlantı alın. Ana Ekran’daki uygulamadaysanız onu silip yeni bağlantıdan tekrar ekleyin.',
        setupTitle: 'Henüz ışık eklenmedi',
        setupText: 'Ampullerin yerel anahtarlarını almak için bilgisayarda bir kez `tuya-light setup` çalıştırın.',
        refusedTitle: 'Bilgisayar bu sayfayı geri çevirdi',
        errorTitle: 'Bilgisayarda bir sorun çıktı',
        tryAgain: 'Tekrar dene',
        addHint: 'Ana Ekran’a eklemek için Paylaş’a, sonra Ana Ekrana Ekle’ye dokunun.',
        dismiss: 'Kapat',
        names: {
            red: 'kırmızı', orange: 'turuncu', yellow: 'sarı', green: 'yeşil',
            cyan: 'camgöbeği', blue: 'mavi', purple: 'mor', pink: 'pembe',
        },
        builtins: {
            relax: 'Rahat', reading: 'Okuma', focus: 'Odak',
            movie: 'Film', night: 'Gece', party: 'Parti',
        },
    },
}

const lang = (navigator.language || 'en').toLowerCase().startsWith('tr') ? 'tr' : 'en'
const S = STRINGS[lang]
const fmt = (text, ...args) => args.reduce((s, a, i) => s.replace(`%${i + 1}`, a), text)
const pct = n => (lang === 'tr' ? `%${Math.round(n)}` : `${Math.round(n)}%`)

const $ = id => document.getElementById(id)
const app = $('app')

// -- state ---------------------------------------------------------------

const ui = {
    light: null,          // the last state the computer reported
    on: false,            // what the controls show; ahead of `light` while
    mode: 'white',        // commands are on their way
    shown: { bright: 50, temp: 50, hue: 0, sat: 100 },
    dragging: false,
    conn: 'loading',
    detail: '',
    badKey: false,
    devices: [],
    device: localStorage.getItem('device') || '',
    scenes: [],
    transport: 'local',
    pollMs: POLL_MS,
    lastActive: Date.now(),
    idle: false,
}

// -- colour helpers ------------------------------------------------------

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))

function hsvToHex(h, s, v) {
    const f = n => {
        const k = (n + h / 60) % 6
        return v - v * s * Math.max(0, Math.min(k, 4 - k, 1))
    }
    return '#' + [f(5), f(3), f(1)].map(x => Math.round(x * 255).toString(16).padStart(2, '0')).join('')
}

function hexToHsv(hex) {
    const n = parseInt(hex.slice(1), 16)
    const r = (n >> 16 & 255) / 255, g = (n >> 8 & 255) / 255, b = (n & 255) / 255
    const max = Math.max(r, g, b), d = max - Math.min(r, g, b)
    let h = 0
    if (d) {
        h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4
    }
    return { hue: Math.round((h * 60 + 360) % 360), sat: Math.round(max ? d / max * 100 : 0) }
}

// White light: amber at 0, near-white in the middle, pale blue at 100 (as in
// the widget's SceneInfo.qml).
function whiteColour(temperature) {
    const t = clamp(temperature, 0, 100) / 100
    let r, g, b
    if (t < 0.5) {
        const k = t / 0.5
        ;[r, g, b] = [1, 0.71 + 0.25 * k, 0.36 + 0.52 * k]
    } else {
        const k = (t - 0.5) / 0.5
        ;[r, g, b] = [1 - 0.19 * k, 0.96 - 0.07 * k, 0.88 + 0.12 * k]
    }
    return '#' + [r, g, b].map(x => Math.round(x * 255).toString(16).padStart(2, '0')).join('')
}

function luminance(hex) {
    const n = parseInt(hex.slice(1), 16)
    return (0.2126 * (n >> 16 & 255) + 0.7152 * (n >> 8 & 255) + 0.0722 * (n & 255)) / 255
}

const HUES = [[15, 'red'], [45, 'orange'], [70, 'yellow'], [165, 'green'], [200, 'cyan'],
    [256, 'blue'], [295, 'purple'], [345, 'pink'], [361, 'red']]

function hueName(hue, sat) {
    const key = HUES.find(([limit]) => hue % 360 < limit)[1]
    const name = S.names[key]
    return sat < 35 ? fmt(S.pale, name) : name
}

function toneOf(temp) {
    return temp < 34 ? 'warm' : temp > 66 ? 'cool' : 'neutral'
}

const near = (a, b, d = 2) => Math.abs(a - b) <= d
const hueNear = (a, b, d = 2) => Math.min(Math.abs(a - b), 360 - Math.abs(a - b)) <= d

function sceneLabel(scene) {
    const builtin = scene.builtin && STRINGS.en.builtins[scene.name]
    return builtin && scene.label === builtin ? S.builtins[scene.name] : scene.label
}

function sceneColour(scene) {
    if (scene.mode === 'colour') {
        return hsvToHex(scene.hue % 360, scene.saturation / 100, 0.45 + 0.55 * scene.brightness / 100)
    }
    return whiteColour(scene.temperature)
}

// "Warm, 45%" or "Blue, 18%": short enough for half a phone's width.
function describe(mode, { bright, temp, hue, sat }) {
    const what = mode === 'colour' ? hueName(hue, sat) : S[toneOf(temp)]
    return `${what}, ${pct(bright)}`
}

// -- talking to the computer -------------------------------------------------

class ApiError extends Error {
    constructor(status, data) {
        super((data && data.error) || `HTTP ${status}`)
        this.status = status
        this.data = data || {}
    }
}

async function api(path, body) {
    const url = new URL(path, location.origin)
    if (ui.device && path !== '/api/devices' && path !== '/api/scenes') {
        url.searchParams.set('device', ui.device)
    }
    const ctl = new AbortController()
    const timer = setTimeout(() => ctl.abort(), body === undefined ? POLL_TIMEOUT_MS : SEND_TIMEOUT_MS)
    let res
    try {
        res = await fetch(url, {
            method: body === undefined ? 'GET' : 'POST',
            headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
            body: body === undefined ? undefined : JSON.stringify(body),
            credentials: 'same-origin',
            cache: 'no-store',
            signal: ctl.signal,
        })
    } catch (err) {
        throw new ApiError(0, null) // the computer is off, asleep or out of reach
    } finally {
        clearTimeout(timer)
    }
    let data = null
    try {
        data = await res.json()
    } catch (err) {
        data = null
    }
    if (!res.ok) {
        throw new ApiError(res.status, data)
    }
    return data
}

// Light commands: one in flight; at most one waiting per kind, and a newer one
// of the same kind replaces it and moves to the back of the line.
const queue = new Map()
let inFlight = false
let epoch = 0 // bumped by every command, so an older poll answer is ignored
let lastSent = null

function send(kind, path, body) {
    const key = JSON.stringify(body)
    if (lastSent && lastSent.kind === kind && lastSent.key === key) {
        return
    }
    lastSent = { kind, key }
    epoch += 1
    queue.delete(kind)
    queue.set(kind, { path, body })
    pump()
}

async function pump() {
    if (inFlight || queue.size === 0) {
        return
    }
    const [kind, cmd] = queue.entries().next().value
    queue.delete(kind)
    inFlight = true
    let state = null
    try {
        state = await api(cmd.path, cmd.body)
    } catch (err) {
        inFlight = false
        queue.clear() // don't replay old commands once the computer is back
        lastSent = null
        fail(err)
        return
    }
    inFlight = false
    receive(state, state.latest !== false && queue.size === 0)
    if (queue.size) {
        pump()
    } else {
        lastSent = null
        pollLater()
    }
}

let pollTimer = 0
let failures = 0

function schedule(ms) {
    clearTimeout(pollTimer)
    pollTimer = setTimeout(poll, ms)
}

// Cloud lights: after a while without a touch, stop asking until there is one.
function pollLater() {
    if (ui.transport === 'cloud' && Date.now() - ui.lastActive > IDLE_MS) {
        ui.idle = true
        return
    }
    schedule(ui.pollMs)
}

function wake() {
    ui.lastActive = Date.now()
    if (ui.idle) {
        ui.idle = false
        poll()
    }
}

async function poll() {
    clearTimeout(pollTimer)
    if (document.hidden) {
        return // picked up again on visibilitychange
    }
    if (inFlight || queue.size || ui.dragging) {
        return schedule(ui.pollMs)
    }
    const started = epoch
    try {
        const state = await api('/api/state')
        if (started === epoch) {
            receive(state, state.latest !== false && !inFlight && queue.size === 0)
        }
        pollLater()
    } catch (err) {
        fail(err)
    }
}

function receive(state, settled) {
    failures = 0
    ui.light = state
    ui.transport = state.transport === 'cloud' ? 'cloud' : 'local'
    ui.pollMs = Math.max(2, Number(state.poll) || POLL_MS / 1000) * 1000
    if (!state.online) {
        setConn('bulb', state.error || '')
        render()
        return
    }
    setConn('ok')
    if (settled && !ui.dragging) {
        ui.on = state.on
        ui.mode = state.mode
        ui.shown = {
            bright: state.mode === 'colour' ? state.value : state.brightness,
            temp: state.temperature,
            hue: state.hue,
            sat: state.saturation,
        }
    }
    render()
}

function fail(err) {
    const status = err.status
    if (status === 401) {
        setConn(ui.badKey ? 'badkey' : 'unpaired')
    } else if (status === 503 && err.data.config) {
        setConn('setup')
        schedule(RETRY_MS * 3)
    } else if (status === 403) {
        setConn('refused', err.message)
    } else if (status === 404 && ui.device) {
        selectDevice('') // that light is gone from the list
    } else if (status === 0) {
        failures += 1
        // One miss is often the phone's network waking up: retry quietly first.
        if (failures > 1 || ui.conn === 'loading') {
            setConn('pc')
        }
        schedule(failures > 1 ? RETRY_MS : 1500)
    } else {
        setConn('error', err.message)
        schedule(RETRY_MS)
    }
    render()
}

async function refreshAll() {
    try {
        const [devices, scenes] = await Promise.all([api('/api/devices'), api('/api/scenes')])
        ui.devices = devices.devices || []
        if (ui.device && !ui.devices.some(d => d.id === ui.device)) {
            ui.device = ''
        }
        ui.scenes = Array.isArray(scenes) ? scenes : []
        renderDevices(devices.default)
        renderScenes()
    } catch (err) {
        fail(err)
        return
    }
    poll()
}

function selectDevice(id) {
    ui.device = id
    if (id) {
        localStorage.setItem('device', id)
    } else {
        localStorage.removeItem('device')
    }
    queue.clear()
    lastSent = null
    ui.light = null
    setConn('loading')
    render()
    poll()
}

// -- drawing ---------------------------------------------------------------

function setConn(conn, detail = '') {
    ui.conn = conn
    ui.detail = detail
}

function lampColour() {
    return ui.mode === 'colour' ? hsvToHex(ui.shown.hue, ui.shown.sat / 100, 1) : whiteColour(ui.shown.temp)
}

// Text with `code` spans, built without innerHTML.
function setRich(el, text) {
    el.replaceChildren(...text.split('`').map((part, i) => {
        if (i % 2 === 0) {
            return document.createTextNode(part)
        }
        const code = document.createElement('code')
        code.textContent = part
        return code
    }))
}

const NOTICES = {
    pc: ['pcTitle', 'pcText', true],
    bulb: ['bulbTitle', 'bulbText', true],
    unpaired: ['unpairedTitle', 'unpairedText', false],
    badkey: ['badKeyTitle', 'badKeyText', false],
    setup: ['setupTitle', 'setupText', true],
    refused: ['refusedTitle', null, false],
    error: ['errorTitle', null, true],
}

function render() {
    const colour = lampColour()
    const usable = ui.conn === 'ok'
    app.dataset.conn = ui.conn
    app.dataset.power = ui.on ? 'on' : 'off'
    app.dataset.mode = ui.mode
    app.style.setProperty('--lamp', colour)
    app.style.setProperty('--glow', ui.on ? (0.2 + 0.55 * ui.shown.bright / 100).toFixed(2) : '0')
    app.style.setProperty('--grip', luminance(colour) > 0.55 ? 'rgba(27, 29, 42, 0.32)' : 'rgba(255, 255, 255, 0.7)')

    // Header
    if (ui.light && ui.light.name) {
        $('name').textContent = ui.light.name
    }
    $('via').hidden = ui.transport !== 'cloud' || ui.conn !== 'ok'

    // Lamp, or a message in its place
    const notice = NOTICES[ui.conn]
    $('notice').hidden = !notice
    $('lamp').hidden = Boolean(notice)
    if (notice) {
        const [title, text, retry] = notice
        $('notice-title').textContent = S[title]
        setRich($('notice-text'), text ? S[text] : '')
        $('notice-detail').textContent = text ? ui.detail : ''
        if (!text) {
            $('notice-text').textContent = ui.detail
        }
        $('retry').hidden = !retry
    }
    const lamp = $('lamp')
    lamp.disabled = !usable
    lamp.setAttribute('aria-checked', String(ui.on))
    if (ui.conn === 'loading') {
        $('lamp-title').textContent = S.connecting
        $('lamp-detail').textContent = ''
    } else if (!ui.on) {
        $('lamp-title').textContent = S.off
        $('lamp-detail').textContent = S.tapToTurnOn
    } else if (ui.mode === 'scene') {
        $('lamp-title').textContent = S.effect
        $('lamp-detail').textContent = S.effectDetail
    } else {
        $('lamp-title').textContent = ui.mode === 'colour'
            ? hueName(ui.shown.hue, ui.shown.sat) : S[toneOf(ui.shown.temp) + 'White']
        $('lamp-detail').textContent = fmt(S.brightnessIs, pct(ui.shown.bright))
    }

    // Sliders
    const bright = $('bright')
    bright.style.setProperty('--v', ui.shown.bright)
    bright.setAttribute('aria-valuenow', ui.shown.bright)
    bright.setAttribute('aria-valuetext', pct(ui.shown.bright))
    $('bright-value').textContent = pct(ui.shown.bright)

    const temp = $('temp')
    const tone = ui.mode === 'white' ? S[toneOf(ui.shown.temp)] : '–'
    temp.style.setProperty('--v', ui.shown.temp)
    temp.setAttribute('aria-valuenow', ui.shown.temp)
    temp.setAttribute('aria-valuetext', tone)
    $('temp-value').textContent = tone

    for (const el of [bright, temp, $('more-colour')]) {
        el.toggleAttribute('aria-disabled', !usable)
    }

    // Colours
    for (const button of document.querySelectorAll('.swatch[data-hue]')) {
        const on = ui.on && ui.mode === 'colour'
            && hueNear(ui.shown.hue, Number(button.dataset.hue)) && near(ui.shown.sat, Number(button.dataset.sat))
        button.setAttribute('aria-pressed', String(on))
    }
    const more = $('more-colour')
    if (document.activeElement !== more) {
        more.value = hsvToHex(ui.shown.hue, ui.shown.sat / 100, 1)
    }

    // Scenes
    for (const button of $('scenes').children) {
        const scene = button.scene
        let on = false
        if (ui.on && scene.mode === 'white') {
            on = ui.mode === 'white' && near(ui.shown.bright, scene.brightness) && near(ui.shown.temp, scene.temperature)
        } else if (ui.on) {
            on = ui.mode === 'colour' && hueNear(ui.shown.hue, scene.hue) && near(ui.shown.sat, scene.saturation)
                && near(ui.shown.bright, scene.brightness)
        }
        button.setAttribute('aria-pressed', String(on))
    }

    $('hint').hidden = !(usable && showHint())
}

function renderDevices(defaultId) {
    const select = $('device')
    const several = ui.devices.length > 1
    $('device-wrap').hidden = !several
    $('name').hidden = several
    if (!several) {
        return
    }
    select.replaceChildren(...ui.devices.map(d => new Option(d.name, d.id)))
    select.value = ui.device || defaultId || ui.devices[0].id
}

function renderScenes() {
    $('scenes').replaceChildren(...ui.scenes.map(scene => {
        const button = document.createElement('button')
        button.type = 'button'
        button.className = 'scene'
        button.scene = scene
        const dot = document.createElement('span')
        dot.className = 'scene-dot'
        dot.style.setProperty('--c', sceneColour(scene))
        const label = document.createElement('span')
        label.className = 'scene-label'
        label.textContent = sceneLabel(scene)
        const desc = document.createElement('span')
        desc.className = 'scene-desc'
        desc.textContent = describe(scene.mode, {
            bright: scene.brightness, temp: scene.temperature, hue: scene.hue, sat: scene.saturation,
        })
        button.append(dot, label, desc)
        button.addEventListener('click', () => applyScene(scene))
        return button
    }))
    render()
}

// -- actions ---------------------------------------------------------------

function usable() {
    return ui.conn === 'ok'
}

function togglePower() {
    if (!usable()) {
        return
    }
    ui.on = !ui.on
    render()
    send('power', '/api/power', { on: ui.on })
}

// `final` is false while a finger is still moving. Local lights get every
// step (the queue keeps it to the first and the last); cloud lights only the
// value where the movement ended.
const wants = final => final || ui.transport !== 'cloud'

function setBrightness(value, final = true) {
    ui.shown.bright = value
    ui.on = true // the core switches the light on for any change
    render()
    if (wants(final)) {
        send('brightness', '/api/brightness', { value })
    }
}

function setTemperature(value, final = true) {
    ui.shown.temp = value
    ui.mode = 'white'
    ui.on = true
    render()
    if (wants(final)) {
        send('temperature', '/api/temperature', { value })
    }
}

function setColour(hue, sat, final = true) {
    ui.shown.hue = hue
    ui.shown.sat = sat
    if (ui.mode !== 'colour') {
        ui.shown.bright = Math.max(ui.shown.bright, 5)
    }
    ui.mode = 'colour'
    ui.on = true
    render()
    if (wants(final)) {
        send('colour', '/api/colour', { hue, saturation: sat, value: Math.max(5, ui.shown.bright) })
    }
}

function applyScene(scene) {
    if (!usable()) {
        return
    }
    ui.on = true
    ui.mode = scene.mode
    ui.shown = scene.mode === 'white'
        ? { ...ui.shown, bright: scene.brightness, temp: scene.temperature }
        : { ...ui.shown, bright: scene.brightness, hue: scene.hue, sat: scene.saturation }
    render()
    send('scene', '/api/scene', { name: scene.name })
}

// A slider: drag sideways or tap anywhere on it. A vertical swipe that starts
// on it scrolls the page instead (touch-action: pan-y), and changes nothing.
function bindBar(el, min, apply) {
    let start = null
    const valueAt = x => {
        const box = el.getBoundingClientRect()
        return Math.round(clamp(min + (x - box.left) / box.width * (100 - min), min, 100))
    }
    el.addEventListener('pointerdown', e => {
        if (!usable() || e.button > 0) {
            return
        }
        start = { id: e.pointerId, x: e.clientX, moved: false }
    })
    el.addEventListener('pointermove', e => {
        if (!start || e.pointerId !== start.id) {
            return
        }
        if (!start.moved) {
            if (Math.abs(e.clientX - start.x) < 6) {
                return
            }
            start.moved = true
            ui.dragging = true
            el.setPointerCapture(e.pointerId)
        }
        start.last = valueAt(e.clientX)
        apply(start.last, false)
    })
    el.addEventListener('pointerup', e => {
        if (!start || e.pointerId !== start.id) {
            return
        }
        start = null
        ui.dragging = false
        apply(valueAt(e.clientX))
    })
    el.addEventListener('pointercancel', () => {
        const last = start && start.moved ? start.last : null
        start = null
        ui.dragging = false
        if (last !== null && last !== undefined) {
            apply(last, true) // the browser took the gesture over mid-drag
        }
    })
    el.addEventListener('keydown', e => {
        if (!usable()) {
            return
        }
        const now = Number(el.getAttribute('aria-valuenow'))
        const step = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 10, PageDown: -10 }[e.key]
        let next = null
        if (step !== undefined) {
            next = now + step * (e.shiftKey ? 10 : 1)
        } else if (e.key === 'Home') {
            next = min
        } else if (e.key === 'End') {
            next = 100
        }
        if (next !== null) {
            e.preventDefault()
            apply(clamp(next, min, 100))
        }
    })
}

// -- Home Screen hint ------------------------------------------------------

function showHint() {
    const ios = /iPhone|iPad|iPod/.test(navigator.userAgent)
        || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
    const standalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone === true
    return ios && !standalone && localStorage.getItem('hint-closed') !== '1'
}

// -- start -----------------------------------------------------------------

function start() {
    document.documentElement.lang = lang
    for (const el of document.querySelectorAll('[data-t]')) {
        el.textContent = S[el.dataset.t]
    }
    for (const el of document.querySelectorAll('[data-t-label]')) {
        el.setAttribute('aria-label', S[el.dataset.tLabel])
    }

    const more = document.querySelector('.swatch-more')
    for (const [name, hex] of SWATCHES) {
        const { hue, sat } = hexToHsv(hex)
        const button = document.createElement('button')
        button.type = 'button'
        button.className = 'swatch'
        button.dataset.hue = hue
        button.dataset.sat = sat
        button.style.setProperty('--c', hex)
        button.setAttribute('aria-label', S.names[name])
        button.addEventListener('click', () => usable() && setColour(hue, sat))
        more.before(button)
    }
    // The system colour picker reports while you choose and once at the end.
    let pickTimer = 0
    const pick = final => e => {
        if (!usable()) {
            return
        }
        const { hue, sat } = hexToHsv(e.target.value)
        clearTimeout(pickTimer)
        setColour(hue, sat, final)
        if (!final && !wants(false)) { // cloud: send once the choice rests
            pickTimer = setTimeout(() => setColour(hue, sat, true), 700)
        }
    }
    $('more-colour').addEventListener('input', pick(false))
    $('more-colour').addEventListener('change', pick(true))

    $('lamp').addEventListener('click', togglePower)
    bindBar($('bright'), 1, setBrightness)
    bindBar($('temp'), 0, setTemperature)
    $('device').addEventListener('change', e => selectDevice(e.target.value))
    $('retry').addEventListener('click', () => {
        failures = 0
        setConn('loading')
        render()
        refreshAll()
    })
    $('hint-close').addEventListener('click', () => {
        localStorage.setItem('hint-closed', '1')
        render()
    })

    if (location.hash === '#bad-key') {
        ui.badKey = true
        history.replaceState(null, '', '/')
    }

    // Back from the background or the lock screen: look again right away.
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            ui.lastActive = Date.now()
            ui.idle = false
            refreshAll()
        }
    })
    document.addEventListener('pointerdown', wake, { capture: true, passive: true })
    document.addEventListener('keydown', wake, { capture: true })
    window.addEventListener('pageshow', e => e.persisted && refreshAll())
    window.addEventListener('online', () => refreshAll())

    // An offline copy of the page needs a secure context (HTTPS or localhost);
    // over plain HTTP the page simply loads from the computer each time.
    if (window.isSecureContext && 'serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(() => {})
    }

    render()
    refreshAll()
}

start()

/*
    SPDX-FileCopyrightText: 2026 Yakup Emre Yerli
    SPDX-License-Identifier: GPL-2.0-or-later
*/

// The phone page: the panel widget's popup, for a phone. It talks to
// `tuya-light serve` and keeps the widget's rules: one light command at a
// time, a newer command replaces one that is still waiting, and the controls
// never jump back to an answer that is already out of date.
//
// A light reached through the Tuya cloud costs an API call per request, so
// for those the page sends a value only where a drag stops, asks for the
// state less often (the server says how often), and stops asking after five
// quiet minutes until the page is touched or shown again.

const POLL_MS = 4000
const IDLE_MS = 5 * 60 * 1000
const RETRY_MS = 5000
const POLL_TIMEOUT_MS = 12000
const SEND_TIMEOUT_MS = 25000

const STRINGS = {
    en: {
        light: 'Light',
        power: 'Light on',
        colour: 'Colour',
        brightness: 'Brightness',
        white: 'White temperature',
        warm: 'Warm', neutral: 'Neutral', cool: 'Cool',
        scenes: 'Scenes',
        favourites: 'Favourite colours',
        viaCloud: 'Tuya cloud',
        connecting: 'Connecting…',
        pcTitle: "Can't reach your computer",
        pcText: 'Is it switched on and awake? This phone has to be on your home Wi-Fi, or connected to Tailscale.',
        serverTitle: "Can't reach the server",
        serverText: 'Check that this phone is online and that tuya-light is running on the server.',
        bulbTitle: 'The light is not answering',
        bulbText: 'Is it switched on at the wall and on the same network?',
        unpairedTitle: 'This phone is not paired yet',
        unpairedText: 'On the computer, run `tuya-light serve --pair` and open the link it shows on this phone.',
        badKeyTitle: 'That pairing link no longer works',
        badKeyText: 'The key has been changed. Run `tuya-light serve --pair` on the computer for a new link. If this is the Home Screen app, delete it and add it again from the new link.',
        setupTitle: 'No lights set up yet',
        setupText: 'Run `tuya-light setup` on the computer once to fetch your bulbs’ local keys.',
        refusedTitle: 'The computer turned this page away',
        errorTitle: 'Something went wrong on the computer',
        tryAgain: 'Try again',
        addHint: 'To keep this on your Home Screen, tap Share, then Add to Home Screen.',
        dismiss: 'Close',
        names: {
            red: 'Red', orange: 'Orange', yellow: 'Yellow', green: 'Green',
            cyan: 'Cyan', blue: 'Blue', purple: 'Purple', pink: 'Pink',
        },
        builtins: {
            relax: 'Relax', reading: 'Reading', focus: 'Focus',
            movie: 'Movie', night: 'Night', party: 'Party',
        },
    },
    tr: {
        light: 'Işık',
        power: 'Işık açık',
        colour: 'Renk',
        brightness: 'Parlaklık',
        white: 'Beyaz ışık sıcaklığı',
        warm: 'Sıcak', neutral: 'Nötr', cool: 'Soğuk',
        scenes: 'Sahneler',
        favourites: 'Favori renkler',
        viaCloud: 'Tuya bulutu',
        connecting: 'Bağlanıyor…',
        pcTitle: 'Bilgisayara ulaşılamıyor',
        pcText: 'Bilgisayar açık ve uyanık mı? Telefon evdeki Wi-Fi’a ya da Tailscale’e bağlı olmalı.',
        serverTitle: 'Sunucuya ulaşılamıyor',
        serverText: 'Telefonun internete bağlı olduğuna ve sunucuda tuya-light’ın çalıştığına bakın.',
        bulbTitle: 'Işık cevap vermiyor',
        bulbText: 'Anahtardan açık ve aynı ağda mı?',
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
            red: 'Kırmızı', orange: 'Turuncu', yellow: 'Sarı', green: 'Yeşil',
            cyan: 'Camgöbeği', blue: 'Mavi', purple: 'Mor', pink: 'Pembe',
        },
        builtins: {
            relax: 'Rahat', reading: 'Okuma', focus: 'Odak',
            movie: 'Film', night: 'Gece', party: 'Parti',
        },
    },
}

const lang = (navigator.language || 'en').toLowerCase().startsWith('tr') ? 'tr' : 'en'
const S = STRINGS[lang]
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
    favourites: [],       // shared favourite colours, as #rrggbb
    transport: 'local',
    pollMs: POLL_MS,
    lastActive: Date.now(),
    idle: false,
}

// -- colour helpers (the widget's SceneInfo.qml and ColorWheel.qml) ----------

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
const hex = channels => '#' + channels.map(x => Math.round(x * 255).toString(16).padStart(2, '0')).join('')

function hsvToHex(h, s, v) {
    const f = n => {
        const k = (n + h / 60) % 6
        return v - v * s * Math.max(0, Math.min(k, 4 - k, 1))
    }
    return hex([f(5), f(3), f(1)])
}

// White light: amber at 0, near-white in the middle, pale blue at 100.
function whiteColour(temperature) {
    const t = clamp(temperature, 0, 100) / 100
    if (t < 0.5) {
        const k = t / 0.5
        return hex([1, 0.71 + 0.25 * k, 0.36 + 0.52 * k])
    }
    const k = (t - 0.5) / 0.5
    return hex([1 - 0.19 * k, 0.96 - 0.07 * k, 0.88 + 0.12 * k])
}

const HUES = [[15, 'red'], [45, 'orange'], [70, 'yellow'], [165, 'green'], [200, 'cyan'],
    [256, 'blue'], [295, 'purple'], [345, 'pink'], [361, 'red']]

const hueName = hue => S.names[HUES.find(([limit]) => hue % 360 < limit)[1]]
const toneOf = temp => (temp < 34 ? 'warm' : temp > 66 ? 'cool' : 'neutral')
const near = (a, b, d = 2) => Math.abs(a - b) <= d
function hexToHsv(value) {
    const n = parseInt(value.slice(1), 16)
    const r = (n >> 16 & 255) / 255, g = (n >> 8 & 255) / 255, b = (n & 255) / 255
    const max = Math.max(r, g, b), d = max - Math.min(r, g, b)
    let h = 0
    if (d) {
        h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4
    }
    return { hue: Math.round((h * 60 + 360) % 360), sat: Math.round(max ? d / max * 100 : 0) }
}

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
    app.toggleAttribute('data-busy', true)
    let state = null
    try {
        state = await api(cmd.path, cmd.body)
    } catch (err) {
        inFlight = false
        app.toggleAttribute('data-busy', false)
        queue.clear() // don't replay old commands once the computer is back
        lastSent = null
        fail(err)
        return
    }
    inFlight = false
    app.toggleAttribute('data-busy', queue.size > 0)
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
        const [devices, scenes, favourites] = await Promise.all(
            [api('/api/devices'), api('/api/scenes'),
                api('/api/favourites').catch(() => ({ colours: [] }))])
        ui.devices = devices.devices || []
        if (ui.device && !ui.devices.some(d => d.id === ui.device)) {
            ui.device = ''
        }
        ui.scenes = Array.isArray(scenes) ? scenes : []
        ui.favourites = Array.isArray(favourites.colours) ? favourites.colours : []
        renderDevices(devices.default)
        renderFavourites()
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

// Line icons for the message, in the spirit of Breeze's.
const ICONS = {
    disconnected: 'M17 31l-4 4a5.7 5.7 0 0 1-8-8l4-4M31 17l4-4a5.7 5.7 0 0 0-8-8l-4 4M19 29l-3 3M29 19l3-3M8 8l32 32',
    key: 'M20 28a8 8 0 1 1 5.7-2.3L40 40M33 33l3-3M37 37l3-3',
    setup: 'M24 6v6M24 36v6M6 24h6M36 24h6M11.3 11.3l4.2 4.2M32.5 32.5l4.2 4.2M11.3 36.7l4.2-4.2M32.5 15.5l4.2-4.2M24 30a6 6 0 1 0 0-12 6 6 0 0 0 0 12z',
}

// Opened by a home address (LAN, Tailscale, .local) or by a public name?
const atHome = /^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|100\.|\[|[^.]+$|.*\.(local|lan|home|internal|ts\.net)$)/
    .test(location.hostname)

const NOTICES = {
    loading: [null, 'connecting', null, false],
    pc: atHome ? ['disconnected', 'pcTitle', 'pcText', true]
        : ['disconnected', 'serverTitle', 'serverText', true],
    bulb: ['disconnected', 'bulbTitle', 'bulbText', true],
    unpaired: ['key', 'unpairedTitle', 'unpairedText', false],
    badkey: ['key', 'badKeyTitle', 'badKeyText', false],
    setup: ['setup', 'setupTitle', 'setupText', true],
    refused: ['key', 'refusedTitle', null, false],
    error: ['disconnected', 'errorTitle', null, true],
}

function render() {
    const usable = ui.conn === 'ok'
    app.dataset.conn = ui.conn
    app.dataset.power = ui.on ? 'on' : 'off'
    app.dataset.mode = ui.mode

    // Heading
    if (ui.light && ui.light.name) {
        $('name').textContent = ui.light.name
    }
    $('via').hidden = ui.transport !== 'cloud' || !usable
    const power = $('power')
    power.disabled = !usable
    power.setAttribute('aria-checked', String(ui.on))

    // A message in place of the controls
    const notice = NOTICES[ui.conn]
    $('notice').hidden = !notice
    if (notice) {
        const [icon, title, text, retry] = notice
        const svg = $('notice-icon')
        svg.hidden = !icon
        if (icon) {
            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
            path.setAttribute('d', ICONS[icon])
            svg.replaceChildren(path)
        }
        $('notice-title').textContent = S[title]
        setRich($('notice-text'), text ? S[text] : ui.detail)
        $('notice-detail').textContent = text ? ui.detail : ''
        $('retry').hidden = !retry
    }

    // Colour wheel
    const wheel = $('wheel')
    wheel.style.setProperty('--hue', ui.shown.hue)
    wheel.style.setProperty('--sat', ui.shown.sat)
    wheel.style.setProperty('--knob', hsvToHex(ui.shown.hue, ui.shown.sat / 100, 1))
    wheel.setAttribute('aria-valuenow', ui.shown.hue)
    wheel.setAttribute('aria-valuetext', `${hueName(ui.shown.hue)}, ${pct(ui.shown.sat)}`)

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
    for (const el of [bright, temp]) {
        el.toggleAttribute('aria-disabled', !ui.on)
    }

    // Favourites
    for (const button of $('favourites').children) {
        const on = ui.on && ui.mode === 'colour' && hueNear(ui.shown.hue, button.hsv.hue)
            && near(ui.shown.sat, button.hsv.sat)
        button.setAttribute('aria-pressed', String(on))
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

// Only when there are any: the widget shows them only when chosen, too.
function renderFavourites() {
    const row = $('favourites')
    row.hidden = ui.favourites.length === 0
    row.replaceChildren(...ui.favourites.map(colour => {
        const button = document.createElement('button')
        button.type = 'button'
        button.className = 'swatch'
        button.hsv = hexToHsv(colour)
        button.style.setProperty('--c', colour)
        button.setAttribute('aria-label', hueName(button.hsv.hue))
        button.addEventListener('click', () => usable() && setColour(button.hsv.hue, button.hsv.sat))
        return button
    }))
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
        button.append(dot, label)
        button.addEventListener('click', () => applyScene(scene))
        return button
    }))
    render()
}

// -- actions ---------------------------------------------------------------

const usable = () => ui.conn === 'ok'

// `final` is false while a finger is still moving. Local lights get every
// step (the queue keeps it to the first and the last); cloud lights only the
// value where the movement ended.
const wants = final => final || ui.transport !== 'cloud'

function togglePower() {
    if (!usable()) {
        return
    }
    ui.on = !ui.on
    render()
    send('power', '/api/power', { on: ui.on })
}

function setBrightness(value, final = true) {
    ui.shown.bright = value
    render()
    if (wants(final)) {
        send('brightness', '/api/brightness', { value })
    }
}

function setTemperature(value, final = true) {
    ui.shown.temp = value
    ui.mode = 'white'
    render()
    if (wants(final)) {
        send('temperature', '/api/temperature', { value })
    }
}

// As in the widget: picking on the wheel turns the light on, in colour,
// keeping its brightness (at least 5 %).
function setColour(hue, sat, final = true) {
    ui.shown.hue = hue
    ui.shown.sat = sat
    ui.mode = 'colour'
    ui.on = true
    render()
    if (wants(final)) {
        send('colour', '/api/colour', { hue, saturation: sat, value: Math.max(5, Math.round(ui.shown.bright)) })
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

// One finger on a control: follow it until it lifts. `read(e)` turns the
// pointer into a value; `apply(value, final)` shows and sends it.
function track(el, read, apply, allowed) {
    let id = null
    let last = null
    el.addEventListener('pointerdown', e => {
        if (!allowed() || e.button > 0) {
            return
        }
        id = e.pointerId
        el.setPointerCapture(id)
        ui.dragging = true
        last = read(e)
        apply(last, false)
    })
    el.addEventListener('pointermove', e => {
        if (e.pointerId === id) {
            last = read(e)
            apply(last, false)
        }
    })
    const finish = e => {
        if (e.pointerId !== id) {
            return
        }
        id = null
        ui.dragging = false
        apply(last, true)
    }
    el.addEventListener('pointerup', finish)
    el.addEventListener('pointercancel', finish)
}

function bindSlider(el, min, apply) {
    // The handle's centre runs from 13 px in from each end, as the CSS draws it.
    const read = e => {
        const box = el.getBoundingClientRect()
        return Math.round(clamp(min + (e.clientX - box.left - 13) / (box.width - 26) * (100 - min), min, 100))
    }
    track(el, read, apply, () => usable() && ui.on)
    el.addEventListener('keydown', e => {
        if (!usable() || !ui.on) {
            return
        }
        const now = Number(el.getAttribute('aria-valuenow'))
        const step = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 10, PageDown: -10 }[e.key]
        const next = step !== undefined ? now + step * (e.shiftKey ? 10 : 1)
            : e.key === 'Home' ? min : e.key === 'End' ? 100 : null
        if (next !== null) {
            e.preventDefault()
            apply(clamp(next, min, 100), true)
        }
    })
}

// Hue around the circle (red at three o'clock, clockwise), saturation from the
// centre out: the same geometry as the widget's ColorWheel.qml.
function bindWheel(el) {
    const read = e => {
        const box = el.getBoundingClientRect()
        const dx = e.clientX - (box.left + box.width / 2)
        const dy = e.clientY - (box.top + box.height / 2)
        const hue = (Math.round(Math.atan2(dy, dx) * 180 / Math.PI) + 360) % 360
        return { hue, sat: Math.round(Math.min(100, Math.hypot(dx, dy) / (box.width / 2) * 100)) }
    }
    track(el, read, (v, final) => setColour(v.hue, v.sat, final), usable)
    el.addEventListener('keydown', e => {
        if (!usable()) {
            return
        }
        const turn = { ArrowRight: 5, ArrowLeft: -5 }[e.key]
        const reach = { ArrowUp: 5, ArrowDown: -5 }[e.key]
        if (turn !== undefined || reach !== undefined) {
            e.preventDefault()
            setColour((ui.shown.hue + (turn || 0) + 360) % 360, clamp(ui.shown.sat + (reach || 0), 0, 100))
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

    $('power').addEventListener('click', togglePower)
    bindWheel($('wheel'))
    bindSlider($('bright'), 1, setBrightness)
    bindSlider($('temp'), 0, setTemperature)
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
    // iOS pinch gestures: the page stays at its size.
    for (const name of ['gesturestart', 'gesturechange']) {
        document.addEventListener(name, e => e.preventDefault(), { passive: false })
    }
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

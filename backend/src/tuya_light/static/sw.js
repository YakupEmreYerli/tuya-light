/*
    SPDX-FileCopyrightText: 2026 Yakup Emre Yerli
    SPDX-License-Identifier: GPL-2.0-or-later
*/

// Keeps a copy of the page so that, when the computer is off, the app still
// opens and says so instead of showing the browser's error page. Browsers run
// this only on HTTPS or localhost. The API and the manifest are never cached:
// the first is live state, the second carries the pairing key.

const CACHE = 'tuya-light-1'
const SHELL = ['/', '/app.css', '/app.js', '/icon.svg', '/apple-touch-icon.png']

self.addEventListener('install', event => {
    event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', event => {
    event.waitUntil(caches.keys()
        .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
        .then(() => self.clients.claim()))
})

self.addEventListener('fetch', event => {
    const request = event.request
    const url = new URL(request.url)
    if (request.method !== 'GET' || url.origin !== self.location.origin) {
        return
    }
    if (request.mode === 'navigate' && url.pathname === '/') {
        // Includes the Home Screen launch at /?key=..., which the computer
        // answers with a redirect; offline, open the saved page instead.
        event.respondWith(fetch(request).catch(() => caches.match('/')))
        return
    }
    if (url.search || !SHELL.includes(url.pathname)) {
        return
    }
    event.respondWith(fetch(request)
        .then(response => {
            if (response.ok) {
                const copy = response.clone()
                caches.open(CACHE).then(cache => cache.put(request, copy))
            }
            return response
        })
        .catch(() => caches.match(request).then(found => found || Response.error())))
})

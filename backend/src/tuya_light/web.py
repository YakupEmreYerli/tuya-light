"""The phone page: a small HTTP server on the PC, opened from a phone.

`tuya-light serve` serves one page (static files in ``static/``) and a JSON
API on top of the same core as the CLI and the MCP server. Bulb traffic goes
through one LightWorker per bulb, so a slider dragged on the phone sends the
first and the last value, never a flood.

Access is guarded by one random key, made on first use and kept next to
devices.json (0600). The phone opens ``/?key=...`` once; the key becomes an
HttpOnly, SameSite=Strict cookie and the address bar is cleaned. Every API
call needs that cookie. On top of it the server only answers to its own
addresses and names (no DNS rebinding), and changes need a same-origin JSON
request. Local keys, cloud credentials and devices.json never leave the
server: the API knows devices by id and name only.

Behind a reverse proxy (`--trust-proxy`) the X-Forwarded-Host/Proto/For
headers are believed; without the flag they are ignored, since anyone could
send them.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import hmac
import http.cookies
import io
import ipaddress
import json
import math
import os
import re
import secrets
import shutil
import socket
import socketserver
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, urlsplit

from . import __version__, config
from . import scenes as scene_store
from .backend import transport_for
from .config import ConfigError, Device
from .light import BaseLight, LightError
from .worker import LightWorker

DEFAULT_PORT = 8892  # "TUYA" on a phone keypad
COOKIE = "tuya_light"
COOKIE_MAX_AGE = 400 * 24 * 3600  # the longest browsers keep a cookie
SERVICE = "tuya-light-serve.service"
MAX_BODY = 4096
STATE_MAX_AGE = 2.0  # several phones polling share one bulb read
WAIT = 20.0  # longest a request waits for the bulb
LOCAL_POLL = 4  # seconds between state reads of an open page, local bulbs
CLOUD_POLL = 30  # ... cloud bulbs (each read is an API call); see --cloud-poll
CLOUD_SETTLE = 0.6  # a change to a cloud bulb waits this long for a newer one
TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")

STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; manifest-src 'self'; worker-src 'self'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
}

_REDACT = re.compile(r"(key=)[^&\s\"']+")


# -- the key ---------------------------------------------------------------


def key_path() -> Path:
    return config.config_path().with_name("web.key")


class KeyStore:
    """The pairing key, re-read when the file changes, so `serve --rotate-key`
    locks out paired phones at once, without restarting the server."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or key_path()
        self._lock = threading.Lock()
        self._key = ""
        self._stamp: tuple | None = None

    def get(self) -> str:
        with self._lock:
            try:
                st = self.path.stat()
            except FileNotFoundError:
                return self._write(secrets.token_urlsafe(32))
            stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
            if stamp != self._stamp:
                if st.st_uid == os.getuid() and st.st_mode & 0o077:
                    os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
                key = self.path.read_text(encoding="utf-8").strip()
                if len(key) < 16:
                    return self._write(secrets.token_urlsafe(32))
                self._key, self._stamp = key, stamp
            return self._key

    def rotate(self) -> str:
        with self._lock:
            return self._write(secrets.token_urlsafe(32))

    def matches(self, given: str) -> bool:
        key = self.get()
        return bool(given) and hmac.compare_digest(given.encode(), key.encode())

    def _write(self, key: str) -> str:
        config.write_private(self.path, key + "\n")
        st = self.path.stat()
        self._key, self._stamp = key, (st.st_mtime_ns, st.st_size, st.st_ino)
        return key


# -- where this computer can be reached --------------------------------------


def _is_physical(ifname: str) -> bool:
    # Real network cards have a device link; bridges, Docker, VPN tunnels don't.
    return Path("/sys/class/net", ifname, "device").exists()


def parse_addresses(data: list, is_physical: Callable[[str], bool] = _is_physical
                    ) -> list[tuple[str, str]]:
    """``ip -j -4 addr`` output -> [(label, address)], Tailscale first."""
    tailnet, home = [], []
    for iface in data or []:
        name = str(iface.get("ifname", ""))
        for info in iface.get("addr_info") or []:
            if info.get("family", "inet") != "inet":
                continue
            try:
                addr = ipaddress.ip_address(info.get("local", ""))
            except ValueError:
                continue
            if addr.is_loopback:
                continue
            if name.startswith("tailscale") or addr in TAILSCALE_NET:
                tailnet.append(("Tailscale", str(addr)))
            elif addr.is_private and is_physical(name):
                home.append((f"Home network ({name})", str(addr)))
    return tailnet + home


def _primary_address() -> str | None:
    # Asks the routing table which source address would be used; sends nothing.
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]
    return None


def local_addresses() -> list[tuple[str, str]]:
    try:
        out = subprocess.run(["ip", "-j", "-4", "addr", "show"], capture_output=True,
                             text=True, timeout=3, check=False).stdout
        found = parse_addresses(json.loads(out or "[]"))
    except (OSError, subprocess.SubprocessError, ValueError):
        found = []
    if not any(label != "Tailscale" for label, _ in found):
        primary = _primary_address()
        if primary and primary not in [a for _, a in found]:
            found.append(("This computer", primary))
    return found


def tailscale_name() -> str | None:
    """This computer's MagicDNS name, if Tailscale is installed and up."""
    if not shutil.which("tailscale"):
        return None
    try:
        out = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True,
                             timeout=2, check=False).stdout
        name = json.loads(out).get("Self", {}).get("DNSName") or ""
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None
    return name.rstrip(".").lower() or None


def own_names(extra: tuple[str, ...] = ()) -> set[str]:
    host = socket.gethostname().lower()
    names = {"localhost", host, f"{host}.local", *(n.lower().rstrip(".") for n in extra)}
    ts = tailscale_name()
    if ts:
        names.add(ts)
    return {n for n in names if n}


def _hostname(netloc: str) -> str:
    """'example:8892' -> 'example'; '[fe80::1]:8892' -> 'fe80::1'."""
    try:
        return (urlsplit("//" + netloc).hostname or "").rstrip(".")
    except ValueError:
        return ""


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


# -- the HTTP server ---------------------------------------------------------


class BadRequest(Exception):
    def __init__(self, status: int, message: str, **extra) -> None:
        super().__init__(message)
        self.status, self.extra = status, extra


def _number(body: dict, key: str, required: bool = True) -> float | None:
    value = body.get(key)
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BadRequest(400, f"`{key}` must be a number")
    return float(value)


def _no_constants(name: str):
    raise ValueError(f"{name} is not a number")


class Handler(BaseHTTPRequestHandler):
    server: "PhoneServer"
    server_version = f"tuya-light/{__version__}"
    protocol_version = "HTTP/1.1"
    timeout = 30  # idle keep-alive connections

    # -- plumbing ------------------------------------------------------------

    def version_string(self) -> str:
        return self.server_version

    def log_request(self, code="-", size="-") -> None:
        if isinstance(code, int) and code >= 400:
            self.log_message('"%s %s" %d', self.command, urlsplit(self.path).path, code)

    def log_message(self, format: str, *args) -> None:
        self.server.log(_REDACT.sub(r"\1...", f"{self.address_string()} {format % args}"))

    def address_string(self) -> str:
        forwarded = self._forwarded("X-Forwarded-For")
        return forwarded or super().address_string()

    def _forwarded(self, name: str) -> str:
        """A proxy header's first value, only with --trust-proxy."""
        if not self.server.trust_proxy:
            return ""
        return (self.headers.get(name) or "").split(",")[0].strip()

    def _host_header(self) -> str:
        return self._forwarded("X-Forwarded-Host") or self.headers.get("Host", "")

    def _scheme(self) -> str:
        proto = self._forwarded("X-Forwarded-Proto").lower()
        return proto if proto in ("http", "https") else "http"

    def _send(self, status: int, body: bytes, ctype: str, headers: dict | None = None) -> None:
        self.send_response(status)
        for name, value in {**SECURITY_HEADERS, **(headers or {})}.items():
            self.send_header(name, value)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, data, headers: dict | None = None) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self._send(status, body, "application/json; charset=utf-8",
                   {"Cache-Control": "no-store", **(headers or {})})

    def _redirect(self, location: str, headers: dict | None = None) -> None:
        self._send(303, b"", "text/plain; charset=utf-8",
                   {"Location": location, "Cache-Control": "no-store", **(headers or {})})

    def _host(self) -> str:
        return _hostname(self._host_header()).lower()

    def _host_ok(self) -> bool:
        # IP addresses are always fine: a DNS rebinding attack needs a name.
        host = self._host()
        return bool(host) and (_is_ip(host) or self.server.known_name(host))

    def _host_refused(self) -> None:
        host = self._host() or "?"
        self._json(403, {"error": f"this server does not answer to the name {host!r}; "
                                  f"start it with --allow-host {host}"})

    def _authed(self) -> bool:
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            return False
        morsel = jar.get(COOKIE)
        return morsel is not None and self.server.keys.matches(morsel.value)

    def _same_origin(self) -> bool:
        # A page on another site can neither read nor change anything: the cookie
        # is SameSite=Strict, and changes need a same-origin JSON request on top.
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site not in ("same-origin", "none"):
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return False
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https"):
            return False
        if parts.netloc.lower() == self._host_header().lower():
            return True
        # A trusted proxy (TLS in front, say) may pass on a rewritten Host and
        # no X-Forwarded-Host; then a name this server answers to is fine.
        # Without one, the port must match too: another web app on this
        # machine is the same "site" as far as cookies go.
        if not self.server.trust_proxy:
            return False
        name = (parts.hostname or "").rstrip(".").lower()
        return bool(name) and not _is_ip(name) and self.server.known_name(name)

    def _cookie_header(self) -> dict:
        key = self.server.keys.get()
        secure = "; Secure" if self._scheme() == "https" else ""
        return {"Set-Cookie": f"{COOKIE}={key}; Max-Age={COOKIE_MAX_AGE}; Path=/; "
                              f"HttpOnly; SameSite=Strict{secure}"}

    # -- methods -------------------------------------------------------------

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path.startswith("/api/"):
            return self._api("GET", url.path, url.query, {})
        if url.path == "/" and "key" in parse_qs(url.query):
            return self._pair(parse_qs(url.query)["key"][0])
        if url.path == "/manifest.webmanifest":
            return self._manifest()
        if url.path in STATIC:
            return self._static(url.path)
        self._json(404, {"error": "not found"})

    def do_HEAD(self) -> None:
        url = urlsplit(self.path)
        if url.path in STATIC:
            return self._static(url.path)
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        url = urlsplit(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self.close_connection = True
            return self._json(413, {"error": "request too large"})
        raw = self.rfile.read(length) if length else b""
        if not url.path.startswith("/api/"):
            return self._json(404, {"error": "not found"})
        self._api("POST", url.path, url.query, raw)

    def do_OPTIONS(self) -> None:  # no CORS: other sites get nothing here
        self._json(405, {"error": "method not allowed"}, {"Allow": "GET, HEAD, POST"})

    # -- pages ---------------------------------------------------------------

    def _static(self, path: str) -> None:
        name, ctype = STATIC[path]
        try:
            body = (resources.files("tuya_light") / "static" / name).read_bytes()
        except OSError:
            return self._json(404, {"error": "not found"})
        etag = '"%s"' % hashlib.sha256(body).hexdigest()[:20]
        headers = {"Cache-Control": "no-cache", "ETag": etag}
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            for k, v in {**SECURITY_HEADERS, **headers}.items():
                self.send_header(k, v)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send(200, body, ctype, headers)

    def _pair(self, given: str) -> None:
        if not self._host_ok():
            return self._host_refused()
        if self.server.keys.matches(given):
            return self._redirect("/", self._cookie_header())
        time.sleep(self.server.bad_key_delay)  # guessing stays slow
        self._redirect("/#bad-key")

    def _manifest(self) -> None:
        # The Home Screen app on iOS keeps its own cookies, apart from Safari's.
        # A paired phone gets a start address that pairs the app itself on
        # every launch (the server cleans the address bar right away).
        start = "/"
        if self._host_ok() and self._authed():
            start = "/?key=" + quote(self.server.keys.get())
        manifest = {
            "id": "/",
            "name": "Tuya Light",
            "short_name": "Tuya Light",
            "description": "Your Tuya lights, through your computer",
            "start_url": start,
            "scope": "/",
            "display": "standalone",
            "orientation": "portrait",
            "background_color": "#10111a",
            "theme_color": "#10111a",
            "icons": [
                {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
                {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png",
                 "purpose": "maskable"},
            ],
        }
        self._send(200, json.dumps(manifest).encode(), "application/manifest+json",
                   {"Cache-Control": "no-store", "Vary": "Cookie"})

    # -- the API -------------------------------------------------------------

    def _api(self, method: str, path: str, query: str, raw) -> None:
        if not self._host_ok():
            return self._host_refused()
        if not self._authed():
            return self._json(401, {"error": "this phone is not paired", "paired": False})
        if method == "POST":
            if not self._same_origin():
                return self._json(403, {"error": "changes must come from the page itself"})
            ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return self._json(415, {"error": "send JSON"})
        try:
            body = self._body(raw) if method == "POST" else {}
            status, data = self._route(method, path, parse_qs(query), body)
        except BadRequest as err:
            return self._json(err.status, {"error": str(err), **err.extra})
        self._json(status, data)

    @staticmethod
    def _body(raw: bytes) -> dict:
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"), parse_constant=_no_constants)
        except (ValueError, UnicodeDecodeError):
            raise BadRequest(400, "the body is not valid JSON") from None
        if not isinstance(data, dict):
            raise BadRequest(400, "the body must be a JSON object")
        return data

    def _device(self, query: dict) -> Device:
        try:
            devices = config.load()
            if not devices:
                raise ConfigError("the device list is empty; run `tuya-light setup`")
        except ConfigError as err:
            raise BadRequest(503, str(err), config=True) from None
        wanted = (query.get("device") or [None])[0]
        if wanted is None:
            default = self.server.default_device
            return next((d for d in devices if default in (d.id, d.name)), devices[0])
        try:
            return config.pick(devices, wanted)
        except ConfigError as err:
            raise BadRequest(404, str(err)) from None

    def _transport(self, device: Device) -> str:
        try:
            return transport_for(device, self.server.transport)
        except ConfigError as err:
            raise BadRequest(503, str(err), config=True) from None

    def _route(self, method: str, path: str, query: dict, body: dict) -> tuple[int, object]:
        if method == "GET":
            if path == "/api/state":
                device = self._device(query)
                worker = self.server.worker(device, self._transport(device))
                return self._wait(worker.read(STATE_MAX_AGE), worker)
            if path == "/api/devices":
                try:
                    devices = config.load()
                except ConfigError as err:
                    raise BadRequest(503, str(err), config=True) from None
                default = self._device(query).id if devices else None
                return 200, {"devices": [{"id": d.id, "name": d.name,
                                          "transport": self._transport(d)} for d in devices],
                             "default": default}
            if path == "/api/scenes":
                try:
                    return 200, [s.to_json() for s in scene_store.load()]
                except ConfigError as err:
                    raise BadRequest(500, str(err)) from None
            raise BadRequest(404, "not found")

        action = self._action(path, body)
        device = self._device(query)
        worker = self.server.worker(device, self._transport(device))
        return self._wait(worker.submit(action), worker)

    def _action(self, path: str, body: dict) -> Callable[[BaseLight], None]:
        if path == "/api/power":
            on = body.get("on")
            if not isinstance(on, bool):
                raise BadRequest(400, "`on` must be true or false")
            return lambda light: light.power(on)
        if path == "/api/toggle":
            return lambda light: light.toggle()
        if path == "/api/brightness":
            value = _number(body, "value")
            return lambda light: light.brightness(value)
        if path == "/api/temperature":
            value = _number(body, "value")
            return lambda light: light.temperature(value)
        if path in ("/api/colour", "/api/color"):
            return self._colour(body)
        if path == "/api/scene":
            name = body.get("name")
            if not isinstance(name, str) or not name:
                raise BadRequest(400, "`name` must be a scene name")
            try:
                scene = scene_store.get(name)
            except ConfigError as err:
                raise BadRequest(404, str(err)) from None
            return lambda light: light.apply(scene)
        raise BadRequest(404, "not found")

    @staticmethod
    def _colour(body: dict) -> Callable[[BaseLight], None]:
        if isinstance(body.get("hex"), str):
            from .cli import _hex_to_hsv

            try:
                hue, sat, _ = _hex_to_hsv(body["hex"])
            except ValueError:
                raise BadRequest(400, "`hex` must look like #rrggbb") from None
        else:
            hue, sat = _number(body, "hue"), _number(body, "saturation")
        value = _number(body, "value", required=False)

        def act(light: BaseLight) -> None:
            bright = value
            if bright is None:  # keep how bright the light is now
                now = light._current()
                if not now.online:
                    raise LightError(now.error or "the light did not answer")
                bright = max(5, now.value if now.mode == "colour" else now.brightness)
            light.colour(hue, sat, bright)

        return act

    def _wait(self, ticket, worker: LightWorker) -> tuple[int, dict]:
        state = ticket.wait(WAIT)
        if state is None:
            raise BadRequest(504, "the light took too long to answer")
        cloud = worker.transport == "cloud"
        return 200, {**state.to_json(), "latest": ticket.latest,
                     "transport": worker.transport,
                     "poll": self.server.cloud_poll if cloud else LOCAL_POLL}


def _open_light(device: Device, timeout: float, transport: str) -> BaseLight:
    from .backend import open_light

    return open_light(device, timeout=timeout, transport=transport)


class PhoneServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], *, allow_hosts: tuple[str, ...] = (),
                 default_device: str | None = None, keys: KeyStore | None = None,
                 linger: float = 1.5, bad_key_delay: float = 1.0, trust_proxy: bool = False,
                 cloud_poll: int = CLOUD_POLL, cloud_settle: float = CLOUD_SETTLE,
                 transport: str | None = None,
                 log: Callable[[str], None] | None = None) -> None:
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        self.allow_hosts = tuple(allow_hosts)
        self.default_device = default_device
        self.trust_proxy = trust_proxy
        self.cloud_poll = max(10, int(cloud_poll))
        self.cloud_settle = cloud_settle
        self.transport = transport  # the command line's --transport, if any
        self.keys = keys or KeyStore()
        self.linger = linger
        self.bad_key_delay = bad_key_delay
        self.log = log or (lambda line: print(f"tuya-light: {line}", file=sys.stderr, flush=True))
        self._workers: dict[tuple[Device, str], LightWorker] = {}
        self._lock = threading.Lock()
        self._names = own_names(self.allow_hosts)
        self._names_at = time.monotonic()
        super().__init__(address, Handler)

    def server_bind(self) -> None:
        if self.address_family == socket.AF_INET6:
            with contextlib.suppress(OSError, AttributeError):
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        # HTTPServer.server_bind would also look up a host name we never use.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = str(self.server_address[0]), self.server_address[1]

    def known_name(self, name: str) -> bool:
        name = name.rstrip(".").lower()
        if name in self._names:
            return True
        # Tailscale may come up after the server; look again, at most twice a minute.
        with self._lock:
            if time.monotonic() - self._names_at > 30:
                self._names = own_names(self.allow_hosts)
                self._names_at = time.monotonic()
        return name in self._names

    def worker(self, device: Device, transport: str = "local") -> LightWorker:
        with self._lock:
            found = self._workers.get((device, transport))
            if found is None:
                found = LightWorker(
                    device, linger=self.linger,
                    settle=self.cloud_settle if transport == "cloud" else 0.0,
                    light_factory=lambda dev, timeout: _open_light(dev, timeout, transport))
                found.transport = transport
                self._workers[(device, transport)] = found
            return found

    def server_close(self) -> None:
        super().server_close()
        with self._lock:
            for worker in self._workers.values():
                worker.stop()


# -- commands ----------------------------------------------------------------


@dataclass(frozen=True)
class Options:
    """How `tuya-light serve` was asked to run (also what the service repeats)."""

    host: str = "0.0.0.0"
    port: int = DEFAULT_PORT
    allow_hosts: tuple[str, ...] = ()
    device: str | None = None
    trust_proxy: bool = False
    cloud_poll: int = CLOUD_POLL
    transport: str | None = None

    def argv(self) -> list[str]:
        out = []
        if self.device:
            out += ["-d", self.device]
        if self.transport:
            out += ["--transport", self.transport]
        out += ["serve", "--host", self.host, "--port", str(self.port)]
        for name in self.allow_hosts:
            out += ["--allow-host", name]
        if self.trust_proxy:
            out.append("--trust-proxy")
        if self.cloud_poll != CLOUD_POLL:
            out += ["--cloud-poll", str(self.cloud_poll)]
        return out


def serve(opts: Options) -> int:
    keys = KeyStore()
    keys.get()  # first run: make the key now, not on the first request
    try:
        server = PhoneServer((opts.host, opts.port), allow_hosts=opts.allow_hosts,
                             default_device=opts.device, keys=keys,
                             trust_proxy=opts.trust_proxy, cloud_poll=opts.cloud_poll,
                             transport=opts.transport)
    except OSError as err:
        print(f"tuya-light: cannot listen on {opts.host} port {opts.port}: {err}", file=sys.stderr)
        return 1
    print(f"tuya-light {__version__}: phone page on port {opts.port}"
          + (" (trusting proxy headers)" if opts.trust_proxy else ""), flush=True)
    if Path("/.dockerenv").exists():
        print("  in a container: open it at the host's address, or the proxy's;"
              " pair with `tuya-light serve --pair --url ADDRESS`", flush=True)
    elif opts.host in ("0.0.0.0", "::", ""):
        for label, addr in local_addresses():
            print(f"  {label:<24} http://{addr}:{opts.port}/", flush=True)
    else:
        print(f"  http://{_url_host(opts.host)}:{opts.port}/", flush=True)
    print("Pair a phone with: tuya-light serve --pair", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


def _qr(text: str) -> str | None:
    try:
        import segno
    except ImportError:
        segno = None
    if segno is not None:
        out = io.StringIO()
        segno.make(text, error="l").terminal(out=out, compact=True)
        return out.getvalue()
    if shutil.which("qrencode"):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            return subprocess.run(["qrencode", "-t", "UTF8", "-m", "2", text], capture_output=True,
                                  text=True, timeout=5, check=True).stdout
    return None


def _listening(port: int) -> bool:
    with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", port), timeout=0.5):
        return True
    return False


def pairing_links(port: int, url: str | None = None) -> list[dict]:
    key = KeyStore().get()
    if url:
        bases = [("Your address", url.rstrip("/"))]
    else:
        bases = [(label, f"http://{addr}:{port}") for label, addr in local_addresses()]
    return [{"label": label, "url": f"{base}/?key={key}"} for label, base in bases]


def print_pairing(port: int, url: str | None, as_json: bool) -> int:
    links = pairing_links(port, url)
    if as_json:
        print(json.dumps(links))
        return 0
    if not links:
        print("tuya-light: found no network address for this computer; "
              "give one with --url http://ADDRESS:PORT", file=sys.stderr)
        return 1
    print("Open one of these on your phone, in Safari:\n")
    width = max(len(link["label"]) for link in links)
    for link in links:
        print(f"  {link['label']:<{width}}  {link['url']}")
    print("\nThen Share > Add to Home Screen.")
    if not url and len(links) > 1:
        print("The Tailscale address works at home and away (with Tailscale on in the phone);"
              "\na home network address works at home only.")
    print("The link is the password to your lights: don't share it."
          "\nTo lock out every paired phone: tuya-light serve --rotate-key")
    for link in links:
        code = _qr(link["url"])
        if code is None:
            print("\n(For QR codes here, install segno: pipx inject tuya-light segno)")
            break
        print(f"\n{link['label']}:\n{code}", end="")
    if not _listening(port):
        print(f"\nNothing is answering on port {port} yet. Start the server with "
              "`tuya-light serve`, or `tuya-light serve --install-service` to start it at login.")
    return 0


def rotate_key() -> int:
    KeyStore().rotate()
    print("Made a new key. Paired phones are locked out until you pair them again:\n"
          "  tuya-light serve --pair\n"
          "A running server uses the new key at once. On the phone, delete the old\n"
          "Home Screen icon and add it again after opening the new link.")
    return 0


# -- systemd user service ----------------------------------------------------


def unit_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "systemd" / "user" / SERVICE


def _command() -> list[str]:
    """How to start this same tuya-light again."""
    argv0 = Path(sys.argv[0])
    if argv0.name == "tuya-light" and argv0.is_absolute() and os.access(argv0, os.X_OK):
        return [str(argv0)]
    found = shutil.which("tuya-light")
    return [found] if found else [sys.executable, "-m", "tuya_light"]


def _sd_quote(arg: str) -> str:
    arg = arg.replace("%", "%%").replace("$", "$$")
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", arg):
        return arg
    return '"' + arg.replace("\\", "\\\\").replace('"', '\\"') + '"'


def unit_text(argv: list[str], env: dict[str, str]) -> str:
    lines = [
        "[Unit]",
        "Description=Tuya Light phone page",
        "Documentation=https://github.com/YakupEmreYerli/tuya-light#on-your-phone",
        "",
        "[Service]",
        "Type=simple",
        "ExecStart=" + " ".join(_sd_quote(a) for a in argv),
        *(f"Environment={_sd_quote(f'{k}={v}')}" for k, v in sorted(env.items())),
        "Restart=on-failure",
        "RestartSec=5",
        "NoNewPrivileges=yes",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ]
    return "\n".join(lines)


def _systemctl(run, *args: str) -> subprocess.CompletedProcess:
    return run(["systemctl", "--user", *args], capture_output=True, text=True, check=False)


# Settings worth repeating in the unit. Never the cloud secret: unit files are
# world-readable; the service finds it in cloud.json instead.
UNIT_ENV = ("TUYA_LIGHT_CONFIG", "TUYA_LIGHT_SCENES", "TUYA_LIGHT_TRANSPORT", "TUYA_REGION")


def install_service(opts: Options, run=subprocess.run) -> int:
    if not shutil.which("systemctl"):
        print("tuya-light: systemctl not found; run `tuya-light serve` from your session's "
              "autostart instead", file=sys.stderr)
        return 1
    KeyStore().get()
    argv = _command() + opts.argv()
    env = {k: os.environ[k] for k in UNIT_ENV if os.environ.get(k)}
    path = unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit_text(argv, env), encoding="utf-8")
    for args in (("daemon-reload",), ("enable", SERVICE), ("restart", SERVICE)):
        done = _systemctl(run, *args)
        if done.returncode != 0:
            print(f"tuya-light: systemctl --user {' '.join(args)} failed: "
                  f"{(done.stderr or '').strip()}", file=sys.stderr)
            return 1
    name = SERVICE.removesuffix(".service")
    print(f"Installed {path} and started it. It starts at login and restarts if it fails.\n"
          f"  Stop:     systemctl --user stop {name}\n"
          f"  Disable:  systemctl --user disable --now {name}\n"
          f"  Remove:   tuya-light serve --remove-service\n"
          f"  Logs:     journalctl --user -u {name}\n"
          f"Pair a phone: tuya-light serve --pair"
          + (f" --port {opts.port}" if opts.port != DEFAULT_PORT else ""))
    return 0


def remove_service(run=subprocess.run) -> int:
    path = unit_path()
    if shutil.which("systemctl"):
        _systemctl(run, "disable", "--now", SERVICE)
    existed = path.exists()
    path.unlink(missing_ok=True)
    if shutil.which("systemctl"):
        _systemctl(run, "daemon-reload")
    print(f"Stopped and removed {path}." if existed else "No phone page service was installed.")
    return 0


def main(args: argparse.Namespace) -> int:
    if args.url and not args.pair:
        raise SystemExit("tuya-light: --url goes with --pair")
    if not 1 <= args.port <= 65535:
        raise SystemExit("tuya-light: --port must be 1-65535")
    if args.cloud_poll < 10:
        raise SystemExit("tuya-light: --cloud-poll must be at least 10 seconds")
    opts = Options(host=args.host, port=args.port, allow_hosts=tuple(args.allow_host),
                   device=args.device, trust_proxy=args.trust_proxy,
                   cloud_poll=args.cloud_poll, transport=args.transport)
    if args.pair:
        return print_pairing(args.port, args.url, args.json)
    if args.rotate_key:
        return rotate_key()
    if args.install_service:
        return install_service(opts)
    if args.remove_service:
        return remove_service()
    return serve(opts)

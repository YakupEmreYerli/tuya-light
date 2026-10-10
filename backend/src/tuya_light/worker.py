"""One bulb, one conversation at a time, for long-running front ends.

A bulb handles one TCP session at a time and takes a few hundred
milliseconds per command. A front end that stays up (the phone page's
server) sends far more than that while someone drags a slider, so every
command for a bulb goes through one LightWorker:

- Commands run one after the other on a single thread.
- While one runs, at most one more waits. A newer command replaces the
  waiting one, so a drag sends the first and the last value, not every
  step. This is the same rule the widget's Backend.qml follows.
- Every command ends with a state read, and its caller gets that state
  back, with ``latest`` false when another command was already queued
  behind it (so a client should not snap its controls to it).
- After a change the connection stays open for a short pause, in case the
  next value of a drag follows; after that, and right after a plain read, it
  is closed, so the widget and the CLI can reach the bulb in between.
- With ``settle`` (used for cloud bulbs, where every request counts against
  a monthly allowance) a change waits that long for a newer one before it is
  sent, so a drag sends only where it stopped.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Callable

from .config import ConfigError, Device
from .light import BaseLight, LightError, State

Action = Callable[[BaseLight], None]


def _open(device: Device, timeout: float) -> BaseLight:
    from .backend import open_light

    return open_light(device, timeout=timeout)


class Ticket:
    """A caller's handle on a queued command: wait() returns the state after it."""

    def __init__(self) -> None:
        self._done = threading.Event()
        self.state: State | None = None
        self.latest = True

    def _finish(self, state: State, latest: bool) -> None:
        self.state, self.latest = state, latest
        self._done.set()

    def wait(self, timeout: float | None = None) -> State | None:
        self._done.wait(timeout)
        return self.state


class _Job:
    def __init__(self, action: Action | None, replaces: "_Job | None" = None) -> None:
        self.action = action
        self.tickets = [Ticket()]
        self.created = time.monotonic()
        self.first = replaces.first if replaces is not None else self.created


class LightWorker:
    def __init__(self, device: Device, *, linger: float = 1.5, timeout: float = 3.0,
                 settle: float = 0.0,
                 light_factory: Callable[..., BaseLight] = _open) -> None:
        self.device = device
        self.transport = "local"  # informational; set by whoever picks the factory
        self.linger = linger
        self.timeout = timeout
        self.settle = settle
        self._light_factory = light_factory
        self._cond = threading.Condition()
        self._pending: _Job | None = None
        self._running: _Job | None = None
        self._last: tuple[State, float] | None = None
        self._thread: threading.Thread | None = None
        self._stopped = False

    # -- queueing --------------------------------------------------------

    def submit(self, action: Action) -> Ticket:
        """Queue a change. A change still waiting is dropped; its callers get
        this one's result instead."""
        with self._cond:
            job = _Job(action, self._pending)
            if self._pending is not None:
                job.tickets.extend(self._pending.tickets)
            self._pending = job
            self._wake()
            return job.tickets[0]

    def read(self, max_age: float = 0.0) -> Ticket:
        """The current state. A command already queued or running answers the
        read too; a state younger than ``max_age`` seconds is reused."""
        with self._cond:
            ticket = Ticket()
            busy = self._pending or self._running
            if busy is not None:
                busy.tickets.append(ticket)
                return ticket
            if self._last is not None and time.monotonic() - self._last[1] < max_age:
                ticket._finish(self._last[0], True)
                return ticket
            job = _Job(None)
            job.tickets = [ticket]
            self._pending = job
            self._wake()
            return ticket

    def stop(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify_all()

    def _wake(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name=f"light-{self.device.id}",
                                            daemon=True)
            self._thread.start()
        self._cond.notify()

    # -- the one thread that talks to the bulb ---------------------------

    def _loop(self) -> None:
        light: BaseLight | None = None
        while True:
            with self._cond:
                if self._pending is None and not self._stopped:
                    self._cond.wait(self.linger if light is not None else None)
                self._settle()
                job = self._pending
                self._pending = None
                self._running = job
                stopped = self._stopped
            if job is None:
                # Idle: let go of the bulb so other programs can reach it.
                if light is not None:
                    light.close()
                    light = None
                if stopped:
                    return
                continue
            reason = ""
            if light is None:
                light, reason = self._open()
            state = self._execute(light, job.action) if light else self._offline(reason)
            if not state.online and light is not None:
                light.close()  # start the next command on a fresh connection
                light = None
            with self._cond:
                self._running = None
                latest = self._pending is None
                self._last = (state, time.monotonic())
            for ticket in job.tickets:
                ticket._finish(state, latest)
            if job.action is None and latest and light is not None:
                # A plain read (a phone polling) does not hold on to the bulb:
                # only a change is likely to be followed by another one.
                light.close()
                light = None

    def _settle(self) -> None:
        """Debounce: wait until no newer change came for `settle` seconds, but
        never more than four times that since the first of them."""
        while self.settle > 0 and not self._stopped:
            job = self._pending
            if job is None or job.action is None:
                return
            wait = min(job.created + self.settle, job.first + 4 * self.settle) - time.monotonic()
            if wait <= 0:
                return
            self._cond.wait(wait)

    def _offline(self, reason: str) -> State:
        return State(id=self.device.id, name=self.device.name, online=False, error=reason)

    def _open(self) -> tuple[BaseLight | None, str]:
        try:
            return self._light_factory(self.device, timeout=self.timeout), ""
        except ConfigError as err:  # e.g. no cloud credentials: say exactly that
            return None, str(err)
        except Exception as err:  # tinytuya may fail before any command is sent
            print(f"tuya-light: cannot open {self.device.name}: {type(err).__name__}",
                  file=sys.stderr)
            return None, "could not connect to the light"

    def _execute(self, light: BaseLight, action: Action | None) -> State:
        try:
            if action is not None:
                action(light)
            return light.state()
        except LightError as err:
            return self._offline(str(err))
        except Exception as err:  # a surprise from tinytuya must not stop the worker
            print(f"tuya-light: {self.device.name}: {type(err).__name__}: {err}", file=sys.stderr)
            return self._offline(f"{type(err).__name__}: {err}")

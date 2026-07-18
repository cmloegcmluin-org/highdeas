from types import SimpleNamespace

import pytest

import highdeas.app


@pytest.fixture(autouse=True)
def keep_the_real_env_file_out_of_the_tests(monkeypatch):
    """`build_app()` loads the `.env` beside it, which on a real machine is the user's
    own: a state folder, an inbox full of memos, live API keys. A test that deletes a
    variable to go without it would find `.env` handing it straight back — and it would
    pass in a fresh worktree (no `.env` there) while failing in the checkout the app
    actually runs from. So no test ever reads it; each says what it needs."""
    monkeypatch.setattr(highdeas.app, "load_dotenv", lambda *args, **kwargs: None)


class _Event:
    """Stand-in for a pywebview window event: handlers subscribe with ``+=``."""

    def __init__(self):
        self._handlers = []

    def __iadd__(self, handler):
        self._handlers.append(handler)
        return self

    def fire(self, *args):
        for handler in self._handlers:
            handler(*args)


class FakeWindow:
    """The slice of a pywebview window the geometry tracker touches.

    ``maximize``/``minimize``/``restore`` replay the event order the winforms backend
    really emits (traced on Windows 11): ``moved`` first, then the state event, then
    ``resized`` — with ``native.WindowState`` already reporting the *new* state. The
    screen-filling and parked-off-screen coordinates are the ones Windows reports.
    """

    def __init__(self, width=1360, height=900, x=0, y=0):
        self.events = SimpleNamespace(
            resized=_Event(), moved=_Event(), maximized=_Event(),
            minimized=_Event(), restored=_Event(), closing=_Event(),
        )
        self.native = SimpleNamespace(WindowState="Normal")
        self._normal = (x, y, width, height)
        self._set_frame(x, y, width, height)

    def _set_frame(self, x, y, width, height):
        self.x, self.y, self.width, self.height = x, y, width, height

    def move(self, x, y):
        self._normal = (x, y, *self._normal[2:])
        self._set_frame(x, y, *self._normal[2:])
        self.events.moved.fire(x, y)

    def resize(self, width, height):
        self._normal = (*self._normal[:2], width, height)
        self._set_frame(*self._normal[:2], width, height)
        self.events.resized.fire(width, height)

    def maximize(self):
        self.native.WindowState = "Maximized"
        self._set_frame(-8, -8, 2576, 1408)
        self.events.moved.fire(-8, -8)
        self.events.maximized.fire()
        self.events.resized.fire(2576, 1408)

    def minimize(self):
        self.native.WindowState = "Minimized"
        self._set_frame(-32000, -32000, 160, 33)
        self.events.moved.fire(-32000, -32000)
        self.events.minimized.fire()
        self.events.resized.fire(160, 33)

    def restore(self):
        x, y, width, height = self._normal
        self.native.WindowState = "Normal"
        self._set_frame(x, y, width, height)
        self.events.moved.fire(x, y)
        self.events.restored.fire()
        self.events.resized.fire(width, height)

    def close(self):
        self.events.closing.fire()


class FakeCocoaWindow:
    """The slice of pywebview's Cocoa window the geometry tracker touches.

    Modeled on a live probe of pywebview 6.2.1 on macOS (2026-07-10):
    ``moved``/``resized``/``closing`` fire (with float coordinates);
    ``maximized``/``minimized``/``restored`` exist but never fire, even across
    a programmatic zoom; ``native`` is an NSWindow answering ``isZoomed()``,
    ``isMiniaturized()``, and ``styleMask()`` — and the frame is already in
    its new state by the time the events fire.
    """

    _FULLSCREEN_MASK = 1 << 14  # NSWindowStyleMaskFullScreen

    def __init__(self, width=1360, height=900, x=0, y=0):
        self.events = SimpleNamespace(
            resized=_Event(), moved=_Event(), maximized=_Event(),
            minimized=_Event(), restored=_Event(), closing=_Event(),
        )
        self._zoomed = False
        self._miniaturized = False
        self._fullscreen = False
        self.native = SimpleNamespace(
            isZoomed=lambda: self._zoomed,
            isMiniaturized=lambda: self._miniaturized,
            styleMask=lambda: self._FULLSCREEN_MASK if self._fullscreen else 0,
        )
        self._normal = (x, y, width, height)
        self._set_frame(x, y, width, height)

    def _set_frame(self, x, y, width, height):
        self.x, self.y, self.width, self.height = x, y, width, height

    def move(self, x, y):
        self._normal = (x, y, *self._normal[2:])
        self._set_frame(x, y, *self._normal[2:])
        self.events.moved.fire(float(x), float(y))

    def drag_silently(self, x, y):
        """A USER title-bar drag: the frame moves, and — probed live on
        pywebview 6.2.1 — no moved event fires at all. Only programmatic
        move() announces itself on Cocoa."""
        self._normal = (x, y, *self._normal[2:])
        self._set_frame(x, y, *self._normal[2:])

    def resize(self, width, height):
        self._normal = (*self._normal[:2], width, height)
        self._set_frame(*self._normal[:2], width, height)
        self.events.resized.fire(float(width), float(height))

    def zoom(self):
        """The green button (or window.maximize()): frame fills the screen's
        visible area. No maximized event — only moved/resized."""
        self._zoomed = True
        self._set_frame(0, 25, 1637, 930)
        self.events.moved.fire(0.0, 25.0)
        self.events.resized.fire(1637.0, 930.0)

    def unzoom(self):
        self._zoomed = False
        x, y, width, height = self._normal
        self._set_frame(x, y, width, height)
        self.events.moved.fire(float(x), float(y))
        self.events.resized.fire(float(width), float(height))

    def enter_fullscreen(self):
        self._fullscreen = True
        self.events.resized.fire(1710.0, 1112.0)

    def miniaturize(self):
        self._miniaturized = True

    def close(self):
        self.events.closing.fire()


@pytest.fixture
def fake_window():
    return FakeWindow()


@pytest.fixture
def fake_cocoa_window():
    return FakeCocoaWindow()

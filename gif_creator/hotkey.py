"""Raccourcis globaux pour arrêter l'enregistrement, via X11."""

import ctypes
import select
import threading
from ctypes import c_int, c_uint, c_ulong, c_void_p


class _XKeyEvent(ctypes.Structure):
    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", c_int),
        ("display", c_void_p),
        ("window", c_ulong),
        ("root", c_ulong),
        ("subwindow", c_ulong),
        ("time", c_ulong),
        ("x", c_int),
        ("y", c_int),
        ("x_root", c_int),
        ("y_root", c_int),
        ("state", c_uint),
        ("keycode", c_uint),
        ("same_screen", c_int),
    ]


_SHIFT = 1
_LOCK = 2
_CONTROL = 4
_MOD2 = 16
_MOD1 = 8
_MOD4 = 64
_GRAB_ASYNC = 1
_KEY_PRESS = 2
_RELEVANT = _SHIFT | _CONTROL | _MOD1 | _MOD4


class StopHotkey:
    def __init__(self, on_stop):
        self._on_stop = on_stop
        self._stop = threading.Event()
        self._thread = None
        self.armed = False
        self._handler = None
        self._bindings = []

    def arm(self, bindings):
        if self._thread and self._thread.is_alive():
            return
        unique = []
        for keycode, modifiers in bindings:
            binding = (int(keycode), int(modifiers))
            if binding[0] and binding not in unique:
                unique.append(binding)
        self._bindings = unique
        if not self._bindings:
            return
        self._stop.clear()
        self.armed = False
        self._thread = threading.Thread(target=self._run, name="gif-creator-hotkey", daemon=True)
        self._thread.start()

    def disarm(self):
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._thread = None
        self.armed = False

    def _run(self):
        lib = ctypes.CDLL("libX11.so.6")
        lib.XOpenDisplay.argtypes = [c_void_p]
        lib.XOpenDisplay.restype = c_void_p
        lib.XCloseDisplay.argtypes = [c_void_p]
        lib.XDefaultRootWindow.argtypes = [c_void_p]
        lib.XDefaultRootWindow.restype = c_ulong
        lib.XGrabKey.argtypes = [c_void_p, c_int, c_uint, c_ulong, c_int, c_int, c_int]
        lib.XUngrabKey.argtypes = [c_void_p, c_int, c_uint, c_ulong]
        lib.XConnectionNumber.argtypes = [c_void_p]
        lib.XConnectionNumber.restype = c_int
        lib.XPending.argtypes = [c_void_p]
        lib.XPending.restype = c_int
        lib.XNextEvent.argtypes = [c_void_p, c_void_p]
        lib.XSync.argtypes = [c_void_p, c_int]
        lib.XSetErrorHandler.argtypes = [c_void_p]
        lib.XSetErrorHandler.restype = c_void_p
        display = lib.XOpenDisplay(None)
        if not display:
            return
        set_repeat = getattr(lib, "XkbSetDetectableAutoRepeat", None)
        if set_repeat is not None:
            set_repeat.argtypes = [c_void_p, c_int, c_void_p]
            set_repeat.restype = c_int
            set_repeat(display, 1, None)
        root = lib.XDefaultRootWindow(display)
        bindings = list(self._bindings)
        if not bindings:
            lib.XCloseDisplay(display)
            return

        errors = {"count": 0}

        def _ignore(_display, _event):
            errors["count"] += 1
            return 0

        handler_type = ctypes.CFUNCTYPE(c_int, c_void_p, c_void_p)
        self._handler = handler_type(_ignore)
        previous = lib.XSetErrorHandler(self._handler)
        grabbed = []
        for keycode, modifiers in bindings:
            for extra in (0, _LOCK, _MOD2, _LOCK | _MOD2):
                mask = modifiers | extra
                lib.XGrabKey(display, keycode, mask, root, 0, _GRAB_ASYNC, _GRAB_ASYNC)
                grabbed.append((keycode, mask))
        lib.XSync(display, 0)
        lib.XSetErrorHandler(previous)
        self.armed = errors["count"] == 0

        connection = lib.XConnectionNumber(display)
        event = ctypes.create_string_buffer(256)
        held = set()
        try:
            while not self._stop.is_set():
                ready, _, _ = select.select([connection], [], [], 0.1)
                if not ready:
                    continue
                while lib.XPending(display):
                    lib.XNextEvent(display, event)
                    key_event = ctypes.cast(event, ctypes.POINTER(_XKeyEvent)).contents
                    state = int(key_event.state) & _RELEVANT
                    found = None
                    for keycode, modifiers in bindings:
                        if int(key_event.keycode) == keycode and state == modifiers:
                            found = (keycode, modifiers)
                            break
                    if found is None:
                        continue
                    if key_event.type == _KEY_PRESS:
                        if found in held:
                            continue
                        held.add(found)
                        self._on_stop(found[0], found[1])
                    elif key_event.type == 3:
                        held.discard(found)
        finally:
            for keycode, mask in grabbed:
                lib.XUngrabKey(display, keycode, mask, root)
            lib.XSync(display, 0)
            lib.XCloseDisplay(display)
            self.armed = False

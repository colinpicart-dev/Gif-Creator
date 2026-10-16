"""Capture X11 d'une zone. Wayland est refusé avec un message explicite."""

import ctypes
import os
import time
from ctypes import (
    CFUNCTYPE,
    POINTER,
    c_int,
    c_uint,
    c_ulong,
    c_void_p,
    Structure,
)

from PIL import Image

from gif_creator.cursor_overlay import composite_cursor

WAYLAND_MESSAGE = (
    "L’enregistrement d’une zone n’est pas disponible en session Wayland : "
    "le composant de capture PipeWire n’est pas installé. "
    "Aucune image n’a été enregistrée."
)


def session_kind():
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "none"


class _XImage(Structure):
    _fields_ = [
        ("width", c_int),
        ("height", c_int),
        ("xoffset", c_int),
        ("format", c_int),
        ("data", c_void_p),
        ("byte_order", c_int),
        ("bitmap_unit", c_int),
        ("bitmap_bit_order", c_int),
        ("bitmap_pad", c_int),
        ("depth", c_int),
        ("bytes_per_line", c_int),
        ("bits_per_pixel", c_int),
        ("red_mask", c_ulong),
        ("green_mask", c_ulong),
        ("blue_mask", c_ulong),
        ("obdata", c_void_p),
        ("create_image", c_void_p),
        ("destroy_image", c_void_p),
        ("get_pixel", c_void_p),
        ("put_pixel", c_void_p),
        ("sub_image", c_void_p),
        ("add_pixel", c_void_p),
    ]


_DESTROY = CFUNCTYPE(c_int, POINTER(_XImage))


class _Screen:
    def __init__(self):
        self.lib = ctypes.CDLL("libX11.so.6")
        self.lib.XOpenDisplay.argtypes = [c_void_p]
        self.lib.XOpenDisplay.restype = c_void_p
        self.lib.XCloseDisplay.argtypes = [c_void_p]
        self.lib.XDefaultRootWindow.argtypes = [c_void_p]
        self.lib.XDefaultRootWindow.restype = c_ulong
        self.lib.XGetImage.argtypes = [
            c_void_p,
            c_ulong,
            c_int,
            c_int,
            c_uint,
            c_uint,
            c_ulong,
            c_int,
        ]
        self.lib.XGetImage.restype = c_void_p
        self.display = self.lib.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError("Impossible d’ouvrir l’écran X11.")
        self.root = self.lib.XDefaultRootWindow(self.display)
        self._all_planes = c_ulong(-1).value

    def close(self):
        if self.display:
            self.lib.XCloseDisplay(self.display)
            self.display = None

    def grab(self, region):
        pointer = self.lib.XGetImage(
            self.display,
            self.root,
            int(region.x),
            int(region.y),
            int(region.width),
            int(region.height),
            self._all_planes,
            2,
        )
        if not pointer:
            raise RuntimeError("La zone choisie ne peut pas être lue.")
        image_pointer = ctypes.cast(pointer, POINTER(_XImage))
        image = image_pointer.contents
        try:
            width = int(image.width)
            height = int(image.height)
            stride = int(image.bytes_per_line)
            supported = (
                int(image.bits_per_pixel) == 32
                and int(image.byte_order) == 0
                and int(image.red_mask) == 0xFF0000
            )
            raw = ctypes.string_at(image.data, stride * height) if supported else None
        finally:
            _DESTROY(image.destroy_image)(image_pointer)
        if raw is None:
            raise RuntimeError("Le format de l’écran X11 n’est pas pris en charge.")
        return Image.frombytes("RGB", (width, height), raw, "raw", "BGRX", stride, 1)


def record_region(region, fps, duration, include_cursor, stop_event):
    kind = session_kind()
    if kind == "wayland":
        raise RuntimeError(WAYLAND_MESSAGE)
    if kind != "x11":
        raise RuntimeError("Aucune session graphique n’est détectée.")

    screen = _Screen()
    frames = []
    frame_count = max(1, int(round(duration * fps)))
    interval = 1.0 / fps
    try:
        started = time.monotonic()
        next_tick = started
        while len(frames) < frame_count and not stop_event.is_set():
            now = time.monotonic()
            if now < next_tick:
                time.sleep(min(0.01, next_tick - now))
                continue
            frame = screen.grab(region)
            if include_cursor:
                composite_cursor(frame, region, screen.display)
            late = now - next_tick
            slots = 1 + max(0, int(late / interval))
            room = frame_count - len(frames)
            slots = max(1, min(slots, room))
            frames.extend([frame] * slots)
            next_tick += slots * interval
            if time.monotonic() - started >= duration:
                break
    finally:
        screen.close()

    if not frames:
        raise RuntimeError("Aucune image n’a été capturée.")
    return frames

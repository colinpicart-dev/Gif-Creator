"""Ajoute le curseur X11 sur une image. XGetImage ne le contient pas."""

import ctypes
from ctypes import (
    POINTER,
    c_short,
    c_ulong,
    c_ushort,
    c_void_p,
)

from PIL import Image


class _XFixesCursorImage(ctypes.Structure):
    _fields_ = [
        ("x", c_short),
        ("y", c_short),
        ("width", c_ushort),
        ("height", c_ushort),
        ("xhot", c_ushort),
        ("yhot", c_ushort),
        ("cursor_serial", c_ulong),
        ("pixels", POINTER(c_ulong)),
        ("atom", c_ulong),
        ("name", c_void_p),
    ]


_libx11 = None
_libxfixes = None


def _libraries():
    global _libx11, _libxfixes
    if _libx11 is None:
        _libx11 = ctypes.CDLL("libX11.so.6")
        _libxfixes = ctypes.CDLL("libXfixes.so.3")
        _libx11.XFree.argtypes = [c_void_p]
        _libxfixes.XFixesGetCursorImage.argtypes = [c_void_p]
        _libxfixes.XFixesGetCursorImage.restype = c_void_p
    return _libx11, _libxfixes


def _cursor_rgba(display):
    libx11, libxfixes = _libraries()
    pointer = libxfixes.XFixesGetCursorImage(display)
    if not pointer:
        return None
    try:
        image = ctypes.cast(pointer, POINTER(_XFixesCursorImage)).contents
        width = int(image.width)
        height = int(image.height)
        if width <= 0 or height <= 0:
            return None
        count = width * height
        raw = bytearray(count * 4)
        offset = 0
        for index in range(count):
            pixel = int(image.pixels[index]) & 0xFFFFFFFF
            alpha = (pixel >> 24) & 0xFF
            red = (pixel >> 16) & 0xFF
            green = (pixel >> 8) & 0xFF
            blue = pixel & 0xFF
            if 0 < alpha < 255:
                red = min(255, (red * 255) // alpha)
                green = min(255, (green * 255) // alpha)
                blue = min(255, (blue * 255) // alpha)
            raw[offset:offset + 4] = bytes((red, green, blue, alpha))
            offset += 4
        return (
            int(image.x),
            int(image.y),
            width,
            height,
            int(image.xhot),
            int(image.yhot),
            bytes(raw),
        )
    finally:
        libx11.XFree(pointer)


def _paste_clamped(base, overlay, dest_x, dest_y):
    base_w, base_h = base.size
    over_w, over_h = overlay.size
    src_x0 = max(0, -dest_x)
    src_y0 = max(0, -dest_y)
    src_x1 = min(over_w, base_w - dest_x)
    src_y1 = min(over_h, base_h - dest_y)
    if src_x1 <= src_x0 or src_y1 <= src_y0:
        return
    cropped = overlay.crop((src_x0, src_y0, src_x1, src_y1))
    base.paste(cropped, (dest_x + src_x0, dest_y + src_y0), cropped)


def composite_cursor(image, region, display):
    info = _cursor_rgba(display)
    if info is None:
        return image
    cursor_x, cursor_y, width, height, hot_x, hot_y, raw = info
    overlay = Image.frombytes("RGBA", (width, height), raw)
    _paste_clamped(image, overlay, cursor_x - hot_x - region.x, cursor_y - hot_y - region.y)
    return image

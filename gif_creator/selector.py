import cairo
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from gif_creator.region import (
    Region,
    corner_positions,
    hit_corner,
    hit_edge,
    is_large_enough,
    normalize_rect,
    point_inside,
    rectangles_intersect,
    set_corner,
)
from gif_creator.shortcuts import event_matches, shortcut_label

_RESIZE_CURSORS = {
    "nw": "nw-resize",
    "ne": "ne-resize",
    "se": "se-resize",
    "sw": "sw-resize",
}


def counter_anchor(left, top, rect_w, rect_h, badge_w, badge_h, bounds_w, bounds_h):
    gap = 4
    x = left + rect_w - badge_w
    y = top - badge_h - gap
    if y < 0:
        y = top + rect_h + gap
    x = min(max(0, x), max(0, bounds_w - badge_w))
    y = min(max(0, y), max(0, bounds_h - badge_h))
    return x, y


class RegionSelector(Gtk.Window):
    def __init__(self, on_result, existing, cancel_accel, validate_accel, duration_seconds=4):
        super().__init__(title="Choisir la zone")
        self._on_result = on_result
        self._finished = False
        self._cancel_accel = cancel_accel
        self._validate_accel = validate_accel
        self._x0 = None
        self._y0 = None
        self._x1 = None
        self._y1 = None
        self._drag = None
        self._notice = ""
        self._duration_seconds = max(1, int(duration_seconds))

        display = Gdk.Display.get_default()
        screen = display.get_default_screen()
        seat = display.get_default_seat()
        _screen, pointer_x, pointer_y = seat.get_pointer().get_position()
        self._monitor = screen.get_monitor_at_point(pointer_x, pointer_y)
        geometry = screen.get_monitor_geometry(self._monitor)
        self._origin_x = geometry.x
        self._origin_y = geometry.y
        self._monitor_width = geometry.width
        self._monitor_height = geometry.height
        self._scale = screen.get_monitor_scale_factor(self._monitor)
        self._load_existing(existing)

        self.set_decorated(False)
        self.set_app_paintable(True)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(True)
        self.set_can_focus(True)

        visual = screen.get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        transparent = Gdk.RGBA()
        transparent.red = 0
        transparent.green = 0
        transparent.blue = 0
        transparent.alpha = 0
        self.override_background_color(Gtk.StateFlags.NORMAL, transparent)

        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.BUTTON_MOTION_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.KEY_PRESS_MASK
        )
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._press_event)
        self.connect("motion-notify-event", self._motion_event)
        self.connect("button-release-event", self._release_event)
        self.connect("key-press-event", self._key_event)
        self.connect("map-event", self._mapped)
        self.connect("delete-event", self._delete)
        self.fullscreen_on_monitor(screen, self._monitor)

    def _load_existing(self, region):
        if region is None:
            return
        scale = self._scale
        monitor_x = int(round(self._origin_x * scale))
        monitor_y = int(round(self._origin_y * scale))
        monitor_w = int(round(self._monitor_width * scale))
        monitor_h = int(round(self._monitor_height * scale))
        if not rectangles_intersect(
            region.x, region.y, region.width, region.height,
            monitor_x, monitor_y, monitor_w, monitor_h,
        ):
            return
        self._x0, self._y0 = self._to_local(region.x, region.y)
        self._x1, self._y1 = self._to_local(region.x + region.width, region.y + region.height)

    def _mapped(self, *_args):
        self._set_cursor("crosshair")
        self.get_window().raise_()
        self.set_keep_above(True)
        GLib.idle_add(self._focus)
        return False

    def _focus(self):
        seat = self.get_display().get_default_seat()
        seat.grab(
            self.get_window(),
            Gdk.SeatCapabilities.KEYBOARD,
            False,
            None,
            None,
            None,
        )
        self.grab_focus()
        return False

    def _set_cursor(self, name):
        window = self.get_window()
        if window is None:
            return
        cursor = Gdk.Cursor.new_from_name(self.get_display(), name)
        window.set_cursor(cursor)

    def _to_device(self, local_x, local_y):
        return (
            int(round((self._origin_x + local_x) * self._scale)),
            int(round((self._origin_y + local_y) * self._scale)),
        )

    def _to_local(self, device_x, device_y):
        return (
            device_x / self._scale - self._origin_x,
            device_y / self._scale - self._origin_y,
        )

    def _clamp_local(self, x, y):
        width = max(1, self.get_allocated_width())
        height = max(1, self.get_allocated_height())
        return min(max(0, x), width), min(max(0, y), height)

    def _has_rect(self):
        return self._x0 is not None

    def _current_region(self):
        if not self._has_rect():
            return None
        x0, y0 = self._to_device(self._x0, self._y0)
        x1, y1 = self._to_device(self._x1, self._y1)
        left, top, width, height = normalize_rect(x0, y0, x1, y1)
        return Region(left, top, width, height)

    def _press_event(self, _widget, event):
        if event.button != 1:
            return False
        x, y = self._clamp_local(event.x, event.y)
        self._notice = ""
        if self._has_rect():
            corner = hit_corner(x, y, self._x0, self._y0, self._x1, self._y1)
            if corner is not None:
                self._drag = {
                    "kind": "corner",
                    "corner": corner,
                    "origin": (self._x0, self._y0, self._x1, self._y1),
                }
                self.queue_draw()
                return True
            if hit_edge(x, y, self._x0, self._y0, self._x1, self._y1):
                self._drag = {
                    "kind": "move",
                    "origin": (self._x0, self._y0, self._x1, self._y1),
                    "pointer": (x, y),
                }
                self._set_cursor("move")
                self.queue_draw()
                return True
            if point_inside(x, y, self._x0, self._y0, self._x1, self._y1):
                return True
        previous = (self._x0, self._y0, self._x1, self._y1) if self._has_rect() else None
        self._drag = {"kind": "new", "origin": previous}
        self._x0, self._y0 = x, y
        self._x1, self._y1 = x, y
        self.queue_draw()
        return True

    def _motion_event(self, _widget, event):
        x, y = self._clamp_local(event.x, event.y)
        if self._drag is None:
            if self._has_rect():
                corner = hit_corner(x, y, self._x0, self._y0, self._x1, self._y1)
                if corner is not None:
                    self._set_cursor(_RESIZE_CURSORS[corner])
                elif hit_edge(x, y, self._x0, self._y0, self._x1, self._y1):
                    self._set_cursor("move")
                else:
                    self._set_cursor("crosshair")
            return False
        if self._drag["kind"] == "corner":
            self._x0, self._y0, self._x1, self._y1 = set_corner(
                self._drag["corner"], self._x0, self._y0, self._x1, self._y1, x, y
            )
        elif self._drag["kind"] == "move":
            self._move_rect(x, y)
        else:
            self._x1, self._y1 = x, y
        self.queue_draw()
        return True

    def _release_event(self, _widget, event):
        if self._drag is None or event.button != 1:
            return False
        origin = self._drag.get("origin")
        self._drag = None
        if not self._has_rect():
            return True
        region = self._current_region()
        if region is None or not is_large_enough(region.width, region.height):
            if origin is not None:
                self._x0, self._y0, self._x1, self._y1 = origin
            else:
                self._x0 = self._y0 = self._x1 = self._y1 = None
            self._notice = "La zone doit mesurer au moins 10 × 10 pixels."
        else:
            self._x0, self._y0, self._x1, self._y1 = self._normalized_local()
        self.queue_draw()
        return True

    def _move_rect(self, x, y):
        origin_x0, origin_y0, origin_x1, origin_y1 = self._drag["origin"]
        pointer_x, pointer_y = self._drag["pointer"]
        dx = x - pointer_x
        dy = y - pointer_y
        left = min(origin_x0, origin_x1)
        top = min(origin_y0, origin_y1)
        right = max(origin_x0, origin_x1)
        bottom = max(origin_y0, origin_y1)
        width = max(1, self.get_allocated_width())
        height = max(1, self.get_allocated_height())
        dx = min(max(dx, -left), width - right)
        dy = min(max(dy, -top), height - bottom)
        self._x0 = origin_x0 + dx
        self._y0 = origin_y0 + dy
        self._x1 = origin_x1 + dx
        self._y1 = origin_y1 + dy

    def _normalized_local(self):
        left = min(self._x0, self._x1)
        top = min(self._y0, self._y1)
        right = max(self._x0, self._x1)
        bottom = max(self._y0, self._y1)
        return left, top, right, bottom

    def _key_event(self, _widget, event):
        if event_matches(event, self._cancel_accel):
            self._finish(None)
            return True
        if event_matches(event, self._validate_accel):
            self._validate()
            return True
        return False

    def _validate(self):
        region = self._current_region()
        if region is None:
            self._notice = "Tracez une zone, puis validez."
            self.queue_draw()
            return
        if not is_large_enough(region.width, region.height):
            self._notice = "La zone doit mesurer au moins 10 × 10 pixels."
            self.queue_draw()
            return
        self._finish(region)

    def _delete(self, *_args):
        self._finish(None)
        return True

    def _finish(self, result):
        if self._finished:
            return
        self._finished = True
        seat = self.get_display().get_default_seat()
        seat.ungrab()
        self.destroy()
        self._on_result(result)

    def _draw(self, _widget, context):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        context.set_operator(cairo.OPERATOR_SOURCE)
        context.set_source_rgba(0, 0, 0, 0.4)
        context.paint()
        context.set_operator(cairo.OPERATOR_OVER)
        if self._has_rect():
            left, top, rect_w, rect_h = normalize_rect(self._x0, self._y0, self._x1, self._y1)
            context.set_source_rgba(0.2, 0.55, 1, 0.28)
            context.rectangle(left, top, rect_w, rect_h)
            context.fill()
            context.set_source_rgba(0.25, 0.7, 1, 1)
            context.set_line_width(2)
            context.rectangle(left, top, rect_w, rect_h)
            context.stroke()
            for _name, corner_x, corner_y in corner_positions(self._x0, self._y0, self._x1, self._y1):
                context.set_source_rgba(1, 1, 1, 1)
                context.rectangle(corner_x - 6, corner_y - 6, 12, 12)
                context.fill()
                context.set_source_rgba(0.15, 0.45, 0.9, 1)
                context.set_line_width(2)
                context.rectangle(corner_x - 6, corner_y - 6, 12, 12)
                context.stroke()
            region = self._current_region()
            if region is not None:
                context.set_source_rgba(1, 1, 1, 1)
                context.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                context.set_font_size(16)
                context.move_to(left, max(18, top - 10))
                context.show_text(f"{region.width} × {region.height}")
            self._draw_counter(context, left, top, rect_w, rect_h, width, height)
        self._draw_help(context, width, height)
        return True

    def _draw_counter(self, context, left, top, rect_w, rect_h, bounds_w, bounds_h):
        badge_w, badge_h = 168, 28
        x, y = counter_anchor(left, top, rect_w, rect_h, badge_w, badge_h, bounds_w, bounds_h)
        context.set_source_rgba(0.08, 0.08, 0.08, 0.92)
        context.rectangle(x, y, badge_w, badge_h)
        context.fill()
        context.set_source_rgba(0.45, 0.45, 0.45, 1)
        context.arc(x + 14, y + badge_h / 2, 5, 0, 6.2832)
        context.fill()
        context.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        context.set_font_size(13)
        context.move_to(x + 24, y + 18)
        context.show_text("REC")
        context.set_source_rgba(0.25, 0.25, 0.25, 1)
        context.rectangle(x + 62, y + 12, 46, 5)
        context.fill()
        context.set_source_rgba(0.75, 0.75, 0.75, 1)
        context.set_font_size(12)
        context.move_to(x + 114, y + 18)
        context.show_text(f"0,0 / {self._duration_seconds} s")

    def _draw_help(self, context, width, height):
        validate = shortcut_label(self._validate_accel)
        cancel = shortcut_label(self._cancel_accel)
        lines = [
            "Saisissez un côté pour déplacer le cadre, un coin pour l’ajuster.",
            "Un tracé hors du cadre le remplace.",
            f"Valider : {validate}    Annuler : {cancel}",
        ]
        if self._notice:
            lines.append(self._notice)
        context.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        context.set_font_size(16)
        line_height = 22
        bar_height = 16 + line_height * len(lines)
        context.set_source_rgba(0, 0, 0, 0.72)
        context.rectangle(0, height - bar_height, width, bar_height)
        context.fill()
        context.set_source_rgba(1, 1, 1, 1)
        y = height - bar_height + 22
        for line in lines:
            context.move_to(24, y)
            context.show_text(line)
            y += line_height

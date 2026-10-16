import cairo
import os
import shutil
import subprocess
import tempfile
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from gif_creator.capture import WAYLAND_MESSAGE, record_region, session_kind
from gif_creator.config import load_config, save_config
from gif_creator.encode import estimate_gif_bytes, write_gif
from gif_creator.hotkey import StopHotkey
from gif_creator.paths import downloads_dir
from gif_creator.region import Region, rectangles_intersect
from gif_creator.selector import RegionSelector
from gif_creator.shortcuts import (
    ACTIONS,
    ACTION_LABELS,
    accel_from_event,
    event_matches,
    same_shortcut,
    shortcut_label,
    x11_grab,
)

TOO_SMALL_MESSAGE = "La zone doit mesurer au moins 10 × 10 pixels."
_FRAME_THICKNESS = 4


class ActiveFrame(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_decorated(False)
        self.set_app_paintable(True)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        self.stick()
        visual = Gdk.Screen.get_default().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        self.connect("draw", self._draw)
        self.connect("realize", self._passthrough)
        self.connect("size-allocate", self._reshape)

    def place(self, region):
        screen = Gdk.Display.get_default().get_default_screen()
        scale = 1
        for index in range(screen.get_n_monitors()):
            geometry = screen.get_monitor_geometry(index)
            monitor_scale = screen.get_monitor_scale_factor(index)
            if rectangles_intersect(
                region.x, region.y, region.width, region.height,
                int(round(geometry.x * monitor_scale)),
                int(round(geometry.y * monitor_scale)),
                int(round(geometry.width * monitor_scale)),
                int(round(geometry.height * monitor_scale)),
            ):
                scale = monitor_scale
                break
        thickness = _FRAME_THICKNESS
        self.move(
            int(round(region.x / scale)) - thickness,
            int(round(region.y / scale)) - thickness,
        )
        width = int(round(region.width / scale)) + thickness * 2
        height = int(round(region.height / scale)) + thickness * 2
        self.set_size_request(width, height)
        self.resize(width, height)

    def _passthrough(self, *_args):
        window = self.get_window()
        if window is not None:
            window.set_pass_through(True)

    def _reshape(self, *_args):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        thickness = _FRAME_THICKNESS
        if width <= thickness * 2 or height <= thickness * 2:
            return
        surface = cairo.ImageSurface(cairo.FORMAT_A1, width, height)
        context = cairo.Context(surface)
        context.set_source_rgb(0, 0, 0)
        context.rectangle(0, 0, width, thickness)
        context.rectangle(0, height - thickness, width, thickness)
        context.rectangle(0, 0, thickness, height)
        context.rectangle(width - thickness, 0, thickness, height)
        context.fill()
        region = Gdk.cairo_region_create_from_surface(surface)
        self.shape_combine_region(region)

    def _draw(self, _widget, context):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        context.set_operator(cairo.OPERATOR_SOURCE)
        context.set_source_rgba(0.25, 0.7, 1, 1)
        context.paint()
        return True


def _elapsed_text(seconds):
    return f"Écoulé : {seconds:.1f} s".replace(".", ",")


def _format_bytes(size):
    if size < 1024:
        return f"{int(size)} o"
    if size < 1024 * 1024:
        text = f"{size / 1024:.1f}".replace(".", ",").removesuffix(",0")
        return f"{text} Ko"
    text = f"{size / (1024 * 1024):.1f}".replace(".", ",").removesuffix(",0")
    return f"{text} Mo"


def _estimate_text(region, fps, duration):
    if region is None:
        return "Poids estimé : en attente d’une zone."
    size = estimate_gif_bytes(region.width, region.height, fps, duration)
    return f"Poids estimé : {_format_bytes(size)}"


def _proposed_name():
    return time.strftime("capture-%Y%m%d-%H%M%S.gif")


def _with_gif_suffix(path):
    if path.lower().endswith(".gif"):
        return path
    return path + ".gif"


def reveal_in_folder(path):
    uri = Gio.File.new_for_path(path).get_uri()
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        proxy = Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.freedesktop.FileManager1",
            "/org/freedesktop/FileManager1",
            "org.freedesktop.FileManager1",
            None,
        )
        proxy.call_sync(
            "ShowItems",
            GLib.Variant("(ass)", ([uri], "")),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        return
    except GLib.Error:
        pass
    subprocess.Popen(["xdg-open", os.path.dirname(path)])


class MainWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Gif Créator")
        self.set_default_size(640, 670)
        self.set_border_width(18)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.settings = load_config()
        self.region = None
        self.recording = False
        self.alive = True
        self.stop_event = threading.Event()
        self.capture_thread = None
        self.started_at = 0.0
        self.pending_path = None
        self.saved_path = None
        self._selector = None
        self._capturing_shortcut = None
        self.hotkey = StopHotkey(self._on_hotkey)
        self._ignore_toggle_until = 0.0
        self._toggle_held = False

        self.zone_label = Gtk.Label(label="Aucune zone sélectionnée", xalign=0)
        self.zone_label.set_line_wrap(True)
        self.zone_label.set_can_focus(True)
        self.estimate_label = Gtk.Label(label="", xalign=0)
        self.estimate_label.set_line_wrap(True)
        self.estimate_label.get_style_context().add_class("dim-label")

        self.fps_spin = Gtk.SpinButton.new_with_range(1, 30, 1)
        self.fps_spin.set_digits(0)
        self.fps_spin.set_value(self.settings["fps"])
        self.duration_spin = Gtk.SpinButton.new_with_range(1, 180, 1)
        self.duration_spin.set_digits(0)
        self.duration_spin.set_value(self.settings["max_duration_seconds"])
        self.cursor_check = Gtk.CheckButton.new_with_label("Inclure le curseur")
        self.cursor_check.set_active(self.settings["include_cursor"])
        self.show_window_check = Gtk.CheckButton.new_with_label("Afficher Gif Créator pendant la prise")
        self.show_window_check.set_active(self.settings["show_window_during_capture"])
        self.show_frame_check = Gtk.CheckButton.new_with_label("Afficher le cadre actif")
        self.show_frame_check.set_active(self.settings["show_frame_during_capture"])
        self.active_frame = ActiveFrame()

        self.choose_button = Gtk.Button.new_with_label("Choisir la zone")
        self.choose_button.connect("clicked", self._choose_zone)
        self.start_button = Gtk.Button.new_with_label("Démarrer")
        self.start_button.set_sensitive(False)
        self.start_button.connect("clicked", self._toggle_record)

        self.elapsed_label = Gtk.Label(label=_elapsed_text(0), xalign=0)
        self.hint_label = Gtk.Label(label="", xalign=0)
        self.hint_label.set_line_wrap(True)
        self.hint_label.get_style_context().add_class("dim-label")
        self.shortcut_labels = {}
        self.shortcut_buttons = {}

        self.result_label = Gtk.Label(label="", xalign=0)
        self.result_label.set_line_wrap(True)
        self.result_label.set_selectable(True)
        self.result_label.set_max_width_chars(48)

        self.open_button = Gtk.Button.new_with_label("Ouvrir le dossier")
        self.open_button.connect("clicked", self._open_folder)
        self.open_button.set_no_show_all(True)
        self.save_button = Gtk.Button.new_with_label("Enregistrer sous")
        self.save_button.connect("clicked", self._save_as)
        self.save_button.set_no_show_all(True)

        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        grid.attach(Gtk.Label(label="Cadence (images par seconde)", xalign=0), 0, 0, 1, 1)
        grid.attach(self.fps_spin, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Durée maximale (secondes)", xalign=0), 0, 1, 1, 1)
        grid.attach(self.duration_spin, 1, 1, 1, 1)
        grid.attach(self.cursor_check, 0, 2, 2, 1)
        grid.attach(self.show_window_check, 0, 3, 2, 1)
        grid.attach(self.show_frame_check, 0, 4, 2, 1)

        shortcut_grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        shortcut_grid.attach(Gtk.Label(label="Raccourcis", xalign=0), 0, 0, 3, 1)
        for row, action in enumerate(ACTIONS, start=1):
            shortcut_grid.attach(Gtk.Label(label=ACTION_LABELS[action], xalign=0), 0, row, 1, 1)
            value = Gtk.Label(xalign=0)
            value.set_selectable(True)
            self.shortcut_labels[action] = value
            shortcut_grid.attach(value, 1, row, 1, 1)
            button = Gtk.Button.new_with_label("Modifier")
            button.connect("clicked", self._toggle_shortcut_capture, action)
            self.shortcut_buttons[action] = button
            shortcut_grid.attach(button, 2, row, 1, 1)
        self._refresh_shortcut_labels()

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.pack_start(self.open_button, False, False, 0)
        actions.pack_start(self.save_button, False, False, 0)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.pack_start(self.choose_button, False, False, 0)
        box.pack_start(self.zone_label, False, False, 0)
        box.pack_start(self.estimate_label, False, False, 0)
        box.pack_start(grid, False, False, 0)
        box.pack_start(shortcut_grid, False, False, 0)
        box.pack_start(self.start_button, False, False, 0)
        box.pack_start(self.elapsed_label, False, False, 0)
        box.pack_start(self.hint_label, False, False, 0)
        box.pack_start(self.result_label, False, False, 0)
        box.pack_start(actions, False, False, 0)
        self.add(box)

        self.fps_spin.connect("value-changed", self._save_settings)
        self.duration_spin.connect("value-changed", self._save_settings)
        self.cursor_check.connect("toggled", self._save_settings)
        self.show_window_check.connect("toggled", self._on_show_window_toggled)
        self.show_frame_check.connect("toggled", self._on_show_frame_toggled)
        self._update_hint()
        self.connect("delete-event", self._on_delete)
        self.connect("key-press-event", self._on_key)
        self.connect("key-release-event", self._on_key_release)
        for widget in (
            self.fps_spin,
            self.duration_spin,
            self.cursor_check,
            self.show_window_check,
            self.show_frame_check,
            self.choose_button,
            self.start_button,
            self.open_button,
            self.save_button,
            self.result_label,
            *self.shortcut_buttons.values(),
            *self.shortcut_labels.values(),
        ):
            widget.connect("key-press-event", self._on_key)
            widget.connect("key-release-event", self._on_key_release)

        kind = session_kind()
        if kind == "wayland":
            self.result_label.set_text(WAYLAND_MESSAGE)
        elif kind == "none":
            self.result_label.set_text("Aucune session graphique n’est détectée.")
        self._build_hud()
        self._restore_region()
        self._update_estimate()

    def _save_settings(self, *_args):
        self.settings["fps"] = int(self.fps_spin.get_value())
        self.settings["max_duration_seconds"] = int(self.duration_spin.get_value())
        self.settings["include_cursor"] = self.cursor_check.get_active()
        self.settings["show_window_during_capture"] = self.show_window_check.get_active()
        self.settings["show_frame_during_capture"] = self.show_frame_check.get_active()
        save_config(self.settings)
        self._update_estimate()

    def _update_hint(self):
        if self.show_window_check.get_active():
            self.hint_label.set_text("La fenêtre reste visible pendant l’enregistrement.")
        else:
            self.hint_label.set_text("La fenêtre se masque pendant l’enregistrement.")

    def _update_estimate(self):
        self.estimate_label.set_text(
            _estimate_text(
                self.region,
                int(self.fps_spin.get_value()),
                int(self.duration_spin.get_value()),
            )
        )

    def _on_show_window_toggled(self, *_args):
        self._save_settings()
        self._update_hint()
        if not self.recording:
            return
        if self.show_window_check.get_active():
            self.show()
            self.present()
        else:
            self.hide()

    def _on_show_frame_toggled(self, *_args):
        self._save_settings()
        self._sync_overlay()

    def _sync_overlay(self):
        visible = (
            self._selector is None
            and self.region is not None
            and self.show_frame_check.get_active()
        )
        if not visible:
            self.active_frame.hide()
            self._hide_hud()
            return
        self.active_frame.place(self.region)
        self.active_frame.show_all()
        self.active_frame.present()
        self._show_hud()

    def _update_frame_overlay(self):
        self._sync_overlay()

    def _build_hud(self):
        self._capture_limit = int(self.duration_spin.get_value())
        self.hud = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.hud.set_decorated(False)
        self.hud.set_resizable(False)
        self.hud.set_keep_above(True)
        self.hud.set_skip_taskbar_hint(True)
        self.hud.set_skip_pager_hint(True)
        self.hud.set_accept_focus(False)
        self.hud.set_focus_on_map(False)
        self.hud.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        self.hud.stick()

        self.rec_dot = Gtk.Box()
        self.rec_dot.set_size_request(10, 10)
        self.rec_dot.get_style_context().add_class("rec-dot")
        self.rec_label = Gtk.Label(label="REC")
        self.rec_label.get_style_context().add_class("rec-label")
        self.hud_progress = Gtk.ProgressBar()
        self.hud_progress.set_fraction(0)
        self.hud_progress.set_size_request(120, 8)
        self.hud_progress.get_style_context().add_class("rec-bar")
        self.hud_time = Gtk.Label(label=self._hud_time_text(0), xalign=0)
        self.hud_time.get_style_context().add_class("rec-time")

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_start(10)
        row.set_margin_end(10)
        row.set_margin_top(6)
        row.set_margin_bottom(6)
        row.pack_start(self.rec_dot, False, False, 0)
        row.pack_start(self.rec_label, False, False, 0)
        row.pack_start(self.hud_progress, False, False, 0)
        row.pack_start(self.hud_time, False, False, 0)
        self.hud.add(row)

        css = Gtk.CssProvider()
        css.load_from_data(
            b"""
            .rec-dot { background: #6a6a6a; border-radius: 5px; }
            .rec-dot.lit { background: #e23b3b; }
            .rec-label { color: #8a8a8a; font-weight: bold; }
            .rec-label.lit { color: #e23b3b; }
            .rec-time { font-size: 12px; }
            progressbar.rec-bar trough { min-height: 6px; }
            progressbar.rec-bar progress { min-height: 6px; background: #e23b3b; }
            """
        )
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _hud_time_text(self, seconds):
        limit = max(1, int(self._capture_limit))
        shown = min(max(0.0, seconds), float(limit))
        return f"{shown:.1f} / {limit} s".replace(".", ",")

    def _set_rec_lit(self, lit):
        for widget in (self.rec_dot, self.rec_label):
            style = widget.get_style_context()
            if lit:
                style.add_class("lit")
            else:
                style.remove_class("lit")

    def _show_hud(self):
        self._capture_limit = max(1, int(self.duration_spin.get_value()))
        if not self.recording:
            self.hud_progress.set_fraction(0)
            self.hud_time.set_text(self._hud_time_text(0))
        self._set_rec_lit(self.recording)
        self.hud.show_all()
        self.hud.present()
        GLib.idle_add(self._place_hud)

    def _hide_hud(self):
        self.hud.hide()
        self.hud.set_visible(False)

    def _place_hud(self):
        if not self.hud.get_visible():
            return False
        natural = self.hud.get_preferred_size()[1]
        width = max(natural.width, 1)
        height = max(natural.height, 1)
        screen = Gdk.Display.get_default().get_default_screen()
        monitors = []
        for index in range(screen.get_n_monitors()):
            geometry = screen.get_monitor_geometry(index)
            scale = screen.get_monitor_scale_factor(index)
            monitors.append(
                (
                    int(round(geometry.x * scale)),
                    int(round(geometry.y * scale)),
                    int(round(geometry.width * scale)),
                    int(round(geometry.height * scale)),
                    scale,
                )
            )
        if not monitors:
            return False
        chosen = monitors[0]
        if self.region is not None:
            for monitor in monitors:
                if rectangles_intersect(
                    self.region.x, self.region.y, self.region.width, self.region.height,
                    monitor[0], monitor[1], monitor[2], monitor[3],
                ):
                    chosen = monitor
                    break
        left, top, mon_w, mon_h, scale = chosen
        if self.region is None:
            return False
        frame_top = int(round(self.region.y / scale)) - _FRAME_THICKNESS
        frame_right = int(round((self.region.x + self.region.width) / scale)) + _FRAME_THICKNESS
        frame_bottom = int(round((self.region.y + self.region.height) / scale)) + _FRAME_THICKNESS
        gap = 4
        pos_x = frame_right - width
        pos_y = frame_top - height - gap
        if pos_y < top:
            pos_y = frame_bottom + gap
        pos_x = min(max(left, pos_x), max(left, left + mon_w - width))
        pos_y = min(max(top, pos_y), max(top, top + mon_h - height))
        self.hud.move(int(pos_x), int(pos_y))
        return False

    def _monitor_rects(self):
        screen = Gdk.Display.get_default().get_default_screen()
        rects = []
        for index in range(screen.get_n_monitors()):
            geometry = screen.get_monitor_geometry(index)
            scale = screen.get_monitor_scale_factor(index)
            rects.append(
                (
                    int(round(geometry.x * scale)),
                    int(round(geometry.y * scale)),
                    int(round(geometry.width * scale)),
                    int(round(geometry.height * scale)),
                )
            )
        return rects

    def _region_is_visible(self, region):
        for left, top, width, height in self._monitor_rects():
            if rectangles_intersect(region.x, region.y, region.width, region.height, left, top, width, height):
                return True
        return False

    def _restore_region(self):
        raw = self.settings.get("region")
        if not raw:
            return
        region = Region(raw["x"], raw["y"], raw["width"], raw["height"])
        if not self._region_is_visible(region):
            self.settings["region"] = None
            save_config(self.settings)
            return
        self._apply_region(region, persist=False)

    def _apply_region(self, region, persist):
        self.region = region
        self.zone_label.set_text(
            f"Zone : {region.width} × {region.height} pixels, origine ({region.x}, {region.y})"
        )
        self.start_button.set_sensitive(True)
        if persist:
            self.result_label.set_text("")
            self.settings["region"] = {
                "x": region.x,
                "y": region.y,
                "width": region.width,
                "height": region.height,
            }
            save_config(self.settings)
        self._update_estimate()
        self._sync_overlay()

    def _refresh_shortcut_labels(self):
        for action in ACTIONS:
            label = self.shortcut_labels[action]
            button = self.shortcut_buttons[action]
            if self._capturing_shortcut == action:
                label.set_text("Appuyez sur le raccourci…")
                button.set_label("Annuler")
            else:
                label.set_text(shortcut_label(self.settings["shortcuts"][action]))
                button.set_label("Modifier")

    def _toggle_shortcut_capture(self, _button, action):
        if self.recording:
            return
        if self._capturing_shortcut == action:
            self._capturing_shortcut = None
        else:
            self._capturing_shortcut = action
            GLib.idle_add(self._focus_for_shortcut)
        self._refresh_shortcut_labels()

    def _focus_for_shortcut(self):
        if self._capturing_shortcut is not None:
            self.zone_label.grab_focus()
        return False

    def _assign_shortcut(self, event):
        action = self._capturing_shortcut
        accel = accel_from_event(event)
        if accel is None:
            return True
        for other, current in self.settings["shortcuts"].items():
            if other != action and same_shortcut(current, accel):
                self.result_label.set_text("Ce raccourci est déjà utilisé.")
                return True
        self.settings["shortcuts"][action] = accel
        self._capturing_shortcut = None
        save_config(self.settings)
        self._refresh_shortcut_labels()
        self.result_label.set_text(f"Raccourci enregistré : {shortcut_label(accel)}")
        return True

    def _set_controls_locked(self, locked):
        self.choose_button.set_sensitive(not locked)
        self.fps_spin.set_sensitive(not locked)
        self.duration_spin.set_sensitive(not locked)
        self.cursor_check.set_sensitive(not locked)
        for button in self.shortcut_buttons.values():
            button.set_sensitive(not locked)
        if locked:
            self._capturing_shortcut = None
            self._refresh_shortcut_labels()

    def _choose_zone(self, *_args):
        if self.recording or self._selector is not None:
            return
        self.hide()
        self._capturing_shortcut = None
        self._refresh_shortcut_labels()
        self._selector = RegionSelector(
            self._zone_chosen,
            self.region,
            self.settings["shortcuts"]["cancel_zone"],
            self.settings["shortcuts"]["validate_zone"],
            int(self.duration_spin.get_value()),
        )
        self._sync_overlay()
        self._selector.show_all()

    def _zone_chosen(self, result):
        self._selector = None
        if self.alive:
            self.show()
            self.present()
        if not self.alive:
            return
        if result is None:
            self._sync_overlay()
            return
        if result is False:
            self.result_label.set_text(TOO_SMALL_MESSAGE)
            self._sync_overlay()
            return
        self._apply_region(result, persist=True)

    def _on_key(self, _widget, event):
        if self._capturing_shortcut is not None:
            return self._assign_shortcut(event)
        if event_matches(event, self.settings["shortcuts"]["toggle_recording"]):
            if not self._toggle_held:
                self._toggle_held = True
                self._handle_toggle()
            return True
        return False

    def _on_key_release(self, _widget, event):
        if event_matches(event, self.settings["shortcuts"]["toggle_recording"]):
            self._toggle_held = False
        return False

    def _handle_toggle(self):
        if self._selector is not None:
            return
        if time.monotonic() < self._ignore_toggle_until:
            return
        if self.recording:
            self.stop_event.set()
            return
        if self.region is None or not self.start_button.get_sensitive():
            if self.region is None:
                self.result_label.set_text("Aucune zone sélectionnée.")
            return
        self._ignore_toggle_until = time.monotonic() + 0.4
        self._begin_record()

    def _on_hotkey(self, keycode, modifiers):
        if not self.recording:
            return
        toggle = x11_grab(self.settings["shortcuts"]["toggle_recording"])
        if toggle == (int(keycode), int(modifiers)) and time.monotonic() < self._ignore_toggle_until:
            return
        self.stop_event.set()

    def _stop_bindings(self):
        bindings = []
        for action in ("toggle_recording",):
            grab = x11_grab(self.settings["shortcuts"][action])
            if grab is not None:
                bindings.append(grab)
        return bindings

    def _toggle_record(self, *_args):
        if self.recording:
            self.stop_event.set()
            return
        self._begin_record()

    def _begin_record(self):
        if self.region is None or self.recording:
            return
        kind = session_kind()
        if kind == "wayland":
            self._error(WAYLAND_MESSAGE)
            return
        if kind != "x11":
            self._error("Aucune session graphique n’est détectée.")
            return
        self._delete_pending()
        self.saved_path = None
        self.open_button.hide()
        self.save_button.hide()
        self.result_label.set_text("")
        self._save_settings()
        self.recording = True
        self.stop_event.clear()
        self.elapsed_label.set_text(_elapsed_text(0))
        self.start_button.set_label("Arrêter")
        self._set_controls_locked(True)
        if self.show_window_check.get_active():
            self.present()
        else:
            self.hide()
        self._update_frame_overlay()
        GLib.timeout_add(250, self._start_capture)

    def _start_capture(self):
        if not self.recording or not self.alive:
            return False
        self.started_at = time.monotonic()
        self.hotkey.arm(self._stop_bindings())
        if self.hud.get_visible():
            self._capture_limit = max(1, int(self.duration_spin.get_value()))
            self.hud_progress.set_fraction(0)
            self.hud_time.set_text(self._hud_time_text(0))
            self._set_rec_lit(True)
        GLib.timeout_add(100, self._tick)
        fps = int(self.fps_spin.get_value())
        duration = int(self.duration_spin.get_value())
        include_cursor = self.cursor_check.get_active()
        region = self.region

        def work():
            try:
                frames = record_region(region, fps, duration, include_cursor, self.stop_event)
            except Exception as error:
                message = str(error)
                GLib.idle_add(self._capture_failed, message)
                return
            GLib.idle_add(self._capture_finished, frames, fps)

        self.capture_thread = threading.Thread(target=work, name="gif-creator-capture", daemon=True)
        self.capture_thread.start()
        return False

    def _tick(self):
        if not self.recording:
            return False
        elapsed = time.monotonic() - self.started_at
        limit = max(1, int(self._capture_limit))
        self.elapsed_label.set_text(_elapsed_text(min(elapsed, limit)))
        self.hud_progress.set_fraction(min(1.0, elapsed / limit))
        self.hud_time.set_text(self._hud_time_text(elapsed))
        return True

    def _show_again(self):
        self.hotkey.disarm()
        self.recording = False
        self._sync_overlay()
        self.start_button.set_label("Démarrer")
        self._set_controls_locked(False)
        self.start_button.set_sensitive(self.region is not None)
        if self.alive:
            self.show()
            self.present()

    def _capture_failed(self, message):
        if not self.alive:
            return False
        self._show_again()
        self._error(message)
        return False

    def _capture_finished(self, frames, fps):
        if not self.alive:
            return False
        self._show_again()
        self.result_label.set_text("Encodage en cours…")
        self.start_button.set_sensitive(False)
        self._set_controls_locked(True)

        def work():
            handle = tempfile.NamedTemporaryFile(
                prefix="gif-creator-", suffix=".gif", delete=False
            )
            handle.close()
            try:
                write_gif(frames, handle.name, fps)
            except Exception as error:
                try:
                    os.remove(handle.name)
                except OSError:
                    pass
                GLib.idle_add(self._encode_failed, str(error))
                return
            GLib.idle_add(self._encode_finished, handle.name)

        threading.Thread(target=work, name="gif-creator-encode", daemon=True).start()
        return False

    def _encode_failed(self, message):
        if not self.alive:
            return False
        self._set_controls_locked(False)
        self.start_button.set_sensitive(self.region is not None)
        self._error("Le GIF n’a pas pu être créé.", message)
        return False

    def _encode_finished(self, path):
        if not self.alive:
            try:
                os.remove(path)
            except OSError:
                pass
            return False
        self.pending_path = path
        self._set_controls_locked(False)
        self.start_button.set_sensitive(self.region is not None)
        self.result_label.set_text("Choisissez l’emplacement du GIF.")
        self._save_as()
        return False

    def _save_as(self, *_args):
        if not self.pending_path or not os.path.isfile(self.pending_path):
            return
        dialog = Gtk.FileChooserNative.new(
            "Enregistrer sous",
            self,
            Gtk.FileChooserAction.SAVE,
            "Enregistrer",
            "Annuler",
        )
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_name(_proposed_name())
        dialog.set_current_folder(downloads_dir())
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Images GIF")
        file_filter.add_pattern("*.gif")
        dialog.add_filter(file_filter)
        response = dialog.run()
        filename = dialog.get_filename() if response == Gtk.ResponseType.ACCEPT else None
        dialog.destroy()
        if not filename:
            self.result_label.set_text("Export annulé. Le GIF est prêt : utilisez « Enregistrer sous ».")
            self.save_button.show()
            self.open_button.hide()
            return
        destination = _with_gif_suffix(filename)
        try:
            folder = os.path.dirname(destination)
            if folder:
                os.makedirs(folder, exist_ok=True)
            if os.path.abspath(destination) != os.path.abspath(self.pending_path):
                shutil.copyfile(self.pending_path, destination)
                self._delete_pending()
            else:
                self.pending_path = None
        except OSError as error:
            self._error("Le fichier n’a pas pu être enregistré.", str(error))
            self.save_button.show()
            return
        self.saved_path = destination
        self.result_label.set_text(f"GIF enregistré : {destination}")
        self.save_button.hide()
        self.open_button.show()

    def _open_folder(self, *_args):
        if self.saved_path and os.path.isfile(self.saved_path):
            reveal_in_folder(self.saved_path)

    def _delete_pending(self):
        if self.pending_path and os.path.isfile(self.pending_path):
            try:
                os.remove(self.pending_path)
            except OSError:
                pass
        self.pending_path = None

    def _error(self, message, detail=None):
        self.result_label.set_text(message)
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=message,
        )
        if detail:
            dialog.format_secondary_text(detail)
        dialog.run()
        dialog.destroy()

    def _on_delete(self, *_args):
        self.alive = False
        self.recording = False
        self.stop_event.set()
        self.hotkey.disarm()
        self.active_frame.hide()
        if self.capture_thread is not None:
            self.capture_thread.join(timeout=1)
        self._delete_pending()
        return False


def main():
    window = MainWindow()
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    window.open_button.hide()
    window.save_button.hide()
    Gtk.main()

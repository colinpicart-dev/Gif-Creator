import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk

ACTIONS = ("toggle_recording", "validate_zone", "cancel_zone")

ACTION_LABELS = {
    "toggle_recording": "Démarrer ou arrêter",
    "validate_zone": "Valider la zone",
    "cancel_zone": "Annuler la sélection",
}

DEFAULT_SHORTCUTS = {
    "toggle_recording": "space",
    "validate_zone": "Return",
    "cancel_zone": "Escape",
}

_MODIFIER_KEYVALS = {
    Gdk.KEY_Shift_L,
    Gdk.KEY_Shift_R,
    Gdk.KEY_Control_L,
    Gdk.KEY_Control_R,
    Gdk.KEY_Alt_L,
    Gdk.KEY_Alt_R,
    Gdk.KEY_Meta_L,
    Gdk.KEY_Meta_R,
    Gdk.KEY_Super_L,
    Gdk.KEY_Super_R,
    Gdk.KEY_Hyper_L,
    Gdk.KEY_Hyper_R,
    Gdk.KEY_ISO_Level3_Shift,
    Gdk.KEY_Mode_switch,
}


def parse_accel(accel):
    if not isinstance(accel, str) or not accel:
        return 0, 0
    key, mods = Gtk.accelerator_parse(accel)
    return int(key), int(mods)


def is_valid_accel(accel):
    key, _mods = parse_accel(accel)
    return key != 0


def _masked_mods(mods):
    mask = int(Gtk.accelerator_get_default_mod_mask())
    return Gdk.ModifierType(int(mods) & mask)


def normalize_accel(accel):
    key, mods = parse_accel(accel)
    if key == 0:
        return ""
    return Gtk.accelerator_name(Gdk.keyval_to_lower(key), _masked_mods(mods))


def shortcut_label(accel):
    key, mods = parse_accel(accel)
    if key == 0:
        return "Aucun"
    mods = _masked_mods(mods)
    parts = []
    if mods & Gdk.ModifierType.CONTROL_MASK:
        parts.append("Ctrl")
    if mods & Gdk.ModifierType.SHIFT_MASK:
        parts.append("Maj")
    if mods & Gdk.ModifierType.MOD1_MASK:
        parts.append("Alt")
    super_mask = getattr(Gdk.ModifierType, "SUPER_MASK", 0)
    if int(mods) & int(Gdk.ModifierType.MOD4_MASK | super_mask):
        parts.append("Super")
    key_name = Gtk.accelerator_get_label(Gdk.keyval_to_lower(key), Gdk.ModifierType(0))
    key_name = {
        "Escape": "Échap",
        "Return": "Entrée",
        "Enter": "Entrée",
        "space": "Espace",
        "Space": "Espace",
        "Espace": "Espace",
    }.get(key_name, key_name)
    parts.append(key_name)
    return "+".join(parts)


def same_shortcut(left, right):
    normalized = normalize_accel(left)
    return bool(normalized) and normalized == normalize_accel(right)


def event_matches(event, accel):
    key, mods = parse_accel(accel)
    if key == 0:
        return False
    state = int(event.state & Gtk.accelerator_get_default_mod_mask())
    return Gdk.keyval_to_lower(event.keyval) == Gdk.keyval_to_lower(key) and state == int(_masked_mods(mods))


def accel_from_event(event):
    if event.keyval in _MODIFIER_KEYVALS:
        return None
    name = Gtk.accelerator_name(Gdk.keyval_to_lower(event.keyval), _masked_mods(event.state))
    if not is_valid_accel(name):
        return None
    return name


def x11_grab(accel):
    key, mods = parse_accel(accel)
    if key == 0:
        return None
    keymap = Gdk.Keymap.get_default()
    if keymap is None:
        return None
    found, entries = keymap.get_entries_for_keyval(Gdk.keyval_to_lower(key))
    if not found or not entries:
        return None
    keycode = int(entries[0].keycode)
    x_mask = 0
    if mods & Gdk.ModifierType.SHIFT_MASK:
        x_mask |= 1
    if mods & Gdk.ModifierType.CONTROL_MASK:
        x_mask |= 4
    if mods & Gdk.ModifierType.MOD1_MASK:
        x_mask |= 8
    super_mask = getattr(Gdk.ModifierType, "SUPER_MASK", 0)
    if mods & (Gdk.ModifierType.MOD4_MASK | super_mask):
        x_mask |= 64
    return keycode, x_mask

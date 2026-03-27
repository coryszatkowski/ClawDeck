#!/usr/bin/env python3
"""
ClawDeck — Stream Deck controller for Claude Code terminal sessions

Maps a 5x3 (15-key) Elgato Stream Deck to terminal windows arranged in a grid.

GRID MODE (default):
  ┌─────┬─────┬─────┬─────┬─────┐
  │ T1  │ T2  │ T3  │ T4  │ T5  │
  ├─────┼─────┼─────┼─────┼─────┤
  │ T6  │ T7  │ T8  │ T9  │ T10 │
  ├─────┼─────┼─────┼─────┼─────┤
  │ T11 │ T12 │ T13 │ T14 │  ⏎  │
  └─────┴─────┴─────┴─────┴─────┘
  - Tap a terminal button → activate that window (turns amber)
  - Tap the already-active button → enter Nav Mode
  - Hold any terminal button (>=0.5s) → activate + trigger Whisprflow (fn)
  - Bottom-right key always sends Enter to active window

NAV MODE (tap the active terminal):
  ┌─────┬─────┬─────┬─────┬─────┐
  │  1  │  2  │  3  │  4  │  5  │  ← ROYGB number keys
  ├─────┼─────┼─────┼─────┼─────┤
  │     │     │  ↑  │     │BACK │
  ├─────┼─────┼─────┼─────┼─────┤
  │ MIC │  ←  │  ↓  │  →  │  ⏎  │
  └─────┴─────┴─────┴─────┴─────┘
  - 1-5 keys send number keystrokes (for Claude Code multi-choice)
  - Arrow cluster for navigation (slate-blue zone)
  - MIC triggers Whisprflow (fn double-press)
  - Enter sends Return (stays in Nav Mode for multi-question flows)
  - BACK returns to Grid Mode

Active terminal is amber; all others are black.
"""

import time
import threading
import subprocess
import sys
import json
import os
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler

def _setup_logging():
    """Configure clawdeck logger with console and file handlers."""
    log_dir = Path.home() / ".clawdeck"
    log_dir.mkdir(exist_ok=True)

    logger = logging.getLogger("clawdeck")
    logger.setLevel(logging.DEBUG)

    # Console: INFO and above
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(console)

    # File: DEBUG and above, rotating 1MB x 3 backups
    file_handler = RotatingFileHandler(
        log_dir / "clawdeck.log", maxBytes=1_000_000, backupCount=3
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(file_handler)

    return logger

logger = _setup_logging()

from PIL import Image, ImageDraw, ImageFont
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper
from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGWindowListOptionOnScreenOnly,
    kCGWindowListExcludeDesktopElements,
    kCGNullWindowID,
    CGGetActiveDisplayList,
    CGDisplayBounds,
    CGMainDisplayID,
    CGEventCreate,
    CGEventCreateKeyboardEvent,
    CGEventGetLocation,
    CGEventPost,
    CGEventGetIntegerValueField,
    CGEventGetFlags,
    CGEventSetFlags,
    CGEventTapCreate,
    kCGHIDEventTap,
    kCGSessionEventTap,
    kCGHeadInsertEventTap,
    kCGEventKeyDown,
    kCGEventFlagsChanged,
)
import CoreFoundation


# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION — edit these to match your setup
# ═══════════════════════════════════════════════════════════════════════

# All terminal apps to include in the grid (windows from any of these get tiled)
TERMINAL_APPS = {"Terminal", "iTerm2", "iTerm", "Warp", "Alacritty", "kitty", "Hyper"}
COLS = 5
ROWS = 3
HOLD_THRESHOLD_SEC = 0.5        # hold longer than this → trigger Whisprflow
FN_KEY_CODE = 63                # macOS fn key code for Whisprflow/dictation
POLL_INTERVAL = 0.2             # seconds between active-window checks
SNAP_TOLERANCE = 20             # px — ignore micro-movements smaller than this
SNAP_SETTLE_POLLS = 5           # window must be stable for this many polls (~1s) before snapping
STATUS_DIR = "/tmp/deck-status" # where hook scripts write state files
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OVERLAY_FILE = os.path.join(SCRIPT_DIR, ".deck-overlay.json")
STATUS_STALE_SEC = 3600         # ignore idle/working status after 1 hour
PENDING_INFER_SEC = 2.0         # if "pending" (PreToolUse) sits this long → infer permission
BLINK_INTERVAL = 0.5            # seconds per blink phase (on/off) for permission
TTY_MAP_REFRESH_SEC = 30        # rebuild TTY map every N seconds
SCREEN_REFRESH_SEC = 30         # recheck display bounds every N seconds
BRIGHTNESS = 80                 # Stream Deck brightness (0-100)

# Colors (R, G, B)
COLOR_BG_DEFAULT    = (0, 0, 0)         # black
COLOR_FG_DEFAULT    = (255, 255, 255)   # white
COLOR_BG_ACTIVE     = (255, 176, 0)     # amber
COLOR_FG_ACTIVE     = (0, 0, 0)         # black
COLOR_BG_IDLE       = (30, 100, 220)    # blue  — Claude waiting for input
COLOR_FG_IDLE       = (255, 255, 255)   # white
COLOR_BG_WORKING    = (30, 160, 70)     # green — Claude actively working
COLOR_FG_WORKING    = (255, 255, 255)   # white
COLOR_BG_PERMISSION = (200, 50, 50)     # red   — Claude needs permission
COLOR_FG_PERMISSION = (255, 255, 255)   # white
COLOR_BG_ENTER      = (30, 30, 30)      # dark gray
COLOR_FG_ENTER      = (255, 176, 0)     # amber
COLOR_FG_NAV_NUM    = (255, 255, 255)   # white
COLOR_BG_NAV_BACK   = (160, 30, 30)     # saturated red
COLOR_BG_NAV_ARROW  = (30, 35, 55)      # dark slate-blue — arrow zone
COLOR_FG_NAV_ARROW  = (180, 200, 255)   # pale blue — arrow glyphs
COLOR_BG_NAV_ACTION = (230, 230, 230)   # white — MIC / Enter zone
COLOR_FG_NAV_ACTION = (0, 0, 0)         # black — MIC / Enter glyphs
COLOR_BG_NAV_EMPTY  = (15, 15, 15)      # near-black
# ROYGB backgrounds for number keys 1-5
COLOR_BG_NUM_1 = (180, 40, 40)          # red
COLOR_BG_NUM_2 = (200, 120, 20)         # orange
COLOR_BG_NUM_3 = (190, 175, 20)         # yellow
COLOR_BG_NUM_4 = (40, 150, 60)          # green
COLOR_BG_NUM_5 = (40, 80, 200)          # blue


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS (derived)
# ═══════════════════════════════════════════════════════════════════════

TOTAL_KEYS = COLS * ROWS            # 15
GRID_SLOTS = TOTAL_KEYS             # 15 — all slots tile on screen
DECK_TERMINAL_SLOTS = TOTAL_KEYS - 1  # 14 — slots with Stream Deck buttons
ENTER_KEY_INDEX = TOTAL_KEYS - 1    # 14 (bottom-right key = Enter)

MODE_GRID = "grid"
MODE_NAV = "nav"

# ═══════════════════════════════════════════════════════════════════════
# LAYOUTS — each maps key index to a terminal name
# Multiple keys with the same name merge into one window.
# Key 14 is always ENTER.
# ═══════════════════════════════════════════════════════════════════════

LAYOUTS = {
    "default": [
        "T1",  "T2",  "T3",  "T4",  "T5",
        "T6",  "T7",  "T8",  "T9",  "T10",
        "T11", "T12", "T13", "T14", "ENTER",
    ],
    # Quad: T1 = 2x2 top-left (keys 0,1,5,6)
    "quad": [
        "T1",  "T1",  "T2",  "T3",  "T4",
        "T1",  "T1",  "T5",  "T6",  "T7",
        "T8",  "T9",  "T10", "T11", "ENTER",
    ],
    # Double Quad: T1 = 2x2 top-left, T2 = 2x2 top-middle (keys 2,3,7,8)
    "double_quad": [
        "T1",  "T1",  "T2",  "T2",  "T3",
        "T1",  "T1",  "T2",  "T2",  "T4",
        "T5",  "T6",  "T7",  "T8",  "ENTER",
    ],
    # Wide: T1 = 3x2 top-left (keys 0,1,2,5,6,7)
    "wide": [
        "T1",  "T1",  "T1",  "T2",  "T3",
        "T1",  "T1",  "T1",  "T4",  "T5",
        "T6",  "T7",  "T8",  "T9",  "ENTER",
    ],
    # Half: T1 = 2x3 left side (keys 0,1,5,6,10,11)
    "half": [
        "T1",  "T1",  "T2",  "T3",  "T4",
        "T1",  "T1",  "T5",  "T6",  "T7",
        "T1",  "T1",  "T8",  "T9",  "ENTER",
    ],
}

LAYOUT_NAMES = list(LAYOUTS.keys())

# Nav mode layout: key_index -> (action_type, value)
NAV_KEYMAP = {
    0:  ("num",   "1"),
    1:  ("num",   "2"),
    2:  ("num",   "3"),
    3:  ("num",   "4"),
    4:  ("num",   "5"),
    9:  ("back",  None),
    7:  ("arrow", "Up"),
    10: ("whisprflow", None),
    11: ("arrow", "Left"),
    12: ("arrow", "Down"),
    13: ("arrow", "Right"),
    14: ("enter", None),
}

# Nav mode button labels and styles
NAV_BUTTON_STYLES = {
    0:  {"label": "1",    "bg": COLOR_BG_NUM_1,      "fg": COLOR_FG_NAV_NUM},
    1:  {"label": "2",    "bg": COLOR_BG_NUM_2,      "fg": COLOR_FG_NAV_NUM},
    2:  {"label": "3",    "bg": COLOR_BG_NUM_3,      "fg": COLOR_FG_NAV_NUM},
    3:  {"label": "4",    "bg": COLOR_BG_NUM_4,      "fg": COLOR_FG_NAV_NUM},
    4:  {"label": "5",    "bg": COLOR_BG_NUM_5,      "fg": COLOR_FG_NAV_NUM},
    9:  {"label": "BACK", "bg": COLOR_BG_NAV_BACK,   "fg": COLOR_FG_DEFAULT},
    7:  {"label": "↑",    "bg": COLOR_BG_NAV_ARROW,  "fg": COLOR_FG_NAV_ARROW},
    10: {"label": "MIC",  "bg": COLOR_BG_NAV_ACTION, "fg": COLOR_FG_NAV_ACTION},
    11: {"label": "←",    "bg": COLOR_BG_NAV_ARROW,  "fg": COLOR_FG_NAV_ARROW},
    12: {"label": "↓",    "bg": COLOR_BG_NAV_ARROW,  "fg": COLOR_FG_NAV_ARROW},
    13: {"label": "→",    "bg": COLOR_BG_NAV_ARROW,  "fg": COLOR_FG_NAV_ARROW},
    14: {"label": "⏎",    "bg": COLOR_BG_NAV_ACTION, "fg": COLOR_FG_NAV_ACTION},
}

# macOS key codes for arrow keys
ARROW_KEY_CODES = {"Up": 126, "Down": 125, "Left": 123, "Right": 124}

# CGEvent field IDs and modifier masks
kCGKeyboardEventKeycode = 9
MOD_SHIFT   = 0x20000
MOD_CONTROL = 0x40000
MOD_OPTION  = 0x80000
MOD_COMMAND = 0x100000
MOD_FN      = 0x800000

# Common macOS key codes → names (for display only)
KEY_NAMES = {
    0: "A", 1: "S", 2: "D", 3: "F", 4: "H", 5: "G", 6: "Z", 7: "X", 8: "C", 9: "V",
    11: "B", 12: "Q", 13: "W", 14: "E", 15: "R", 16: "Y", 17: "T", 18: "1", 19: "2",
    20: "3", 21: "4", 22: "6", 23: "5", 24: "=", 25: "9", 26: "7", 27: "-", 28: "8",
    29: "0", 31: "O", 32: "U", 34: "I", 35: "P", 37: "L", 38: "J", 40: "K", 45: "N",
    46: "M", 36: "Return", 48: "Tab", 49: "Space", 51: "Delete", 53: "Escape",
    63: "fn", 122: "F1", 120: "F2", 99: "F3", 118: "F4", 96: "F5", 97: "F6",
    98: "F7", 100: "F8", 101: "F9", 109: "F10", 103: "F11", 111: "F12",
    123: "Left", 124: "Right", 125: "Down", 126: "Up",
}


def _format_keystroke(key_code, flags):
    """Build a human-readable label like '⌘⇧A' from key code + modifier flags."""
    parts = []
    if flags & MOD_CONTROL:
        parts.append("⌃")
    if flags & MOD_OPTION:
        parts.append("⌥")
    if flags & MOD_SHIFT:
        parts.append("⇧")
    if flags & MOD_COMMAND:
        parts.append("⌘")
    if flags & MOD_FN:
        parts.append("fn+")
    name = KEY_NAMES.get(key_code, f"key{key_code}")
    parts.append(name)
    return "".join(parts)


# ═══════════════════════════════════════════════════════════════════════
# CONTROLLER
# ═══════════════════════════════════════════════════════════════════════

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def _rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)

def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

CONFIG_DEFAULTS = {
    "brightness": BRIGHTNESS,
    "hold_threshold": HOLD_THRESHOLD_SEC,
    "poll_interval": POLL_INTERVAL,
    "snap_enabled": True,
    "mic_command": "fn",   # "fn" = double fn press, anything else = shell command
    "idle_timeout": STATUS_STALE_SEC,  # seconds before idle/working status resets to black
    "layout": "default",
    "colors": {
        "active":     _rgb_to_hex(COLOR_BG_ACTIVE),
        "idle":       _rgb_to_hex(COLOR_BG_IDLE),
        "working":    _rgb_to_hex(COLOR_BG_WORKING),
        "permission": _rgb_to_hex(COLOR_BG_PERMISSION),
        "num_1":      _rgb_to_hex(COLOR_BG_NUM_1),
        "num_2":      _rgb_to_hex(COLOR_BG_NUM_2),
        "num_3":      _rgb_to_hex(COLOR_BG_NUM_3),
        "num_4":      _rgb_to_hex(COLOR_BG_NUM_4),
        "num_5":      _rgb_to_hex(COLOR_BG_NUM_5),
        "arrows":     _rgb_to_hex(COLOR_BG_NAV_ARROW),
        "mic_enter":  _rgb_to_hex(COLOR_BG_NAV_ACTION),
    },
}


class DeckController:
    def __init__(self):
        self.config = self._load_config()
        self.mode = MODE_GRID
        self.active_slot = None       # which grid slot (0-13) is focused
        self._key_press_time = {}     # key_index -> press timestamp (for hold detection)
        self.deck = None
        self.running = False
        self.screen = self._get_screen_bounds()
        self._init_fonts()
        self.slot_tty = {}            # slot -> tty name (e.g. "ttys003")
        self.slot_status = {}         # slot -> "idle"|"working"|"permission"|None
        self.blink_on = True          # toggles every BLINK_INTERVAL for red blink
        self._last_blink_toggle = time.time()
        self.overlay_proc = None      # subprocess for screen border overlay
        self._last_tty_refresh = 0    # force immediate TTY map build
        self._last_screen_refresh = 0   # force immediate screen bounds check
        # Snap-to-grid: track window positions to detect drag-and-drop
        self._prev_win_positions = {}   # window_id -> (x, y, w, h)
        self._snap_candidates = {}     # window_id -> {pos, polls_stable, win}
        self._controller_win_id = None  # Quartz window ID of the controller terminal

    # ─── Config ───────────────────────────────────────────────────────

    def _load_config(self):
        """Load config from config.json, filling in defaults for missing keys.
        Merges nested dicts (like colors) so new defaults get picked up."""
        config = dict(CONFIG_DEFAULTS)
        # Deep copy default colors
        config["colors"] = dict(CONFIG_DEFAULTS.get("colors", {}))
        try:
            with open(CONFIG_FILE) as f:
                saved = json.load(f)
            # Merge colors: defaults first, then saved overrides
            if "colors" in saved:
                config["colors"].update(saved["colors"])
                del saved["colors"]
            config.update(saved)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.debug("Config load skipped: %s", e)
        return config

    def _save_config(self):
        """Persist current config to config.json."""
        try:
            tmp = CONFIG_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.config, f, indent=2)
                f.write("\n")
            os.rename(tmp, CONFIG_FILE)
        except Exception as e:
            logger.error("Config save failed: %s", e)

    def _color(self, key, fallback):
        """Get a color from config, falling back to the constant."""
        colors = self.config.get("colors", {})
        h = colors.get(key)
        if h:
            try:
                return _hex_to_rgb(h)
            except (ValueError, IndexError) as e:
                logger.debug("Invalid color hex for '%s': %s", key, e)
        return fallback

    # ─── Layout ──────────────────────────────────────────────────────

    def _get_layout(self):
        """Get the current layout mapping (list of 15 terminal names)."""
        name = self.config.get("layout", "default")
        return LAYOUTS.get(name, LAYOUTS["default"])

    def _get_terminal_names(self):
        """Get unique terminal names in the current layout (excluding ENTER), in order."""
        seen = set()
        names = []
        for name in self._get_layout():
            if name != "ENTER" and name not in seen:
                seen.add(name)
                names.append(name)
        return names

    def _get_terminal_slots(self):
        """Map each terminal name to its list of key indices."""
        layout = self._get_layout()
        groups = {}
        for i, name in enumerate(layout):
            if name == "ENTER":
                continue
            groups.setdefault(name, []).append(i)
        return groups

    def _get_terminal_rect(self, terminal_name):
        """Get the screen rectangle for a terminal (merged from all its slots)."""
        layout = self._get_layout()
        slots = [i for i, name in enumerate(layout) if name == terminal_name]
        if not slots:
            return None
        # Find bounding box of all slots
        rects = [self._grid_rect(s) for s in slots]
        x = min(r["x"] for r in rects)
        y = min(r["y"] for r in rects)
        x2 = max(r["x"] + r["w"] for r in rects)
        y2 = max(r["y"] + r["h"] for r in rects)
        return {"x": x, "y": y, "w": x2 - x, "h": y2 - y,
                "cx": (x + x2) // 2, "cy": (y + y2) // 2}

    def _key_to_terminal(self, key):
        """Get the terminal name for a key index."""
        layout = self._get_layout()
        if 0 <= key < len(layout):
            name = layout[key]
            return name if name != "ENTER" else None
        return None

    def _terminal_to_active_slot(self, terminal_name):
        """Get the 'primary' key index for a terminal (first key in its group).
        Used as the active_slot identifier."""
        layout = self._get_layout()
        for i, name in enumerate(layout):
            if name == terminal_name:
                return i
        return None

    # ─── Setup ───────────────────────────────────────────────────────

    def _check_accessibility(self):
        """Check if Accessibility permissions are granted for this terminal app.
        If not, opens System Settings to the right pane and waits for the user."""
        # Try a simple System Events query — this will fail without Accessibility
        result = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to get name of first process'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return True

        print()
        print("━━━ Accessibility Permission Required ━━━")
        print("  Your terminal app needs Accessibility access for")
        print("  window management and keystroke sending.")
        print()
        print("  Opening System Settings now...")
        print("  → Toggle ON your terminal app, then press Enter here.")
        print()

        # Open System Settings to the Accessibility pane
        subprocess.run(
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
            capture_output=True,
        )

        # Wait for the user to grant permission and press Enter
        while True:
            try:
                input("  Press Enter after granting permission...")
            except (KeyboardInterrupt, EOFError):
                sys.exit(1)

            result = subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to get name of first process'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                print("  Accessibility permission granted!")
                return True
            print("  Not yet — make sure your terminal app is toggled ON, then try again.")

    def _get_terminal_windows(self):
        """Get all on-screen windows from any recognized terminal app via Quartz.
        Returns a list of dicts with owner, pid, id, and bounds."""
        windows = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
            kCGNullWindowID,
        )
        results = []
        for w in windows:
            owner = w.get("kCGWindowOwnerName", "")
            if owner not in TERMINAL_APPS:
                continue
            bounds = w.get("kCGWindowBounds", {})
            # Skip tiny windows (toolbars, popovers, etc.)
            if bounds.get("Width", 0) < 100 or bounds.get("Height", 0) < 100:
                continue
            results.append({
                "owner": owner,
                "pid": w.get("kCGWindowOwnerPID"),
                "id": w.get("kCGWindowNumber"),
                "x": int(bounds.get("X", 0)),
                "y": int(bounds.get("Y", 0)),
                "w": int(bounds.get("Width", 0)),
                "h": int(bounds.get("Height", 0)),
            })
        return results

    def _get_screen_bounds(self):
        """Get the usable frame of the screen where the user's mouse cursor is.
        Uses Quartz CGDisplay (top-left coords natively) to avoid NSScreen
        coordinate conversion issues."""
        # Get mouse position in Quartz coords (top-left origin)
        event = CGEventCreate(None)
        mouse = CGEventGetLocation(event) if event else None

        # Get all active displays
        err, display_ids, count = CGGetActiveDisplayList(16, None, None)

        # Find the display containing the mouse cursor
        target_display = CGMainDisplayID()  # fallback
        if mouse and display_ids:
            for did in display_ids[:count]:
                b = CGDisplayBounds(did)
                if (b.origin.x <= mouse.x <= b.origin.x + b.size.width
                        and b.origin.y <= mouse.y <= b.origin.y + b.size.height):
                    target_display = did
                    break

        disp_bounds = CGDisplayBounds(target_display)

        # Detect menu bar and dock by scanning Quartz window list directly.
        # The menu bar is a window owned by "Window Server" at layer 25.
        # The Dock is owned by "Dock". Both are real windows we can measure.
        menu_bar_h = 0
        dock_h = 0
        all_windows = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
            kCGNullWindowID,
        )
        dx, dw = int(disp_bounds.origin.x), int(disp_bounds.size.width)
        dy, dh = int(disp_bounds.origin.y), int(disp_bounds.size.height)

        for w in all_windows or []:
            owner = w.get("kCGWindowOwnerName", "")
            layer = w.get("kCGWindowLayer", 0)
            b = w.get("kCGWindowBounds", {})
            bx, by = int(b.get("X", 0)), int(b.get("Y", 0))
            bw, bh = int(b.get("Width", 0)), int(b.get("Height", 0))

            # Menu bar: layer 25, spans full display width, at the top
            if layer == 25 and abs(bx - dx) < 5 and abs(bw - dw) < 5:
                if abs(by - dy) < 5:
                    menu_bar_h = max(menu_bar_h, bh)

            # Dock: owned by "Dock", on this display
            if owner == "Dock" and bx >= dx and bx + bw <= dx + dw + 5:
                # Bottom dock: sits at the bottom of the display
                if by + bh >= dy + dh - 5 and bh < dh / 2:
                    dock_h = max(dock_h, bh)

        if menu_bar_h == 0:
            menu_bar_h = 25  # safe fallback

        x = int(disp_bounds.origin.x)
        y = int(disp_bounds.origin.y) + menu_bar_h
        w = int(disp_bounds.size.width)
        h = int(disp_bounds.size.height) - menu_bar_h - dock_h

        logger.info("Display at (%d, %d), %dx%d, menu_bar=%dpx, dock=%dpx", x, y, w, h, menu_bar_h, dock_h)
        return {"x": x, "y": y, "w": w, "h": h}

    def _init_fonts(self):
        """Load system fonts for button labels."""
        candidates = [
            "/System/Library/Fonts/SFCompact.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Geneva.ttf",
            "/Library/Fonts/Arial.ttf",
        ]
        def load(size):
            for path in candidates:
                try:
                    return ImageFont.truetype(path, size)
                except (IOError, OSError):
                    logger.debug("Font not found: %s", path)
                    continue
            return ImageFont.load_default()

        self.font_sm = load(12)
        self.font_md = load(18)
        self.font_lg = load(26)

    def _pick_font(self, label):
        if len(label) <= 2:
            return self.font_lg
        elif len(label) <= 4:
            return self.font_md
        return self.font_sm

    # ─── Claude Status (Hook Integration) ───────────────────────────

    def _build_tty_map(self):
        """Map each terminal's primary slot to its TTY.
        Uses AppleScript to get the TTY for each window (per app), then
        matches window positions to layout terminal zones."""
        tty_map = {}

        # Get TTY + bounds for each window, grouped by app
        for app in TERMINAL_APPS:
            window_ttys = self._get_app_window_ttys(app)
            if not window_ttys:
                continue

            # Match each window to a terminal zone by position
            for info in window_ttys:
                win_cx = info["x"] + info["w"] / 2
                win_cy = info["y"] + info["h"] / 2
                for name in self._get_terminal_names():
                    r = self._get_terminal_rect(name)
                    if (r["x"] <= win_cx <= r["x"] + r["w"]
                            and r["y"] <= win_cy <= r["y"] + r["h"]):
                        primary = self._terminal_to_active_slot(name)
                        tty_map[primary] = info["tty"]
                        break

        self.slot_tty = tty_map

    def _get_app_window_ttys(self, app_name):
        """Get TTY and bounds for each window of a terminal app via AppleScript.
        Returns list of dicts with x, y, w, h, tty. Returns [] if app not running."""
        if app_name in ("Terminal",):
            # Terminal.app: 'bounds' gives {left, top, right, bottom}
            #               'tty of tab 1' gives the TTY
            script = '''
tell application "Terminal"
    set output to ""
    repeat with i from 1 to count of windows
        try
            set b to bounds of window i
            set t to tty of tab 1 of window i
            set output to output & (item 1 of b as text) & "," & (item 2 of b as text) & "," & (item 3 of b as text) & "," & (item 4 of b as text) & "," & t & linefeed
        end try
    end repeat
    return output
end tell
'''
        elif app_name in ("iTerm2", "iTerm"):
            # iTerm2: use System Events for position/size, iTerm2 for tty
            script = '''
set output to ""
tell application "iTerm2"
    set winCount to count of windows
end tell
tell application "System Events"
    tell process "iTerm2"
        repeat with i from 1 to winCount
            try
                set p to position of window i
                set s to size of window i
                tell application "iTerm2"
                    set t to tty of current session of current tab of window i
                end tell
                set output to output & (item 1 of p as text) & "," & (item 2 of p as text) & "," & ((item 1 of p) + (item 1 of s) as text) & "," & ((item 2 of p) + (item 2 of s) as text) & "," & t & linefeed
            end try
        end repeat
    end tell
end tell
return output
'''
        else:
            return []

        try:
            result = subprocess.run(
                ["osascript", "-e", script], capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0 or not result.stdout.strip():
                return []

            windows = []
            for line in result.stdout.strip().split("\n"):
                parts = line.strip().split(",")
                if len(parts) >= 5:
                    try:
                        left, top, right, bottom = (
                            int(parts[0]), int(parts[1]),
                            int(parts[2]), int(parts[3]),
                        )
                        tty = parts[4].strip()
                        # Normalize TTY: "/dev/ttys003" -> "ttys003"
                        if tty.startswith("/dev/"):
                            tty = tty[5:]
                        windows.append({
                            "x": left, "y": top,
                            "w": right - left, "h": bottom - top,
                            "tty": tty,
                        })
                    except ValueError as e:
                        logger.debug("Skipping malformed window line: %s", e)
                        continue
            return windows
        except Exception:
            logger.warning("Failed to get terminal windows", exc_info=True)
            return []

    def _read_status_files(self):
        """Read hook status files and update slot_status.

        States from hooks:
          pending    — PreToolUse fired (tool about to run)
          working    — PostToolUse fired (tool completed) or UserPromptSubmit
          permission — Notification/permission_prompt (Claude Code confirms)
          idle       — Stop, idle_prompt, elicitation_dialog

        Inference: if "pending" sits for > PENDING_INFER_SEC without a
        PostToolUse updating it, the tool is likely waiting for permission.
        """
        status_dir = Path(STATUS_DIR)
        if not status_dir.exists():
            return

        now = time.time()
        new_status = {}
        tty_to_slot = {tty: slot for slot, tty in self.slot_tty.items()}

        for f in status_dir.iterdir():
            if f.name.startswith("."):
                continue
            try:
                data = json.loads(f.read_text())
                tty = data.get("tty", f.name)
                ts = data.get("ts", 0)
                state = data.get("state", "unknown")
                age = now - ts

                # Permission (red) never expires — stays until a new state arrives.
                # Other states expire after STATUS_STALE_SEC (1 hour).
                idle_timeout = self.config.get("idle_timeout", STATUS_STALE_SEC)
                if idle_timeout and state not in ("permission", "pending") and age > idle_timeout:
                    continue

                # Infer permission: "pending" (PreToolUse) with no PostToolUse
                # after PENDING_INFER_SEC means the tool is waiting for approval.
                if state == "pending":
                    if age >= PENDING_INFER_SEC:
                        state = "permission"  # inferred
                    else:
                        state = "working"     # still fresh — show as working

                slot = tty_to_slot.get(tty)
                if slot is not None:
                    new_status[slot] = state
            except (json.JSONDecodeError, IOError) as e:
                logger.debug("Skipping status file: %s", e)
                continue

        self.slot_status = new_status

    # ─── Screen Border Overlay ────────────────────────────────────────

    def _start_overlay(self):
        """Spawn the overlay helper process."""
        # Clean up stale overlay file from previous runs
        try:
            Path(OVERLAY_FILE).unlink(missing_ok=True)
        except Exception:
            logger.warning("Failed to clean stale overlay file", exc_info=True)

        script_dir = os.path.dirname(os.path.abspath(__file__))
        overlay_script = os.path.join(script_dir, "overlay.py")
        venv_python = os.path.join(script_dir, ".venv", "bin", "python")

        # Use venv python if available, otherwise sys.executable
        python = venv_python if os.path.exists(venv_python) else sys.executable
        cmd = [python, overlay_script]

        try:
            log_path = os.path.join(script_dir, "overlay.log")
            try:
                log_file = open(log_path, "w")
                self._overlay_log = log_file  # keep ref so fd stays open
            except PermissionError:
                logger.debug("Overlay log file permission denied, discarding output")
                # Stale root-owned log from previous sudo run — discard output
                log_file = open(os.devnull, "w")
            self.overlay_proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL,
                stdout=log_file, stderr=log_file,
                start_new_session=True,
            )
        except Exception:
            logger.error("Failed to start overlay", exc_info=True)
            self.overlay_proc = None

    def _stop_overlay(self):
        """Kill the overlay helper and clean up."""
        if self.overlay_proc:
            try:
                self.overlay_proc.terminate()
                self.overlay_proc.wait(timeout=3)
            except Exception:
                logger.warning("Overlay terminate failed, attempting kill", exc_info=True)
                try:
                    self.overlay_proc.kill()
                except Exception:
                    logger.warning("Overlay kill also failed", exc_info=True)
            self.overlay_proc = None
        # Remove overlay file
        try:
            Path(OVERLAY_FILE).unlink(missing_ok=True)
        except Exception:
            logger.warning("Failed to remove overlay file", exc_info=True)

    def _update_overlay(self):
        """Write active window position to the overlay file (atomic)."""
        overlay_path = Path(OVERLAY_FILE)
        if self.active_slot is not None:
            terminal_name = self._key_to_terminal(self.active_slot)
            rect = self._get_terminal_rect(terminal_name) if terminal_name else self._grid_rect(self.active_slot)
            active_color = self._color("active", COLOR_BG_ACTIVE)
            data = {"visible": True,
                    "x": rect["x"], "y": rect["y"],
                    "w": rect["w"], "h": rect["h"],
                    "color": list(active_color)}
        else:
            data = {"visible": False}

        try:
            tmp = overlay_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            tmp.rename(overlay_path)
        except Exception:
            logger.warning("Failed to write overlay file", exc_info=True)

    # ─── Grid Geometry ───────────────────────────────────────────────

    def _grid_rect(self, slot):
        """Screen rectangle for a grid slot (0-indexed, row-major)."""
        col = slot % COLS
        row = slot // COLS
        cell_w = self.screen["w"] / COLS
        cell_h = self.screen["h"] / ROWS
        x = self.screen["x"] + col * cell_w
        y = self.screen["y"] + row * cell_h
        return {
            "x": int(x), "y": int(y),
            "w": int(cell_w), "h": int(cell_h),
            "cx": int(x + cell_w / 2),
            "cy": int(y + cell_h / 2),
        }

    # ─── Window Management ───────────────────────────────────────────

    def _get_our_tty(self):
        """Get the TTY name of the terminal running this process."""
        try:
            tty_path = os.ttyname(sys.stdin.fileno())
            return tty_path.replace("/dev/", "")
        except (OSError, AttributeError) as e:
            logger.debug("TTY detection via stdin failed: %s", e)
        # Fallback: tty command
        try:
            result = subprocess.run(["tty"], capture_output=True, text=True, timeout=2)
            if result.returncode == 0 and result.stdout.strip() != "not a tty":
                return result.stdout.strip().replace("/dev/", "")
        except Exception as e:
            logger.debug("TTY detection via tty command failed: %s", e)
        return None

    def _find_controller_window(self, term_wins):
        """Find which terminal window belongs to this controller by matching TTY.
        Returns the window dict, or None if not found."""
        our_tty = self._get_our_tty()
        if not our_tty:
            return None

        # Query all terminal apps for their window TTYs
        for app in TERMINAL_APPS:
            window_ttys = self._get_app_window_ttys(app)
            for info in window_ttys:
                if info["tty"] == our_tty:
                    # Found our TTY — match to a Quartz window by position
                    for win in term_wins:
                        if (abs(win["x"] - info["x"]) <= 5
                                and abs(win["y"] - info["y"]) <= 5):
                            return win
        return None

    def _refresh_controller_win_id(self):
        """Update the cached controller window ID by re-matching TTY."""
        term_wins = self._get_terminal_windows()
        controller_win = self._find_controller_window(term_wins)
        if controller_win:
            self._controller_win_id = controller_win["id"]
        else:
            self._controller_win_id = None

    def tile_windows(self):
        """Arrange terminal windows according to the current layout.
        The controller's own terminal is always placed in slot 14 (bottom-right).
        Remaining windows are matched to layout terminals by proximity."""
        term_wins = self._get_terminal_windows()
        if not term_wins:
            logger.warning("No terminal windows found")
            return

        # Find the controller's own terminal window by TTY
        controller_win = self._find_controller_window(term_wins)
        other_wins = []
        for win in term_wins:
            if controller_win and win["id"] == controller_win["id"]:
                continue
            other_wins.append(win)

        # Place controller window in slot 14 (bottom-right, always single cell)
        if controller_win:
            logger.info("Controller terminal -> slot 14")
            self._move_window_to_rect(controller_win, self._grid_rect(GRID_SLOTS - 1))
            self._controller_win_id = controller_win["id"]
        else:
            self._controller_win_id = None

        # Get terminal zones from layout
        terminal_names = self._get_terminal_names()
        terminal_rects = {name: self._get_terminal_rect(name) for name in terminal_names}

        count = min(len(other_wins), len(terminal_names))
        logger.info("Found %d terminal window(s), tiling %d into layout '%s'", len(term_wins), count, self.config.get('layout', 'default'))

        # Match windows to terminal zones by proximity
        assignments = self._match_windows_to_terminals(other_wins[:count], terminal_names, terminal_rects)

        for name, win in sorted(assignments.items()):
            self._move_window_to_rect(win, terminal_rects[name])

    def _match_windows_to_terminals(self, windows, terminal_names, terminal_rects):
        """Match windows to terminal zones by proximity (nearest center-to-center).
        Returns dict of terminal_name -> window."""
        pairs = []
        for win in windows:
            win_cx = win["x"] + win["w"] / 2
            win_cy = win["y"] + win["h"] / 2
            for name in terminal_names:
                r = terminal_rects[name]
                dx = win_cx - r["cx"]
                dy = win_cy - r["cy"]
                pairs.append((dx * dx + dy * dy, name, id(win), win))

        pairs.sort()
        used_names = set()
        used_wins = set()
        assignments = {}
        for dist, name, win_id, win in pairs:
            if name in used_names or win_id in used_wins:
                continue
            assignments[name] = win
            used_names.add(name)
            used_wins.add(win_id)
            if len(assignments) >= len(windows):
                break

        return assignments

    def _move_window_to_rect(self, win, r):
        """Move and resize a window to fill the given rect."""
        script = f'''
tell application "System Events"
    tell process "{win["owner"]}"
        repeat with w in windows
            set p to position of w
            set s to size of w
            set wx to item 1 of p
            set wy to item 2 of p
            set ww to item 1 of s
            set wh to item 2 of s
            if wx = {win["x"]} and wy = {win["y"]} and ww = {win["w"]} and wh = {win["h"]} then
                set position of w to {{{r["x"]}, {r["y"]}}}
                set size of w to {{{r["w"]}, {r["h"]}}}
                return
            end if
        end repeat
    end tell
end tell
'''
        subprocess.run(["osascript", "-e", script], capture_output=True)

    def _is_snapped(self, win):
        """Check if a window is already snapped to a terminal zone."""
        for name in self._get_terminal_names():
            r = self._get_terminal_rect(name)
            if (abs(win["x"] - r["x"]) <= 2
                    and abs(win["y"] - r["y"]) <= 2
                    and abs(win["w"] - r["w"]) <= 2
                    and abs(win["h"] - r["h"]) <= 2):
                return True
        # Also check the enter slot
        r = self._grid_rect(ENTER_KEY_INDEX)
        if (abs(win["x"] - r["x"]) <= 2
                and abs(win["y"] - r["y"]) <= 2
                and abs(win["w"] - r["w"]) <= 2
                and abs(win["h"] - r["h"]) <= 2):
            return True
        return False

    def _check_snap_to_grid(self):
        """Detect windows that have been dragged and dropped, then snap them
        into the nearest grid slot. Works by tracking position changes:
        1. Window moves → mark as candidate
        2. Window holds still for SNAP_SETTLE_POLLS → snap it
        This avoids snapping mid-drag."""
        term_wins = self._get_terminal_windows()
        current_positions = {}
        win_by_id = {}

        for win in term_wins:
            wid = win["id"]
            current_positions[wid] = (win["x"], win["y"], win["w"], win["h"])
            win_by_id[wid] = win

        snapped_any = False

        for wid, pos in current_positions.items():
            prev_pos = self._prev_win_positions.get(wid)
            win = win_by_id[wid]

            if prev_pos is None:
                # New window — just record it
                continue

            # Check if position changed since last poll
            dx = abs(pos[0] - prev_pos[0])
            dy = abs(pos[1] - prev_pos[1])
            moved = (dx > SNAP_TOLERANCE or dy > SNAP_TOLERANCE
                     or abs(pos[2] - prev_pos[2]) > SNAP_TOLERANCE
                     or abs(pos[3] - prev_pos[3]) > SNAP_TOLERANCE)

            if moved:
                # Window is moving — reset settle counter
                self._snap_candidates[wid] = {"pos": pos, "polls_stable": 0, "win": win}
            elif wid in self._snap_candidates:
                cand = self._snap_candidates[wid]
                # Check if position matches what we recorded as the candidate
                cdx = abs(pos[0] - cand["pos"][0])
                cdy = abs(pos[1] - cand["pos"][1])
                if cdx <= SNAP_TOLERANCE and cdy <= SNAP_TOLERANCE:
                    cand["polls_stable"] += 1
                    cand["win"] = win  # update with latest bounds
                    if cand["polls_stable"] >= SNAP_SETTLE_POLLS:
                        # Window has settled — snap if not already in a slot
                        if not self._is_snapped(win):
                            # Controller always snaps to slot 14
                            if wid == self._controller_win_id:
                                r = self._grid_rect(ENTER_KEY_INDEX)
                                logger.info("Snapping controller window to slot 14")
                                self._move_window_to_rect(win, r)
                                snapped_any = True
                            else:
                                best_terminal = self._find_nearest_empty_terminal(win)
                                if best_terminal is not None:
                                    r = self._get_terminal_rect(best_terminal)
                                    logger.info("Snapping window to %s", best_terminal)
                                    self._move_window_to_rect(win, r)
                                    snapped_any = True
                        del self._snap_candidates[wid]
                else:
                    # Moved again to a new spot — reset
                    cand["pos"] = pos
                    cand["polls_stable"] = 0
                    cand["win"] = win

        # Update previous positions (re-read after any snaps)
        if snapped_any:
            term_wins = self._get_terminal_windows()
            self._prev_win_positions = {
                w["id"]: (w["x"], w["y"], w["w"], w["h"]) for w in term_wins
            }
            self._snap_candidates.clear()
            # Rebuild TTY map since windows moved
            self._build_tty_map()
        else:
            self._prev_win_positions = current_positions

        # Clean up candidates for windows that no longer exist
        live_ids = set(current_positions.keys())
        for wid in list(self._snap_candidates.keys()):
            if wid not in live_ids:
                del self._snap_candidates[wid]

        return snapped_any

    def _find_nearest_empty_terminal(self, win):
        """Find the terminal zone closest to the window's center that doesn't
        already have a properly-snapped window in it."""
        win_cx = win["x"] + win["w"] / 2
        win_cy = win["y"] + win["h"] / 2

        # Find which terminals are occupied by snapped windows
        occupied = set()
        for tw in self._get_terminal_windows():
            if tw["id"] == win["id"]:
                continue
            tw_cx = tw["x"] + tw["w"] / 2
            tw_cy = tw["y"] + tw["h"] / 2
            for name in self._get_terminal_names():
                r = self._get_terminal_rect(name)
                if (abs(tw["x"] - r["x"]) <= 5
                        and abs(tw["y"] - r["y"]) <= 5
                        and abs(tw["w"] - r["w"]) <= 5
                        and abs(tw["h"] - r["h"]) <= 5):
                    occupied.add(name)
                    break

        best_name = None
        best_dist = float("inf")
        for name in self._get_terminal_names():
            if name in occupied:
                continue
            r = self._get_terminal_rect(name)
            dx = win_cx - r["cx"]
            dy = win_cy - r["cy"]
            dist = dx * dx + dy * dy
            if dist < best_dist:
                best_dist = dist
                best_name = name

        return best_name

    def _activate_slot(self, slot):
        """Focus the terminal window at the given grid slot (any app).
        For merged layouts, resolves to the terminal's primary slot."""
        terminal_name = self._key_to_terminal(slot)
        if terminal_name:
            # Use the terminal's merged rect for activation
            rect = self._get_terminal_rect(terminal_name)
            # Set active_slot to the primary key for this terminal
            slot = self._terminal_to_active_slot(terminal_name)
        else:
            rect = self._grid_rect(slot)
        cx, cy = rect["cx"], rect["cy"]
        # Find which terminal window is at this slot via Quartz
        term_wins = self._get_terminal_windows()
        target_owner = None
        for w in term_wins:
            if (w["x"] <= cx <= w["x"] + w["w"]
                    and w["y"] <= cy <= w["y"] + w["h"]):
                target_owner = w["owner"]
                break

        if target_owner is None:
            self.active_slot = slot
            self._update_overlay()
            return

        script = f'''
tell application "{target_owner}" to activate
delay 0.05
tell application "System Events"
    tell process "{target_owner}"
        repeat with w in windows
            set p to position of w
            set s to size of w
            set wx to item 1 of p
            set wy to item 2 of p
            set ww to item 1 of s
            set wh to item 2 of s
            if {cx} >= wx and {cx} <= (wx + ww) and {cy} >= wy and {cy} <= (wy + wh) then
                perform action "AXRaise" of w
                return
            end if
        end repeat
    end tell
end tell
'''
        subprocess.run(["osascript", "-e", script], capture_output=True)
        self.active_slot = slot
        self._update_overlay()

    def _get_frontmost_slot(self):
        """Detect which grid slot the frontmost terminal window occupies.
        Uses Quartz window list (no subprocess) to avoid title bar flicker."""
        # The Quartz window list is ordered front-to-back.
        # Find the first (frontmost) terminal window and match it to a grid slot.
        windows = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
            kCGNullWindowID,
        )
        for w in windows or []:
            layer = w.get("kCGWindowLayer", 0)
            if layer != 0:  # normal windows are layer 0
                continue
            bounds = w.get("kCGWindowBounds", {})
            bw = bounds.get("Width", 0)
            bh = bounds.get("Height", 0)
            if bw < 100 or bh < 100:
                continue
            # First real window — if it's not a terminal app, no terminal is frontmost
            owner = w.get("kCGWindowOwnerName", "")
            if owner not in TERMINAL_APPS:
                return None
            # If this is the controller window, always slot 14
            win_id = w.get("kCGWindowNumber", 0)
            if win_id and win_id == self._controller_win_id:
                return ENTER_KEY_INDEX
            win_cx = bounds.get("X", 0) + bw / 2
            win_cy = bounds.get("Y", 0) + bh / 2
            # Match against terminal zones (handles merged slots)
            for name in self._get_terminal_names():
                r = self._get_terminal_rect(name)
                if (r["x"] <= win_cx <= r["x"] + r["w"]
                        and r["y"] <= win_cy <= r["y"] + r["h"]):
                    return self._terminal_to_active_slot(name)
            return None  # frontmost terminal found but not in any grid slot
        return None  # no terminal window is frontmost

    # ─── Keystroke Sending ───────────────────────────────────────────

    def _trigger_mic(self):
        """Trigger the MIC action based on config:
          'fn'          → double-press fn key (Whisprflow default)
          dict          → learned keystroke (key_code + flags)
          other string  → shell command
        """
        mic_cmd = self.config.get("mic_command", "fn")

        if mic_cmd == "fn":
            # Default: double fn press for Whisprflow
            for _ in range(2):
                event_down = CGEventCreateKeyboardEvent(None, FN_KEY_CODE, True)
                CGEventPost(kCGHIDEventTap, event_down)
                event_up = CGEventCreateKeyboardEvent(None, FN_KEY_CODE, False)
                CGEventPost(kCGHIDEventTap, event_up)
                time.sleep(0.05)

        elif isinstance(mic_cmd, dict) and mic_cmd.get("type") == "keystroke":
            # Learned keystroke
            kc = mic_cmd["key_code"]
            flags = mic_cmd.get("flags", 0)
            event_down = CGEventCreateKeyboardEvent(None, kc, True)
            if flags:
                CGEventSetFlags(event_down, flags)
            CGEventPost(kCGHIDEventTap, event_down)
            event_up = CGEventCreateKeyboardEvent(None, kc, False)
            if flags:
                CGEventSetFlags(event_up, flags)
            CGEventPost(kCGHIDEventTap, event_up)

        elif isinstance(mic_cmd, str):
            # Shell command
            try:
                subprocess.Popen(mic_cmd, shell=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                logger.warning("MIC command failed", exc_info=True)

    def _learn_keystroke(self):
        """Listen for a single keystroke and save it as the MIC action.
        Uses a CGEvent tap to capture the next key press with modifiers."""
        captured = {}

        def callback(proxy, event_type, event, refcon):
            if event_type == kCGEventKeyDown:
                captured["key_code"] = CGEventGetIntegerValueField(
                    event, kCGKeyboardEventKeycode
                )
                captured["flags"] = CGEventGetFlags(event)
                CoreFoundation.CFRunLoopStop(CoreFoundation.CFRunLoopGetCurrent())
                return None  # swallow the event
            elif event_type == kCGEventFlagsChanged:
                # Modifier-only key (like fn alone) — capture on press
                flags = CGEventGetFlags(event)
                key_code = CGEventGetIntegerValueField(
                    event, kCGKeyboardEventKeycode
                )
                # Only capture on press (flags non-zero), skip release
                if flags & (MOD_SHIFT | MOD_CONTROL | MOD_OPTION | MOD_COMMAND | MOD_FN):
                    captured["key_code"] = key_code
                    captured["flags"] = flags
                    CoreFoundation.CFRunLoopStop(CoreFoundation.CFRunLoopGetCurrent())
                    return None
            return event

        # Listen for both key down and modifier-only presses (like fn)
        event_mask = (1 << kCGEventKeyDown) | (1 << kCGEventFlagsChanged)
        tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            0,  # active filter (can suppress events)
            event_mask,
            callback,
            None,
        )

        if tap is None:
            logger.error("Failed to create event tap — check Accessibility permissions")
            print("  Failed to create event tap — check Accessibility permissions")
            return

        source = CoreFoundation.CFMachPortCreateRunLoopSource(None, tap, 0)
        loop = CoreFoundation.CFRunLoopGetCurrent()
        CoreFoundation.CFRunLoopAddSource(loop, source, CoreFoundation.kCFRunLoopCommonModes)

        print("  Press the key (or combo) you want for MIC...")

        # Block until a keystroke is captured
        CoreFoundation.CFRunLoopRun()

        # Clean up the tap
        CoreFoundation.CFRunLoopRemoveSource(loop, source, CoreFoundation.kCFRunLoopCommonModes)

        if not captured:
            print("  No keystroke captured")
            return

        key_code = captured["key_code"]
        flags = captured["flags"]
        # Strip low bits from flags — only keep modifier masks
        clean_flags = flags & (MOD_SHIFT | MOD_CONTROL | MOD_OPTION | MOD_COMMAND | MOD_FN)

        label = _format_keystroke(key_code, clean_flags)
        self.config["mic_command"] = {
            "type": "keystroke",
            "key_code": key_code,
            "flags": clean_flags,
            "label": label,
        }
        self._save_config()
        print(f"  mic → {label}")

    def _send_key(self, key_name):
        """Send a single keystroke to the currently active window."""
        if key_name == "Return":
            script = 'tell application "System Events" to key code 36'
        elif key_name in ARROW_KEY_CODES:
            script = f'tell application "System Events" to key code {ARROW_KEY_CODES[key_name]}'
        else:
            # For number keys 1-4
            script = f'tell application "System Events" to keystroke "{key_name}"'
        subprocess.run(["osascript", "-e", script], capture_output=True)

    # ─── Button Rendering ────────────────────────────────────────────

    def _render_button(self, label, bg=COLOR_BG_DEFAULT, fg=COLOR_FG_DEFAULT,
                       border_color=None, border_width=8):
        """Create a button image for the Stream Deck.
        If border_color is set, draws a colored border around the button."""
        image = PILHelper.create_image(self.deck, background=bg)
        draw = ImageDraw.Draw(image)
        w, h = image.size

        # Draw border if specified (for active window indicator)
        if border_color:
            for i in range(border_width):
                draw.rectangle(
                    [i, i, w - 1 - i, h - 1 - i],
                    outline=border_color,
                )

        font = self._pick_font(label)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (w - tw) / 2
        y = (h - th) / 2 - 2
        draw.text((x, y), label, font=font, fill=fg)
        return PILHelper.to_native_format(self.deck, image)

    # ─── Display Updates ─────────────────────────────────────────────

    def _update_all_buttons(self):
        """Redraw all buttons for the current mode."""
        if self.mode == MODE_GRID:
            self._draw_grid_mode()
        else:
            self._draw_nav_mode()

    def _get_slot_style(self, slot):
        """Determine bg, fg, and border for a grid slot.
        For merged layouts, all keys in the same terminal share state.
        Status color is always the fill. Active window gets an amber border."""
        # Resolve to primary slot for merged terminals
        terminal_name = self._key_to_terminal(slot)
        primary = self._terminal_to_active_slot(terminal_name) if terminal_name else slot
        is_active = (primary == self.active_slot)
        status = self.slot_status.get(primary)
        active_color = self._color("active", COLOR_BG_ACTIVE)
        border = active_color if is_active else None

        if status == "idle":
            return self._color("idle", COLOR_BG_IDLE), COLOR_FG_IDLE, border
        elif status == "working":
            return self._color("working", COLOR_BG_WORKING), COLOR_FG_WORKING, border
        elif status == "permission":
            perm_color = self._color("permission", COLOR_BG_PERMISSION)
            if self.blink_on:
                return perm_color, COLOR_FG_PERMISSION, border
            else:
                # Blink off phase: dim version of permission color
                dim = tuple(max(c // 4, 10) for c in perm_color)
                return dim, (100, 100, 100), border

        # No Claude status — use amber fill for active, black for inactive
        if is_active:
            return active_color, COLOR_FG_ACTIVE, None
        return COLOR_BG_DEFAULT, COLOR_FG_DEFAULT, None

    def _draw_grid_mode(self):
        layout = self._get_layout()
        for i in range(DECK_TERMINAL_SLOTS):
            label = layout[i] if i < len(layout) else f"T{i+1}"
            bg, fg, border = self._get_slot_style(i)
            self.deck.set_key_image(
                i, self._render_button(label, bg, fg, border_color=border)
            )
        # Enter key (always present)
        self.deck.set_key_image(
            ENTER_KEY_INDEX,
            self._render_button("⏎", COLOR_BG_ENTER, COLOR_FG_ENTER),
        )

    def _get_nav_style(self, key):
        """Get nav button style with config color overrides."""
        style = NAV_BUTTON_STYLES.get(key)
        if style is None:
            return None
        # Override colors from config
        label = style["label"]
        bg = style["bg"]
        fg = style["fg"]
        if key in (0, 1, 2, 3, 4):  # number keys
            bg = self._color(f"num_{key+1}", bg)
        elif key in (7, 11, 12, 13):  # arrows
            bg = self._color("arrows", bg)
        elif key in (10, 14):  # MIC, Enter
            bg = self._color("mic_enter", bg)
        return {"label": label, "bg": bg, "fg": fg}

    def _draw_nav_mode(self):
        for i in range(TOTAL_KEYS):
            border = self._color("active", COLOR_BG_ACTIVE) if i == self.active_slot else None
            style = self._get_nav_style(i)
            if style:
                self.deck.set_key_image(
                    i, self._render_button(
                        style["label"], style["bg"], style["fg"],
                        border_color=border,
                    )
                )
            else:
                self.deck.set_key_image(
                    i, self._render_button(
                        "", COLOR_BG_NAV_EMPTY, border_color=border,
                    )
                )

    # ─── Key Press Handling ──────────────────────────────────────────

    def _on_key_change(self, deck, key, pressed):
        """Stream Deck callback — fires on both press and release.
        Grid mode terminal keys use press/release timing for hold detection:
          tap (<0.5s)  → normal behavior (activate / enter nav)
          hold (>=0.5s) → activate window + trigger Whisprflow
        Enter key and Nav mode keys fire immediately on press."""
        if self.mode == MODE_GRID:
            # Enter key fires immediately on press (no hold behavior)
            if key == ENTER_KEY_INDEX:
                if pressed:
                    self._send_key("Return")
                return

            if key >= DECK_TERMINAL_SLOTS:
                return

            # Resolve merged keys to primary slot
            terminal_name = self._key_to_terminal(key)
            primary = self._terminal_to_active_slot(terminal_name) if terminal_name else key

            if pressed:
                self._key_press_time[key] = time.time()
            else:
                press_time = self._key_press_time.pop(key, None)
                if press_time is None:
                    return
                held = time.time() - press_time
                if held >= self.config["hold_threshold"]:
                    # Long press → activate window + Whisprflow
                    if primary != self.active_slot:
                        self._activate_slot(key)
                        self._update_all_buttons()
                    self._trigger_mic()
                else:
                    # Short tap → normal grid behavior
                    self._handle_grid_key(primary)
        else:
            if pressed:
                self._handle_nav_key(key)

    def _handle_grid_key(self, key):
        # Enter and out-of-range keys are handled in _on_key_change
        if key == self.active_slot:
            # Already active (amber) → enter Nav Mode
            self.mode = MODE_NAV
            self._update_all_buttons()
        else:
            # Different window → activate it
            self._activate_slot(key)
            self._update_all_buttons()

    def _handle_nav_key(self, key):
        action = NAV_KEYMAP.get(key)
        if action is None:
            return

        kind, value = action

        if kind == "back":
            # Return to grid mode
            self.mode = MODE_GRID
            self._update_all_buttons()

        elif kind == "num":
            self._send_key(value)

        elif kind == "arrow":
            self._send_key(value)

        elif kind == "whisprflow":
            self._trigger_mic()

        elif kind == "enter":
            self._send_key("Return")
            # Stay in nav mode — user hits BACK when done.
            # This supports multi-question flows naturally.

    # ─── Active Window Polling ───────────────────────────────────────

    def _poll_active_loop(self):
        """Background thread: sync active_slot and Claude status with the grid."""
        consecutive_errors = 0
        while self.running:
            try:
                if self.mode == MODE_GRID:
                    needs_redraw = False

                    # Periodically refresh TTY map so new/changed terminals get picked up
                    now_tty = time.time()
                    if now_tty - self._last_tty_refresh >= TTY_MAP_REFRESH_SEC:
                        self._build_tty_map()
                        self._refresh_controller_win_id()
                        self._last_tty_refresh = now_tty

                    # Periodically recheck display bounds (handles sleep/wake)
                    if now_tty - self._last_screen_refresh >= SCREEN_REFRESH_SEC:
                        new_screen = self._get_screen_bounds()
                        if new_screen != self.screen:
                            logger.info("Display bounds changed: %s -> %s", self.screen, new_screen)
                            self.screen = new_screen
                            self.tile_windows()
                            time.sleep(0.3)
                            self._build_tty_map()
                            self._update_overlay()
                            needs_redraw = True
                        self._last_screen_refresh = now_tty

                    # Snap-to-grid: detect dragged windows and snap them
                    if self.config["snap_enabled"] and self._check_snap_to_grid():
                        needs_redraw = True

                    # Check frontmost window
                    slot = self._get_frontmost_slot()
                    if slot != self.active_slot:
                        self.active_slot = slot  # None when non-terminal is frontmost
                        self._update_overlay()
                        needs_redraw = True

                    # Read Claude Code status from hook files
                    old_status = dict(self.slot_status)
                    self._read_status_files()
                    if self.slot_status != old_status:
                        needs_redraw = True

                    # Toggle blink phase for permission (red) slots
                    now = time.time()
                    if now - self._last_blink_toggle >= BLINK_INTERVAL:
                        self.blink_on = not self.blink_on
                        self._last_blink_toggle = now
                        # Only redraw for blink if any slot is in permission state
                        if "permission" in self.slot_status.values():
                            needs_redraw = True

                    if needs_redraw:
                        self._update_all_buttons()

                consecutive_errors = 0
            except Exception:
                consecutive_errors += 1
                if consecutive_errors <= 10 or consecutive_errors % 100 == 0:
                    level = logging.ERROR if consecutive_errors >= 10 else logging.WARNING
                    logger.log(level, "Poll loop error (consecutive: %d)", consecutive_errors, exc_info=True)
            time.sleep(self.config["poll_interval"])

    # ─── REPL Commands ────────────────────────────────────────────────

    def _handle_command(self, raw):
        parts = raw.split(None, 1)
        if not parts:
            return
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else None

        if cmd == "help":
            print("━━━ Commands ━━━")
            print("  tile                  Re-arrange windows into grid")
            print("  brightness <0-100>    Set Stream Deck brightness")
            print("  hold <seconds>        Set hold threshold for Whisprflow (default 0.5)")
            print("  poll <seconds>        Set poll interval (default 0.2)")
            print("  snap <on|off>         Toggle snap-to-grid")
            print("  mic <fn|command>      Set MIC key action (fn = Whisprflow, or shell command)")
            print("  mic learn             Press a key to capture it as the MIC action")
            print(f"  layout <name>         Set layout ({', '.join(LAYOUT_NAMES)})")
            print("  settings              Open settings in browser")
            print("  quit                  Exit")

        elif cmd == "tile":
            self.tile_windows()
            time.sleep(0.3)
            self._build_tty_map()
            self._update_overlay()
            self._update_all_buttons()

        elif cmd == "brightness":
            if arg is None:
                print(f"  brightness = {self.config['brightness']}")
                return
            try:
                val = int(arg)
                if not 0 <= val <= 100:
                    raise ValueError
            except ValueError:
                print("  Usage: brightness <0-100>")
                return
            self.config["brightness"] = val
            self.deck.set_brightness(val)
            self._save_config()
            print(f"  brightness → {val}")

        elif cmd == "hold":
            if arg is None:
                print(f"  hold = {self.config['hold_threshold']}s")
                return
            try:
                val = float(arg)
                if val <= 0:
                    raise ValueError
            except ValueError:
                print("  Usage: hold <seconds>  (e.g. hold 0.3)")
                return
            self.config["hold_threshold"] = val
            self._save_config()
            print(f"  hold → {val}s")

        elif cmd == "poll":
            if arg is None:
                print(f"  poll = {self.config['poll_interval']}s")
                return
            try:
                val = float(arg)
                if val <= 0:
                    raise ValueError
            except ValueError:
                print("  Usage: poll <seconds>  (e.g. poll 0.1)")
                return
            self.config["poll_interval"] = val
            self._save_config()
            print(f"  poll → {val}s")

        elif cmd == "snap":
            if arg is None:
                state = "on" if self.config["snap_enabled"] else "off"
                print(f"  snap = {state}")
                return
            if arg.lower() in ("on", "true", "1", "yes"):
                self.config["snap_enabled"] = True
            elif arg.lower() in ("off", "false", "0", "no"):
                self.config["snap_enabled"] = False
            else:
                print("  Usage: snap <on|off>")
                return
            self._save_config()
            state = "on" if self.config["snap_enabled"] else "off"
            print(f"  snap → {state}")

        elif cmd == "mic":
            if arg is None:
                mc = self.config["mic_command"]
                if isinstance(mc, dict):
                    print(f"  mic = {mc.get('label', mc)}")
                else:
                    print(f"  mic = {mc}")
                return
            if arg.lower() == "learn":
                self._learn_keystroke()
                return
            self.config["mic_command"] = arg
            self._save_config()
            print(f"  mic → {arg}")

        elif cmd == "layout":
            if arg is None:
                print(f"  layout = {self.config.get('layout', 'default')}")
                print(f"  available: {', '.join(LAYOUT_NAMES)}")
                return
            name = arg.lower().strip()
            if name not in LAYOUTS:
                print(f"  Unknown layout: {name}")
                print(f"  available: {', '.join(LAYOUT_NAMES)}")
                return
            self.config["layout"] = name
            self._save_config()
            print(f"  layout → {name}")
            self.tile_windows()
            time.sleep(0.3)
            self._build_tty_map()
            self._update_overlay()
            self._update_all_buttons()

        elif cmd == "settings":
            if hasattr(self, '_settings_port') and self._settings_port:
                import webbrowser
                webbrowser.open(f"http://127.0.0.1:{self._settings_port}/")
                print(f"  Opened settings in browser")
            else:
                print("━━━ Settings ━━━")
                for k, v in self.config.items():
                    print(f"  {k} = {v}")

        elif cmd in ("quit", "exit", "q"):
            raise SystemExit

        else:
            print(f"  Unknown command: {cmd} (type 'help' for commands)")

    # ─── Main Entry Point ────────────────────────────────────────────

    def run(self):
        # Check Accessibility permissions before anything else
        self._check_accessibility()

        devices = DeviceManager().enumerate()
        if not devices:
            logger.error("No Stream Deck found")
            print("No Stream Deck found. Make sure it's plugged in.")
            print("Also verify: brew install hidapi && pip install streamdeck")
            sys.exit(1)

        # The Stream Deck Original exposes multiple HID interfaces.
        # Try each until one opens successfully.
        logger.info("Found %d HID interface(s), attempting to open...", len(devices))
        for i, dev in enumerate(devices):
            try:
                dev.open()
                self.deck = dev
                logger.info("Opened interface %d: %s", i, dev.deck_type())
                break
            except Exception as e:
                logger.warning("Interface %d failed: %s", i, e)
        else:
            logger.error("Could not open any Stream Deck interface")
            print("ERROR: Could not open any Stream Deck interface.")
            print("If this is a permissions issue, try: sudo python main.py")
            sys.exit(1)

        self.deck.reset()
        self.deck.set_brightness(self.config["brightness"])

        key_count = self.deck.key_count()
        logger.info("Connected: %s (%d keys)", self.deck.deck_type(), key_count)

        if key_count != TOTAL_KEYS:
            logger.warning("Expected %d keys but deck has %d — layout may not work correctly", TOTAL_KEYS, key_count)
            print(f"Warning: this script expects {TOTAL_KEYS} keys but your deck has {key_count}.")
            print("The key layout may not work correctly.")

        # Tile windows into grid
        logger.info("Tiling terminal windows...")
        self.tile_windows()
        time.sleep(0.3)

        # Seed snap detector with current positions
        for w in self._get_terminal_windows():
            self._prev_win_positions[w["id"]] = (w["x"], w["y"], w["w"], w["h"])

        # Build TTY mapping for Claude status hooks
        self._build_tty_map()

        # Ensure status directory exists; clear stale files from previous runs
        os.makedirs(STATUS_DIR, exist_ok=True)
        for f in Path(STATUS_DIR).iterdir():
            try:
                f.unlink()
            except PermissionError:
                logger.debug("Could not unlink %s, falling back to rm", f)
                subprocess.run(["rm", "-f", str(f)], capture_output=True)

        # Initial render
        self._update_all_buttons()

        # Register key callback
        self.deck.set_key_callback(self._on_key_change)

        # Start screen border overlay
        logger.info("Starting screen overlay...")
        self._start_overlay()

        # Start settings server
        self._settings_port = None
        settings_port = self._start_settings_server()

        # Start background poller for active window sync
        self.running = True
        poller = threading.Thread(target=self._poll_active_loop, daemon=True)
        poller.start()

        print()
        print("━━━ Stream Deck Controller Running ━━━")
        print("  Type 'help' for commands")
        if settings_port:
            print(f"  Settings UI: http://127.0.0.1:{settings_port}")
        print()

        try:
            while True:
                cmd = input().strip()
                self._handle_command(cmd)
        except (KeyboardInterrupt, EOFError, SystemExit):
            pass
        finally:
            print("\nShutting down...")
            self.running = False
            self._stop_overlay()
            self.deck.reset()
            self.deck.close()
            print("Done.")

    # ─── Settings HTTP Server ─────────────────────────────────────────

    def _start_settings_server(self):
        """Start a local HTTP server for the browser-based settings UI.
        Returns the port number, or None if it couldn't start."""
        from http.server import HTTPServer, BaseHTTPRequestHandler
        from urllib.parse import urlparse

        controller_ref = self
        settings_html_path = os.path.join(SCRIPT_DIR, "settings.html")

        class SettingsHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_GET(self):
                path = urlparse(self.path).path
                if path in ("/", "/settings"):
                    with open(settings_html_path, "rb") as f:
                        content = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(content)
                elif path == "/api/settings":
                    self._json_response(controller_ref.config)
                elif path == "/api/status":
                    if controller_ref.running and controller_ref.deck:
                        self._json_response({
                            "running": True,
                            "deck": controller_ref.deck.deck_type(),
                            "terminals": len(controller_ref.slot_tty),
                        })
                    else:
                        self._json_response({"running": False})
                else:
                    self.send_error(404)

            def do_POST(self):
                path = urlparse(self.path).path
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len) if content_len else b""
                if path == "/api/settings":
                    try:
                        new_config = json.loads(body)
                    except json.JSONDecodeError:
                        self._json_response({"ok": False, "error": "Invalid JSON"}, 400)
                        return
                    try:
                        tmp = CONFIG_FILE + ".tmp"
                        with open(tmp, "w") as f:
                            json.dump(new_config, f, indent=2)
                            f.write("\n")
                        os.rename(tmp, CONFIG_FILE)
                    except Exception as e:
                        logger.error("Settings API: config save failed", exc_info=True)
                        self._json_response({"ok": False, "error": str(e)}, 500)
                        return
                    old_layout = controller_ref.config.get("layout")
                    controller_ref.config.update(new_config)
                    if controller_ref.deck and controller_ref.running:
                        try:
                            controller_ref.deck.set_brightness(new_config.get("brightness", 80))
                        except Exception:
                            logger.warning("Failed to set brightness via settings API", exc_info=True)
                        # Re-tile if layout changed
                        if new_config.get("layout") != old_layout:
                            controller_ref.tile_windows()
                            time.sleep(0.3)
                            controller_ref._build_tty_map()
                        controller_ref._update_overlay()
                        controller_ref._update_all_buttons()
                    self._json_response({"ok": True})
                elif path == "/api/hooks":
                    result = subprocess.run(
                        [sys.executable, os.path.join(SCRIPT_DIR, "install_hooks.py")],
                        input="y\n", capture_output=True, text=True, timeout=10,
                    )
                    output = (result.stdout + result.stderr).strip()
                    self._json_response({"ok": result.returncode == 0, "output": output})
                else:
                    self.send_error(404)

            def _json_response(self, data, code=200):
                body = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        for port in range(19830, 19850):
            try:
                server = HTTPServer(("127.0.0.1", port), SettingsHandler)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                self._settings_port = port
                return port
            except OSError:
                logger.debug("Port %d in use, trying next", port)
                continue
        return None


# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        print("Usage: python main.py")
        print()
        print("Runtime commands (type while running):")
        print("  tile                  Re-arrange windows into grid")
        print("  brightness <0-100>    Set Stream Deck brightness")
        print("  hold <seconds>        Set hold threshold for MIC trigger")
        print("  poll <seconds>        Set poll interval")
        print("  snap <on|off>         Toggle snap-to-grid")
        print("  mic <fn|command>      Set MIC key action")
        print("  mic learn             Capture a keystroke for MIC key")
        print("  settings              Open settings in browser")
        print("  help                  Show all commands")
        print("  quit                  Exit")
        sys.exit(0)
    DeckController().run()

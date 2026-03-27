# Wave 2 — Visible Bug Fixes Design

Branch: `feature/wave2-visible-bugs` (off current `feature/logging-and-exception-handling`)
Three bugs, three commits, one branch.

---

## Bug 1: Overlay persists when non-terminal app gets focus

**Symptom:** Yellow border stays visible when clicking to browser, iMessage, etc. User thinks they're typing in terminal but aren't.

**Root cause:** `_poll_active_loop` (main.py:1531-1534) only updates `active_slot` when `_get_frontmost_slot()` returns a non-None value different from current. When a non-terminal app is frontmost, it returns `None`, and the `slot is not None` guard skips the update — overlay stays on the last terminal.

**Fix:** After the existing frontmost-slot check, add a second condition: if `_get_frontmost_slot()` returns `None` AND `active_slot` is currently set, clear `active_slot` and call `_update_overlay()`. The overlay file will get `{"visible": false}` and overlay.py hides the border.

**Edge case:** We should only hide when a non-terminal app is genuinely frontmost — not when the window list is temporarily empty (e.g. during a space transition). `_get_frontmost_slot()` already returns `None` in two cases: "frontmost terminal found but not in any grid slot" and "no terminal window is frontmost." Both are correct cases to hide. Transient empty window lists are unlikely since we filter `kCGWindowListOptionOnScreenOnly`.

---

## Bug 2: Overlay on wrong monitor after sleep/wake

**Symptom:** Yellow border appeared on secondary monitor (happened once, after sleep/wake).

**Root cause (overlay.py):** `primary_h` is computed once in `OverlayTick.init()` from `CGMainDisplayID()`. After sleep/wake, display configuration can change (display IDs reshuffle, bounds change). The cached height produces wrong Quartz→AppKit coordinate conversion.

**Root cause (main.py):** `_get_screen_bounds()` runs once in `__init__`. If display config changes, `self.screen` is stale. All grid rects and overlay positions use stale bounds.

**Fix (overlay.py):** Re-read `CGDisplayBounds(CGMainDisplayID())` each tick instead of caching. This is a single C call — negligible cost at 100ms intervals.

**Fix (main.py):** Add a `_refresh_screen_bounds()` call in the poll loop, throttled to once every 30 seconds (same cadence as TTY refresh). If bounds changed, update `self.screen`, re-tile windows, and update overlay. This handles sleep/wake without needing a sleep/wake notification listener.

---

## Bug 3: Controller terminal drifts to slot 0 after idle

**Symptom:** After long idle, the controller terminal (should always be slot 14) sometimes shows up in slot 0.

**Root cause:** `_get_frontmost_slot()` matches the frontmost terminal window by checking if its center point falls within a terminal zone's rect. It iterates `_get_terminal_names()` which returns terminals in layout order (T1, T2, ... T14). It does NOT know which window is the controller. If after sleep/wake the controller window's position drifts or the grid rects shift due to stale screen bounds, the center-point check could match T1 (slot 0) before reaching the correct zone.

Additionally, `_check_snap_to_grid` doesn't exempt the controller window — if the controller window position drifts slightly after sleep/wake, snap-to-grid could reassign it to the nearest zone (slot 0 if it's closest).

**Fix:** Two changes:
1. In `_get_frontmost_slot()`: after finding the frontmost terminal window, check if it's the controller's window (by TTY match, same logic as `_find_controller_window`). If it is, always return slot 14 regardless of position.
2. In `_check_snap_to_grid()`: skip snapping the controller's window entirely (or always snap it to slot 14). The controller window should never leave slot 14.

To support both fixes efficiently, cache the controller's window ID (Quartz `kCGWindowID`) after `tile_windows()` and refresh it during TTY map rebuilds. This avoids running AppleScript TTY queries every 200ms poll.

---

## Scope & non-goals

- No multi-monitor tiling support (all terminals stay on one monitor)
- No sleep/wake event listener (periodic refresh is simpler and sufficient)
- No changes to overlay.py's architecture (still reads IPC file)
- No changes to hook behavior or status state machine

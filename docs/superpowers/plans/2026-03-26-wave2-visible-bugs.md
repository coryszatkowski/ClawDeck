# Wave 2 — Visible Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three visible bugs — overlay persisting on non-terminal focus, overlay wrong monitor after sleep/wake, controller terminal drifting to slot 0.

**Architecture:** All fixes are in `main.py` and `overlay.py`. Bug 1 is a poll loop logic change. Bug 2 adds periodic display bounds refresh in both files. Bug 3 adds controller window identity tracking to prevent mis-assignment.

**Tech Stack:** Python, Quartz (CGWindowList, CGDisplay), AppKit (NSWindow), PyObjC

---

### Task 1: Hide overlay when non-terminal app is frontmost

**Files:**
- Modify: `main.py:1530-1535` (poll loop frontmost check)

- [ ] **Step 1: Modify the frontmost window check in `_poll_active_loop`**

Replace the existing frontmost check block at line 1530-1535:

```python
                    # Check frontmost window
                    slot = self._get_frontmost_slot()
                    if slot is not None and slot != self.active_slot:
                        self.active_slot = slot
                        self._update_overlay()
                        needs_redraw = True
```

With:

```python
                    # Check frontmost window
                    slot = self._get_frontmost_slot()
                    if slot != self.active_slot:
                        self.active_slot = slot  # None when non-terminal is frontmost
                        self._update_overlay()
                        needs_redraw = True
```

The key change: remove `slot is not None and` from the condition. Now when a non-terminal app is frontmost (`slot=None`) and `active_slot` is set, we clear it. `_update_overlay()` already writes `{"visible": false}` when `active_slot is None` (line 825-826).

- [ ] **Step 2: Test manually**

1. Run the controller: `.venv/bin/python main.py`
2. Click a terminal window — verify yellow overlay appears
3. Click a non-terminal app (browser, Finder) — verify overlay disappears
4. Click back to a terminal — verify overlay reappears
5. Cmd+Tab between terminal and non-terminal rapidly — verify no stuck overlay

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "Fix overlay persisting when non-terminal app gets focus

Remove the 'slot is not None' guard in the poll loop frontmost check.
When no terminal is frontmost, active_slot clears to None and the
overlay hides. Previously, None was silently ignored and the overlay
stayed visible on the last terminal."
```

---

### Task 2: Refresh display bounds in overlay.py after sleep/wake

**Files:**
- Modify: `overlay.py:97-98` (cached primary_h in init)
- Modify: `overlay.py:128` (show_overlay call in tick)

- [ ] **Step 1: Move display height lookup into tick**

In `overlay.py`, the `OverlayTick.init()` method caches `primary_h` once:

```python
    def init(self):
        self = objc.super(OverlayTick, self).init()
        if self is None:
            return None

        main_bounds = CGDisplayBounds(CGMainDisplayID())
        self.primary_h = main_bounds.size.height
        self.win = create_overlay_window()
        self.visible = False
        self.last_rect = None
        self.last_color = None

        return self
```

Replace with (remove the display bounds lines from init, read fresh each tick):

```python
    def init(self):
        self = objc.super(OverlayTick, self).init()
        if self is None:
            return None

        self.win = create_overlay_window()
        self.visible = False
        self.last_rect = None
        self.last_color = None

        return self
```

- [ ] **Step 2: Update tick to read fresh display height**

In the `tick_` method, after parsing `data` and before calling `show_overlay`, read the current display height. Replace the show_overlay call at line 130:

```python
                if rect != self.last_rect or not self.visible:
                    show_overlay(self.win, self.primary_h, *rect)
```

With:

```python
                if rect != self.last_rect or not self.visible:
                    primary_h = CGDisplayBounds(CGMainDisplayID()).size.height
                    show_overlay(self.win, primary_h, *rect)
```

- [ ] **Step 3: Test manually**

1. Run overlay standalone: `.venv/bin/python overlay.py`
2. Create a test `.deck-overlay.json` with `{"visible": true, "x": 100, "y": 100, "w": 800, "h": 600, "color": [255, 176, 0]}`
3. Verify overlay appears in the correct position on the correct monitor
4. (If possible) put display to sleep and wake — verify overlay still appears correctly

- [ ] **Step 4: Commit**

```bash
git add overlay.py
git commit -m "Fix overlay wrong monitor after sleep/wake

Read display bounds fresh each tick instead of caching at init.
CGDisplayBounds is a cheap C call and the tick runs every 100ms.
After sleep/wake, display IDs and bounds can change — the cached
value produced wrong Quartz-to-AppKit coordinate conversion."
```

---

### Task 3: Refresh screen bounds periodically in main.py

**Files:**
- Modify: `main.py:122` (add constant)
- Modify: `main.py:331` (add tracking field)
- Modify: `main.py:1520-1524` (poll loop, add screen bounds refresh)

- [ ] **Step 1: Add screen refresh constant**

After the existing `TTY_MAP_REFRESH_SEC` constant at line 122:

```python
TTY_MAP_REFRESH_SEC = 30        # rebuild TTY map every N seconds
```

Add:

```python
SCREEN_REFRESH_SEC = 30         # recheck display bounds every N seconds
```

- [ ] **Step 2: Add tracking field in `__init__`**

After `self._last_tty_refresh = 0` at line 331, add:

```python
        self._last_screen_refresh = 0   # force immediate screen bounds check
```

- [ ] **Step 3: Add screen bounds refresh in poll loop**

In `_poll_active_loop`, after the TTY map refresh block (lines 1520-1524), add:

```python
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
```

This reuses the `now_tty` timestamp already computed for TTY refresh. If bounds haven't changed (the common case), it's just a dict comparison — no work done. If they have changed (sleep/wake), it re-tiles and rebuilds everything.

- [ ] **Step 4: Test manually**

1. Run the controller: `.venv/bin/python main.py`
2. Verify normal operation — no extra tiling triggered
3. Check logs for "Display bounds changed" — should NOT appear unless display config actually changes
4. (If possible) change display arrangement in System Settings and wait 30s — verify controller detects and re-tiles

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "Refresh screen bounds periodically to handle sleep/wake

Check display bounds every 30s in the poll loop. If bounds changed
(e.g. after sleep/wake or display reconfiguration), re-tile windows
and update the overlay. The check is cheap — just a Quartz call and
dict comparison — so no performance impact in the common case."
```

---

### Task 4: Track controller window ID and pin it to slot 14

**Files:**
- Modify: `main.py:334` (add `_controller_win_id` field)
- Modify: `main.py:889-909` (`tile_windows` — cache controller window ID)
- Modify: `main.py:1159-1189` (`_get_frontmost_slot` — always return slot 14 for controller)
- Modify: `main.py:1036-1044` (`_check_snap_to_grid` — snap controller to slot 14)

- [ ] **Step 1: Add controller window ID field in `__init__`**

After `self._snap_candidates = {}` at line 334, add:

```python
        self._controller_win_id = None  # Quartz window ID of the controller terminal
```

- [ ] **Step 2: Cache controller window ID in `tile_windows`**

In `tile_windows()`, after the controller window is placed (line 908-909):

```python
        if controller_win:
            logger.info("Controller terminal -> slot 14")
            self._move_window_to_rect(controller_win, self._grid_rect(GRID_SLOTS - 1))
```

Add after line 909:

```python
            self._controller_win_id = controller_win["id"]
```

And add an else branch:

```python
        else:
            self._controller_win_id = None
```

- [ ] **Step 3: Also refresh controller window ID during TTY map rebuild**

In `_poll_active_loop`, after the `_build_tty_map()` call at line 1523, add a controller ID refresh. Find:

```python
                    if now_tty - self._last_tty_refresh >= TTY_MAP_REFRESH_SEC:
                        self._build_tty_map()
                        self._last_tty_refresh = now_tty
```

Replace with:

```python
                    if now_tty - self._last_tty_refresh >= TTY_MAP_REFRESH_SEC:
                        self._build_tty_map()
                        self._refresh_controller_win_id()
                        self._last_tty_refresh = now_tty
```

And add a new method after `_find_controller_window` (after line 887):

```python
    def _refresh_controller_win_id(self):
        """Update the cached controller window ID by re-matching TTY."""
        term_wins = self._get_terminal_windows()
        controller_win = self._find_controller_window(term_wins)
        if controller_win:
            self._controller_win_id = controller_win["id"]
```

- [ ] **Step 4: Pin controller to slot 14 in `_get_frontmost_slot`**

In `_get_frontmost_slot()`, after finding the first terminal window (line 1168-1174 — the `for w in windows` loop), add a controller check before the position matching. Replace:

```python
        for w in windows or []:
            owner = w.get("kCGWindowOwnerName", "")
            if owner not in TERMINAL_APPS:
                continue
            layer = w.get("kCGWindowLayer", 0)
            if layer != 0:  # normal windows are layer 0
                continue
            bounds = w.get("kCGWindowBounds", {})
            bw = bounds.get("Width", 0)
            bh = bounds.get("Height", 0)
            if bw < 100 or bh < 100:
                continue
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
```

With:

```python
        for w in windows or []:
            owner = w.get("kCGWindowOwnerName", "")
            if owner not in TERMINAL_APPS:
                continue
            layer = w.get("kCGWindowLayer", 0)
            if layer != 0:  # normal windows are layer 0
                continue
            bounds = w.get("kCGWindowBounds", {})
            bw = bounds.get("Width", 0)
            bh = bounds.get("Height", 0)
            if bw < 100 or bh < 100:
                continue
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
```

The only addition is the `win_id` check before position matching — 3 lines.

- [ ] **Step 5: Snap controller to slot 14 in `_check_snap_to_grid`**

In `_check_snap_to_grid()`, at the snap decision point (line 1036-1044), add a controller check. Replace:

```python
                    if cand["polls_stable"] >= SNAP_SETTLE_POLLS:
                        # Window has settled — snap if not already in a slot
                        if not self._is_snapped(win):
                            best_terminal = self._find_nearest_empty_terminal(win)
                            if best_terminal is not None:
                                r = self._get_terminal_rect(best_terminal)
                                logger.info("Snapping window to %s", best_terminal)
                                self._move_window_to_rect(win, r)
                                snapped_any = True
                        del self._snap_candidates[wid]
```

With:

```python
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
```

- [ ] **Step 6: Test manually**

1. Run the controller: `.venv/bin/python main.py`
2. Verify controller terminal tiles to slot 14 (bottom-right)
3. Drag the controller window out of its slot — verify it snaps back to slot 14 (not slot 0)
4. Click the controller terminal — verify it highlights as slot 14 on the deck
5. After a long idle period (or simulate by restarting), verify controller stays in slot 14

- [ ] **Step 7: Commit**

```bash
git add main.py
git commit -m "Pin controller terminal to slot 14 to prevent drift

Track the controller's Quartz window ID after tiling. In frontmost
detection, always return slot 14 for the controller window instead
of relying on position matching. In snap-to-grid, always snap the
controller to slot 14. Refreshed every 30s alongside TTY map."
```

---

### Task 5: Final integration test

- [ ] **Step 1: Full integration test**

Run the controller and verify all three fixes work together:

1. Start controller, tile 3+ terminal windows
2. Click between terminals — overlay follows correctly
3. Click to Finder/browser — overlay hides
4. Click back to terminal — overlay reappears
5. Drag controller terminal — snaps to slot 14
6. Drag another terminal — snaps to nearest available slot (not slot 14)
7. Verify no errors in logs: `tail -f ~/Library/Logs/clawdeck.log` (or wherever the log file is)

- [ ] **Step 2: Verify no regressions**

1. Test all layouts (default, quad, double_quad, wide, half) — switch between them
2. Test Nav Mode toggle and back to Grid Mode
3. Test hold-for-MIC on a terminal button
4. Verify Claude Code status colors still update (start a session, run a command)

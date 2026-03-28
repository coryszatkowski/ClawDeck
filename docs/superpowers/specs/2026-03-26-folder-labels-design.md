# Folder Labels — Design Spec

Show the active terminal's working directory on both the screen overlay and Stream Deck buttons. Helps identify which project a terminal is running when you have 14 windows open.

---

## Data Source: CWD from TTY

Resolve each terminal's CWD by looking up the foreground process on its TTY. This is independent of Claude hooks — every terminal gets a label, not just ones running Claude.

**How:** During `_build_tty_map()` (runs every 30s), after mapping slot→TTY, also resolve the CWD for each TTY in two steps:

1. Find the shell PID on the TTY:
   ```bash
   ps -t <tty> -o pid=,comm= 2>/dev/null
   ```
   Match the first process whose comm is `zsh`, `bash`, `fish`, `-zsh`, `-bash`, or `-fish`.

2. Get CWD from the shell PID:
   ```bash
   lsof -a -p <pid> -d cwd -Fn 2>/dev/null
   ```
   Parse the `n` line for the directory path.

**Fallback:** If `lsof` fails or the TTY has no foreground process, the slot gets no label (shows slot name only, like today).

**Cache:** Store in `self.slot_cwd = {}` (slot → path string). Updated alongside `self.slot_tty` during TTY map builds.

---

## Display Format

Default: last folder name only (e.g. `ClawDeck`).

Configurable via `config.json` under a new `"folder_label"` key:

```json
{
  "folder_label": "last"
}
```

Values:
- `"last"` — last folder name: `ClawDeck` (default)
- `"two"` — last two segments: `Desktop/ClawDeck`
- `"full"` — full path with tilde: `~/Desktop/ClawDeck`
- `"off"` — disable folder labels entirely

The formatting function takes a full path and returns the display string based on this setting. Home directory prefix is replaced with `~` for the `"full"` format.

---

## Overlay Label

An amber bar spanning the top of the active window, inside the border. Shows the active terminal's CWD.

**Implementation in overlay.py:**

Add a second `NSWindow` (the "label window") that sits on top of the overlay border window. This is simpler than adding subviews to the existing CALayer-based window and avoids PyObjC selector conflicts.

The label window:
- Borderless, transparent background, ignores mouse events (same as overlay window)
- Contains an `NSTextField` (label mode, non-editable) with:
  - Amber background matching the border color
  - Black text, monospace font (SF Mono or Menlo), ~12pt
  - Centered text
- Positioned at the top of the overlay frame, spanning the full width
- Height: ~22px (enough for one line of text)
- Same window level as the overlay (NSFloatingWindowLevel + 1)
- Hidden/shown in sync with the main overlay window

**IPC change:** Add `"cwd"` field to `.deck-overlay.json`:

```json
{
  "visible": true,
  "x": 100, "y": 100, "w": 800, "h": 600,
  "color": [255, 176, 0],
  "cwd": "ClawDeck"
}
```

When `cwd` is null/missing or `visible` is false, the label window hides. The `cwd` value is already formatted by main.py (based on the config setting) — overlay.py just displays it.

**Update behavior:** The label only redraws when the `cwd` value changes (tracked via `self.last_cwd`).

---

## Button Labels

A dark semi-transparent bar across the top of each Stream Deck button showing the folder name.

**Implementation in main.py `_render_button()`:**

Add an optional `subtitle` parameter to `_render_button()`. When provided:
- Draw a dark bar (rgba black ~60% opacity) across the top ~20% of the button
- Render the subtitle text in the bar using a small font (~8pt)
- Shift the main label down slightly to compensate

**In `_draw_grid_mode()`:** Look up `self.slot_cwd.get(slot)` for each terminal slot. If present, pass it as `subtitle` to `_render_button()`. The ENTER key never gets a subtitle.

---

## `_update_overlay()` Change

In `_update_overlay()`, include the formatted CWD in the overlay JSON:

```python
cwd = self.slot_cwd.get(self.active_slot)
if cwd:
    formatted = self._format_cwd(cwd)
else:
    formatted = None
data = {"visible": True, "x": ..., "cwd": formatted, ...}
```

---

## Settings UI

Add a "Folder Labels" dropdown to the Behavior section of `settings.html`:
- Options: "Last folder" (default), "Last two folders", "Full path", "Off"
- Maps to `folder_label` config key

---

## Scope & Non-Goals

- No per-slot label customization (all slots use the same format)
- No live CWD tracking — updates every 30s during TTY map rebuild
- No labels for terminals without a mapped TTY
- No labels in Nav Mode (buttons have fixed functions there)
- The overlay label window is a separate NSWindow, not a subview (avoids PyObjC conflicts)

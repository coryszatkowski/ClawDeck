# Folder Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each terminal's working directory on both the screen overlay (amber top bar) and Stream Deck buttons (dark top bar).

**Architecture:** CWD is resolved per-slot by finding the shell process on each TTY and reading its CWD via `lsof`. Data flows through main.py (`slot_cwd` dict) to both button rendering and the overlay IPC file. overlay.py renders a second NSWindow as a text label bar.

**Tech Stack:** Python, Pillow (button rendering), AppKit/PyObjC (overlay text), `lsof`/`ps` (CWD resolution)

---

### Task 1: Add CWD resolution to TTY map build

**Files:**
- Modify: `main.py:326` (add `slot_cwd` field in `__init__`)
- Modify: `main.py:604-628` (add CWD lookup in `_build_tty_map`)
- Modify: `main.py:292-313` (add `folder_label` to config defaults)

- [ ] **Step 1: Add config default and instance field**

In `CONFIG_DEFAULTS` (line 292), add after `"layout": "default"`:

```python
    "folder_label": "last",  # "last", "two", "full", "off"
```

In `__init__` (line 326), add after `self.slot_tty = {}`:

```python
        self.slot_cwd = {}            # slot -> cwd path string
```

- [ ] **Step 2: Add CWD resolution helper method**

Add after `_build_tty_map` (after line 628):

```python
    def _resolve_tty_cwd(self, tty_name):
        """Get the working directory of the shell process on a TTY.
        Returns the path string, or None if it can't be resolved."""
        try:
            # Find shell PID on this TTY
            result = subprocess.run(
                ["ps", "-t", tty_name, "-o", "pid=,comm="],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return None

            shell_pid = None
            for line in result.stdout.strip().split("\n"):
                parts = line.strip().split(None, 1)
                if len(parts) == 2:
                    comm = parts[1].strip().lstrip("-")
                    if comm in ("zsh", "bash", "fish"):
                        shell_pid = parts[0].strip()
                        break
            if not shell_pid:
                return None

            # Get CWD from the shell process
            result = subprocess.run(
                ["lsof", "-a", "-p", shell_pid, "-d", "cwd", "-Fn"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return None

            for line in result.stdout.strip().split("\n"):
                if line.startswith("n"):
                    return line[1:]  # strip the 'n' prefix
            return None
        except Exception:
            logger.debug("Failed to resolve CWD for %s", tty_name, exc_info=True)
            return None
```

- [ ] **Step 3: Add CWD format helper method**

Add after `_resolve_tty_cwd`:

```python
    def _format_cwd(self, path):
        """Format a CWD path according to the folder_label config setting.
        Returns the formatted string for display."""
        if not path:
            return None
        mode = self.config.get("folder_label", "last")
        if mode == "off":
            return None

        home = str(Path.home())
        if path.startswith(home):
            tilde_path = "~" + path[len(home):]
        else:
            tilde_path = path

        if mode == "full":
            return tilde_path
        elif mode == "two":
            parts = Path(path).parts
            return "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
        else:  # "last"
            return Path(path).name
```

- [ ] **Step 4: Call CWD resolution in `_build_tty_map`**

At the end of `_build_tty_map`, after `self.slot_tty = tty_map` (line 628), add:

```python
        # Resolve CWD for each mapped TTY
        cwd_map = {}
        for slot, tty in tty_map.items():
            cwd = self._resolve_tty_cwd(tty)
            if cwd:
                cwd_map[slot] = cwd
        self.slot_cwd = cwd_map
```

- [ ] **Step 5: Test manually**

Run the controller: `.venv/bin/python main.py`

In the REPL, check that CWDs are being resolved:
```
tile
```
Then check the log output — you should see TTY map build happening. Add a temporary `print(self.slot_cwd)` after the assignment to verify CWDs are populated. Remove it after confirming.

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "Add CWD resolution per slot during TTY map build

Resolve each terminal's working directory by finding the shell
process on its TTY (ps) and reading its CWD (lsof). Cached in
slot_cwd dict, refreshed every 30s alongside the TTY map.
Format is configurable: last folder, two segments, full path, or off."
```

---

### Task 2: Add folder label to Stream Deck buttons

**Files:**
- Modify: `main.py:1344-1367` (`_render_button` — add subtitle parameter)
- Modify: `main.py:1408-1420` (`_draw_grid_mode` — pass CWD as subtitle)
- Modify: `main.py:575-593` (`_init_fonts` — add tiny font)

- [ ] **Step 1: Add a tiny font for subtitles**

In `_init_fonts` (line 591-593), add after `self.font_lg = load(26)`:

```python
        self.font_xs = load(9)
```

- [ ] **Step 2: Add subtitle support to `_render_button`**

Replace the `_render_button` method (lines 1344-1367) with:

```python
    def _render_button(self, label, bg=COLOR_BG_DEFAULT, fg=COLOR_FG_DEFAULT,
                       border_color=None, border_width=8, subtitle=None):
        """Create a button image for the Stream Deck.
        If border_color is set, draws a colored border around the button.
        If subtitle is set, draws a dark bar across the top with the subtitle text."""
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

        # Draw subtitle bar across top
        bar_h = 0
        if subtitle:
            bar_h = 16
            draw.rectangle([0, 0, w, bar_h], fill=(0, 0, 0, 153))
            # Truncate subtitle if too wide
            sub_bbox = draw.textbbox((0, 0), subtitle, font=self.font_xs)
            sub_tw = sub_bbox[2] - sub_bbox[0]
            if sub_tw > w - 4:
                while sub_tw > w - 10 and len(subtitle) > 3:
                    subtitle = subtitle[:-1]
                    sub_bbox = draw.textbbox((0, 0), subtitle + "…", font=self.font_xs)
                    sub_tw = sub_bbox[2] - sub_bbox[0]
                subtitle = subtitle + "…"
                sub_bbox = draw.textbbox((0, 0), subtitle, font=self.font_xs)
                sub_tw = sub_bbox[2] - sub_bbox[0]
            sub_x = (w - sub_tw) / 2
            sub_y = (bar_h - (sub_bbox[3] - sub_bbox[1])) / 2 - 1
            draw.text((sub_x, sub_y), subtitle, font=self.font_xs, fill=(255, 255, 255))

        # Draw main label (shifted down if subtitle present)
        font = self._pick_font(label)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (w - tw) / 2
        y = (h - th) / 2 - 2 + (bar_h / 2 if bar_h else 0)
        draw.text((x, y), label, font=font, fill=fg)
        return PILHelper.to_native_format(self.deck, image)
```

- [ ] **Step 3: Pass CWD subtitle in `_draw_grid_mode`**

Replace the grid drawing loop in `_draw_grid_mode` (lines 1408-1420) with:

```python
    def _draw_grid_mode(self):
        layout = self._get_layout()
        for i in range(DECK_TERMINAL_SLOTS):
            label = layout[i] if i < len(layout) else f"T{i+1}"
            bg, fg, border = self._get_slot_style(i)
            # Resolve CWD subtitle for this slot
            terminal_name = self._key_to_terminal(i)
            primary = self._terminal_to_active_slot(terminal_name) if terminal_name else i
            raw_cwd = self.slot_cwd.get(primary)
            subtitle = self._format_cwd(raw_cwd) if raw_cwd else None
            self.deck.set_key_image(
                i, self._render_button(label, bg, fg, border_color=border, subtitle=subtitle)
            )
        # Enter key (always present, no subtitle)
        self.deck.set_key_image(
            ENTER_KEY_INDEX,
            self._render_button("⏎", COLOR_BG_ENTER, COLOR_FG_ENTER),
        )
```

- [ ] **Step 4: Test manually**

1. Run the controller: `.venv/bin/python main.py`
2. Verify buttons show folder names in a dark bar across the top
3. Verify the main slot label (T1, T2, etc.) is still visible below
4. Verify the ENTER button has no subtitle
5. Verify long folder names get truncated with "…"

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "Add folder labels to Stream Deck buttons

Dark bar across the top of each button shows the terminal's working
directory. Folder name is truncated with ellipsis if too wide.
Main slot label shifts down to accommodate the bar."
```

---

### Task 3: Add folder label to overlay window

**Files:**
- Modify: `overlay.py` (add label window, update tick to show/hide label)
- Modify: `main.py:816-835` (`_update_overlay` — include `cwd` in IPC data)

- [ ] **Step 1: Add `cwd` to overlay IPC data in main.py**

In `_update_overlay` (line 816-835), update the data dict when `active_slot is not None`. Replace:

```python
            data = {"visible": True,
                    "x": rect["x"], "y": rect["y"],
                    "w": rect["w"], "h": rect["h"],
                    "color": list(active_color)}
```

With:

```python
            raw_cwd = self.slot_cwd.get(self.active_slot)
            formatted_cwd = self._format_cwd(raw_cwd) if raw_cwd else None
            data = {"visible": True,
                    "x": rect["x"], "y": rect["y"],
                    "w": rect["w"], "h": rect["h"],
                    "color": list(active_color),
                    "cwd": formatted_cwd}
```

- [ ] **Step 2: Add AppKit imports for text rendering in overlay.py**

Update the AppKit import block (line 18-26) to add NSTextField and font classes:

```python
from AppKit import (
    NSApplication,
    NSWindow,
    NSColor,
    NSTimer,
    NSWindowStyleMaskBorderless,
    NSBackingStoreBuffered,
    NSFloatingWindowLevel,
    NSTextField,
    NSFont,
    NSTextAlignmentCenter,
)
```

- [ ] **Step 3: Add `create_label_window` function**

Add after the `hide_overlay` function (after line 83):

```python
LABEL_HEIGHT = 22     # pixels for the folder label bar


def create_label_window():
    """Create a window for the folder label bar at the top of the overlay."""
    frame = ((0, 0), (1, 1))
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        frame,
        NSWindowStyleMaskBorderless,
        NSBackingStoreBuffered,
        False,
    )
    win.setLevel_(NSFloatingWindowLevel + 2)  # above the border overlay
    win.setOpaque_(False)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setIgnoresMouseEvents_(True)
    win.setHasShadow_(False)
    win.setCollectionBehavior_(1 << 0)  # canJoinAllSpaces

    # Create text field for the label
    label = NSTextField.alloc().initWithFrame_(((0, 0), (1, LABEL_HEIGHT)))
    label.setBezeled_(False)
    label.setDrawsBackground_(True)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setAlignment_(NSTextAlignmentCenter)
    label.setFont_(NSFont.fontWithName_size_("Menlo", 12.0) or NSFont.monospacedSystemFontOfSize_weight_(12.0, 0.0))
    label.setTextColor_(NSColor.blackColor())
    # Amber background matching border
    r, g, b = AMBER
    label.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(
        r / 255.0, g / 255.0, b / 255.0, 0.9
    ))

    win.contentView().addSubview_(label)
    win._label_field = label  # stash reference
    return win


def show_label(win, primary_h, qx, qy, qw):
    """Position the label window at the top of the overlay rect."""
    ns_y = primary_h - qy - LABEL_HEIGHT
    win.setFrame_display_(((qx, ns_y), (qw, LABEL_HEIGHT)), True)
    win._label_field.setFrame_(((0, 0), (qw, LABEL_HEIGHT)))
    win.orderFront_(None)


def hide_label(win):
    """Hide the label window."""
    win.orderOut_(None)
```

- [ ] **Step 4: Initialize label window in OverlayTick**

In `OverlayTick.init()`, add after `self.last_color = None`:

```python
        self.label_win = create_label_window()
        self.last_cwd = None
```

- [ ] **Step 5: Update tick to show/hide label**

In the `tick_` method, after the `show_overlay` call (inside the `if data.get("visible", False):` block), add label handling. After the block that calls `show_overlay`:

```python
                # Show/hide folder label
                cwd = data.get("cwd")
                if cwd:
                    if cwd != self.last_cwd or not self.visible:
                        self.label_win._label_field.setStringValue_(cwd)
                        primary_h = CGDisplayBounds(CGMainDisplayID()).size.height
                        show_label(self.label_win, primary_h, rect[0], rect[1], rect[2])
                    self.last_cwd = cwd
                else:
                    if self.last_cwd is not None:
                        hide_label(self.label_win)
                        self.last_cwd = None
```

In the `else` block (when `visible` is False) and in the `except` block, add label cleanup after `hide_overlay`:

```python
                    self.last_cwd = None
                    hide_label(self.label_win)
```

The full updated `tick_` method should be:

```python
    def tick_(self, timer):
        """Called every CHECK_INTERVAL by NSTimer."""
        try:
            text = Path(OVERLAY_FILE).read_text()
            data = json.loads(text)

            if data.get("visible", False):
                # Update color if provided
                color_list = data.get("color")
                if color_list and len(color_list) == 3:
                    self._update_border_color(tuple(color_list))

                rect = (data["x"], data["y"], data["w"], data["h"])
                if rect != self.last_rect or not self.visible:
                    primary_h = CGDisplayBounds(CGMainDisplayID()).size.height
                    show_overlay(self.win, primary_h, *rect)
                    self.last_rect = rect
                    self.visible = True

                # Show/hide folder label
                cwd = data.get("cwd")
                if cwd:
                    if cwd != self.last_cwd or rect != self.last_rect or not self.visible:
                        self.label_win._label_field.setStringValue_(cwd)
                        primary_h = CGDisplayBounds(CGMainDisplayID()).size.height
                        show_label(self.label_win, primary_h, rect[0], rect[1], rect[2])
                    self.last_cwd = cwd
                else:
                    if self.last_cwd is not None:
                        hide_label(self.label_win)
                        self.last_cwd = None
            else:
                if self.visible:
                    hide_overlay(self.win)
                    hide_label(self.label_win)
                    self.visible = False
                    self.last_rect = None
                    self.last_cwd = None

        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            if self.visible:
                hide_overlay(self.win)
                hide_label(self.label_win)
                self.visible = False
                self.last_rect = None
                self.last_cwd = None
```

- [ ] **Step 6: Test manually**

1. Run the controller: `.venv/bin/python main.py`
2. Click a terminal window — verify amber label bar appears at the top of the overlay with the folder name
3. Click a different terminal — verify label updates to that terminal's folder
4. Click a non-terminal app — verify both overlay and label disappear
5. Verify label text is centered and readable

- [ ] **Step 7: Commit**

```bash
git add main.py overlay.py
git commit -m "Add folder label to screen overlay

Amber bar at the top of the active window overlay shows the
terminal's working directory. Uses a second NSWindow with an
NSTextField, positioned above the border overlay. CWD is passed
through the overlay IPC file from main.py."
```

---

### Task 4: Add folder label setting to settings UI

**Files:**
- Modify: `settings.html` (add dropdown in Behavior section)

- [ ] **Step 1: Add dropdown HTML**

In `settings.html`, after the Idle Timeout row (after line 436 `</div>`), add:

```html
  <div class="row">
    <div>
      <label>Folder Labels</label>
      <div class="sublabel">Show working directory on buttons and overlay</div>
    </div>
    <select id="folder_label">
      <option value="last" selected>Last folder</option>
      <option value="two">Last two folders</option>
      <option value="full">Full path</option>
      <option value="off">Off</option>
    </select>
  </div>
```

- [ ] **Step 2: Add load/save JavaScript**

In the `loadSettings` function, after the `idle_timeout` line (around line 561), add:

```javascript
      document.getElementById('folder_label').value = s.folder_label || 'last';
```

In the `saveSettings` function, after the `idle_timeout` line (around line 591), add:

```javascript
      folder_label: document.getElementById('folder_label').value,
```

- [ ] **Step 3: Test manually**

1. Open settings at `http://127.0.0.1:19830`
2. Verify "Folder Labels" dropdown appears in the Behavior section
3. Change the setting and save — verify it persists on reload
4. Verify buttons and overlay update to reflect the new format

- [ ] **Step 4: Commit**

```bash
git add settings.html
git commit -m "Add folder label setting to settings UI

Dropdown in Behavior section: Last folder (default), Last two
folders, Full path, or Off."
```

---

### Task 5: Integration test

- [ ] **Step 1: Full integration test**

1. Run the controller: `.venv/bin/python main.py`
2. Verify buttons show folder names in dark top bar
3. Click terminal — overlay shows amber label bar with folder name
4. Click different terminal — label updates
5. Click non-terminal app — overlay and label both disappear
6. Change folder_label setting to "full" — verify buttons and overlay show full path
7. Change to "off" — verify no labels shown
8. Change to "last" — verify last folder name shown
9. `cd` to a different directory in a terminal, wait 30s — verify label updates

- [ ] **Step 2: Verify no regressions**

1. Test all layouts — switch between them, verify labels appear on correct buttons
2. Test Nav Mode — verify no labels shown (nav buttons are fixed)
3. Test status colors — verify idle/working/permission colors still work with labels
4. Verify ENTER button never shows a label

# Plan: Multi-Device Support for ClawDeck (Stream Deck Mini + Original)

## Context

The original ClawDeck is hardcoded for a Stream Deck Original (5x3, 15 keys). The goal is to refactor for multi-device support — auto-detecting the connected device and loading the appropriate configuration — while keeping the original 5x3 behavior as the default. This should be a clean, minimal change suitable for a PR back to the upstream repo.

**Key principle**: Don't rewrite the architecture. Introduce a `DEVICE_PROFILES` dict, auto-detect the device at startup, and set module-level globals from the matched profile. All existing code continues to reference the same variable names.

## Hardware Reference

| Spec | Stream Deck Original | Stream Deck Mini |
|------|---------------------|-----------------|
| Keys | 15 (5x3) | 6 (3x2) |
| Key image size | 72x72 px | 80x80 px |
| Image format | JPEG | BMP |
| `deck_type()` | `"Stream Deck Original"` | `"Stream Deck Mini"` |
| `key_count()` | `15` | `6` |
| HID interfaces | Multiple (needs retry loop) | Single |
| Key numbering | 0-14, left-to-right top-to-bottom | 0-5, left-to-right top-to-bottom |

Image size and format differences are handled automatically by `PILHelper` — no code changes needed for rendering.

## Files to Modify

1. **`main.py`** — device profiles, auto-detection, nav style logic, comments, settings API
2. **`settings.html`** — show/hide layout cards per device
3. **`README.md`** — document multi-device support

**No changes needed**: `overlay.py`, `deck-hook.sh`, `install_hooks.py`, `claude-hooks.json`, `menubar.py`, `setup.py`, `setup.sh`

---

## Phases

### Phase 1: Core Multi-Device Support (main.py)

**Goal**: Add `DEVICE_PROFILES`, auto-detection, fix nav style logic, and clean up hardcoded comments. After this phase, both devices should work correctly from the terminal REPL.

#### 1a. Add `DEVICE_PROFILES` dict (after existing constants, ~line 205)

The 15-key profile references the existing module-level `LAYOUTS`, `NAV_KEYMAP`, `NAV_BUTTON_STYLES` — no duplication. The 6-key profile defines new Mini-specific data inline.

```python
DEVICE_PROFILES = {
    15: {
        "name": "Stream Deck Original",
        "cols": 5, "rows": 3,
        "layouts": LAYOUTS,
        "nav_keymap": NAV_KEYMAP,
        "nav_button_styles": NAV_BUTTON_STYLES,
    },
    6: {
        "name": "Stream Deck Mini",
        "cols": 3, "rows": 2,
        "layouts": {
            "default": ["T1", "T2", "T3", "T4", "T5", "ENTER"],
            "focus":   ["T1", "T1", "T1", "T2", "T3", "ENTER"],
            "dual":    ["T1", "T2", "T3", "T1", "T2", "ENTER"],
            "wide":    ["T1", "T1", "T2", "T1", "T1", "ENTER"],
        },
        "nav_keymap": {
            0: ("arrow", "Up"),   1: ("arrow", "Down"), 2: ("back", None),
            3: ("num",   "1"),    4: ("num",   "2"),    5: ("enter", None),
        },
        "nav_button_styles": {
            0: {"label": "↑",    "bg": COLOR_BG_NAV_ARROW,  "fg": COLOR_FG_NAV_ARROW},
            1: {"label": "↓",    "bg": COLOR_BG_NAV_ARROW,  "fg": COLOR_FG_NAV_ARROW},
            2: {"label": "BACK", "bg": COLOR_BG_NAV_BACK,   "fg": COLOR_FG_DEFAULT},
            3: {"label": "1",    "bg": COLOR_BG_NUM_1,      "fg": COLOR_FG_NAV_NUM},
            4: {"label": "2",    "bg": COLOR_BG_NUM_2,      "fg": COLOR_FG_NAV_NUM},
            5: {"label": "⏎",    "bg": COLOR_BG_NAV_ACTION, "fg": COLOR_FG_NAV_ACTION},
        },
    },
}
```

Mini Nav Mode layout:
```
┌─────┬─────┬─────┐
│  ↑  │  ↓  │BACK │   keys 0, 1, 2
├─────┼─────┼─────┤
│  1  │  2  │  ⏎  │   keys 3, 4, 5
└─────┴─────┴─────┘
```

#### 1b. Add `apply_device_profile()` function

Must be called before any threads start. Includes layout length validation.

```python
def apply_device_profile(key_count):
    """Apply device-specific configuration. Must be called before threads start."""
    global COLS, ROWS, TOTAL_KEYS, GRID_SLOTS, DECK_TERMINAL_SLOTS, ENTER_KEY_INDEX
    global LAYOUTS, LAYOUT_NAMES, NAV_KEYMAP, NAV_BUTTON_STYLES
    profile = DEVICE_PROFILES.get(key_count, DEVICE_PROFILES[15])
    COLS = profile["cols"]
    ROWS = profile["rows"]
    TOTAL_KEYS = COLS * ROWS
    GRID_SLOTS = TOTAL_KEYS
    DECK_TERMINAL_SLOTS = TOTAL_KEYS - 1
    ENTER_KEY_INDEX = TOTAL_KEYS - 1
    LAYOUTS = profile["layouts"]
    LAYOUT_NAMES = list(LAYOUTS.keys())
    NAV_KEYMAP = profile["nav_keymap"]
    NAV_BUTTON_STYLES = profile["nav_button_styles"]
    # Validate all layouts have the correct number of entries
    for name, layout in LAYOUTS.items():
        assert len(layout) == TOTAL_KEYS, (
            f"Layout '{name}' has {len(layout)} entries, expected {TOTAL_KEYS}"
        )
```

#### 1c. Replace key count warning in `run()` (lines 1692-1697)

```python
key_count = self.deck.key_count()
apply_device_profile(key_count)
profile = DEVICE_PROFILES.get(key_count)
profile_name = profile["name"] if profile else "Unknown"
print(f"Connected: {self.deck.deck_type()} ({key_count} keys) — profile: {profile_name}")
if key_count not in DEVICE_PROFILES:
    print(f"Warning: no profile for {key_count} keys, using Stream Deck Original default.")
    print("The key layout may not work correctly.")
```

#### 1d. Make `_get_nav_style()` dynamic (lines 1359-1374)

Replace hardcoded key index sets with logic derived from `NAV_KEYMAP`:

```python
def _get_nav_style(self, key):
    """Get nav button style with config color overrides."""
    style = NAV_BUTTON_STYLES.get(key)
    if style is None:
        return None
    label = style["label"]
    bg = style["bg"]
    fg = style["fg"]
    action = NAV_KEYMAP.get(key)
    if action:
        action_type, action_val = action
        if action_type == "num":
            bg = self._color(f"num_{action_val}", bg)
        elif action_type == "arrow":
            bg = self._color("arrows", bg)
        elif action_type in ("whisprflow", "enter"):
            bg = self._color("mic_enter", bg)
    return {"label": label, "bg": bg, "fg": fg}
```

**Why this must be in Phase 1**: Without this fix, Mini nav mode would use wrong color groups (key 3 would be treated as `num_4` instead of `num_1`). The nav style fix is a correctness requirement, not optional.

#### 1e. Clean up hardcoded comments

| Location | Before | After |
|----------|--------|-------|
| Line 5 (docstring) | `Maps a 5x3 (15-key) Elgato Stream Deck` | `Maps an Elgato Stream Deck to terminal windows` |
| Lines 8-27 (diagrams) | Only 5x3 diagrams | Keep 5x3 as "Original", add Mini diagram below |
| Line 138 | `Key 14 is always ENTER.` | `Last key is always ENTER.` |
| Line 290 | `slot (0-13) is focused` | `which grid slot is focused` |
| Line 351 | `list of 15 terminal names` | `list of terminal names (length = TOTAL_KEYS)` |
| Line 855 | `slot 14 (bottom-right)` | `the last slot (bottom-right)` |
| Line 872 | `f"...slot 14"` | `f"...slot {ENTER_KEY_INDEX}"` |

#### 1f. Fix `_get_layout()` fallback for cross-device configs (line 352-353)

When a saved layout (e.g. `"quad"`) doesn't exist in the current device's profile, the fallback already works (`LAYOUTS.get(name, LAYOUTS["default"])`). But also update the config's effective value so the settings API returns the actual active layout:

```python
def _get_layout(self):
    """Get the current layout mapping."""
    name = self.config.get("layout", "default")
    if name not in LAYOUTS:
        name = "default"
    return LAYOUTS[name]
```

**How to test Phase 1**:
- Connect a Stream Deck Original → startup prints `profile: Stream Deck Original`, all behavior identical to before
- REPL `layout` command lists correct layouts for the connected device
- Enter Nav Mode on Original → verify all button colors are correct
- (If you have a Mini: connect it → verify profile detection, grid mode, nav mode)
- Grep for stale "14" / "15" / "5x3" references to confirm cleanup

---

### Phase 2: Settings UI (settings.html + main.py API)

**Goal**: The settings page shows the correct layout cards for whichever device is connected.

#### 2a. Extend `/api/settings` response to include device info (main.py, ~line 1783)

```python
elif path == "/api/settings":
    data = dict(controller_ref.config)
    data["_device"] = {
        "cols": COLS,
        "rows": ROWS,
        "layout_names": LAYOUT_NAMES,
    }
    self._json_response(data)
```

#### 2b. Add Mini layout SVG cards alongside existing ones (settings.html)

Keep the existing 5 SVG layout cards for the Original. Add 4 new cards for the Mini, each with `data-device="mini"`. Add `data-device="original"` to the existing cards. Show/hide based on `_device` info from the API.

This is simpler than JS-generated SVGs — the HTML is directly inspectable, and adding a third device someday just means adding more cards.

```html
<!-- Existing Original cards get data-device="original" attribute -->
<div class="layout-card" data-layout="default" data-device="original" onclick="selectLayout('default')">
  ...existing SVG...
</div>
<!-- ... other Original cards ... -->

<!-- New Mini cards -->
<div class="layout-card" data-layout="default" data-device="mini" onclick="selectLayout('default')" style="display:none">
  <div class="layout-label">Default</div>
  <svg viewBox="0 0 30 20" class="layout-svg">
    <rect x="1" y="1" width="9" height="9" rx="1"/>
    <rect x="11" y="1" width="9" height="9" rx="1"/>
    <rect x="21" y="1" width="8" height="9" rx="1"/>
    <rect x="1" y="11" width="9" height="8" rx="1"/>
    <rect x="11" y="11" width="9" height="8" rx="1"/>
    <rect x="21" y="11" width="8" height="8" rx="1" class="enter-key"/>
  </svg>
  <div class="layout-count">5 terminals</div>
</div>
<!-- ... focus, dual, wide cards for Mini ... -->
```

#### 2c. Add JS device detection in `loadSettings()`

```javascript
// After fetching settings:
const device = s._device;
const deviceType = (device && device.cols === 3 && device.rows === 2) ? 'mini' : 'original';
document.querySelectorAll('.layout-card').forEach(card => {
  card.style.display = card.dataset.device === deviceType ? '' : 'none';
});
// Adjust grid columns
const grid = document.querySelector('.layout-grid');
const visibleCards = document.querySelectorAll(`.layout-card[data-device="${deviceType}"]`).length;
grid.style.gridTemplateColumns = `repeat(${visibleCards}, 1fr)`;
```

**How to test Phase 2**:
- Connect Original → open `http://localhost:19830` → verify 5 Original layout cards shown, Mini cards hidden
- Connect Mini → open settings → verify 4 Mini layout cards shown, Original cards hidden
- Click a layout card → verify selection highlights and saving works
- Switch layouts → verify tiling updates on the Stream Deck

---

### Phase 3: Documentation (README.md)

**Goal**: Update README to document multi-device support.

**Changes**:

1. Update header: add "Also supports the **Stream Deck Mini** (6-key, 3x2 grid)"
2. Add "Supported Devices" section with device table:

```markdown
## Supported Devices

ClawDeck auto-detects your Stream Deck model on startup:

| Device               | Keys | Grid | Terminal Slots |
|----------------------|------|------|----------------|
| Stream Deck Original | 15   | 5×3  | 14             |
| Stream Deck Mini     | 6    | 3×2  | 5              |

The Mini uses a simplified Nav Mode (Up/Down arrows + 2 number keys).
```

3. Add Mini layout diagrams (keep existing Original diagrams)
4. Update requirements: "Stream Deck Original or Mini"
5. Update layout command docs: mention available layouts depend on device

**How to test Phase 3**:
- Read through and verify accuracy against implemented code
- Verify device table matches `DEVICE_PROFILES`

---

### Phase 4: Mini Hardware Testing & Debugging

**Goal**: Plug in the actual Stream Deck Mini and verify everything works end-to-end. This phase is dedicated time for hands-on testing and fixing any issues that only surface with real hardware.

#### Test checklist:

**Startup & Detection**
- [ ] Mini is detected on startup (prints `profile: Stream Deck Mini`)
- [ ] No Python errors or warnings (except expected ones for unsupported devices)
- [ ] `key_count()` returns 6

**Grid Mode**
- [ ] All 6 buttons render with correct labels (T1-T5 + ⏎)
- [ ] Button images render correctly at 80x80 (no clipping, proper scaling)
- [ ] Text labels are readable (font sizes may need adjustment for 80x80 vs 72x72)
- [ ] Tapping a terminal button activates the window (turns amber)
- [ ] Enter key sends Return keystroke
- [ ] Hold-to-activate triggers Whisprflow/MIC

**Window Tiling**
- [ ] `tile` command arranges windows in 3x2 grid on screen
- [ ] Windows snap correctly to the 3-column, 2-row grid
- [ ] Controller terminal is placed in last slot (bottom-right)
- [ ] Switching layouts re-tiles windows correctly

**Nav Mode**
- [ ] Tapping active terminal enters Nav Mode
- [ ] Up/Down arrows send correct keystrokes
- [ ] Number keys 1/2 send correct keystrokes
- [ ] BACK returns to Grid Mode
- [ ] Enter sends Return
- [ ] Button colors match config (arrows = slate-blue, numbers = ROYGB, etc.)

**Layouts**
- [ ] `layout` command cycles through default/focus/dual/wide
- [ ] "focus" merges top row into one window correctly
- [ ] "dual" merges columns correctly
- [ ] "wide" merges 2x2 region correctly

**Claude Status Integration**
- [ ] Hook status colors work (idle=blue, working=green, permission=red blink)
- [ ] TTY-to-slot mapping works with fewer slots

**Settings UI**
- [ ] Settings page loads and shows Mini layout cards
- [ ] Saving settings works
- [ ] Brightness control works

#### Potential issues to watch for:
- **Font rendering at 80x80**: Mini keys have slightly larger pixel canvas. If text looks off, may need to adjust `border_width` (currently 8) or font thresholds in `_pick_font()`
- **Snap tolerance**: The `SNAP_TOLERANCE = 20px` may behave differently with a 3x2 grid (larger cells). May need adjustment
- **Overlay border**: The amber overlay is grid-agnostic but verify it appears at the right position for the wider cells

**How to test Phase 4**:
- This IS the testing phase — work through the checklist above with the physical Mini connected
- Fix any issues found inline, document what needed adjustment

---

## Edge Cases & Risks

1. **Existing config.json**: If saved `"layout": "quad"` and connecting a Mini, `_get_layout()` falls back to `"default"`. Safe.
2. **Module globals & threading**: `apply_device_profile()` runs once before threads start. No race.
3. **Unsupported device** (e.g. XL with 32 keys): Falls back to 15-key profile with warning.
4. **Color pickers**: Keep all 5 number color pickers in settings UI. Unused colors are harmless.
5. **MIC key**: Mini drops dedicated MIC in nav mode. Still accessible via hold-to-activate in grid mode.
6. **Mini Mk.2 variant**: Uses same `StreamDeckMini` class in the library, same key_count of 6. Should work identically.

---

## Suggested Commit & PR

**Commit message:**
```
Add multi-device support: auto-detect Stream Deck model and load appropriate profile

Introduces DEVICE_PROFILES dict with per-device grid dimensions, layouts,
and nav mode mappings. Auto-detects connected device by key count and
applies the matching profile at startup. Default behavior (15-key Original)
is unchanged. Adds Stream Deck Mini (6-key, 3x2) as first additional profile.
```

**PR title:** `Add Stream Deck Mini support via device profiles`

**PR description:**
```
## Summary
- Adds a `DEVICE_PROFILES` system that auto-detects the connected Stream Deck
  model and loads appropriate grid dimensions, layouts, and nav mode mappings
- Stream Deck Original (15-key, 5x3) remains the default — zero behavior change
- Adds Stream Deck Mini (6-key, 3x2) with 4 layouts and simplified nav mode
- Settings UI shows correct layout cards based on connected device
- Makes `_get_nav_style()` derive color groups from `NAV_KEYMAP` instead of
  hardcoded key indices, so it works for any device automatically

## Test plan
- [ ] Connect Stream Deck Original — verify all existing functionality unchanged
- [ ] Connect Stream Deck Mini — verify auto-detection, layouts, nav mode, tiling
- [ ] Open settings UI with each device — verify correct layout cards shown
- [ ] Save config with one device, connect other — verify graceful fallback
- [ ] Connect unsupported device — verify warning message and 15-key fallback
```

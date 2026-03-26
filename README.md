# ClawDeck

Map an Elgato Stream Deck to a grid of terminal windows running Claude Code sessions. Each button shows the session's state — idle (blue), working (green), needs permission (red blink). Tap to switch windows, hold to dictate.

Built for the **Stream Deck Original** (15-key, 5x3 grid) on **macOS**.
Also supports the **Stream Deck Mini** (6-key, 3x2 grid).

## What It Does

- Tiles terminal windows into a screen grid matching your device (5x3 or 3x2)
- Each Stream Deck button reflects Claude Code's live state via hooks
- Tap a button to activate that terminal window
- Hold a button to trigger Whisprflow / dictation
- Nav Mode for arrow keys and number selection (Claude multi-choice prompts)
- Screen border overlay highlights the active window
- Snap-to-grid: drag a terminal and it auto-snaps to the nearest slot
- Browser-based settings UI for colors, layouts, and behavior
- All colors fully customizable

### Button Colors

| Color | Meaning |
|-------|---------|
| Black | No Claude session |
| Blue | Idle — waiting for input |
| Green | Working — actively processing |
| Red (blinking) | Permission needed |
| Amber border | Active window |

All colors are customizable via the settings UI.

### Supported Devices

ClawDeck auto-detects your Stream Deck model on startup:

| Device | Keys | Grid | Terminal Slots | Nav Keys |
|--------|------|------|----------------|----------|
| Stream Deck Original | 15 | 5×3 | 14 | 5 numbers, 4 arrows, MIC, Back, Enter |
| Stream Deck Mini | 6 | 3×2 | 5 | 2 numbers, 2 arrows, Back, Enter |

### Layouts

Choose a window layout from settings or the `layout` command.

```
Default (14 terminals)          Quad (11 terminals)
┌────┬────┬────┬────┬────┐     ┌─────────┬────┬────┬────┐
│ T1 │ T2 │ T3 │ T4 │ T5 │     │         │ T2 │ T3 │ T4 │
├────┼────┼────┼────┼────┤     │   T1    ├────┼────┼────┤
│ T6 │ T7 │ T8 │ T9 │T10│     │         │ T5 │ T6 │ T7 │
├────┼────┼────┼────┼────┤     ├────┼────┼────┼────┼────┤
│T11 │T12 │T13 │T14 │ ⏎  │     │ T8 │ T9 │T10 │T11 │ ⏎  │
└────┴────┴────┴────┴────┘     └────┴────┴────┴────┴────┘

Double Quad (8 terminals)       Wide (9 terminals)
┌─────────┬─────────┬────┐     ┌──────────────┬────┬────┐
│         │         │ T3 │     │              │ T2 │ T3 │
│   T1    │   T2    ├────┤     │     T1       ├────┼────┤
│         │         │ T4 │     │              │ T4 │ T5 │
├────┼────┼────┼────┼────┤     ├────┼────┼────┼────┼────┤
│ T5 │ T6 │ T7 │ T8 │ ⏎  │     │ T6 │ T7 │ T8 │ T9 │ ⏎  │
└────┴────┴────┴────┴────┘     └────┴────┴────┴────┴────┘

Half (6 terminals)
┌─────────┬────┬────┬────┐
│         │ T2 │ T3 │ T4 │
│         ├────┼────┼────┤
│   T1    │ T5 │ T6 │ T7 │
│         ├────┼────┼────┤
│         │ T8 │ T9 │ ⏎  │
└─────────┴────┴────┴────┘
```

**Stream Deck Mini layouts** (3×2):

```
Default (5 terminals)       Focus (3 terminals)
┌────┬────┬────┐           ┌────────────────┐
│ T1 │ T2 │ T3 │           │      T1        │
├────┼────┼────┤           ├────┬────┬──────┤
│ T4 │ T5 │ ⏎  │           │ T2 │ T3 │  ⏎   │
└────┴────┴────┘           └────┴────┴──────┘

Dual (3 terminals)          Wide (2 terminals)
┌────┬────┬────┐           ┌─────────┬──────┐
│    │    │ T3 │           │         │  T2  │
│ T1 │ T2 ├────┤           │   T1    ├──────┤
│    │    │ ⏎  │           │         │  ⏎   │
└────┴────┴────┘           └─────────┴──────┘
```

### Modes

**Grid Mode** (default):
- Tap → activate window
- Tap active window → enter Nav Mode
- Hold any button → activate + trigger MIC (Whisprflow)
- Bottom-right → Enter key

**Nav Mode** (tap the active button):

Original (5×3):
```
  1    2    3    4    5     ← ROYGB number keys
            ↑        BACK
 MIC  ←    ↓    →    ⏎
```

Mini (3×2):
```
  ↑    ↓   BACK
  1    2    ⏎
```

- Number keys → send keystrokes (for Claude multi-choice prompts)
- Arrows → navigation
- MIC → Whisprflow (Original only; on Mini, use hold-to-activate in Grid Mode)
- BACK → return to Grid Mode

## Requirements

- macOS (uses Quartz, AppKit, AppleScript for window management)
- [Homebrew](https://brew.sh)
- Elgato Stream Deck (Original 15-key or Mini 6-key)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed

## Install

```bash
git clone https://github.com/coryszatkowski/ClawDeck.git
cd ClawDeck
bash setup.sh
```

Setup will:
1. Install `hidapi` and Python 3.13 via Homebrew
2. Create a virtual environment and install dependencies
3. Offer to install Claude Code hooks into `~/.claude/settings.json`

On first run, you'll be prompted to grant **Accessibility** permissions to your terminal app (required for window management). If you use multiple terminal apps (e.g. Terminal.app for the controller and iTerm2 for Claude sessions), grant Accessibility to **all of them** in System Settings > Privacy & Security > Accessibility.

## Run

```bash
cd ClawDeck
.venv/bin/python main.py
```

This starts the controller with a terminal REPL and a browser-based settings UI.

## Settings UI

A settings page is available at `http://127.0.0.1:19830` while the controller is running. Type `settings` in the REPL to open it. From here you can configure:

- **Layout** — visual grid selector (shows layouts for your connected device)
- **Brightness** — Stream Deck brightness slider
- **Colors** — pick custom colors for status states, nav keys, and active window
- **Behavior** — hold threshold, poll interval, snap-to-grid, idle timeout
- **MIC key** — Whisprflow (fn) or custom shell command
- **Hooks** — one-click Claude Code hook installation

## Runtime Commands

Type these while the controller is running:

| Command | Description |
|---------|-------------|
| `tile` | Re-arrange windows into grid |
| `layout <name>` | Set layout (available layouts depend on device) |
| `brightness <0-100>` | Set Stream Deck brightness |
| `hold <seconds>` | Set hold threshold for MIC (default 0.5s) |
| `poll <seconds>` | Set poll interval (default 0.2s) |
| `snap <on\|off>` | Toggle snap-to-grid |
| `mic <fn\|command>` | Set MIC action (`fn` = Whisprflow, or any shell command) |
| `mic learn` | Press a key to capture it as the MIC action |
| `settings` | Open settings in browser |
| `quit` | Exit |

Settings persist to `config.json` automatically.

## Menu Bar App (Optional)

For a standalone menu bar experience:

```bash
.venv/bin/python menubar.py
```

Or build a `.app` bundle:

```bash
.venv/bin/python setup.py py2app
open dist/ClawDeck.app
```

## How It Works

```
main.py (DeckController)
  ├── Stream Deck ←→ Key callbacks (press/release/hold)
  ├── Quartz API  ←→ Window discovery, frontmost detection
  ├── AppleScript ←→ Window tiling, activation, keystroke sending
  ├── HTTP server ←→ Settings UI (settings.html)
  ├── /tmp/deck-status/*  ← Hook status files (read)
  └── .deck-overlay.json  → Overlay position + color (write)
          │                              ▲
          ▼                              │
    overlay.py                    deck-hook.sh
    (screen border)               (called by Claude Code hooks)
```

Claude Code hooks fire on state changes (tool use, permission prompts, idle) and write status files. The controller polls these every 200ms and updates button colors accordingly.

## Terminal Apps Supported

Terminal.app and iTerm2 have full TTY mapping (status colors per window). Other apps (Warp, Alacritty, kitty, Hyper) will tile and activate but won't show per-session status colors.

## License

MIT

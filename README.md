# ClawDeck Mini

> **Fork of [ClawDeck](https://github.com/coryszatkowski/ClawDeck)** by [coryszatkowski](https://github.com/coryszatkowski).
> All credit for the original project goes to the original author.
> This fork is not endorsed by or affiliated with the original project.

Map an Elgato Stream Deck to a grid of terminal windows running Claude Code sessions. Each button shows the session's state — idle (blue), working (green), needs permission (red blink). Tap to switch windows, hold to dictate.

Built for the **Stream Deck Original** (15-key, 5x3 grid) on **macOS**.
Also supports the **Stream Deck Mini** (6-key, 3x2 grid).

## What This Fork Adds

This fork extends the original ClawDeck with two changes:

- **Stream Deck Mini support** — auto-detects the connected device and loads the appropriate profile (grid dimensions, layouts, and nav mode mappings). The Original 15-key behavior is unchanged.
- **Ghostty terminal support** — adds [Ghostty](https://ghostty.org) to the list of recognized terminal apps for window tiling and management.

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

- **macOS** (uses Quartz, AppKit, AppleScript for window management)
- **[Homebrew](https://brew.sh)**
- **Python 3.12 or 3.13** (installed automatically by the setup script via Homebrew)
- **Elgato Stream Deck** — Original (15-key) or Mini (6-key)
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** installed and working

> **Important:** ClawDeck talks directly to the Stream Deck hardware over USB. You must **quit the Elgato Stream Deck software** before running ClawDeck. The two cannot run at the same time. Your Elgato profiles are not affected — just relaunch the Elgato app when you're done with ClawDeck.

## Install

```bash
git clone https://github.com/boeightai/ClawDeckMini.git
cd ClawDeckMini
bash setup.sh
```

The setup script will:
1. Install `hidapi` and Python 3.13 via Homebrew
2. Create a virtual environment (`.venv/`) and install Python dependencies
3. Prompt to install Claude Code hooks into `~/.claude/settings.json` — type `y` to accept

### Permissions

On first run, you'll be prompted to grant **Accessibility** permissions to your terminal app. This is required for window management and keystroke sending.

If you use multiple terminal apps (e.g. Terminal.app for the controller and Ghostty for Claude sessions), grant Accessibility to **all of them**:

> System Settings → Privacy & Security → Accessibility → add your terminal app(s)

## Run

1. **Quit the Elgato Stream Deck software** (menu bar → quit)
2. Start ClawDeck:

```bash
cd ClawDeckMini
sudo .venv/bin/python main.py
```

> `sudo` is required for USB HID access to the Stream Deck hardware.

3. ClawDeck will auto-detect your device and print:
```
Connected: Stream Deck Mini (6 keys) — profile: Stream Deck Mini
```
4. Type `tile` to arrange your open terminal windows into the grid.
5. Open more terminal windows and run `claude` in each one to start Claude Code sessions.

This starts the controller with a terminal REPL and a browser-based settings UI.

### Quick Launch

To avoid typing the full path each time, add a shell alias:

```bash
echo "alias clawdeck='cd ~/Documents/ClawDeckMini && sudo .venv/bin/python menubar.py'" >> ~/.zshrc
```

Then open a new terminal and type `clawdeck` to launch.

## Configuration

ClawDeck works out of the box with no configuration file. All settings have sensible defaults.

Settings are saved to `config.json` (gitignored) when you change them via the Settings UI or REPL commands. See [`config.example.json`](config.example.json) for all available options and their defaults.

To start with a custom config, copy the example:

```bash
cp config.example.json config.json
```

| Key | Default | Description |
|-----|---------|-------------|
| `brightness` | `80` | Stream Deck LED brightness (0-100) |
| `hold_threshold` | `0.5` | Seconds before a hold triggers MIC |
| `poll_interval` | `0.2` | Seconds between active-window checks |
| `snap_enabled` | `true` | Auto-snap dragged windows to grid |
| `mic_command` | `"fn"` | MIC action — `"fn"` for Whisprflow, or a shell command |
| `idle_timeout` | `3600` | Seconds before idle/working status resets to black |
| `layout` | `"default"` | Active layout name (available layouts depend on device) |
| `colors` | *(see example)* | Hex colors for status states, nav keys, and active window |

> **Note:** Device detection (Mini vs Original) is automatic based on the connected hardware — it is not a config setting.

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

For a menu bar experience instead of the terminal REPL:

```bash
sudo .venv/bin/python menubar.py
```

A crab icon appears in the menu bar. Click it to Start/Stop the controller, Tile Windows, or open Settings. This also requires `sudo` for USB HID access.

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

Terminal.app, iTerm2, and Ghostty have full TTY mapping (status colors per window). Other apps (Warp, Alacritty, kitty, Hyper) will tile and activate but won't show per-session status colors.

> **Ghostty users:** Make sure to grant Accessibility permissions to Ghostty in System Settings → Privacy & Security → Accessibility. Without this, ClawDeck cannot manage Ghostty windows.

## Stream Deck Mini Notes

- The Mini has **5 terminal slots** plus an Enter key (vs 14 on the Original).
- **Nav Mode** is simplified: Up/Down arrows + numbers 1-2 + Back + Enter. There is no dedicated MIC button — use hold-to-activate on any terminal button in Grid Mode instead.
- The screen tiles into a **3-column, 2-row grid**. The bottom-right cell is used by the controller's own terminal when running `main.py`.
- ClawDeck tiles to **whichever monitor your mouse cursor is on** at startup. Move your mouse to the desired monitor before starting.

## License

MIT

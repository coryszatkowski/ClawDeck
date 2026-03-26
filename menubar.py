#!/usr/bin/env python3
"""
ClawDeck Menu Bar App — wraps DeckController in a macOS menu bar interface.

Provides:
  - Start/Stop Stream Deck controller
  - Status indicator in menu bar
  - Settings window (local HTTP server + browser)
  - Auto-tile on start
  - Install/update hooks
"""

import threading
import json
import os
import sys
import time
import subprocess
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import rumps

from main import DeckController, CONFIG_FILE, CONFIG_DEFAULTS, apply_device_profile, DEVICE_PROFILES

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_HTML = os.path.join(SCRIPT_DIR, "settings.html")

# Global ref so the HTTP handler can reach the app
_app_instance = None


class SettingsHandler(BaseHTTPRequestHandler):
    """Tiny HTTP handler for the settings page."""

    def log_message(self, format, *args):
        pass  # silence request logging

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/settings":
            with open(SETTINGS_HTML, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content)

        elif path == "/api/settings":
            config = dict(CONFIG_DEFAULTS)
            try:
                with open(CONFIG_FILE) as f:
                    config.update(json.load(f))
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            self._json_response(config)

        elif path == "/api/status":
            app = _app_instance
            ctrl = app.controller if app else None
            if ctrl and ctrl.running:
                self._json_response({
                    "running": True,
                    "deck": ctrl.deck.deck_type() if ctrl.deck else "unknown",
                    "terminals": len(ctrl.slot_tty),
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

            # Write config atomically
            try:
                tmp = CONFIG_FILE + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(new_config, f, indent=2)
                    f.write("\n")
                os.rename(tmp, CONFIG_FILE)
            except Exception as e:
                self._json_response({"ok": False, "error": str(e)}, 500)
                return

            # Apply to running controller
            app = _app_instance
            ctrl = app.controller if app else None
            if ctrl and ctrl.running:
                ctrl.config.update(new_config)
                if ctrl.deck:
                    try:
                        ctrl.deck.set_brightness(new_config.get("brightness", 80))
                    except Exception:
                        pass

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


class ClawDeckApp(rumps.App):
    def __init__(self):
        super().__init__(
            "ClawDeck",
            icon=None,
            title="\U0001f99e",
            quit_button=None,
        )
        self.controller = None
        self._controller_thread = None
        self._http_server = None
        self._http_port = None

        self.menu = [
            rumps.MenuItem("Start", callback=self.toggle_controller),
            rumps.MenuItem("Tile Windows", callback=self.tile_windows),
            None,
            rumps.MenuItem("Settings...", callback=self.open_settings),
            rumps.MenuItem("Install Hooks", callback=self.install_hooks),
            None,
            rumps.MenuItem("Quit ClawDeck", callback=self.quit_app),
        ]

        # Start the settings HTTP server in background
        self._start_http_server()

    def _start_http_server(self):
        """Start a local HTTP server for the settings page."""
        # Find a free port
        for port in range(19830, 19850):
            try:
                server = HTTPServer(("127.0.0.1", port), SettingsHandler)
                self._http_server = server
                self._http_port = port
                threading.Thread(target=server.serve_forever, daemon=True).start()
                return
            except OSError:
                continue

    def toggle_controller(self, sender):
        if self.controller and self.controller.running:
            self._stop_controller()
            sender.title = "Start"
            self.title = "\U0001f99e"
        else:
            self._start_controller()
            sender.title = "Stop"

    def _start_controller(self):
        """Start DeckController in a background thread."""
        def run():
            try:
                self.controller = DeckController()
                self.controller._check_accessibility()

                from StreamDeck.DeviceManager import DeviceManager
                devices = DeviceManager().enumerate()
                if not devices:
                    rumps.notification(
                        "ClawDeck", "No Stream Deck Found",
                        "Make sure your Stream Deck is plugged in.",
                    )
                    self.controller = None
                    self._update_menu_state(False)
                    return

                for dev in devices:
                    try:
                        dev.open()
                        self.controller.deck = dev
                        break
                    except Exception:
                        continue
                else:
                    rumps.notification(
                        "ClawDeck", "Connection Failed",
                        "Could not open Stream Deck. Try unplugging and reconnecting.",
                    )
                    self.controller = None
                    self._update_menu_state(False)
                    return

                ctrl = self.controller
                ctrl.deck.reset()
                ctrl.deck.set_brightness(ctrl.config["brightness"])

                # Apply device profile based on detected key count
                key_count = ctrl.deck.key_count()
                apply_device_profile(key_count)
                profile = DEVICE_PROFILES.get(key_count)
                profile_name = profile["name"] if profile else "Unknown"
                print(f"Connected: {ctrl.deck.deck_type()} ({key_count} keys) — profile: {profile_name}")

                # Re-detect screen bounds (use monitor where mouse is NOW)
                ctrl.screen = ctrl._get_screen_bounds()

                ctrl.tile_windows()
                time.sleep(0.3)

                for w in ctrl._get_terminal_windows():
                    ctrl._prev_win_positions[w["id"]] = (w["x"], w["y"], w["w"], w["h"])

                ctrl._build_tty_map()
                os.makedirs("/tmp/deck-status", exist_ok=True)

                ctrl._update_all_buttons()
                ctrl.deck.set_key_callback(ctrl._on_key_change)
                ctrl._start_overlay()

                ctrl.running = True
                self.title = "\U0001f99e\u2713"

                ctrl._poll_active_loop()

            except Exception as e:
                rumps.notification("ClawDeck", "Error", str(e))
                self.controller = None
                self._update_menu_state(False)

        self._controller_thread = threading.Thread(target=run, daemon=True)
        self._controller_thread.start()

    def _stop_controller(self):
        if self.controller:
            self.controller.running = False
            self.controller._stop_overlay()
            if self.controller.deck:
                try:
                    self.controller.deck.reset()
                    self.controller.deck.close()
                except Exception:
                    pass
            self.controller = None

    def _update_menu_state(self, running):
        try:
            start_item = self.menu["Start"]
        except KeyError:
            try:
                start_item = self.menu["Stop"]
            except KeyError:
                return
        start_item.title = "Stop" if running else "Start"
        self.title = "\U0001f99e\u2713" if running else "\U0001f99e"

    def tile_windows(self, _):
        if self.controller and self.controller.running:
            self.controller.tile_windows()
            time.sleep(0.3)
            self.controller._build_tty_map()
            self.controller._update_overlay()
            self.controller._update_all_buttons()
        else:
            rumps.notification("ClawDeck", "", "Start the controller first.")

    def open_settings(self, _):
        """Open settings page in the default browser."""
        if self._http_port:
            webbrowser.open(f"http://127.0.0.1:{self._http_port}/")

    def install_hooks(self, _):
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "install_hooks.py")],
            input="y\n", capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            rumps.notification("ClawDeck", "Hooks Installed",
                               "Restart Claude Code sessions to pick up new hooks.")
        else:
            rumps.notification("ClawDeck", "Hook Install Failed",
                               result.stderr[:200] if result.stderr else "Unknown error")

    def quit_app(self, _):
        self._stop_controller()
        if self._http_server:
            self._http_server.shutdown()
        rumps.quit_application()


if __name__ == "__main__":
    app = ClawDeckApp()
    _app_instance = app
    app.run()

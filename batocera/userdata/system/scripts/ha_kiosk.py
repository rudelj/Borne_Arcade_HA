#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Home Assistant Arcade Kiosk for Batocera
- Displays Home Assistant in fullscreen with live real-time state synchronization
- Prevents WebKit background suspension (anti-sleep, always visible)
- Continuous hass object propagation to Lovelace cards
- WebSocket keep-alive and self-healing watchdog
- Auto-login with configured credentials
- Instant exit on any arcade button or joystick input to return to Batocera
"""

import os
import sys
import time
import select
import threading
import signal
import glob
import json

# Ensure GIO modules and display environment
os.environ["GIO_EXTRA_MODULES"] = "/userdata/system/lib/gio/modules"
os.environ["XDG_RUNTIME_DIR"] = "/var/run"
os.environ["WAYLAND_DISPLAY"] = "wayland-1"
os.environ["DISPLAY"] = ":0"

# Read config
CONF_FILE = "/userdata/system/configs/ha_kiosk/ha_kiosk.conf"
ha_url = "https://ha.wecoachimmo.fr/maison-2026/accueil"
ha_user = ""
ha_pass = ""
exit_on_stick = True
web_zoom = 1.0

if os.path.exists(CONF_FILE):
    try:
        with open(CONF_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or not line or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k == "HA_URL" and v:
                    ha_url = v
                elif k == "HA_USER":
                    ha_user = v
                elif k == "HA_PASSWORD":
                    ha_pass = v
                elif k == "EXIT_ON_JOYSTICK_MOVE":
                    exit_on_stick = (v.lower() == "true")
                elif k == "WEB_ZOOM":
                    try:
                        web_zoom = float(v)
                    except ValueError:
                        pass
    except Exception as e:
        print(f"[ha_kiosk] Error reading config: {e}", flush=True)

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, Gdk, WebKit2, GLib
import evdev

PID_FILE = "/var/run/ha_kiosk.pid"
with open(PID_FILE, "w") as f:
    f.write(str(os.getpid()))

DATA_DIR = "/userdata/system/configs/ha_kiosk/data"
CACHE_DIR = "/tmp/ha_kiosk_cache"
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# Build WebKit Context
data_manager = WebKit2.WebsiteDataManager(
    base_data_directory=DATA_DIR,
    base_cache_directory=CACHE_DIR
)
web_context = WebKit2.WebContext(website_data_manager=data_manager)
web_context.set_cache_model(WebKit2.CacheModel.WEB_BROWSER)

# Settings
settings = WebKit2.Settings()
settings.set_enable_javascript(True)
settings.set_enable_webgl(True)
settings.set_enable_media_stream(True)
settings.set_enable_smooth_scrolling(True)
settings.set_javascript_can_access_clipboard(True)
settings.set_enable_write_console_messages_to_stdout(False)
settings.set_disable_web_security(True)

# Modern Chrome User-Agent
CHROME_UA = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
settings.set_user_agent(CHROME_UA)

# Polyfills & Live Synchronization Watchdog
POLYFILL_JS = """
(function() {
    console.log("[POLYFILL] Initializing Kiosk Polyfills & Real-Time Sync...");

    // 1. Prevent background suspension: Force document to always be visible and focused
    try {
        Object.defineProperty(document, 'hidden', {
            get: function() { return false; },
            configurable: true
        });
        Object.defineProperty(document, 'visibilityState', {
            get: function() { return 'visible'; },
            configurable: true
        });
        document.hasFocus = function() { return true; };
        localStorage.setItem('suspendWhenHidden', 'false');
    } catch(e) {}

    // 2. OffscreenCanvas polyfill
    if (typeof HTMLCanvasElement !== 'undefined' && HTMLCanvasElement.prototype) {
        if (typeof HTMLCanvasElement.prototype.transferControlToOffscreen === 'undefined') {
            HTMLCanvasElement.prototype.transferControlToOffscreen = function() { return this; };
        }
    }
    function FakeOffscreenCanvas(w, h) {
        let c = document.createElement('canvas');
        c.width = w || 300;
        c.height = h || 150;
        return c;
    }
    if (typeof window.OffscreenCanvas === 'undefined') {
        window.OffscreenCanvas = FakeOffscreenCanvas;
        globalThis.OffscreenCanvas = FakeOffscreenCanvas;
        self.OffscreenCanvas = FakeOffscreenCanvas;
    }
    try {
        Object.defineProperty(window.OffscreenCanvas, Symbol.hasInstance, {
            value: function(inst) {
                return inst instanceof HTMLCanvasElement || (inst && typeof inst.getContext === 'function');
            }
        });
    } catch(e) {}

    // 3. CustomElementRegistry safe define
    if (typeof CustomElementRegistry !== 'undefined' && CustomElementRegistry.prototype) {
        const origDefine = CustomElementRegistry.prototype.define;
        const seenConstructors = new WeakSet();
        CustomElementRegistry.prototype.define = function(name, constructor, options) {
            if (this.get(name)) return;
            let ctor = constructor;
            if (seenConstructors.has(constructor)) {
                try { ctor = class extends constructor {}; } catch(e) {}
            }
            try {
                origDefine.call(this, name, ctor, options);
                seenConstructors.add(constructor);
                seenConstructors.add(ctor);
            } catch(err) {}
        };
    }

    // 4. LIVE CONTINUOUS SYNC & KEEP-ALIVE WATCHDOG
    window.__lastHeartbeat = Date.now();
    setInterval(function() {
        try {
            window.__lastHeartbeat = Date.now();
            let ha = document.querySelector('home-assistant');
            if (!ha) return;

            if (ha.hass) {
                // Keep suspendWhenHidden disabled
                if (ha.hass.suspendWhenHidden !== false) {
                    ha.hass.suspendWhenHidden = false;
                }

                // Auto-reconnect WebSocket if dropped
                if (ha.hass.connection && !ha.hass.connection.connected) {
                    if (typeof ha.hass.connection.reconnect === 'function') {
                        ha.hass.connection.reconnect(true);
                    }
                }

                // Initial render transition if on launch screen
                if (ha.hass.states && ha.hass.config && ha.hass.services) {
                    if (ha.render !== ha.renderHass && typeof ha.renderHass === 'function') {
                        ha._databaseMigration = false;
                        ha.render = ha.renderHass;
                        if (typeof ha.requestUpdate === 'function') ha.requestUpdate();
                    }
                    let ls = document.getElementById('ha-launch-screen');
                    let haMain = ha.shadowRoot ? ha.shadowRoot.querySelector('home-assistant-main') : null;
                    if (haMain && ls) {
                        ls.remove();
                    }

                    // CONTINUOUS STATE PROPAGATION TO LOVELACE CARDS:
                    // Ensures real-time state changes push directly to Lovelace view
                    if (haMain && haMain.hass !== ha.hass) {
                        haMain.hass = ha.hass;
                    }
                    if (Array.isArray(ha.__provideHass)) {
                        ha.__provideHass.forEach(function(el) {
                            if (el && el.hass !== ha.hass) {
                                el.hass = ha.hass;
                            }
                        });
                    }
                }
            }
        } catch(e) {}
    }, 400);

    console.log("[POLYFILL] Kiosk Polyfills & Real-Time Sync Watchdog active.");
})();
"""

ucm = WebKit2.UserContentManager()
user_script = WebKit2.UserScript(
    source=POLYFILL_JS,
    injected_frames=WebKit2.UserContentInjectedFrames.ALL_FRAMES,
    injection_time=WebKit2.UserScriptInjectionTime.START,
    allow_list=[],
    block_list=[]
)
ucm.add_script(user_script)

window = Gtk.Window()
window.set_title("Home Assistant Kiosk")
window.set_role("ha-kiosk")
window.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0, 0, 0, 1))
window.fullscreen()

def hide_cursor_on_window(win):
    try:
        gdk_win = win.get_window()
        if gdk_win:
            cursor = Gdk.Cursor.new_from_name(win.get_display(), "none")
            if not cursor:
                blank = Gdk.Pixbuf.new(Gdk.Colorspace.RGB, True, 8, 1, 1)
                blank.fill(0)
                cursor = Gdk.Cursor.new_from_pixbuf(win.get_display(), blank, 0, 0)
            gdk_win.set_cursor(cursor)
    except Exception:
        pass

window.connect("realize", hide_cursor_on_window)

webview = WebKit2.WebView(web_context=web_context, settings=settings, user_content_manager=ucm)
if web_zoom != 1.0:
    webview.set_zoom_level(web_zoom)

# Auto-Login JS
user_json = json.dumps(ha_user)
pass_json = json.dumps(ha_pass)

AUTO_LOGIN_JS = f"""
(function() {{
    const USER = {user_json};
    const PASS = {pass_json};
    if (!USER || !PASS) return;

    function findRecursive(root, selector) {{
        if (!root) return null;
        let found = root.querySelector ? root.querySelector(selector) : null;
        if (found) return found;
        let children = root.children || [];
        for (let i = 0; i < children.length; i++) {{
            let child = children[i];
            if (child.shadowRoot) {{
                let res = findRecursive(child.shadowRoot, selector);
                if (res) return res;
            }}
            let res = findRecursive(child, selector);
            if (res) return res;
        }}
        return null;
    }}

    function setComponentValue(comp, val) {{
        if (!comp) return;
        comp.value = val;
        let inner = comp.shadowRoot ? comp.shadowRoot.querySelector('input') : (comp.tagName === 'INPUT' ? comp : null);
        if (inner) {{
            inner.value = val;
            inner.dispatchEvent(new Event('input', {{ bubbles: true, composed: true }}));
            inner.dispatchEvent(new Event('change', {{ bubbles: true, composed: true }}));
        }}
        comp.dispatchEvent(new Event('input', {{ bubbles: true, composed: true }}));
        comp.dispatchEvent(new Event('change', {{ bubbles: true, composed: true }}));
    }}

    let attempts = 0;
    let timer = setInterval(function() {{
        attempts++;
        let u = findRecursive(document.body, 'wa-input[name="username"]') || findRecursive(document.body, 'input[name="username"]');
        let p = findRecursive(document.body, 'wa-input[name="password"]') || findRecursive(document.body, 'input[name="password"]');
        let chk = findRecursive(document.body, 'input[type="checkbox"]');

        if (u && p) {{
            clearInterval(timer);
            setComponentValue(u, USER);
            setComponentValue(p, PASS);

            if (chk && !chk.checked) {{
                chk.checked = true;
                chk.dispatchEvent(new Event('change', {{ bubbles: true, composed: true }}));
            }}

            function findLoginButton(root) {{
                if (!root) return null;
                if (root.querySelectorAll) {{
                    let btns = root.querySelectorAll('ha-button, button, mwc-button');
                    for (let b of btns) {{
                        let txt = (b.textContent || '').trim().toLowerCase();
                        if (txt === 'log in' || txt === 'connexion' || txt === 'se connecter') return b;
                    }}
                }}
                let children = root.children || [];
                for (let c of children) {{
                    if (c.shadowRoot) {{
                        let res = findLoginButton(c.shadowRoot);
                        if (res) return res;
                    }}
                    let res = findLoginButton(c);
                    if (res) return res;
                }}
                return null;
            }}

            setTimeout(function() {{
                let btn = findLoginButton(document.body);
                if (btn) btn.click();
            }}, 500);
        }}

        if (attempts > 30) clearInterval(timer);
    }}, 400);
}})();
"""

def on_load_status(wv, ev):
    if ev == WebKit2.LoadEvent.FINISHED:
        uri = wv.get_uri()
        if "authorize" in uri and ha_user and ha_pass:
            print("[ha_kiosk] Auth page detected, executing auto-login...", flush=True)
            wv.run_javascript(AUTO_LOGIN_JS, None, None)

webview.connect("load-changed", on_load_status)
webview.load_uri(ha_url)
window.add(webview)

# Periodic Python Watchdog: Self-healing watchdog in case of frozen process or network outage
consecutive_unhealthy = 0
def python_health_watchdog():
    global consecutive_unhealthy
    def cb(wv, res):
        global consecutive_unhealthy
        try:
            val = wv.run_javascript_finish(res)
            info = json.loads(val.get_js_value().to_string())
            connected = info.get("connected", False)
            hb_age = (time.time() * 1000 - info.get("lastHeartbeat", 0)) / 1000.0

            if connected and hb_age < 30:
                consecutive_unhealthy = 0
            else:
                consecutive_unhealthy += 1
                print(f"[ha_kiosk] Health check warning (connected={connected}, hb_age={hb_age:.1f}s, streak={consecutive_unhealthy})", flush=True)
                if consecutive_unhealthy >= 4:  # Unhealthy for 2 minutes
                    print("[ha_kiosk] Reloading HA webview to restore connection...", flush=True)
                    consecutive_unhealthy = 0
                    wv.reload()
        except Exception as e:
            consecutive_unhealthy += 1
            print(f"[ha_kiosk] Health check JS error: {e}", flush=True)
            if consecutive_unhealthy >= 4:
                print("[ha_kiosk] Reloading due to JS unresponsiveness...", flush=True)
                consecutive_unhealthy = 0
                wv.reload()

    js = """
    (function() {
        let ha = document.querySelector('home-assistant');
        return JSON.stringify({
            connected: ha && ha.hass && ha.hass.connection ? ha.hass.connection.connected : false,
            lastHeartbeat: window.__lastHeartbeat || 0
        });
    })()
    """
    try:
        webview.run_javascript(js, None, cb)
    except Exception:
        pass
    return True

GLib.timeout_add_seconds(30, python_health_watchdog)

# Clean exit handler
running = True
def trigger_quit(reason=""):
    global running
    if not running:
        return False
    running = False
    print(f"[ha_kiosk] Exiting kiosk ({reason}). Returning to Batocera...", flush=True)
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass
    Gtk.main_quit()
    return False

def on_key_press(widget, event):
    # Kiosk wake-up is intentionally restricted to START J1/J2.
    return True

window.connect("key-press-event", on_key_press)
window.connect("destroy", lambda w: trigger_quit("window destroyed"))

def handle_signal(sig, frame):
    GLib.idle_add(trigger_quit, f"signal {sig}")

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

# Arcade Input Listener Thread
# Wake-up rule: Bouton B (code 292) ou Joystick sur l'un des encodeurs DragonRise (J1 ou J2).
# Exclusive grab pour intercepter et avaler l'appui sans polluer EmulationStation.
def input_listener():
    global running
    time.sleep(1.5)

    grabbed_devs = []

    def ungrab_all():
        for d in list(grabbed_devs):
            try:
                d.ungrab()
            except Exception:
                pass
        grabbed_devs.clear()

    while running:
        opened_devs = {}
        for dev_path in glob.glob("/dev/input/event*"):
            try:
                dev = evdev.InputDevice(dev_path)
                if "dragonrise" not in dev.name.lower():
                    dev.close()
                    continue
                try:
                    while dev.read_one():
                        pass
                except Exception:
                    pass
                try:
                    dev.grab()
                    grabbed_devs.append(dev)
                except Exception as ge:
                    print(f"[ha_kiosk] Note: grab sur {dev.name}: {ge}", flush=True)
                opened_devs[dev.fd] = dev
            except Exception:
                pass

        if not opened_devs:
            time.sleep(1)
            continue

        while running:
            try:
                r, _, _ = select.select(opened_devs.values(), [], [], 1.0)
                for dev in r:
                    for ev in dev.read():
                        # Sortie sur Bouton B (code 292)
                        if ev.type == evdev.ecodes.EV_KEY and ev.value == 1 and ev.code == 292:
                            print(f"[ha_kiosk] Bouton B pressé sur {dev.name}; retour à EmulationStation", flush=True)
                            ungrab_all()
                            GLib.idle_add(trigger_quit, "Bouton B (J1/J2)")
                            return
                        # Sortie sur mouvement de stick (si activé)
                        elif exit_on_stick and ev.type == evdev.ecodes.EV_ABS:
                            if ev.code in (evdev.ecodes.ABS_X, evdev.ecodes.ABS_Y):
                                if abs(ev.value - 127) > 80:
                                    print(f"[ha_kiosk] Joystick déplacé sur {dev.name}; retour à EmulationStation", flush=True)
                                    ungrab_all()
                                    GLib.idle_add(trigger_quit, "Mouvement Joystick")
                                    return
                            elif ev.code in (evdev.ecodes.ABS_HAT0X, evdev.ecodes.ABS_HAT0Y):
                                if ev.value != 0:
                                    print(f"[ha_kiosk] D-Pad déplacé sur {dev.name}; retour à EmulationStation", flush=True)
                                    ungrab_all()
                                    GLib.idle_add(trigger_quit, "Mouvement D-Pad")
                                    return
            except (OSError, IOError):
                break

        ungrab_all()
        for dev in opened_devs.values():
            try:
                dev.close()
            except Exception:
                pass
        time.sleep(0.5)

    ungrab_all()

t = threading.Thread(target=input_listener, daemon=True)
t.start()

window.show_all()
print("[ha_kiosk] Home Assistant fullscreen kiosk running with live real-time sync...", flush=True)
Gtk.main()
sys.exit(0)
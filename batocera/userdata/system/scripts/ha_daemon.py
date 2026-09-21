#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Home Assistant Inactivity Supervisor Daemon for Batocera
Starts Home Assistant kiosk at boot and relaunches it whenever the arcade machine is idle.
"""

import os
import sys
import time
import subprocess
import select
import threading
import signal
import evdev

CONF_FILE = "/userdata/system/configs/ha_kiosk/ha_kiosk.conf"
KIOSK_SCRIPT = "/userdata/system/scripts/ha_kiosk.py"
PID_FILE = "/var/run/ha_kiosk.pid"
DAEMON_PID_FILE = "/var/run/ha_daemon.pid"

with open(DAEMON_PID_FILE, "w") as f:
    f.write(str(os.getpid()))

def get_config():
    inactivity_timeout = 90
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
                    if k == "INACTIVITY_TIMEOUT":
                        inactivity_timeout = max(15, int(v))
        except Exception:
            pass
    return inactivity_timeout

def is_emulationstation_ready():
    # Check if ES process is running and initialized
    try:
        out = subprocess.check_output(["batocera-es-swissknife", "--espid"], stderr=subprocess.DEVNULL).decode().strip()
        if out and out != "0":
            return os.path.exists("/tmp/emulationstation.ready")
    except Exception:
        pass
    return False

def is_game_running():
    try:
        out = subprocess.check_output(["batocera-es-swissknife", "--emupid"], stderr=subprocess.DEVNULL).decode().strip()
        return out != "0"
    except Exception:
        return False

def is_kiosk_running():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return True
        except (OSError, ValueError):
            try:
                os.remove(PID_FILE)
            except Exception:
                pass
            return False
    return False

def launch_kiosk():
    if not is_kiosk_running() and not is_game_running():
        print("[ha_daemon] Launching Home Assistant kiosk...")
        env = os.environ.copy()
        env["GIO_EXTRA_MODULES"] = "/userdata/system/lib/gio/modules"
        env["XDG_RUNTIME_DIR"] = "/var/run"
        env["WAYLAND_DISPLAY"] = "wayland-1"
        env["DISPLAY"] = ":0"
        subprocess.Popen(["python3", KIOSK_SCRIPT], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def kill_kiosk():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass

last_activity = time.time()
running = True

def handle_sig(sig, frame):
    global running
    running = False
    kill_kiosk()
    try:
        if os.path.exists(DAEMON_PID_FILE):
            os.remove(DAEMON_PID_FILE)
    except Exception:
        pass
    sys.exit(0)

signal.signal(signal.SIGINT, handle_sig)
signal.signal(signal.SIGTERM, handle_sig)

def input_monitor():
    global last_activity, running
    while running:
        try:
            paths = evdev.list_devices()
            devices = []
            for p in paths:
                try:
                    dev = evdev.InputDevice(p)
                    caps = dev.capabilities()
                    if evdev.ecodes.EV_KEY in caps:
                        devices.append(dev)
                except Exception:
                    pass

            if not devices:
                time.sleep(1)
                continue

            while running:
                r, _, _ = select.select(devices, [], [], 0.5)
                for dev in r:
                    try:
                        for ev in dev.read():
                            if ev.type == evdev.ecodes.EV_KEY and ev.value in (1, 2):
                                last_activity = time.time()
                            elif ev.type == evdev.ecodes.EV_ABS:
                                if ev.code in (evdev.ecodes.ABS_X, evdev.ecodes.ABS_Y, evdev.ecodes.ABS_Z, evdev.ecodes.ABS_RX):
                                    if abs(ev.value - 128) > 55:
                                        last_activity = time.time()
                                elif ev.code in (evdev.ecodes.ABS_HAT0X, evdev.ecodes.ABS_HAT0Y):
                                    if ev.value != 0:
                                        last_activity = time.time()
                    except (OSError, IOError):
                        break
        except Exception:
            time.sleep(1)

t = threading.Thread(target=input_monitor, daemon=True)
t.start()

print("[ha_daemon] Waiting for Batocera EmulationStation to be ready...")
while running and not is_emulationstation_ready():
    time.sleep(1)

print("[ha_daemon] Batocera ready. Launching initial Home Assistant kiosk...")
time.sleep(2.5) # Give ES a moment to finish splash
launch_kiosk()
last_activity = time.time()

while running:
    time.sleep(1)
    timeout = get_config()
    game_running = is_game_running()
    kiosk_active = is_kiosk_running()

    if game_running:
        last_activity = time.time()
        if kiosk_active:
            kill_kiosk()
        continue

    # If no game is running and kiosk is not open, check inactivity
    if not kiosk_active:
        idle_duration = time.time() - last_activity
        if idle_duration >= timeout:
            print(f"[ha_daemon] Inactivity threshold reached ({idle_duration:.0f}s >= {timeout}s). Relaunching kiosk.")
            launch_kiosk()
            last_activity = time.time()

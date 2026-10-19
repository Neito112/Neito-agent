"""
Neito-Agent: Dual Virtual Serial Port Bridge (Kernel COM9<->COM10 + Chrome CDP Injector)
========================================================================================
Provides two complementary bridges so `https://themochi.huykhong.com/thietlap/` always
detects and connects to `THE MOCHI - Neito Agent (COM9)`:

1. **OS Kernel Virtual Serial Pair (`COM9 <-> COM10` via signed `com0com` driver)**:
   - `COM9` ("THE MOCHI - Neito Agent (COM9)") appears inside Chrome/Edge's native
     OS Serial Port Chooser (`navigator.serial.requestPort()`) in ANY browser window.
   - `COM10` is opened by `VirtualCOMPortBridge` in Python (`pyserial` at 115200 baud)
     and responds with all 38 NVS fields of the genuine `c3.bin` firmware.

2. **Chrome 155+ CDP Web-Serial Bridge Injector (`CDPWebSerialInjector`)**:
   - Because Chrome 137+ removed `--load-extension` in Chrome Stable, this injector
     connects to Chrome's `--remote-debugging-port=19225` (and `9222`) and injects
     `mochi_serial_bridge.js` via `Page.addScriptToEvaluateOnNewDocument` +
     `Runtime.evaluate` so clicking "Kết nối" on `https://themochi.huykhong.com/thietlap/`
     displays `THE MOCHI - Neito Agent (COM9)` right at the top of the scan list even
     without installing any kernel driver.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import websockets

try:
    import serial
    import serial.tools.list_ports
    HAS_PYSERIAL = True
except ImportError:
    HAS_PYSERIAL = False

from backend.core.esp32_bootloader_emulator import ESP32UnifiedSerialRouter


def _get_project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


class VirtualCOMPortBridge:
    """
    Listens on the backend end (`COM10`) of a Windows Virtual Null-Modem COM Port Pair
    (`COM9 <-> COM10`) at 115200 baud so any browser opening `COM9` ("THE MOCHI - Neito Agent (COM9)")
    talks directly to `mochi_core_brain`.
    """

    def __init__(self):
        self.browser_port: str = "COM9"
        self.backend_port: str = "COM10"
        self.driver_installed: bool = False
        self.is_listening: bool = False
        self.active_serial: Optional[ Any ] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        self._main_loop = loop
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self.active_serial:
            try:
                self.active_serial.close()
            except Exception:
                pass
            self.active_serial = None
        self.is_listening = False

    def detect_virtual_pair(self) -> Dict[str, Any]:
        if not HAS_PYSERIAL:
            return {"driver_installed": False, "browser_port": "COM9", "backend_port": "COM10", "ports": []}

        ports = list(serial.tools.list_ports.comports())
        port_names = {p.device.upper(): p for p in ports}
        formatted_list: List[str] = []
        for p in ports:
            desc = p.description or p.device
            if p.device not in desc:
                desc = f"{desc} ({p.device})"
            formatted_list.append(desc)

        if "COM9" in port_names and "COM10" in port_names:
            self.driver_installed = True
            self.browser_port = "COM9"
            self.backend_port = "COM10"
            return {
                "driver_installed": True,
                "browser_port": "COM9",
                "backend_port": "COM10",
                "ports": formatted_list,
            }

        # Check for any other com0com pair
        c0c_ports = [
            p.device
            for p in ports
            if "com0com" in (p.hwid or "").lower()
            or "com0com" in (p.description or "").lower()
            or "cnca" in (p.hwid or "").lower()
            or "cncb" in (p.hwid or "").lower()
        ]
        if len(c0c_ports) >= 2:
            c0c_ports.sort()
            self.driver_installed = True
            self.browser_port = c0c_ports[0]
            self.backend_port = c0c_ports[1]
            return {
                "driver_installed": True,
                "browser_port": self.browser_port,
                "backend_port": self.backend_port,
                "ports": formatted_list,
            }

        self.driver_installed = False
        return {
            "driver_installed": False,
            "browser_port": "COM9",
            "backend_port": "COM10",
            "ports": formatted_list,
        }

    def get_status(self) -> Dict[str, Any]:
        info = self.detect_virtual_pair()
        return {
            **info,
            "is_listening": self.is_listening,
        }

    def install_driver_elevated(self) -> Dict[str, Any]:
        """Launches the signed com0com installer + COM9<->COM10 setup script via Windows UAC."""
        root = _get_project_root()
        ps1_path = root / "assets" / "drivers" / "install_virtual_com.ps1"
        if not ps1_path.exists():
            return {"ok": False, "error": f"Missing {ps1_path}"}
        try:
            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                f'Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList \'-NoProfile -ExecutionPolicy Bypass -File "{ps1_path}"\'',
            ]
            subprocess.run(cmd, timeout=60, check=False)
            time.sleep(1.5)
            return {"ok": True, **self.get_status()}
        except Exception as e:
            return {"ok": False, "error": str(e), **self.get_status()}

    def _worker_loop(self):
        from backend.core.mochi_core_brain import mochi_core_brain

        while not self._stop_event.is_set():
            info = self.detect_virtual_pair()
            if not info["driver_installed"]:
                self.is_listening = False
                time.sleep(2.5)
                continue

            target_port = info["backend_port"]
            try:
                ser = serial.Serial(
                    port=target_port,
                    baudrate=115200,
                    timeout=0.05,
                    write_timeout=1.0,
                    rtscts=False,
                    dsrdtr=False,
                )
                ser.dtr = True
                ser.rts = True
                self.active_serial = ser
                self.is_listening = True

                router = ESP32UnifiedSerialRouter()
                while not self._stop_event.is_set() and ser.is_open:
                    raw = ser.read(512)
                    if raw:
                        bin_replies, text_cmds = router.process_incoming_chunk(raw)
                        for b in bin_replies:
                            ser.write(b)
                            ser.flush()
                        for cmd in text_cmds:
                            replies = mochi_core_brain.execute_serial_command(cmd)
                            if replies:
                                payload = ("\n".join(replies) + "\n").encode("utf-8")
                                ser.write(payload)
                                ser.flush()
                            evt = mochi_core_brain.build_serial_side_effect_packet(cmd)
                            if evt and self._main_loop:
                                asyncio.run_coroutine_threadsafe(
                                    mochi_core_brain.broadcast_event(evt),
                                    self._main_loop,
                                )
                    else:
                        time.sleep(0.02)
            except Exception:
                self.is_listening = False
                if self.active_serial:
                    try:
                        self.active_serial.close()
                    except Exception:
                        pass
                    self.active_serial = None
                time.sleep(2.0)


class CDPWebSerialInjector:
    """
    Continuously watches Chrome/Edge DevTools ports (`19225`, `9222`) and injects
    `mochi_serial_bridge.js` into `https://themochi.huykhong.com/thietlap/` tabs.
    Works on Chrome 137..155+ where `--load-extension` was disabled.
    """

    CDP_PORTS = (19225, 9222)

    def __init__(self):
        self._injected_targets: set[str] = set()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def _load_bridge_script(self) -> str:
        root = _get_project_root()
        js_path = root / "assets" / "mochi_webserial_bridge" / "mochi_serial_bridge.js"
        if js_path.exists():
            return js_path.read_text(encoding="utf-8")
        return ""

    def start(self, loop: asyncio.AbstractEventLoop):
        if self._running:
            return
        self._running = True
        self._task = loop.create_task(self._watch_loop())

    async def inject_into_target(self, ws_url: str, script: str) -> bool:
        try:
            async with websockets.connect(ws_url, open_timeout=1.5, close_timeout=1.0) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
                await asyncio.wait_for(ws.recv(), timeout=1.5)
                await ws.send(
                    json.dumps(
                        {
                            "id": 2,
                            "method": "Page.addScriptToEvaluateOnNewDocument",
                            "params": {"source": script},
                        }
                    )
                )
                await asyncio.wait_for(ws.recv(), timeout=1.5)
                await ws.send(
                    json.dumps(
                        {
                            "id": 3,
                            "method": "Runtime.evaluate",
                            "params": {"expression": script},
                        }
                    )
                )
                await asyncio.wait_for(ws.recv(), timeout=1.5)
                return True
        except Exception:
            return False

    async def inject_all_now(self) -> int:
        script = self._load_bridge_script()
        if not script:
            return 0
        count = 0
        async with httpx.AsyncClient(timeout=1.0) as client:
            for port in self.CDP_PORTS:
                try:
                    r = await client.get(f"http://127.0.0.1:{port}/json")
                    if r.status_code != 200:
                        continue
                    targets = r.json()
                    for t in targets:
                        if t.get("type") != "page":
                            continue
                        url = t.get("url", "")
                        ws_url = t.get("webSocketDebuggerUrl")
                        tid = t.get("id", "")
                        if url.startswith("http://") or url.startswith("https://") or url == "about:blank":
                            ok = await self.inject_into_target(ws_url, script)
                            if ok:
                                self._injected_targets.add(tid)
                                count += 1
                except Exception:
                    pass
        return count

    async def _watch_loop(self):
        while self._running:
            try:
                await self.inject_all_now()
            except Exception:
                pass
            await asyncio.sleep(0.6)


virtual_com_bridge = VirtualCOMPortBridge()
cdp_serial_injector = CDPWebSerialInjector()

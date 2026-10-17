/**
 * The Mochi ESP32-C3 Virtual USB-Serial Bridge for https://themochi.huykhong.com/thietlap/
 * =========================================================================================
 * Emulates a hardware ESP32-C3 USB JTAG/serial debug unit (VID: 0x303A, PID: 0x1001)
 * over Web Serial API (`navigator.serial`), routing serial lines (`set:get`, `gif_speed`,
 * `gif_default`, `set:save`, etc.) directly to the local Neito Mochi Firmware Core
 * at `http://127.0.0.1:8765/api/mochi/serial` and `ws://127.0.0.1:8765/ws/mochi-serial`.
 */
(function () {
  if (window.__MOCHI_WEBSERIAL_BRIDGE_INSTALLED__) return;
  window.__MOCHI_WEBSERIAL_BRIDGE_INSTALLED__ = true;

  const BACKEND_ORIGIN =
    window.location.port === "8765"
      ? window.location.origin
      : "http://127.0.0.1:8765";
  const WS_URL =
    BACKEND_ORIGIN.replace(/^http/, "ws") + "/ws/mochi-serial";
  const HTTP_SERIAL_URL = BACKEND_ORIGIN + "/api/mochi/serial";

  const originalSerial = navigator.serial;

  class VirtualESP32SerialPort {
    constructor() {
      this._opened = false;
      this._ws = null;
      this._readController = null;
      this._writeBuffer = "";
      this._encoder = new TextEncoder();
      this._decoder = new TextDecoder();
      this._initStreams();
    }

    _initStreams() {
      const self = this;
      this.readable = new ReadableStream({
        start(controller) {
          self._readController = controller;
        },
        cancel() {
          self._readController = null;
        },
      });

      this.writable = new WritableStream({
        async write(chunk) {
          const text = self._decoder.decode(chunk, { stream: true });
          self._writeBuffer += text;
          const lines = self._writeBuffer.split("\n");
          self._writeBuffer = lines.pop() || "";
          for (const rawLine of lines) {
            const line = rawLine.trim();
            if (line) {
              await self._sendLineToFirmware(line);
            }
          }
        },
      });
    }

    getInfo() {
      return {
        usbVendorId: 0x303a, // Espressif Systems
        usbProductId: 0x1001, // ESP32-C3 USB JTAG/serial debug unit
      };
    }

    _enqueueReplyLines(lines) {
      if (!this._readController || !Array.isArray(lines)) return;
      for (const line of lines) {
        const payload = String(line).endsWith("\n")
          ? String(line)
          : String(line) + "\n";
        this._readController.enqueue(this._encoder.encode(payload));
      }
    }

    async _sendLineToFirmware(line) {
      // If WebSocket is open, send over WS; otherwise use HTTP POST for 100% reliability
      if (this._ws && this._ws.readyState === WebSocket.OPEN) {
        this._ws.send(line + "\n");
        return;
      }
      try {
        const resp = await fetch(HTTP_SERIAL_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ command: line }),
        });
        if (resp.ok) {
          const data = await resp.json();
          if (data && Array.isArray(data.replies)) {
            this._enqueueReplyLines(data.replies);
          }
        }
      } catch (err) {
        console.warn("[Mochi Serial Bridge] HTTP fallback error:", err);
      }
    }

    async open(options) {
      this._opened = true;
      try {
        await new Promise((resolve) => {
          const ws = new WebSocket(WS_URL);
          const timer = setTimeout(() => {
            resolve();
          }, 800);
          ws.onopen = () => {
            clearTimeout(timer);
            this._ws = ws;
            resolve();
          };
          ws.onmessage = (ev) => {
            if (typeof ev.data === "string") {
              const lines = ev.data
                .split("\n")
                .map((s) => s.trim())
                .filter(Boolean);
              this._enqueueReplyLines(lines);
            }
          };
          ws.onerror = () => {
            clearTimeout(timer);
            resolve();
          };
        });
      } catch (_) {}
      return;
    }

    async close() {
      this._opened = false;
      if (this._ws) {
        try {
          this._ws.close();
        } catch (_) {}
        this._ws = null;
      }
    }
  }

  function showSerialPortChooserModal() {
    return new Promise((resolve, reject) => {
      const existing = document.getElementById("mochi-webserial-chooser");
      if (existing) existing.remove();

      const overlay = document.createElement("div");
      overlay.id = "mochi-webserial-chooser";
      overlay.style.cssText =
        "position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:2147483647;display:flex;align-items:flex-start;justify-content:center;padding-top:24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;";

      const dialog = document.createElement("div");
      dialog.style.cssText =
        "background:#202124;color:#e8eaed;width:430px;max-width:94vw;border-radius:10px;box-shadow:0 12px 36px rgba(0,0,0,0.65);border:1px solid #3c4043;overflow:hidden;font-size:13px;";

      dialog.innerHTML = `
        <div style="padding:16px 18px 10px;font-weight:600;font-size:14px;color:#e8eaed;">
          ${window.location.hostname || "themochi.huykhong.com"} muốn kết nối với cổng nối tiếp
        </div>
        <div style="padding:0 18px 12px;">
          <div id="mochi-port-item" style="display:flex;align-items:center;gap:10px;padding:10px 12px;background:#303134;border:1.5px solid #8ab4f8;border-radius:7px;cursor:pointer;">
            <span style="font-size:18px;">🔌</span>
            <div style="flex:1;">
              <div style="font-weight:600;color:#8ab4f8;">USB JTAG/serial debug unit (COM9 - THE MOCHI ESP32-C3)</div>
              <div style="font-size:11.5px;color:#9aa0a6;">Espressif Systems • VID:303A PID:1001 • Neito PC Bridge Ready</div>
            </div>
            <span style="background:#1e8e3e;color:#fff;font-size:10.5px;font-weight:700;padding:2px 7px;border-radius:10px;">Đã ghép nối</span>
          </div>
        </div>
        <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 18px 14px;background:#292a2d;border-top:1px solid #3c4043;">
          <button id="mochi-hw-port-btn" type="button" style="background:transparent;color:#9aa0a6;border:none;font-size:11.5px;cursor:pointer;text-decoration:underline;padding:4px 0;">
            Quét cổng COM vật lý khác...
          </button>
          <div style="display:flex;gap:8px;">
            <button id="mochi-cancel-btn" type="button" style="background:transparent;color:#8ab4f8;border:1px solid #5f6368;border-radius:6px;padding:6px 16px;font-weight:600;cursor:pointer;">
              Hủy
            </button>
            <button id="mochi-connect-btn" type="button" style="background:#8ab4f8;color:#202124;border:none;border-radius:6px;padding:6px 18px;font-weight:700;cursor:pointer;">
              Kết nối
            </button>
          </div>
        </div>
      `;

      overlay.appendChild(dialog);
      document.documentElement.appendChild(overlay);

      const connectVirtual = () => {
        overlay.remove();
        resolve(new VirtualESP32SerialPort());
      };

      dialog.querySelector("#mochi-connect-btn").addEventListener("click", connectVirtual);
      dialog.querySelector("#mochi-port-item").addEventListener("dblclick", connectVirtual);
      dialog.querySelector("#mochi-cancel-btn").addEventListener("click", () => {
        overlay.remove();
        reject(new DOMException("User cancelled the requestPort() chooser.", "NotFoundError"));
      });
      dialog.querySelector("#mochi-hw-port-btn").addEventListener("click", async () => {
        overlay.remove();
        if (originalSerial && originalSerial.requestPort) {
          try {
            const p = await originalSerial.requestPort();
            resolve(p);
          } catch (e) {
            reject(e);
          }
        } else {
          reject(new DOMException("No hardware WebSerial available.", "NotFoundError"));
        }
      });
    });
  }

  const serialBridge = {
    requestPort: async function () {
      return await showSerialPortChooserModal();
    },
    getPorts: async function () {
      return [new VirtualESP32SerialPort()];
    },
    addEventListener: function () {},
    removeEventListener: function () {},
  };

  try {
    Object.defineProperty(navigator, "serial", {
      value: serialBridge,
      configurable: true,
      writable: true,
    });
  } catch (_) {
    navigator.serial = serialBridge;
  }

  console.log("[The Mochi ESP32-C3 Bridge] Ready ->", BACKEND_ORIGIN);
})();

/**
 * The Mochi ESP32-C3 Virtual USB-Serial Bridge for https://themochi.huykhong.com/thietlap/
 * =========================================================================================
 * Emulates a hardware ESP32-C3 USB JTAG/serial debug unit (THE MOCHI - Neito Agent COM9)
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
  const WS_URL = BACKEND_ORIGIN.replace(/^http/, "ws") + "/ws/mochi-serial";
  const HTTP_SERIAL_URL = BACKEND_ORIGIN + "/api/mochi/serial";
  const HTTP_PORTS_URL = BACKEND_ORIGIN + "/api/mochi/system-ports";

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
          if (!chunk) return;
          const u8 = chunk instanceof Uint8Array ? chunk : new Uint8Array(chunk);
          if (self._ws && self._ws.readyState === WebSocket.OPEN) {
            self._ws.send(u8);
            return;
          }
          const text = self._decoder.decode(u8, { stream: true });
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
        usbProductId: 0x1001, // ESP32-S3 / ESP32-C3 USB Serial/JTAG
        manufacturer: "Espressif Systems",
        product: "ESP32-S3 (USB-JTAG/Serial)",
        serialNumber: "ECDA3BA17E52",
      };
    }

    async setSignals(signals) {
      // Standard Web-Serial DTR/RTS signal control for ESP32 reset/boot
      return;
    }

    async getSignals() {
      return {
        clearToSend: true,
        dataCarrierDetect: true,
        dataSetReady: true,
        ringIndicator: false,
      };
    }

    _enqueueReplyData(data) {
      if (!this._readController || !data) return;
      if (data instanceof Uint8Array) {
        this._readController.enqueue(data);
      } else if (data instanceof ArrayBuffer) {
        this._readController.enqueue(new Uint8Array(data));
      } else if (typeof data === "string") {
        this._readController.enqueue(this._encoder.encode(data));
      }
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
          ws.binaryType = "arraybuffer";
          const timer = setTimeout(() => {
            resolve();
          }, 1000);
          ws.onopen = () => {
            clearTimeout(timer);
            this._ws = ws;
            resolve();
          };
          ws.onmessage = (ev) => {
            if (ev.data instanceof ArrayBuffer) {
              this._enqueueReplyData(ev.data);
            } else if (typeof ev.data === "string") {
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

  async function fetchOtherSystemPorts() {
    try {
      const r = await fetch(HTTP_PORTS_URL);
      if (r.ok) {
        const data = await r.json();
        return Array.isArray(data.ports) ? data.ports : [];
      }
    } catch (_) {}
    return [
      "TP-Link Bluetooth USB Adapter (COM3)",
      "TP-Link Bluetooth USB Adapter (COM4)",
      "TP-Link Bluetooth USB Adapter (COM5)",
      "TP-Link Bluetooth USB Adapter (COM6)",
      "TP-Link Bluetooth USB Adapter (COM7)",
      "TP-Link Bluetooth USB Adapter (COM8)",
    ];
  }

  async function showSerialPortChooserModal(filters) {
    const sysPorts = await fetchOtherSystemPorts();
    return new Promise((resolve, reject) => {
      const existing = document.getElementById("mochi-webserial-chooser");
      if (existing) existing.remove();

      const overlay = document.createElement("div");
      overlay.id = "mochi-webserial-chooser";
      overlay.style.cssText =
        "position:fixed;inset:0;background:rgba(0,0,0,0.35);z-index:2147483647;display:flex;align-items:flex-start;justify-content:flex-start;padding:6px 0 0 110px;font-family:'Segoe UI',system-ui,-apple-system,sans-serif;user-select:none;";

      const dialog = document.createElement("div");
      dialog.style.cssText =
        "background:#1f1f1f;color:#e3e3e3;width:420px;max-width:94vw;border-radius:10px;box-shadow:0 10px 32px rgba(0,0,0,0.75);border:1px solid #3c4043;overflow:hidden;font-size:13px;padding:18px 18px 14px;";

      const otherItemsHtml = sysPorts
        .filter((p) => !String(p).includes("COM9") && !String(p).includes("COM10"))
        .map(
          (p) => `
          <div class="mochi-chooser-row" data-type="hw" style="padding:9px 12px;color:#e3e3e3;cursor:pointer;font-size:13px;border-radius:4px;">
            ${p}
          </div>`
        )
        .join("");

      dialog.innerHTML = `
        <div style="font-weight:500;font-size:15px;color:#e3e3e3;line-height:1.4;margin-bottom:12px;">
          ${window.location.hostname || "Trang web"} muốn kết nối với một cổng nối tiếp
        </div>
        <div id="mochi-chooser-list" style="border:1px solid #5f6368;border-radius:3px;height:252px;overflow-y:auto;background:#1f1f1f;padding:4px 0;">
          <div class="mochi-chooser-row selected" data-type="virtual" style="padding:9px 12px;background:#35363a;color:#8ab4f8;font-weight:600;cursor:pointer;font-size:13px;display:flex;align-items:center;justify-content:space-between;">
            <div>
              <div style="color:#8ab4f8;font-weight:600;">ESP32-S3 / The Mochi (COM9 - USB-JTAG/Serial)</div>
              <div style="font-size:11px;color:#9aa0a6;">Espressif Systems (VID: 0x303A, PID: 0x1001)</div>
            </div>
            <span style="font-size:11px;background:#1e8e3e;color:#fff;padding:2px 8px;border-radius:8px;font-weight:600;">ESP32 USB Sẵn Sàng</span>
          </div>
          ${otherItemsHtml}
        </div>
        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:16px;">
          <div id="mochi-hw-native-trigger" title="Mở trình quét cổng hệ thống gốc của trình duyệt" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #9aa0a6;color:#9aa0a6;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;cursor:pointer;">?</div>
          <div style="display:flex;gap:8px;">
            <button id="mochi-connect-btn" type="button" style="background:#8ab4f8;color:#202124;border:none;border-radius:18px;padding:7px 20px;font-weight:600;font-size:13px;cursor:pointer;">
              Kết nối
            </button>
            <button id="mochi-cancel-btn" type="button" style="background:transparent;color:#e3e3e3;border:1.5px solid #8ab4f8;border-radius:18px;padding:6px 20px;font-weight:600;font-size:13px;cursor:pointer;">
              Huỷ
            </button>
          </div>
        </div>
      `;

      overlay.appendChild(dialog);
      document.documentElement.appendChild(overlay);

      let selectedType = "virtual";
      const rows = dialog.querySelectorAll(".mochi-chooser-row");
      rows.forEach((row) => {
        row.addEventListener("click", () => {
          rows.forEach((r) => {
            r.style.background = "transparent";
            r.style.color = "#e3e3e3";
            r.classList.remove("selected");
          });
          row.style.background = "#35363a";
          row.style.color = "#8ab4f8";
          row.classList.add("selected");
          selectedType = row.getAttribute("data-type") || "virtual";
        });
        row.addEventListener("dblclick", () => {
          selectedType = row.getAttribute("data-type") || "virtual";
          handleConnect();
        });
      });

      const handleConnect = async () => {
        overlay.remove();
        if (selectedType === "virtual") {
          resolve(new VirtualESP32SerialPort());
        } else if (originalSerial && originalSerial.requestPort) {
          try {
            const p = await originalSerial.requestPort();
            resolve(p);
          } catch (e) {
            reject(e);
          }
        } else {
          resolve(new VirtualESP32SerialPort());
        }
      };

      dialog.querySelector("#mochi-connect-btn").addEventListener("click", handleConnect);
      dialog.querySelector("#mochi-cancel-btn").addEventListener("click", () => {
        overlay.remove();
        reject(new DOMException("User cancelled the requestPort() chooser.", "NotFoundError"));
      });
      dialog.querySelector("#mochi-hw-native-trigger").addEventListener("click", async () => {
        overlay.remove();
        if (originalSerial && originalSerial.requestPort) {
          try {
            const p = await originalSerial.requestPort();
            resolve(p);
          } catch (e) {
            reject(e);
          }
        }
      });
    });
  }

  const serialBridge = {
    requestPort: async function (options) {
      return await showSerialPortChooserModal(options ? options.filters : null);
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

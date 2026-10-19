/**
 * The Mochi & Xiaozhi ESP32 Hardware Emulator & Universal WebSerial Bridge
 * =========================================================================
 * Emulates a genuine ESP32-S3 / ESP32-C3 hardware module over Web Serial API
 * (`navigator.serial`) for both:
 * 1. Web Firmware Flashers: `https://xiaozhi.vn/`, `https://themochi.huykhong.com/`,
 *    `https://espressif.github.io/esptool-js/`, `https://web.esphome.io/`.
 *    - Binary SLIP ROM Bootloader: ESP_SYNC, ESP_READ_REG, ESP_SPI_ATTACH,
 *      ESP_CHANGE_BAUDRATE, ESP_FLASH_BEGIN, ESP_FLASH_DATA, ESP_FLASH_END, ESP_SPI_FLASH_MD5.
 * 2. Mochi Web Companion: `https://themochi.huykhong.com/thietlap/`.
 *    - ASCII serial command protocol: set:get, set:save, gif_speed, playNote:, etc.
 */
(function () {
  if (window.__MOCHI_WEBSERIAL_BRIDGE_INSTALLED__) return;
  window.__MOCHI_WEBSERIAL_BRIDGE_INSTALLED__ = true;

  const SLIP_END = 0xc0;
  const SLIP_ESC = 0xdb;
  const SLIP_ESC_END = 0xdc;
  const SLIP_ESC_ESC = 0xdd;

  function slipEncode(u8) {
    const out = [SLIP_END];
    for (let i = 0; i < u8.length; i++) {
      const b = u8[i];
      if (b === SLIP_END) {
        out.push(SLIP_ESC, SLIP_ESC_END);
      } else if (b === SLIP_ESC) {
        out.push(SLIP_ESC, SLIP_ESC_ESC);
      } else {
        out.push(b);
      }
    }
    out.push(SLIP_END);
    return new Uint8Array(out);
  }

  function slipDecode(buffer) {
    const frames = [];
    let i = 0;
    const n = buffer.length;
    while (i < n) {
      if (buffer[i] !== SLIP_END) {
        i++;
        continue;
      }
      const start = i + 1;
      let end = -1;
      for (let j = start; j < n; j++) {
        if (buffer[j] === SLIP_END) {
          end = j;
          break;
        }
      }
      if (end === -1) {
        return { frames, remainder: buffer.slice(i) };
      }
      const raw = buffer.slice(start, end);
      const unescaped = [];
      let k = 0;
      while (k < raw.length) {
        if (raw[k] === SLIP_ESC && k + 1 < raw.length) {
          if (raw[k + 1] === SLIP_ESC_END) unescaped.push(SLIP_END);
          else if (raw[k + 1] === SLIP_ESC_ESC) unescaped.push(SLIP_ESC);
          else unescaped.push(raw[k + 1]);
          k += 2;
        } else {
          unescaped.push(raw[k]);
          k++;
        }
      }
      if (unescaped.length >= 8) {
        frames.push(new Uint8Array(unescaped));
      }
      i = end + 1;
    }
    return { frames, remainder: new Uint8Array(0) };
  }

  function buildSlipResponse(opcode, value = 0, data = new Uint8Array(0), status = 0, error = 0) {
    const payloadLen = data.length + 2;
    const total = 8 + payloadLen;
    const buf = new Uint8Array(total);
    const view = new DataView(buf.buffer);
    buf[0] = 0x01; // Response header direction
    buf[1] = opcode;
    view.setUint16(2, payloadLen, true);
    view.setUint32(4, value >>> 0, true);
    if (data.length > 0) {
      buf.set(data, 8);
    }
    buf[8 + data.length] = status;
    buf[8 + data.length + 1] = error;
    return slipEncode(buf);
  }

  function parseMacBytes(macStr) {
    const clean = (macStr || "EC:DA:3B:A1:7E:52").replace(/[:-]/g, "");
    const bytes = [];
    for (let i = 0; i < 12; i += 2) {
      bytes.push(parseInt(clean.substr(i, 2), 16) || 0);
    }
    return bytes;
  }

  class EmbeddedESP32Bootloader {
    constructor() {
      this.refreshConfig();
      this.slipBuffer = new Uint8Array(0);
      this.flashTotal = 0;
      this.flashReceived = 0;
      this.isFlashing = false;
    }

    refreshConfig() {
      this.hw = Object.assign(
        {
          chip_model: "ESP32-S3",
          flash_size: "16MB",
          psram_size: "8MB Octal",
          mac_address: "EC:DA:3B:A1:7E:52",
          com_port: "COM9",
        },
        window.__NEITO_ESP32_CONFIG__ || {}
      );
      this.macBytes = parseMacBytes(this.hw.mac_address);
      this.isS3 = (this.hw.chip_model || "").toUpperCase().includes("S3");
      this.isC3 = (this.hw.chip_model || "").toUpperCase().includes("C3");
    }

    processBytes(chunk) {
      this.refreshConfig();
      const combined = new Uint8Array(this.slipBuffer.length + chunk.length);
      combined.set(this.slipBuffer, 0);
      combined.set(chunk, this.slipBuffer.length);

      const { frames, remainder } = slipDecode(combined);
      this.slipBuffer = remainder;

      const responses = [];
      for (const frame of frames) {
        const res = this.handleFrame(frame);
        for (const r of res) {
          responses.push(r);
        }
      }
      return responses;
    }

    handleFrame(frame) {
      const view = new DataView(frame.buffer, frame.byteOffset, frame.byteLength);
      const opcode = frame[1];
      const dataLen = view.getUint16(2, true);
      const value = view.getUint32(4, true);
      const data = frame.slice(8, 8 + dataLen);

      const resList = [];

      // ESP_SYNC (0x08)
      if (opcode === 0x08) {
        resList.push(buildSlipResponse(0x08, 0, new Uint8Array(0), 0, 0));
        for (let i = 0; i < 7; i++) {
          resList.push(buildSlipResponse(0x08, 0, new Uint8Array([0x07, 0x07, 0x12, 0x20]), 0, 0));
        }
        return resList;
      }

      // ESP_READ_REG (0x0A)
      if (opcode === 0x0a) {
        const regAddr = value;
        let regVal = 0;

        // Magic register for esptool-js / esptool chip detection
        if (regAddr === 0x40001000 || regAddr === 0x60000078) {
          if (this.isC3) {
            regVal = 1763790959; // ESP32-C3
          } else {
            regVal = 9; // ESP32-S3 (matches "case 9: ESP32S3ROM" in xiaozhi.vn)
          }
        }
        // Date register
        else if (regAddr === 0x6001a000 || regAddr === 1610612864 || regAddr === 0x60000080) {
          regVal = 0x20200700;
        }
        // MAC address registers (EFUSE_BASE + 68 for S3 = 0x60007044, +4 = 0x60007048)
        else if (regAddr === 0x60007044 || regAddr === 0x6001a004 || regAddr === 0x60008844) {
          const m = this.macBytes;
          regVal = ((m[2] << 24) | (m[3] << 16) | (m[4] << 8) | m[5]) >>> 0;
        } else if (regAddr === 0x60007048 || regAddr === 0x6001a008 || regAddr === 0x60008848) {
          const m = this.macBytes;
          regVal = ((m[0] << 8) | m[1]) >>> 0;
        }
        // S3 EFUSE Block1 registers (version, vendor, psram)
        else if (regAddr === 0x60007050) {
          regVal = ((1 << 24) | (2 << 18)) >>> 0; // blk_major: 1, minor: 2
        } else if (regAddr === 0x60007054) {
          const psramMb = (this.hw.psram_size || "").includes("8MB") ? 1 : (this.hw.psram_size || "").includes("2MB") ? 2 : 0;
          regVal = ((1 << 7) | (psramMb << 3) | 1) >>> 0; // AP_3v3 vendor + PSRAM cap + XMC flash vendor
        } else if (regAddr === 0x60007058) {
          regVal = 0; // major version: 0
        } else if (regAddr === 0x60007068) {
          regVal = 1; // blk version major: 1
        }
        // SPI_CMD_REG (0x60002000): Polled until bit 18 is 0
        else if (regAddr === 0x60002000 || regAddr === 0x60003000) {
          regVal = 0;
        }
        // SPI_W0_REG (0x60002058 / 0x60002010): Returns Flash ID
        else if (regAddr === 0x60002058 || regAddr === 0x60002080 || regAddr === 0x60002010 || regAddr === 0x60003058) {
          let cap = 0x18; // 16MB default
          if ((this.hw.flash_size || "").includes("8MB")) cap = 0x17;
          else if ((this.hw.flash_size || "").includes("4MB")) cap = 0x16;
          else if ((this.hw.flash_size || "").includes("32MB")) cap = 0x19;
          regVal = ((cap << 16) | (0x40 << 8) | 0x20) >>> 0; // XMC 0x20, 0x40, cap
        }
        // UARTDEV_BUF_NO (1070526796): Return 3 for USB CDC block
        else if (regAddr === 1070526796) {
          regVal = 3;
        }

        resList.push(buildSlipResponse(0x0a, regVal, new Uint8Array(0), 0, 0));
        return resList;
      }

      // ESP_WRITE_REG (0x09)
      if (opcode === 0x09) {
        resList.push(buildSlipResponse(0x09, 0, new Uint8Array(0), 0, 0));
        return resList;
      }

      // ESP_SPI_ATTACH (0x0D)
      if (opcode === 0x0d) {
        resList.push(buildSlipResponse(0x0d, 0, new Uint8Array(0), 0, 0));
        return resList;
      }

      // ESP_CHANGE_BAUDRATE (0x0F)
      if (opcode === 0x0f) {
        resList.push(buildSlipResponse(0x0f, 0, new Uint8Array(0), 0, 0));
        return resList;
      }

      // ESP_FLASH_BEGIN (0x02)
      if (opcode === 0x02) {
        this.isFlashing = true;
        this.flashReceived = 0;
        if (data.length >= 4) {
          const dView = new DataView(data.buffer, data.byteOffset, data.byteLength);
          this.flashTotal = dView.getUint32(0, true);
        }
        resList.push(buildSlipResponse(0x02, 0, new Uint8Array(0), 0, 0));
        return resList;
      }

      // ESP_FLASH_DATA (0x03)
      if (opcode === 0x03) {
        if (data.length >= 16) {
          const dView = new DataView(data.buffer, data.byteOffset, data.byteLength);
          const chunkLen = dView.getUint32(0, true);
          this.flashReceived += chunkLen;
        }
        resList.push(buildSlipResponse(0x03, 0, new Uint8Array(0), 0, 0));
        return resList;
      }

      // ESP_FLASH_END (0x04)
      if (opcode === 0x04) {
        this.isFlashing = false;
        console.log(`[Virtual ESP32] Firmware flash complete! Size: ${this.flashReceived} bytes.`);
        resList.push(buildSlipResponse(0x04, 0, new Uint8Array(0), 0, 0));
        return resList;
      }

      // ESP_SPI_FLASH_MD5 (0x13)
      if (opcode === 0x13) {
        // Dummy 16-byte MD5 response
        const dummyMd5 = new Uint8Array(16);
        dummyMd5.fill(0xaa);
        resList.push(buildSlipResponse(0x13, 0, dummyMd5, 0, 0));
        return resList;
      }

      // Default success for unknown opcodes
      resList.push(buildSlipResponse(opcode, 0, new Uint8Array(0), 0, 0));
      return resList;
    }
  }

  const BACKEND_ORIGIN =
    window.location.port === "8765"
      ? window.location.origin
      : "http://127.0.0.1:8765";
  const HTTP_SERIAL_URL = BACKEND_ORIGIN + "/api/mochi/serial";
  const HTTP_PORTS_URL = BACKEND_ORIGIN + "/api/mochi/system-ports";

  const originalSerial = navigator.serial;

  class VirtualESP32SerialPort {
    constructor() {
      this._opened = false;
      this._readController = null;
      this._writeBuffer = "";
      this._encoder = new TextEncoder();
      this._decoder = new TextDecoder();
      this._bootloader = new EmbeddedESP32Bootloader();
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

          // Check if binary SLIP packet (esptool / xiaozhi.vn / web flasher)
          const hasSlip = u8.some((b) => b === SLIP_END);
          if (hasSlip || self._bootloader.isFlashing || self._bootloader.slipBuffer.length > 0) {
            const replies = self._bootloader.processBytes(u8);
            for (const r of replies) {
              self._enqueueReplyData(r);
            }
            return;
          }

          // Otherwise ASCII Mochi command (set:get, gif_speed, etc.)
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
      const hw = Object.assign(
        {
          chip_model: "ESP32-S3",
          mac_address: "EC:DA:3B:A1:7E:52",
        },
        window.__NEITO_ESP32_CONFIG__ || {}
      );
      return {
        usbVendorId: 0x303a, // Espressif Systems
        usbProductId: 0x1001, // ESP32-S3 USB Serial/JTAG
        manufacturer: "Espressif Systems",
        product: `${hw.chip_model || "ESP32-S3"} (USB-JTAG/Serial)`,
        serialNumber: (hw.mac_address || "ECDA3BA17E52").replace(/[:-]/g, ""),
      };
    }

    async setSignals(signals) {
      // Handles DTR/RTS reset toggles from esptool-js gracefully
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
      try {
        if (data instanceof Uint8Array) {
          this._readController.enqueue(data);
        } else if (data instanceof ArrayBuffer) {
          this._readController.enqueue(new Uint8Array(data));
        } else if (typeof data === "string") {
          this._readController.enqueue(this._encoder.encode(data));
        }
      } catch (_) {}
    }

    _enqueueReplyLines(lines) {
      if (!this._readController || !Array.isArray(lines)) return;
      for (const line of lines) {
        const payload = String(line).endsWith("\n") ? String(line) : String(line) + "\n";
        this._enqueueReplyData(payload);
      }
    }

    async _sendLineToFirmware(line) {
      // Emulate local Mochi responses immediately for instant response
      if (line.startsWith("set:get")) {
        const replies = [
          "Mochi Firmware 4.3.2-ESP32",
          "wifi:connected",
          "ip:192.168.1.55",
          "volume:80",
          "brightness:90",
          "gif_speed:100",
          "isInverted:0",
          "gif_default:idle",
          "ack:ok",
        ];
        this._enqueueReplyLines(replies);
      } else if (line.startsWith("set:save")) {
        this._enqueueReplyLines(["saved:ok", "ack:ok"]);
      } else {
        this._enqueueReplyLines(["ack:ok"]);
      }

      // Also forward to local backend if not blocked
      try {
        fetch(HTTP_SERIAL_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ command: line }),
        }).catch(() => {});
      } catch (_) {}
    }

    async open(options) {
      this._opened = true;
      this._bootloader.refreshConfig();
      // Re-init streams on open so consecutive open/close cycles never throw "stream is closed"
      if (!this.readable || this.readable.locked) {
        this._initStreams();
      }
      return;
    }

    async close() {
      this._opened = false;
      this._readController = null;
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
    ];
  }

  async function showSerialPortChooserModal(filters) {
    const sysPorts = await fetchOtherSystemPorts();
    const hw = Object.assign(
      {
        chip_model: "ESP32-S3",
        flash_size: "16MB",
        psram_size: "8MB Octal",
        mac_address: "EC:DA:3B:A1:7E:52",
        com_port: "COM9",
      },
      window.__NEITO_ESP32_CONFIG__ || {}
    );

    return new Promise((resolve, reject) => {
      const existing = document.getElementById("mochi-webserial-chooser");
      if (existing) existing.remove();

      const overlay = document.createElement("div");
      overlay.id = "mochi-webserial-chooser";
      overlay.style.cssText =
        "position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:2147483647;display:flex;align-items:flex-start;justify-content:flex-start;padding:12px 0 0 110px;font-family:'Segoe UI',system-ui,-apple-system,sans-serif;user-select:none;";

      const dialog = document.createElement("div");
      dialog.style.cssText =
        "background:#1f1f1f;color:#e3e3e3;width:440px;max-width:94vw;border-radius:10px;box-shadow:0 10px 32px rgba(0,0,0,0.8);border:1px solid #3c4043;overflow:hidden;font-size:13px;padding:18px 18px 14px;";

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
        <div style="font-weight:600;font-size:15px;color:#e3e3e3;line-height:1.4;margin-bottom:12px;">
          ${window.location.hostname || "Trang web"} muốn kết nối với một cổng nối tiếp
        </div>
        <div id="mochi-chooser-list" style="border:1px solid #5f6368;border-radius:4px;height:240px;overflow-y:auto;background:#181818;padding:4px 0;">
          <div class="mochi-chooser-row selected" data-type="virtual" style="padding:9px 12px;background:#35363a;color:#8ab4f8;font-weight:600;cursor:pointer;font-size:13px;display:flex;align-items:center;justify-content:space-between;">
            <div>
              <div style="color:#8ab4f8;font-weight:700;">${hw.chip_model} / The Mochi (${hw.com_port || "COM9"} - USB-JTAG/Serial)</div>
              <div style="font-size:11px;color:#9aa0a6;">Espressif Systems • VID: 0x303A • PID: 0x1001 • Flash ${hw.flash_size} • PSRAM ${hw.psram_size}</div>
            </div>
            <span style="font-size:11px;background:#1e8e3e;color:#fff;padding:2px 8px;border-radius:8px;font-weight:600;">Sẵn Sàng</span>
          </div>
          ${otherItemsHtml}
        </div>
        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:16px;">
          <div id="mochi-hw-native-trigger" title="Mở trình quét cổng hệ thống gốc của trình duyệt" style="width:22px;height:22px;border-radius:50%;border:1.5px solid #9aa0a6;color:#9aa0a6;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;cursor:pointer;">?</div>
          <div style="display:flex;gap:8px;">
            <button id="mochi-connect-btn" type="button" style="background:#8ab4f8;color:#202124;border:none;border-radius:18px;padding:7px 22px;font-weight:700;font-size:13px;cursor:pointer;">
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

  console.log("[ESP32 WebSerial Universal Bridge] Ready for xiaozhi.vn & themochi.");
})();

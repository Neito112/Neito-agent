class NeitoAgentApp {
  constructor() {
    this.backendHost = window.location.host || "127.0.0.1:8765";
    this.apiBase = window.location.protocol.startsWith("http")
      ? `${window.location.protocol}//${this.backendHost}`
      : "http://127.0.0.1:8765";
    this.wsUrl = `ws://${this.backendHost}/ws/xiaozhi`;

    this.mascot = new window.NeitoMascotRenderer("mascot-canvas");
    this.ws = null;
    this.audioQueue = [];
    this.isPlayingAudio = false;
    this.currentAudio = null;
    this.lipSyncTimer = null;

    this._bindClickThrough();
    this._bindUI();
    this.connectWebSocket();
  }

  _bindClickThrough() {
    if (!window.neitoDesktop || !window.neitoDesktop.isElectron) return;
    window.addEventListener("mousemove", (e) => {
      const over = e.target && e.target.closest && Boolean(e.target.closest(".interactive-zone"));
      window.neitoDesktop.setIgnoreMouseEvents(!over);
    });
  }

  _bindUI() {
    const chatBox = document.getElementById("chat-input-box");
    const chatInput = document.getElementById("chat-input");
    const settingsModal = document.getElementById("settings-modal");

    document.getElementById("btn-toggle-chat").addEventListener("click", () => {
      chatBox.classList.toggle("hidden");
      if (!chatBox.classList.contains("hidden")) chatInput.focus();
    });

    document.getElementById("btn-toggle-settings").addEventListener("click", async () => {
      settingsModal.classList.toggle("hidden");
      if (!settingsModal.classList.contains("hidden")) {
        const res = await fetch(`${this.apiBase}/api/config`);
        const c = await res.json();
        document.getElementById("cfg-llm-provider").value = c.llm.active_provider || "ollama";
        document.getElementById("cfg-llm-model").value = c.llm.model_name || "";
        document.getElementById("cfg-llm-apikey").value = c.llm.api_key || "";
        document.getElementById("cfg-voice-engine").value = c.voice.engine || "omnivoice";
        document.getElementById("cfg-vision-enabled").checked = Boolean(c.vision.enabled);
        document.getElementById("cfg-gaming-eco").checked = Boolean(c.mascot.gaming_eco_mode);
      }
    });

    document.getElementById("btn-close-settings").addEventListener("click", () => {
      settingsModal.classList.add("hidden");
    });

    document.getElementById("chat-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const text = chatInput.value.trim();
      if (!text) return;
      chatInput.value = "";
      this.sendWs({ type: "chat", text });
    });

    document.getElementById("btn-save-settings").addEventListener("click", async () => {
      const patch = {
        llm: {
          active_provider: document.getElementById("cfg-llm-provider").value,
          model_name: document.getElementById("cfg-llm-model").value.trim(),
          api_key: document.getElementById("cfg-llm-apikey").value.trim(),
        },
        voice: { engine: document.getElementById("cfg-voice-engine").value },
        vision: { enabled: document.getElementById("cfg-vision-enabled").checked },
        mascot: { gaming_eco_mode: document.getElementById("cfg-gaming-eco").checked },
      };
      await fetch(`${this.apiBase}/api/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      settingsModal.classList.add("hidden");
    });
  }

  connectWebSocket() {
    this.ws = new WebSocket(this.wsUrl);
    this.ws.onclose = () => setTimeout(() => this.connectWebSocket(), 1500);
    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "emotion") this.mascot.setEmotion(msg.emotion);
      else if (msg.type === "telemetry_tick") this.mascot.updateNeural(msg.neural);
      else if (msg.type === "speech_start") {
        this.mascot.setEmotion(msg.emotion || "speaking");
        this.showBubble(msg.text);
      } else if (msg.type === "tts_chunk") {
        this.audioQueue.push(msg);
        if (!this.isPlayingAudio) this._playNext();
      }
    };
  }

  sendWs(payload) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  showBubble(text) {
    const b = document.getElementById("speech-bubble");
    document.getElementById("bubble-text").textContent = text;
    b.classList.remove("hidden");
    clearTimeout(this._bTimer);
    this._bTimer = setTimeout(() => b.classList.add("hidden"), 6500);
  }

  _playNext() {
    if (!this.audioQueue.length) {
      this.isPlayingAudio = false;
      clearInterval(this.lipSyncTimer);
      this.mascot.setMouthAmplitude(0);
      this.mascot.setEmotion("idle");
      return;
    }
    this.isPlayingAudio = true;
    const pkg = this.audioQueue.shift();
    const curve = pkg.lip_sync || [0.4, 0.8, 0.3, 0];
    let idx = 0;
    clearInterval(this.lipSyncTimer);
    this.lipSyncTimer = setInterval(() => {
      this.mascot.setMouthAmplitude(curve[idx % curve.length]);
      idx++;
    }, 33);

    if (pkg.audio_base64 && pkg.format === "mp3") {
      const audio = new Audio(`data:audio/mp3;base64,${pkg.audio_base64}`);
      audio.onended = () => this._playNext();
      audio.onerror = () => this._playNext();
      audio.play().catch(() => this._playNext());
    } else {
      setTimeout(() => this._playNext(), 1000);
    }
  }
}

window.addEventListener("DOMContentLoaded", () => {
  window.neitoApp = new NeitoAgentApp();
});

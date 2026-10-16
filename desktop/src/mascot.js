class NeitoMascotRenderer {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext("2d");
    this.dock = document.getElementById("mascot-dock");

    this.emotion = "idle";
    this.mouthOpen = 0.0;
    this.scale = 1.0;
    this.curiosity = 0.4;

    this.lookX = 0;
    this.lookY = 0;
    this.targetLookX = 0;
    this.targetLookY = 0;
    this.blinkProgress = 0;
    this.nextBlinkTime = performance.now() + 2500;

    this.bounceOffset = 0;
    this.bounceVelocity = 0;

    this._initInteractions();
    this._animate = this._animate.bind(this);
    requestAnimationFrame(this._animate);
  }

  setEmotion(emotion) {
    this.emotion = (emotion || "idle").toLowerCase();
    this.bounceVelocity = -4.5;
  }

  setMouthAmplitude(val) {
    this.mouthOpen = Math.max(0, Math.min(1, Number(val) || 0));
  }

  updateNeural(neural) {
    if (!neural) return;
    const affect = neural.affect || {};
    this.curiosity = affect.curiosity || 0.4;
    const hs = neural.hotspot || {};
    this.targetLookX = (hs.norm_x || 0) * 9;
    this.targetLookY = (hs.norm_y || 0) * 6.5;
  }

  setScale(newScale) {
    this.scale = Math.max(0.55, Math.min(2.3, Number(newScale) || 1.0));
    this.canvas.style.width = `${Math.round(220 * this.scale)}px`;
    this.canvas.style.height = `${Math.round(220 * this.scale)}px`;
  }

  _initInteractions() {
    window.addEventListener("mousemove", (e) => {
      const rect = this.canvas.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = (e.clientX - cx) / 220;
      const dy = (e.clientY - cy) / 220;
      const mag = Math.hypot(dx, dy) || 1;
      const clamp = Math.min(1, mag);
      this.targetLookX = (dx / mag) * clamp * 10.5;
      this.targetLookY = (dy / mag) * clamp * 7.5;
    });

    this.canvas.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        const delta = e.deltaY < 0 ? 0.08 : -0.08;
        this.setScale(this.scale + delta);
      },
      { passive: false }
    );

    let isDragging = false;
    let dragMoved = false;
    let startX = 0;
    let startY = 0;
    let origRight = 36;
    let origBottom = 28;

    this.canvas.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      isDragging = true;
      dragMoved = false;
      startX = e.clientX;
      startY = e.clientY;
      const style = window.getComputedStyle(this.dock);
      origRight = parseInt(style.right, 10) || 36;
      origBottom = parseInt(style.bottom, 10) || 28;
    });

    window.addEventListener("mousemove", (e) => {
      if (!isDragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) dragMoved = true;
      this.dock.style.right = `${Math.max(8, origRight - dx)}px`;
      this.dock.style.bottom = `${Math.max(8, origBottom - dy)}px`;
    });

    window.addEventListener("mouseup", () => {
      if (isDragging && !dragMoved) {
        this.bounceVelocity = -6.5;
        this.setEmotion("happy");
        setTimeout(() => {
          if (this.emotion === "happy") this.setEmotion("idle");
        }, 1400);
      }
      isDragging = false;
    });
  }

  _palette() {
    if (this.emotion === "alert") return { glow: "#ff4d6d", eye: "#ff758f", blush: "rgba(255, 77, 109, 0.42)" };
    if (this.emotion === "happy") return { glow: "#00f5d4", eye: "#56cfe1", blush: "rgba(255, 117, 143, 0.52)" };
    return { glow: "#00e5ff", eye: "#48cae4", blush: "rgba(255, 133, 161, 0.36)" };
  }

  _animate(now) {
    const ctx = this.ctx;
    const w = this.canvas.width;
    const h = this.canvas.height;
    ctx.clearRect(0, 0, w, h);

    this.lookX += (this.targetLookX - this.lookX) * 0.16;
    this.lookY += (this.targetLookY - this.lookY) * 0.16;

    this.bounceVelocity += (0 - this.bounceOffset) * 0.2;
    this.bounceVelocity *= 0.8;
    this.bounceOffset += this.bounceVelocity;
    const breathY = Math.sin(now * 0.0031) * 3.8 + this.bounceOffset - this.mouthOpen * 3.0;

    if (now > this.nextBlinkTime) {
      this.blinkProgress = Math.min(1, (now - this.nextBlinkTime) / 75);
      if (now - this.nextBlinkTime > 150) {
        this.blinkProgress = 0;
        this.nextBlinkTime = now + 2400 + Math.random() * 2400;
      }
    }

    const cx = w / 2;
    const cy = h / 2 + breathY;
    const r = 68;
    const pal = this._palette();

    ctx.save();

    // 1. Floating Magnetic Side Pods
    const podBob = Math.sin(now * 0.0042) * 2.5;
    [-1, 1].forEach((sign) => {
      ctx.save();
      ctx.translate(cx + sign * 76, cy - 4 + podBob);
      ctx.rotate((sign * (8 + this.mouthOpen * 12) * Math.PI) / 180);
      ctx.fillStyle = "#f1f5f9";
      ctx.strokeStyle = pal.glow;
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      ctx.roundRect(-7, -18, 14, 36, 7);
      ctx.fill();
      ctx.stroke();
      ctx.restore();
    });

    // 2. Pearl-White Porcelain Spherical Shell (Eilik / EVE aesthetic)
    const shellGrad = ctx.createRadialGradient(cx - 22, cy - 26, 8, cx, cy, r * 1.15);
    shellGrad.addColorStop(0, "#ffffff");
    shellGrad.addColorStop(0.6, "#e2e8f0");
    shellGrad.addColorStop(1, "#64748b");
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = shellGrad;
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = "rgba(255,255,255,0.8)";
    ctx.stroke();

    // 3. Curved Deep OLED Black Visor
    ctx.beginPath();
    ctx.roundRect(cx - 56, cy - 42, 112, 86, 38);
    ctx.fillStyle = "#060913";
    ctx.fill();
    ctx.lineWidth = 2.2;
    ctx.strokeStyle = pal.glow;
    ctx.stroke();

    // Blush cheeks
    ctx.fillStyle = pal.blush;
    ctx.beginPath();
    ctx.ellipse(cx - 33 + this.lookX * 0.45, cy + 14 + this.lookY * 0.45, 9.5, 5.2, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.ellipse(cx + 33 + this.lookX * 0.45, cy + 14 + this.lookY * 0.45, 9.5, 5.2, 0, 0, Math.PI * 2);
    ctx.fill();

    // 4. Big Luminous Anime/OLED Eyes
    const eyeY = cy - 4 + this.lookY;
    this._drawEye(ctx, cx - 23 + this.lookX, eyeY, pal);
    this._drawEye(ctx, cx + 23 + this.lookX, eyeY, pal);

    // 5. Cute Mouth (Cat 'ω' smile / Lip-Sync vocal mouth)
    this._drawMouth(ctx, cx + this.lookX * 0.55, cy + 22 + this.lookY * 0.55, pal);

    ctx.restore();
    requestAnimationFrame(this._animate);
  }

  _drawEye(ctx, x, y, pal) {
    ctx.save();
    const openRatio = Math.max(0.06, 1 - this.blinkProgress);
    if (this.emotion === "happy") {
      ctx.strokeStyle = pal.eye;
      ctx.lineWidth = 4.6;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(x - 12, y + 4);
      ctx.quadraticCurveTo(x, y - 12, x + 12, y + 4);
      ctx.stroke();
      ctx.restore();
      return;
    }

    const ew = 14.5;
    const eh = 17.5 * openRatio;
    const grad = ctx.createRadialGradient(x, y + 4, 2, x, y, ew);
    grad.addColorStop(0, "#ffffff");
    grad.addColorStop(0.3, pal.eye);
    grad.addColorStop(1, "#0284c7");

    ctx.shadowColor = pal.glow;
    ctx.shadowBlur = 12;
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.ellipse(x, y, ew, eh, 0, 0, Math.PI * 2);
    ctx.fill();

    if (openRatio > 0.35) {
      ctx.shadowBlur = 0;
      ctx.fillStyle = "rgba(8, 20, 44, 0.6)";
      ctx.beginPath();
      ctx.ellipse(x, y + 1, ew * 0.48, eh * 0.48, 0, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(x - 4.8, y - 5.5, 4.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.arc(x + 4.8, y + 4.8, 2.2, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  _drawMouth(ctx, x, y, pal) {
    ctx.save();
    ctx.strokeStyle = pal.eye;
    ctx.lineWidth = 2.8;
    ctx.lineCap = "round";

    if (this.mouthOpen > 0.06 || this.emotion === "speaking") {
      const amp = Math.max(0.14, this.mouthOpen);
      const mw = 8.5 + amp * 8.5;
      const mh = 2.5 + amp * 11.5;
      ctx.fillStyle = "#090d16";
      ctx.beginPath();
      ctx.ellipse(x, y, mw, mh, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = "#ff758f";
      ctx.beginPath();
      ctx.ellipse(x, y + mh * 0.32, mw * 0.55, mh * 0.42, 0, 0, Math.PI);
      ctx.fill();
    } else {
      ctx.beginPath();
      ctx.moveTo(x - 8.5, y - 1.5);
      ctx.quadraticCurveTo(x - 4.2, y + 4.2, x, y - 0.5);
      ctx.quadraticCurveTo(x + 4.2, y + 4.2, x + 8.5, y - 1.5);
      ctx.stroke();
    }
    ctx.restore();
  }
}

window.NeitoMascotRenderer = NeitoMascotRenderer;

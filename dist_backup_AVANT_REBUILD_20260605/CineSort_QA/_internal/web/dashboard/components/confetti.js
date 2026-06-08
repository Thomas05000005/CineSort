/* components/confetti.js — Pluie de particules canvas (port desktop).
 * ES module export + expose aussi window.launchConfetti.
 */

export function launchConfetti(opts = {}) {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  const count = Math.max(12, Math.min(300, Number(opts.count) || 80));
  const duration = Math.max(800, Math.min(4000, Number(opts.duration) || 2000));
  const colors = opts.colors || ["#60A5FA", "#F59E0B", "#34D399", "#A78BFA", "#FBBF24"];

  const canvas = document.createElement("canvas");
  canvas.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:10002";
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  document.body.appendChild(canvas);
  const ctx = canvas.getContext("2d");

  const particles = [];
  const cx = canvas.width / 2;
  const topY = -20;
  for (let i = 0; i < count; i++) {
    particles.push({
      x: cx + (Math.random() - 0.5) * canvas.width * 0.6,
      y: topY - Math.random() * 80,
      vx: (Math.random() - 0.5) * 4,
      vy: 2 + Math.random() * 5,
      rot: Math.random() * Math.PI * 2,
      vrot: (Math.random() - 0.5) * 0.3,
      size: 4 + Math.random() * 6,
      color: colors[Math.floor(Math.random() * colors.length)],
      life: 1,
      shape: Math.random() < 0.5 ? "rect" : "circle",
    });
  }

  const gravity = 0.12;
  const drag = 0.995;
  const fadeStart = duration * 0.7;
  const start = performance.now();

  function frame(now) {
    const elapsed = now - start;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    let alive = 0;

    for (const p of particles) {
      p.vy += gravity;
      p.vx *= drag;
      p.x += p.vx;
      p.y += p.vy;
      p.rot += p.vrot;
      if (elapsed > fadeStart) p.life = Math.max(0, 1 - (elapsed - fadeStart) / (duration - fadeStart));
      if (p.life <= 0 || p.y > canvas.height + 30) continue;
      alive++;

      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.globalAlpha = p.life;
      ctx.fillStyle = p.color;
      if (p.shape === "rect") {
        ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
      } else {
        ctx.beginPath();
        ctx.arc(0, 0, p.size / 2, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }

    if (alive > 0 && elapsed < duration + 200) {
      requestAnimationFrame(frame);
    } else {
      canvas.remove();
    }
  }

  requestAnimationFrame(frame);
}

// Compat global (anciens appels sans import)
if (typeof window !== "undefined") window.launchConfetti = launchConfetti;

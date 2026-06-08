/* components/copy-to-clipboard.js — Copie au clic sur [data-copy] (port desktop). */

async function _doCopy(text) {
  if (!text) return false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(String(text));
      return true;
    }
  } catch { /* fallback */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = String(text);
    ta.setAttribute("readonly", "");
    ta.style.position = "absolute"; ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

function _resolveText(el) {
  const v = el.getAttribute("data-copy");
  if (v === "*" || v === "") return (el.textContent || "").trim();
  return v;
}

export function initCopyToClipboard() {
  if (document.body.dataset.copyHooked === "1") return;
  document.body.dataset.copyHooked = "1";
  document.addEventListener("click", async (e) => {
    const el = e.target.closest("[data-copy]");
    if (!el) return;
    e.preventDefault();
    const text = _resolveText(el);
    const ok = await _doCopy(text);
    // Toast si dispo
    try {
      const { showToast } = await import("./toast.js");
      showToast({
        type: ok ? "success" : "error",
        text: ok ? `Copié : ${text.length > 40 ? text.slice(0, 40) + "..." : text}` : "Copie impossible.",
        duration: 2200,
      });
    } catch { /* toast optional */ }
  });
}

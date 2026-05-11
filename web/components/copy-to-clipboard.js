/* components/copy-to-clipboard.js — Copie au clic via Clipboard API (E3)
 *
 * Convention : tout element avec [data-copy="texte"] devient cliquable.
 * - Si data-copy="*" → copie textContent de l'element.
 * - Sinon copie la valeur litterale de l'attribut.
 * Toast feedback ("Copie") sur succes/echec.
 */

async function _doCopy(text) {
  if (!text) return false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(String(text));
      return true;
    }
  } catch { /* fallback */ }
  /* Fallback execCommand pour pywebview ancien */
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

document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-copy]");
  if (!el) return;
  e.preventDefault();
  const text = _resolveText(el);
  const ok = await _doCopy(text);
  if (typeof window.toast === "function") {
    window.toast({
      type: ok ? "success" : "error",
      text: ok ? `Copie : ${text.length > 40 ? text.slice(0, 40) + "..." : text}` : "Copie impossible.",
      duration: 2200,
    });
  }
});

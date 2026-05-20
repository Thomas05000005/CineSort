/* components/omdb-status.js — Phase OMDb (spec 03-settings-omdb §3).
 *
 * Helper de rendu pour les 6 états du test de connexion OMDb. Utilisé par
 * `views/parametres.js` (rendu compact dans la catégorie Intégrations).
 * Anciennement utilisé aussi par `views/settings.js` (vue legacy v4, supprimée).
 *
 * Les 6 états documentés (cf spec) :
 *   1. vide              : aucune clé saisie         → message d'invite
 *   2. saisie non testée : clé renseignée, pas de test → invite à tester
 *   3. OK + quota        : ✅ + "Quota : N/M (reset dans Xh)"
 *   4. KO 401 (auth)     : ❌ "Clé invalide"
 *   5. KO 429 (quota)    : ⚠️ "Quota épuisé pour aujourd'hui"
 *   6. KO réseau         : ⚠️ "Réseau indisponible"
 *
 * Le backend retourne un payload :
 *   { ok, message, sample_title?, sample_year?,
 *     quota_remaining?, quota_limit?, quota_reset_at?, error_code? }
 *
 * `error_code` ∈ {auth, quota, timeout, network, invalid_resp, empty_key}
 */

import { escapeHtml } from "../core/dom.js";

/**
 * Calcule le rendu HTML d'un état OMDb à partir du payload backend.
 *
 * @param {object} data - réponse backend (data.ok, data.error_code, etc.)
 * @returns {{html: string, severity: "ok"|"warning"|"error"|"info"|"idle"}}
 */
export function buildOmdbStatusHtml(data) {
  const d = data || {};
  const ok = !!d.ok;

  if (ok) {
    const quotaLine = _quotaLine(d);
    const sampleTitle = d.sample_title ? ` (${_esc(d.sample_title)})` : "";
    return {
      severity: "ok",
      html: `<span class="omdb-status omdb-status--ok" role="status">
          <span class="omdb-status__icon" aria-hidden="true">✅</span>
          <span class="omdb-status__label">Clé valide${sampleTitle}</span>
          ${quotaLine ? `<span class="omdb-quota">${quotaLine}</span>` : ""}
        </span>`,
    };
  }

  const errorCode = String(d.error_code || "").toLowerCase();
  const rawMessage = d.message || d.error || "";

  if (errorCode === "auth") {
    return {
      severity: "error",
      html: `<span class="omdb-status omdb-status--error" role="status">
          <span class="omdb-status__icon" aria-hidden="true">❌</span>
          <span class="omdb-status__label">Clé invalide</span>
          <span class="omdb-status__hint">Vérifiez votre clé sur omdbapi.com</span>
        </span>`,
    };
  }

  if (errorCode === "quota") {
    const quotaLine = _quotaLine(d, { withReset: true });
    return {
      severity: "warning",
      html: `<span class="omdb-status omdb-status--warning" role="status">
          <span class="omdb-status__icon" aria-hidden="true">⚠️</span>
          <span class="omdb-status__label">Quota épuisé pour aujourd'hui</span>
          ${quotaLine ? `<span class="omdb-quota">${quotaLine}</span>` : ""}
        </span>`,
    };
  }

  if (errorCode === "timeout" || errorCode === "network") {
    return {
      severity: "warning",
      html: `<span class="omdb-status omdb-status--warning" role="status">
          <span class="omdb-status__icon" aria-hidden="true">⚠️</span>
          <span class="omdb-status__label">Réseau indisponible</span>
          <span class="omdb-status__hint">Réessayez plus tard</span>
        </span>`,
    };
  }

  if (errorCode === "empty_key") {
    return {
      severity: "idle",
      html: `<span class="omdb-status omdb-status--idle" role="status">
          <span class="omdb-status__label">Configurer une clé API OMDb</span>
        </span>`,
    };
  }

  // Fallback : message générique de l'API
  return {
    severity: "error",
    html: `<span class="omdb-status omdb-status--error" role="status">
        <span class="omdb-status__icon" aria-hidden="true">❌</span>
        <span class="omdb-status__label">${_esc(rawMessage || "Échec du test OMDb")}</span>
      </span>`,
  };
}

/**
 * État 1 : pas de clé saisie. Utilisé avant tout test.
 */
export function buildOmdbEmptyStateHtml() {
  return {
    severity: "idle",
    html: `<span class="omdb-status omdb-status--idle" role="status">
        <span class="omdb-status__label">Configurer une clé API OMDb</span>
        <span class="omdb-status__hint">Récupérez une clé gratuite sur omdbapi.com</span>
      </span>`,
  };
}

/**
 * État 2 : clé saisie, jamais testée. Invite à cliquer sur Tester.
 */
export function buildOmdbUntestedStateHtml() {
  return {
    severity: "info",
    html: `<span class="omdb-status omdb-status--info" role="status">
        <span class="omdb-status__label">Cliquez sur Tester pour vérifier la clé</span>
      </span>`,
  };
}

/**
 * Injecte directement le rendu dans un élément cible.
 */
export function renderOmdbStatusInto(targetEl, data) {
  if (!targetEl) return;
  const { html } = buildOmdbStatusHtml(data);
  targetEl.innerHTML = html;
  // Couleur du <span> parent v5-test-result (compat existant)
  targetEl.style.color = "";
}

/* --- Internals ---------------------------------------------------------- */

function _esc(s) {
  return escapeHtml(String(s == null ? "" : s));
}

function _quotaLine(d, opts) {
  const remaining = _toInt(d.quota_remaining);
  const limit = _toInt(d.quota_limit);
  const resetAt = d.quota_reset_at;
  const withReset = !!(opts && opts.withReset);

  let line = "";
  if (remaining != null && limit != null) {
    line = `Quota : ${remaining} / ${limit}`;
  } else if (remaining != null) {
    line = `Quota : ${remaining} restants`;
  } else if (withReset && resetAt) {
    line = `Réinitialisation à ${_esc(resetAt)}`;
  }

  const resetSuffix = _humanResetSuffix(resetAt);
  if (line && resetSuffix) {
    line = `${line} (${resetSuffix})`;
  } else if (!line && withReset && resetSuffix) {
    line = `Réinitialisé ${resetSuffix}`;
  }
  return line;
}

function _humanResetSuffix(resetAt) {
  if (!resetAt) return "";
  // OMDb peut renvoyer :
  //  - un timestamp Unix epoch en secondes
  //  - une chaîne ISO
  //  - un libellé déjà formaté
  // On essaie de retomber sur "réinitialisé dans Nh" si parseable.
  const asNumber = Number(resetAt);
  let when = null;
  if (Number.isFinite(asNumber) && asNumber > 0) {
    when = new Date(asNumber * 1000);
  } else {
    const parsed = Date.parse(String(resetAt));
    if (Number.isFinite(parsed)) when = new Date(parsed);
  }
  if (!when) return "";
  const diffMs = when.getTime() - Date.now();
  if (diffMs <= 0) return "imminent";
  const diffH = Math.round(diffMs / (1000 * 60 * 60));
  if (diffH >= 1) return `réinitialisé dans ${diffH}h`;
  const diffMin = Math.max(1, Math.round(diffMs / (1000 * 60)));
  return `réinitialisé dans ${diffMin}min`;
}

function _toInt(raw) {
  if (raw == null) return null;
  const v = Number(raw);
  return Number.isFinite(v) ? Math.trunc(v) : null;
}

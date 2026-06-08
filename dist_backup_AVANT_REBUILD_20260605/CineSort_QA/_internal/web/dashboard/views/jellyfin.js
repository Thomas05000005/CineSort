/* views/jellyfin.js — Statut Jellyfin du dashboard distant */

import { $, escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { kpiGridHtml } from "../components/kpi-card.js";
import { badgeHtml } from "../components/badge.js";
import { skeletonKpiGridHtml, skeletonLinesHtml } from "../components/skeleton.js";
import { getNavSignal, isAbortError } from "../core/nav-abort.js";
import { t } from "../core/i18n.js";

/* --- Chargement initial ------------------------------------ */

async function _load() {
  const container = $("jellyfinContent");
  if (!container) return;

  // V2-08 : skeleton uniquement au 1er load (ne flashe pas sur re-render)
  if (!container.innerHTML.trim()) {
    container.innerHTML = `<div aria-busy="true" aria-label="${escapeHtml(t("legacy.jellyfin.loading_aria"))}">
      ${skeletonKpiGridHtml(4)}
      ${skeletonLinesHtml(4)}
    </div>`;
  }

  try {
    const settingsRes = await apiPost("settings/get_settings");
    const settings = settingsRes.data || {};

    // Guard : Jellyfin doit etre active
    if (!settings.jellyfin_enabled) {
      container.innerHTML = `<div class="card">
        <h3>${escapeHtml(t("legacy.jellyfin.not_configured_title"))}</h3>
        <p class="text-muted mt-4">${escapeHtml(t("legacy.jellyfin.not_configured_body"))}</p>
        <p class="text-muted mt-4">${escapeHtml(t("legacy.jellyfin.not_configured_howto"))}</p>
        <a href="#/parametres#integrations-jellyfin" class="btn btn-primary mt-4">${escapeHtml(t("legacy.jellyfin.open_settings"))}</a>
      </div>`;
      return;
    }

    // Tester la connexion et charger les libraries en parallele.
    // Audit ID-ROB-002 : Promise.allSettled pour qu'un timeout connexion
    // ne masque pas les libraries deja en cache (et inversement).
    // V2-C R4-MEM-6 : signal de nav pour abort si l'utilisateur navigate ailleurs.
    const navSig = getNavSignal();
    const labels = ["test_jellyfin_connection", "get_jellyfin_libraries"];
    const results = await Promise.allSettled([
      apiPost("integrations/test_jellyfin_connection", {
        url: settings.jellyfin_url || "",
        api_key: settings.jellyfin_api_key || "",
        timeout_s: settings.jellyfin_timeout_s || 10,
      }, { signal: navSig }),
      apiPost("integrations/get_jellyfin_libraries", {}, { signal: navSig }),
    ]);
    const _val = (r) => (r && r.status === "fulfilled" && r.value ? r.value.data || {} : {});
    const [conn, lib] = results.map(_val);
    const failed = labels.filter((_, i) => results[i].status !== "fulfilled" && !isAbortError(results[i].reason));
    if (failed.length > 0) console.warn("[jellyfin] endpoints en echec:", failed);

    _render(container, settings, conn, lib);
  } catch (err) {
    if (isAbortError(err)) return;
    container.innerHTML = `<p class="status-msg error">${escapeHtml(t("legacy.jellyfin.error_prefix"))} ${escapeHtml(String(err))}</p>`;
    console.error("[jellyfin]", err);
  }
}

/* --- Rendu ------------------------------------------------- */

function _render(container, settings, conn, lib) {
  let html = "";

  // KPIs connexion
  const connected = conn.ok === true;
  const statusBadge = connected
    ? badgeHtml("status", "ok")
    : badgeHtml("status", "error");

  html += kpiGridHtml([
    {
      icon: "server", label: t("legacy.jellyfin.kpi_status"),
      value: connected ? t("legacy.jellyfin.status_connected") : t("legacy.jellyfin.status_disconnected"),
      color: connected ? "var(--success)" : "var(--danger)",
    },
    {
      icon: "film", label: t("legacy.jellyfin.kpi_movies"),
      value: conn.movies_count ?? lib.movies_count ?? "—",
      color: "var(--accent)",
    },
    {
      icon: "server", label: t("legacy.jellyfin.kpi_server"),
      value: conn.server_name || "—",
      color: "var(--info)",
    },
    {
      icon: "tool", label: t("legacy.jellyfin.kpi_version"),
      value: conn.version || "—",
      color: "var(--text-muted)",
    },
  ]);

  // Statut detaille
  html += '<div class="card mt-6">';
  html += `<h3>${escapeHtml(t("legacy.jellyfin.connection_title"))} ${statusBadge}</h3>`;
  if (connected) {
    html += `<p class="mt-4"><strong>${escapeHtml(t("legacy.jellyfin.info_url_label"))}</strong> ${escapeHtml(settings.jellyfin_url || "")}</p>`;
    html += `<p><strong>${escapeHtml(t("legacy.jellyfin.info_user_label"))}</strong> ${escapeHtml(conn.user_name || "—")} ${conn.is_admin ? escapeHtml(t("legacy.jellyfin.info_admin_suffix")) : ""}</p>`;
    html += `<p><strong>${escapeHtml(t("legacy.jellyfin.info_refresh_label"))}</strong> ${settings.jellyfin_refresh_on_apply ? escapeHtml(t("legacy.jellyfin.yes")) : escapeHtml(t("legacy.jellyfin.no"))}</p>`;
    html += `<p><strong>${escapeHtml(t("legacy.jellyfin.info_sync_watched_label"))}</strong> ${settings.jellyfin_sync_watched ? escapeHtml(t("legacy.jellyfin.yes")) : escapeHtml(t("legacy.jellyfin.no"))}</p>`;
  } else {
    html += `<p class="status-msg error mt-4">${escapeHtml(conn.message || t("legacy.jellyfin.connection_failed"))}</p>`;
  }
  html += "</div>";

  // Bibliotheques
  const libraries = Array.isArray(lib.libraries) ? lib.libraries : [];
  if (libraries.length > 0) {
    html += `<div class="card mt-6"><h3>${escapeHtml(t("legacy.jellyfin.libraries_title"))}</h3>`;
    html += '<ul class="jellyfin-lib-list mt-4">';
    for (const l of libraries) {
      html += `<li><strong>${escapeHtml(l.Name || l.name || "—")}</strong>`;
      html += ` — ${escapeHtml(l.CollectionType || l.type || "—")}`;
      if (l.ItemCount != null || l.item_count != null) {
        html += ` ${escapeHtml(t("legacy.jellyfin.items_count", { count: l.ItemCount ?? l.item_count }))}`;
      }
      html += "</li>";
    }
    html += "</ul></div>";
  }

  // Actions
  html += '<div class="flex gap-2 mt-6">';
  html += `<button id="btnJellyTest" class="btn">${escapeHtml(t("legacy.jellyfin.btn_test"))}</button>`;
  html += `<button id="btnJellyRefresh" class="btn btn-primary">${escapeHtml(t("legacy.jellyfin.btn_refresh"))}</button>`;
  html += ` <button id="btnJellyfinSync" class="btn">${escapeHtml(t("legacy.jellyfin.btn_sync"))}</button>`;
  html += "</div>";
  html += '<div id="jellyfinMsg" class="status-msg mt-4"></div>';
  html += '<div id="jellyfinSyncResults" class="mt-4"></div>';

  container.innerHTML = html;

  // Hook boutons
  _hookActions(settings);
}

/* --- Actions ----------------------------------------------- */

function _hookActions(settings) {
  const btnTest = $("btnJellyTest");
  const btnRefresh = $("btnJellyRefresh");

  if (btnTest) {
    btnTest.addEventListener("click", async () => {
      btnTest.disabled = true;
      _showMsg(t("legacy.jellyfin.test_running"));
      try {
        const res = await apiPost("integrations/test_jellyfin_connection", {
          url: settings.jellyfin_url || "",
          api_key: settings.jellyfin_api_key || "",
          timeout_s: settings.jellyfin_timeout_s || 10,
        });
        const d = res.data || {};
        if (d.ok) {
          _showMsg(t("legacy.jellyfin.test_ok", {
            server: escapeHtml(d.server_name || ""),
            version: escapeHtml(d.version || "?"),
            count: d.movies_count ?? "?",
          }));
        } else {
          _showMsg(escapeHtml(d.message || t("legacy.jellyfin.test_fail")), true);
        }
      } catch { _showMsg(t("legacy.jellyfin.network_error"), true); }
      finally { btnTest.disabled = false; }
    });
  }

  if (btnRefresh) {
    btnRefresh.addEventListener("click", async () => {
      btnRefresh.disabled = true;
      _showMsg(t("legacy.jellyfin.refresh_running"));
      try {
        // C6 : le bouton "Rafraichir la bibliotheque" appelle maintenant
        // get_jellyfin_libraries qui renvoie la liste a jour depuis Jellyfin,
        // puis on re-render la vue pour afficher les nouvelles donnees.
        // Le refresh SCAN cote Jellyfin (reindexation) se fait en hook post-apply
        // et ne peut pas etre declenche cote dashboard sans un endpoint dedie.
        const res = await apiPost("integrations/get_jellyfin_libraries");
        const d = res.data || {};
        if (d.ok) {
          const libs = Array.isArray(d.libraries) ? d.libraries : [];
          _showMsg(t("legacy.jellyfin.refresh_ok", { count: libs.length }));
          // Re-render la vue pour afficher la liste a jour
          setTimeout(() => _load(), 500);
        } else {
          _showMsg(escapeHtml(d.message || t("legacy.jellyfin.generic_fail")), true);
        }
      } catch { _showMsg(t("legacy.jellyfin.network_error"), true); }
      finally { btnRefresh.disabled = false; }
    });
  }
}

function _showMsg(text, isError = false) {
  const el = $("jellyfinMsg");
  if (!el) return;
  el.textContent = text;
  el.className = "status-msg" + (isError ? " error" : " success");
}

/* --- Validation croisee ------------------------------------ */

function _hookSyncButton() {
  const btn = document.getElementById("btnJellyfinSync");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    _showMsg(t("legacy.jellyfin.sync_running"));
    try {
      const r = await apiPost("integrations/get_jellyfin_sync_report", {});
      if (!r?.data?.ok) {
        _showMsg(r?.data?.message || t("legacy.jellyfin.generic_error"), true);
        btn.disabled = false;
        return;
      }
      const d = r.data;
      const missing = d.missing_in_jellyfin || [];
      const ghosts = d.ghost_in_jellyfin || [];
      const mismatches = d.metadata_mismatch || [];
      const total = missing.length + ghosts.length + mismatches.length;
      const cls = total === 0 ? "sync-ok" : (missing.length + ghosts.length > 0 ? "sync-error" : "sync-warn");

      let html = `<div class="sync-summary ${cls}">`;
      html += `<strong>${d.matched}</strong> ${escapeHtml(t("legacy.jellyfin.sync_coherent_suffix"))} — `;
      html += `<strong>${missing.length}</strong> ${escapeHtml(t("legacy.jellyfin.sync_missing_suffix"))} — `;
      html += `<strong>${ghosts.length}</strong> ${escapeHtml(t("legacy.jellyfin.sync_ghost_suffix"))} — `;
      html += `<strong>${mismatches.length}</strong> ${escapeHtml(t("legacy.jellyfin.sync_mismatch_suffix"))}`;
      html += "</div>";

      if (missing.length) {
        html += `<h4 class="mt-4">${escapeHtml(t("legacy.jellyfin.section_missing"))}</h4><table class="table"><thead><tr><th>${escapeHtml(t("legacy.jellyfin.col_title"))}</th><th>${escapeHtml(t("legacy.jellyfin.col_year"))}</th><th>${escapeHtml(t("legacy.jellyfin.col_local_path"))}</th></tr></thead><tbody>`;
        for (const m of missing.slice(0, 50)) {
          html += `<tr><td>${escapeHtml(m.title || "")}</td><td>${m.year || ""}</td><td class="text-muted">${escapeHtml(m.local_path || "")}</td></tr>`;
        }
        html += "</tbody></table>";
      }
      if (ghosts.length) {
        html += `<h4 class="mt-4">${escapeHtml(t("legacy.jellyfin.section_ghosts"))}</h4><table class="table"><thead><tr><th>${escapeHtml(t("legacy.jellyfin.col_title"))}</th><th>${escapeHtml(t("legacy.jellyfin.col_year"))}</th><th>${escapeHtml(t("legacy.jellyfin.col_jellyfin_path"))}</th></tr></thead><tbody>`;
        for (const g of ghosts.slice(0, 50)) {
          html += `<tr><td>${escapeHtml(g.title || "")}</td><td>${g.year || ""}</td><td class="text-muted">${escapeHtml(g.jellyfin_path || "")}</td></tr>`;
        }
        html += "</tbody></table>";
      }
      if (mismatches.length) {
        html += `<h4 class="mt-4">${escapeHtml(t("legacy.jellyfin.section_mismatch"))}</h4><table class="table"><thead><tr><th>${escapeHtml(t("legacy.jellyfin.col_field"))}</th><th>${escapeHtml(t("legacy.jellyfin.col_local"))}</th><th>${escapeHtml(t("legacy.jellyfin.col_jellyfin"))}</th></tr></thead><tbody>`;
        for (const mm of mismatches.slice(0, 50)) {
          const localVal = mm.field === "title" ? mm.local_title : String(mm.local_year || "");
          const jfVal = mm.field === "title" ? mm.jellyfin_title : String(mm.jellyfin_year || "");
          html += `<tr><td>${escapeHtml(mm.field || "")}</td><td>${escapeHtml(localVal)}</td><td>${escapeHtml(jfVal)}</td></tr>`;
        }
        html += "</tbody></table>";
      }

      const container = document.getElementById("jellyfinSyncResults");
      if (container) container.innerHTML = html;
      _showMsg(total === 0 ? t("legacy.jellyfin.sync_all_coherent") : t("legacy.jellyfin.sync_issues_detected", { count: total }), total > 0);
    } catch (err) {
      _showMsg(t("legacy.jellyfin.error_prefix") + " " + String(err), true);
    }
    btn.disabled = false;
  });
}

/* --- Point d'entree ---------------------------------------- */

export function initJellyfin() {
  _load().then(() => _hookSyncButton());
}

"""RuntimeFacade : bounded context Runtime / Help (spec 12-aide.md).

Cf docs/internal/design/refonte_2026_05_17/screens/12-aide.md.

Endpoints exposes :
    Phase 4 (ecran Aide / About) :
        - get_diagnostic, get_recent_logs, get_doc, search_docs, get_app_version
    Pass 1 cleanup (P0 #233) :
        - get_update_info, check_for_updates : updater
        - get_log_paths, open_logs_folder : logs (V3-13)
        - is_demo_mode_active, start_demo_mode, stop_demo_mode : mode demo (V3-05)
        - get_notifications, dismiss_notification, mark_notification_read,
          mark_all_notifications_read, clear_notifications,
          get_notifications_unread_count : notification center (v7.6 Vague 9)
        - validate_dropped_path : drag-and-drop UI
    Sprint 7 (api refactor, mai 2026) :
        - get_probe_tools_status, get_tools_status (alias),
          recheck_probe_tools, set_probe_tool_paths,
          install_probe_tools, update_probe_tools,
          auto_install_probe_tools, get_probe : 8 endpoints probe (ffprobe + MediaInfo)
        - get_event_ts : timestamp dernier evenement (scan/apply/settings)
        - reset_incremental_cache : purge totale du cache incremental

Note : `open_path` reste hors facade. Il est exclu du dispatcher REST
(prend un chemin arbitraire en parametre, vector path-traversal) et n'est
appele que via le bridge pywebview en desktop natif.

Strategie : meme pattern Strangler Fig + Adapter que les autres facades.
Les methodes existent EN PARALLELE sur CineSortApi via `_X_impl()` pour
preserver la backward-compat 100%. Cette facade delegue simplement.

Usage frontend :
    api.runtime.get_diagnostic()
    api.runtime.get_update_info()
    api.runtime.get_notifications_unread_count()
    api.runtime.get_probe_tools_status()
    api.runtime.install_probe_tools({"scope": "user", "tools": ["ffprobe"]})
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from cinesort.ui.api.facades._base import _BaseFacade


class RuntimeFacade(_BaseFacade):
    """Bounded context Runtime/Help : diagnostic, logs, docs, updater, demo, notifications, probe."""

    # ---------- Phase 4 (ecran Aide / About) ----------

    def get_diagnostic(self) -> Dict[str, Any]:
        """Retourne le diagnostic complet pour le bouton "Copier diagnostic".

        Cf CineSortApi._get_diagnostic_impl pour la doc complete.
        """
        return self._api._get_diagnostic_impl()

    def get_recent_logs(self, limit: int = 100) -> Dict[str, Any]:
        """Lit les N dernieres lignes du log courant (cap a 1000).

        Cf CineSortApi._get_recent_logs_impl pour la doc complete.
        """
        return self._api._get_recent_logs_impl(limit)

    def get_doc(self, file: str) -> Dict[str, Any]:
        """Retourne le contenu markdown brut d'un document whiteliste.

        Cf CineSortApi._get_doc_impl pour la doc complete. Tout chemin
        contenant `..` ou doc_id inconnu est rejete (category="validation").
        """
        return self._api._get_doc_impl(file)

    def search_docs(self, query: str) -> Dict[str, Any]:
        """Recherche full-text dans tous les documents whitelistes.

        Cf CineSortApi._search_docs_impl pour la doc complete.
        """
        return self._api._search_docs_impl(query)

    def get_app_version(self) -> Dict[str, Any]:
        """Retourne la version applicative + metadonnees build pour l'ecran About.

        Cf CineSortApi._get_app_version_impl pour la doc complete.

        Returns:
            {ok: True, version: str, build_date: str, git_sha: str, python_version: str}
        """
        return self._api._get_app_version_impl()

    # ---------- Updater (V3-12) ----------

    def get_update_info(self, force_refresh: bool = False) -> Dict[str, Any]:
        """V3-12 — Retourne le dernier resultat connu (cache).

        Fix audit 2026-05-24 (v1.5.2) Vague E : accepte ``force_refresh=True``
        pour forcer un check reseau immediat (delegue a ``check_for_updates``).
        Permet a l'UI Parametres > Mises a jour d'avoir un seul endpoint.

        Cf CineSortApi._get_update_info_impl pour la doc complete.
        """
        return self._api._get_update_info_impl(force_refresh=force_refresh)

    def check_for_updates(self) -> Dict[str, Any]:
        """V3-12 — Force un check MAJ immediat (bouton "Verifier maintenant").

        Cf CineSortApi._check_for_updates_impl pour la doc complete.
        """
        return self._api._check_for_updates_impl()

    # ---------- Logs (V3-13) ----------

    def get_log_paths(self) -> Dict[str, Any]:
        """V3-13 — Retourne les chemins des logs (pour affichage UI + copie)."""
        return self._api._get_log_paths_impl()

    def open_logs_folder(self) -> Dict[str, Any]:
        """V3-13 — Ouvre le dossier des logs dans l'explorateur Windows.

        Operation locale uniquement (refusee depuis un client REST distant).
        """
        return self._api._open_logs_folder_impl()

    def open_external_url(self, url: str = "") -> Dict[str, Any]:
        """Fix audit 2026-05-24 — Ouvre une URL externe (http/https) dans le
        navigateur OS via webbrowser.open(). Necessaire car WebView2 sans
        handler bloque silencieusement target='_blank' et window.open().

        Operation locale uniquement (refusee depuis client REST distant).
        Scheme whitelist: http(s) uniquement.
        """
        return self._api._open_external_url_impl(url=url)

    # ---------- Mode demo (V3-05) ----------

    def is_demo_mode_active(self) -> Dict[str, Any]:
        """V3-05 : True si au moins un run is_demo est present en BDD."""
        return self._api._is_demo_mode_active_impl()

    def start_demo_mode(self) -> Dict[str, Any]:
        """V3-05 : active le mode demo (15 films fictifs + run + plan.jsonl)."""
        return self._api._start_demo_mode_impl()

    def stop_demo_mode(self) -> Dict[str, Any]:
        """V3-05 : desactive le mode demo (supprime runs + quality_reports + run_dir)."""
        return self._api._stop_demo_mode_impl()

    # ---------- Notification Center (v7.6.0 Vague 9) ----------

    def get_notifications(
        self,
        unread_only: bool = False,
        limit: int = 100,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : liste les notifications en memoire (LIFO)."""
        return self._api._get_notifications_impl(unread_only=unread_only, limit=limit, category=category)

    def dismiss_notification(self, notification_id: str) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : supprime une notification du centre."""
        return self._api._dismiss_notification_impl(notification_id)

    def mark_notification_read(self, notification_id: str) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : marque une notification comme lue."""
        return self._api._mark_notification_read_impl(notification_id)

    def mark_all_notifications_read(self) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : marque toutes les notifications comme lues."""
        return self._api._mark_all_notifications_read_impl()

    def clear_notifications(self) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : vide completement le centre de notifications."""
        return self._api._clear_notifications_impl()

    def get_notifications_unread_count(self) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : compteur pour le badge top bar."""
        return self._api._get_notifications_unread_count_impl()

    # ---------- Drag-and-drop UI ----------

    def validate_dropped_path(self, path: str = "") -> Dict[str, Any]:
        """Valide qu'un chemin droppe est un dossier existant.

        Cf CineSortApi._validate_dropped_path_impl pour la doc complete.
        """
        return self._api._validate_dropped_path_impl(path)

    # ---------- Outils probe (ffprobe + MediaInfo) ----------

    def get_probe_tools_status(self) -> Dict[str, Any]:
        """Retourne le statut de detection de ffprobe + MediaInfo (version, chemin, dispo)."""
        return self._api._get_probe_tools_status_impl()

    def get_tools_status(self) -> Dict[str, Any]:
        """Alias historique de `get_probe_tools_status` (compat v7.0/v7.1)."""
        return self._api._get_tools_status_impl()

    def recheck_probe_tools(self) -> Dict[str, Any]:
        """Force une redetection des outils probe (utile apres installation manuelle).

        Cf CineSortApi._recheck_probe_tools_impl pour la doc complete.
        """
        return self._api._recheck_probe_tools_impl()

    def set_probe_tool_paths(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Enregistre des chemins manuels vers ffprobe / MediaInfo (si hors PATH).

        Cf CineSortApi._set_probe_tool_paths_impl pour la doc complete.
        """
        return self._api._set_probe_tool_paths_impl(payload)

    def install_probe_tools(self, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Installe ffprobe + MediaInfo via winget (ou options fournies).

        Cf CineSortApi._install_probe_tools_impl pour la doc complete.
        """
        return self._api._install_probe_tools_impl(options)

    def update_probe_tools(self, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Met a jour ffprobe + MediaInfo via winget.

        Cf CineSortApi._update_probe_tools_impl pour la doc complete.
        """
        return self._api._update_probe_tools_impl(options)

    def auto_install_probe_tools(self) -> Dict[str, Any]:
        """Telecharge et installe ffprobe + MediaInfo depuis les sources officielles."""
        return self._api._auto_install_probe_tools_impl()

    def get_probe(self, run_id: str, row_id: str) -> Dict[str, Any]:
        """Retourne la probe normalisee (video/audio/sous-titres) d'un film du run.

        Cf CineSortApi._get_probe_impl pour la doc complete.
        """
        return self._api._get_probe_impl(run_id, row_id)

    # ---------- Sprint 7 : misc runtime ----------

    def get_event_ts(self) -> Dict[str, Any]:
        """Retourne le timestamp du dernier evenement significatif (scan/apply/settings).

        Utilise par le desktop pour detecter les changements et rafraichir.
        Cf CineSortApi._get_event_ts_impl pour la doc complete.
        """
        return self._api._get_event_ts_impl()

    def reset_incremental_cache(self) -> Dict[str, Any]:
        """Purge TOTALE du cache incremental (3 tables, tous roots confondus).

        Utilise par le bouton "Forcer le rescan complet".
        Cf CineSortApi._reset_incremental_cache_impl pour la doc complete.
        """
        return self._api._reset_incremental_cache_impl()

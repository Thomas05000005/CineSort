# -*- coding: utf-8 -*-
"""Fix i18n FR/EN parite + ajout legacy + patch vues legacy v4.

Travail complet en un seul script pour eviter les changes d'etat de branche
entre commandes Bash.

Etapes :
1. Ajoute toutes les cles FR manquantes vs EN (113 cles common/errors/glossary/help)
2. Ajoute une section `legacy` dans FR et EN (login, plex, radarr)
3. Patch les vues login.js, plex.js, radarr.js pour utiliser t()
4. Cree le test de parite tests/test_phase6_i18n_parity.py

Usage : python scripts/i18n_full_sync.py
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
EN_PATH = ROOT / "locales" / "en.json"
FR_PATH = ROOT / "locales" / "fr.json"
VIEWS_DIR = ROOT / "web" / "dashboard" / "views"
TESTS_DIR = ROOT / "tests"

# --------------------------------------------------------------------------- #
# Traductions FR pour les cles EN manquantes                                  #
# --------------------------------------------------------------------------- #
FR_TRANSLATIONS: dict[str, str] = {
    # common
    "common.all": "Tout",
    "common.apply": "Appliquer",
    "common.cancelled": "Annulé",
    "common.completed": "Terminé",
    "common.details": "Détails",
    "common.empty": "Vide",
    "common.info": "Info",
    "common.less": "Moins",
    "common.more": "Plus",
    "common.none": "Aucun",
    "common.open": "Ouvrir",
    "common.preview": "Aperçu",
    "common.retry": "Réessayer",
    "common.running": "En cours",
    "common.search": "Rechercher",
    "common.see_details": "Voir les détails",
    "common.see_more": "Voir plus",
    "common.success": "Succès",
    "common.undo": "Annuler",
    "common.unknown": "Inconnu",
    "common.warning": "Avertissement",
    # errors
    "errors.apply_in_progress": "Une application est déjà en cours.",
    "errors.config_invalid": "Configuration invalide : {{detail}}.",
    "errors.disk_full": "Espace disque insuffisant pour effectuer cette opération.",
    "errors.file_locked": "Le fichier {{path}} est verrouillé par un autre processus.",
    "errors.jellyfin_unauthorized": "Authentification Jellyfin échouée (vérifier la clé API).",
    "errors.network_error": "Erreur réseau : {{detail}}",
    "errors.plex_unauthorized": "Authentification Plex échouée (vérifier le jeton).",
    "errors.radarr_unauthorized": "Authentification Radarr échouée (vérifier la clé API).",
    "errors.rest_unauthorized": "Authentification requise. Fournis un jeton Bearer valide.",
    "errors.scan_in_progress": "Un scan est déjà en cours.",
    "errors.smtp_failed": "Échec d'envoi de l'e-mail : {{detail}}.",
    "errors.tmdb_rate_limited": "Limite TMDb atteinte. Patiente quelques secondes.",
    # glossary
    "glossary.apply": "Apply — exécute le plan pour de vrai (modifie le disque). Crée une entrée dans le journal d'application pour permettre l'annulation ultérieure.",
    "glossary.banding": "Banding — artefact visuel : bandes visibles dans les ciels et dégradés. Causé par une compression trop agressive. Détecté par le moteur perceptuel via analyse de variance par blocs.",
    "glossary.chromaprint": "Chromaprint — empreinte audio générée par fpcalc. Détecte que deux versions d'un film (FR + EN) partagent la même bande son sans comparer les fichiers entiers.",
    "glossary.composite_score_v2": "Composite Score V2 — moteur de scoring de seconde génération. Combine les catégories visuel (60 %), audio (35 %) et cohérence (5 %), avec 9 règles d'ajustement contextuelles et un scoring pondéré par la confiance. Coexiste avec V1 via le réglage `composite_score_version`.",
    "glossary.confidence": "Niveau de certitude du match TMDb. 0.95+ = certain (.nfo + id IMDb). 0.7-0.95 = fort. 0.5-0.7 = moyen (à vérifier). <0.5 = faible (revue manuelle requise).",
    "glossary.dolby_vision": "Dolby Vision (DV) — standard HDR premium avec métadonnées dynamiques par plan. Profils 5/7/8.1/8.2/8.4 détectés via l'enregistrement DOVI. Plus précis que HDR10 mais nécessite une chaîne de lecture compatible.",
    "glossary.drc": "DRC (Dynamic Range Compression) — niveau de compression audio. Cinema = grande dynamique préservée (musique forte, dialogues doux). Standard = légèrement compressé. Broadcast = très compressé (TV, plus uniforme mais aplati).",
    "glossary.ebu_r128": "EBU R128 (loudness) — standard européen de mesure du loudness audio. Mesure le loudness intégré (LUFS), la plage de loudness (LRA) et le true peak. Détecte les loudness wars et les normalisations broadcast.",
    "glossary.edition": "Édition (Director's Cut, Extended, IMAX, etc.) — version particulière d'un film. CineSort la détecte depuis le nom de fichier ou le .nfo et la conserve dans le titre du dossier final. Déduplication consciente de l'édition : même film + éditions différentes ≠ doublons.",
    "glossary.grain_v2": "Analyse de grain v2 — classification perceptuelle du grain de film par époque (16mm 1920+, 35mm classique 1950+, 35mm moderne 1990+, bruit numérique 2000+, numérique propre 2010+, UHD/Dolby Vision 2015+). Détecte le grain authentique vs. DNR excessif (lissage). Inclut des exceptions par réalisateur (Nolan, A24, Pixar).",
    "glossary.hdr10": "HDR10 — standard High Dynamic Range de base, métadonnées statiques (une seule luminance pic pour tout le film). Compatibilité universelle.",
    "glossary.jellyfin": "Jellyfin — serveur multimédia open source. CineSort peut déclencher le rafraîchissement de la bibliothèque Jellyfin après chaque application, et synchroniser le statut vu/non vu.",
    "glossary.lpips": "LPIPS (Learned Perceptual Image Patch Similarity) — mesure scientifique de similarité visuelle utilisant un modèle ML AlexNet pré-entraîné. Plus fiable que SSIM ou PSNR pour la qualité perçue. Utilisé pour comparer les doublons.",
    "glossary.multi_root": "Multi-racine — capacité à scanner plusieurs dossiers racines (SSD + NAS + disque externe) en une seule passe. Chaque racine a ses propres buckets (`_review`, `_Collection`, `_Empty`). Les doublons inter-racines sont détectés.",
    "glossary.naming_preset": "Preset de nommage — modèle de renommage prédéfini. 5 presets fournis : default, plex, jellyfin, quality, custom. Les variables comme {title}, {year}, {resolution} sont remplies au moment de l'application.",
    "glossary.nfo": "NFO — fichier de métadonnées XML (format Kodi/Jellyfin/Emby) placé à côté de la vidéo (titre, année, id IMDb/TMDb). CineSort le lit en source prioritaire (plus fiable que le nom de fichier) et peut aussi le générer.",
    "glossary.perceptual": "Analyse perceptuelle — analyse la qualité réelle de l'image et de l'audio (pas seulement les métadonnées). Détecte les faux 4K (upscale), le DNR excessif, le faux HDR, l'audio mono déguisé en 5.1, etc. Activée dans Paramètres > Perceptuel.",
    "glossary.plan": "Plan — liste des changements proposés (renommages + déplacements) générée à la fin d'un scan. Revisible avant application.",
    "glossary.plex": "Plex — serveur multimédia propriétaire. CineSort se connecte via X-Plex-Token pour rafraîchir la bibliothèque Plex après une application.",
    "glossary.plugin_hook": "Plugin hook — script externe (Python, .bat, .ps1) déclenché automatiquement après un événement (post_scan, post_apply, post_undo, post_error). Reçoit le contexte JSON via stdin et les variables d'environnement CINESORT_EVENT/CINESORT_RUN_ID.",
    "glossary.probe": "Action d'analyser un fichier vidéo pour en extraire les caractéristiques techniques (codec, résolution, bitrate, pistes audio, HDR). Outils utilisés : ffprobe ou mediainfo, en parallèle.",
    "glossary.quality_profile": "Profil qualité — ensemble de poids et de seuils pour le système de scoring (CinemaLux). Indique à CineSort ce qui compte le plus (résolution, codec, audio, sous-titres).",
    "glossary.quarantine": "Quarantaine — le dossier `_review/` où les fichiers invalides sont déplacés : films sans match TMDb, doublons SHA1 (`_duplicates_identical/`), conflits (`_review/_conflicts`), fichiers corrompus. Tu peux les revoir et les rattraper manuellement.",
    "glossary.radarr": "Radarr — gestionnaire automatisé de collection de films. CineSort peut proposer des montées en qualité pour les films monitorés via l'API Radarr.",
    "glossary.reencode": "Ré-encodage (dégradé) — fichier ré-encodé avec un bitrate trop faible, causant une perte de qualité visible. Détecté via des heuristiques codec/bitrate dans `encode_analysis.py`.",
    "glossary.run": "Run — exécution complète d'un scan (identifiant unique, journal dédié). Chaque scan crée un nouveau run avec ses propres logs et rapports.",
    "glossary.saga_collection": "Saga / Collection (TMDb) — regroupement de films liés (par ex. Le Seigneur des Anneaux, Marvel Cinematic Universe). CineSort détecte les collections via TMDb et peut créer un dossier parent `_Collection/` pour les conserver ensemble.",
    "glossary.score_v1": "Composite Score V1 — système de scoring legacy (pré-v7.5.0). Basé uniquement sur les métadonnées (résolution, codec, audio). Conservé pour les rapports créés avant la migration 011.",
    "glossary.score_v2": "Composite Score V2 — note composite sur 100 (CinemaLux v2). Pondérations Vidéo 60 %, Audio 35 %, Cohérence 5 %. Inclut l'analyse perceptuelle si activée. Plus lisible que V1 (conservée pour compatibilité).",
    "glossary.smart_playlist": "Smart playlist — filtre sauvegardé dans la vue bibliothèque (par ex. « tous les films de Nolan en 4K HDR »). Persisté entre sessions avec CRUD complet.",
    "glossary.ssim": "SSIM (Structural Similarity Index) — compare deux images sur structure + luminance + contraste. Utilisé pour détecter les faux 4K (un upscale a un SSIM élevé avec sa version 1080p downscalée).",
    "glossary.upscale": "Upscale (suspect) — fichier annoncé en 4K mais avec un bitrate trop faible pour sa résolution. Probablement une source 1080p étirée en 4K. Signalé par le module d'analyse d'encodage.",
    "glossary.watch_folder": "Watch folder (auto-monitor) — mode de surveillance : CineSort scrute la racine toutes les N minutes (1-60) et déclenche un scan automatiquement quand de nouveaux fichiers sont détectés. Aucune dépendance externe, threading Python pur.",
    # help
    "help.copy_path_button": "Copier le chemin",
    "help.diagnostic": "Diagnostic exportable : Paramètres > Logs > Exporter diagnostic. Les clés API et mots de passe SMTP sont automatiquement masqués du zip.",
    "help.full_docs": "Documentation complète",
    "help.local_logs": "Logs locaux (à joindre à ton rapport)",
    "help.no_results_faq": "Aucune question ne correspond à ta recherche.",
    "help.no_results_glossary": "Aucun terme ne correspond à ta recherche.",
    "help.open_logs_button": "Ouvrir le dossier des logs",
    "help.report_bug": "Signaler un bug ou poser une question",
    "help.report_button": "Signaler un bug sur GitHub",
    "help.search_placeholder": "Rechercher une question, un terme…",
    "help.shortcuts_global": "Actions globales",
    "help.shortcuts_intro": "Mémorise ces combinaisons pour gagner du temps. Les raccourcis Alt+chiffre fonctionnent même dans les champs texte ; les chiffres seuls ne fonctionnent qu'en dehors d'un champ.",
    "help.shortcuts_navigation": "Navigation",
    "help.shortcuts_section_title": "Raccourcis clavier",
    "help.shortcuts_validation": "Validation (vue Validation active)",
    "help.support_intro": "Tu n'as pas trouvé ta réponse ? Plusieurs canaux sont disponibles :",
    "help.support_title": "Besoin de plus d'aide ?",
    "help.faq.q_first_scan.question": "Comment lancer mon premier scan ?",
    "help.faq.q_first_scan.answer": "Va dans Paramètres > Dossiers racine, ajoute le dossier contenant tes films (par ex. D:\\Films), sauvegarde, puis ouvre Bibliothèque > Scan. CineSort lit chaque fichier vidéo, récupère les infos depuis TMDb et génère une analyse complète. Au premier lancement, le wizard 5 étapes te guide automatiquement.",
    "help.faq.q_dry_run.question": "Qu'est-ce qu'un dry-run ?",
    "help.faq.q_dry_run.answer": "Un dry-run simule l'application des changements sans rien déplacer ni renommer sur ton disque. Tu vois exactement ce qui serait fait. C'est l'option recommandée pour ta première passe : zéro risque de perdre un fichier. Décoche « Mode dry-run » dans l'écran Application uniquement quand tu es confiant.",
    "help.faq.q_auto_approve.question": "Comment fonctionne l'auto-approbation ?",
    "help.faq.q_auto_approve.answer": "Quand un film a un score élevé et une confiance forte (match TMDb exact + .nfo cohérent), CineSort le marque comme approuvé automatiquement. Tu peux manuellement décocher ceux que tu ne veux pas appliquer. Réglage : Paramètres > Validation > seuils de confiance.",
    "help.faq.q_decisions_lost.question": "Mes décisions ont disparu après rafraîchissement, pourquoi ?",
    "help.faq.q_decisions_lost.answer": "Les décisions de validation sont persistées dans la base SQLite via Ctrl+S ou le bouton Sauvegarder. Si tu n'as pas sauvegardé avant un F5 ou un changement de vue, elles sont perdues. CineSort affiche un avertissement « décisions non sauvegardées » si tu navigues sans sauvegarder.",
    "help.faq.q_undo_apply.question": "Comment annuler une application ?",
    "help.faq.q_undo_apply.answer": "CineSort tient un journal de chaque déplacement/renommage (table apply_operations). Va dans Application > Undo, choisis le batch à annuler, prévisualise en dry-run, puis confirme. L'undo peut être par batch complet ou par film (Undo v5). Les conflits (fichier modifié depuis) sont redirigés vers `_review/_undo_conflicts`.",
    "help.faq.q_configure_integrations.question": "Comment configurer Jellyfin / Plex / Radarr ?",
    "help.faq.q_configure_integrations.answer": "Section Paramètres > Intégrations. Pour Jellyfin : URL du serveur + clé API (Profil > Clés API dans Jellyfin). Pour Plex : URL + X-Plex-Token (récupérable via plex.tv/account). Pour Radarr : URL + clé API (Paramètres > Général). Le bouton « Tester la connexion » valide immédiatement. Active l'auto-refresh pour déclencher un scan après chaque application.",
    "help.faq.q_scan_no_movies.question": "Mon scan ne trouve aucun film, que faire ?",
    "help.faq.q_scan_no_movies.answer": "Vérifie dans cet ordre : (1) le dossier racine est-il accessible (pas de NAS déconnecté) ; (2) les extensions vidéo sont-elles supportées (mkv, mp4, avi, mov par défaut) ; (3) les fichiers sont-ils en lecture seule ou bloqués par antivirus ; (4) consulte la vue Logs pour le message d'erreur exact. Si rien ne fonctionne, exporte les logs et signale via GitHub Issues.",
    "help.faq.q_perceptual_mode.question": "Qu'est-ce que le mode perceptuel ?",
    "help.faq.q_perceptual_mode.answer": "L'analyse perceptuelle regarde la qualité réelle de l'image et de l'audio (pas seulement les métadonnées). Elle détecte les faux 4K (upscale), le DNR excessif (lissage qui efface le grain), la compression audio DRC (cinema/standard/broadcast), le HDR mal encodé, etc. Réglage : Paramètres > Perceptuel. Active-le si tu veux noter la qualité réelle, pas seulement la résolution affichée.",
    "help.faq.q_install_ffmpeg.question": "Comment installer ffmpeg / mediainfo ?",
    "help.faq.q_install_ffmpeg.answer": "Paramètres > Outils vidéo > bouton « Installer automatiquement ». CineSort télécharge les binaires officiels et les place dans le dossier de l'app, sans toucher au PATH système. Si tu préfères une install manuelle : ffmpeg.org et mediaarea.net/MediaInfo, puis fournis le chemin complet dans Paramètres.",
    "help.faq.q_share_logs.question": "Comment partager mes logs pour signaler un bug ?",
    "help.faq.q_share_logs.answer": "Paramètres > Logs > bouton « Exporter diagnostic ». Le fichier zip contient logs + version + config (sans tes clés API, automatiquement masquées : TMDb, Jellyfin, Plex, Radarr, mots de passe SMTP). Joins-le à une issue GitHub. Logs bruts : %LOCALAPPDATA%/CineSort/logs/cinesort.log (rotation 50 Mo x 5).",
    "help.faq.q_install_antivirus.question": "Mon antivirus dit que CineSort est dangereux",
    "help.faq.q_install_antivirus.answer": "Faux positif courant pour les EXE Python compilés avec PyInstaller. CineSort est open source (code lisible sur GitHub) et signé. Solutions : (1) ajouter une exception pour CineSort.exe dans ton antivirus ; (2) vérifier la signature du binaire (clic droit > Propriétés > Signatures numériques) ; (3) compiler depuis les sources si tu préfères. Aucune télémétrie, aucun code réseau hors TMDb/Jellyfin/Plex/Radarr (que tu actives toi-même).",
    "help.faq.q_dashboard_connection.question": "Le dashboard distant ne se connecte pas",
    "help.faq.q_dashboard_connection.answer": "Vérifie : (1) Paramètres > API REST est activée ; (2) tu utilises bien le token d'accès complet (au moins 32 caractères pour le binding LAN) ; (3) le pare-feu Windows autorise CineSort.exe sur le port 8642 ; (4) PC et téléphone sont sur le même Wi-Fi. La carte « Accès distant » sur la page Accueil affiche l'URL et un QR code à scanner.",
    "help.faq.q_tier_meaning.question": "Que signifient les tiers Platinum / Gold / Silver / Bronze / Reject ?",
    "help.faq.q_tier_meaning.answer": "C'est la note finale de qualité du film sur 5 niveaux. Platinum = excellence (4K HDR Dolby Atmos sans défaut). Gold = très bonne version (1080p ou 4K propre). Silver = correct (DVD ou 720p). Bronze = limité (faible résolution ou encode dégradant). Reject = à refaire (faux 4K, audio mono, fichier corrompu). Le calcul combine résolution, codec, audio, sous-titres et détection perceptuelle.",
    "help.faq.q_export_report.question": "Comment exporter un rapport de mon analyse ?",
    "help.faq.q_export_report.answer": "Après un scan : Bibliothèque > Application > bouton « Exporter ». Trois formats : HTML (rapport autonome avec graphiques, ouvrable dans n'importe quel navigateur, imprimable en PDF via Ctrl+P) ; CSV enrichi (30 colonnes, ouvrable dans Excel) ; .nfo XML (Kodi/Jellyfin/Emby, un fichier par film à côté de la vidéo).",
    "help.faq.q_offline_mode.question": "Puis-je utiliser CineSort sans connexion Internet ?",
    "help.faq.q_offline_mode.answer": "Oui pour le scan et l'application locaux. Non pour l'enrichissement TMDb (titre original, année, poster, collection). Astuce : lance un premier scan en ligne pour remplir le cache TMDb local, ensuite tu peux travailler hors ligne. Les sous-titres sont détectés localement sans Internet. Jellyfin/Plex/Radarr fonctionnent tant que ton serveur est accessible (le LAN suffit).",
}

# --------------------------------------------------------------------------- #
# Sections legacy (login, plex, radarr) a ajouter dans FR et EN               #
# --------------------------------------------------------------------------- #
LEGACY_FR = {
    "login": {
        "token_required": "Saisis la clé d'accès.",
        "connection_refused": "Connexion refusée.",
        "network_error": "Erreur réseau. Vérifie l'adresse du serveur.",
    },
    "plex": {
        "not_configured_title": "Plex non configuré",
        "not_configured_body": "L'intégration Plex est désactivée. Pour l'activer, ouvre les réglages et configure la section Plex (URL, token, refresh automatique).",
        "open_settings": "Ouvrir les réglages Plex",
        "kpi_status": "Statut",
        "kpi_server": "Serveur",
        "kpi_version": "Version",
        "status_connected": "Connecté",
        "status_disconnected": "Déconnecté",
        "info_title": "Informations",
        "info_url": "URL : {{url}}",
        "info_refresh": "Refresh auto : {{value}}",
        "btn_test": "Tester la connexion",
        "btn_sync": "Validation croisée",
        "loading": "Chargement…",
        "network_error": "Erreur réseau.",
        "test_ok": "OK — {{name}}",
        "test_fail": "Échec",
        "kpi_matches": "Matches",
        "kpi_missing": "Manquants",
        "kpi_ghosts": "Fantômes",
    },
    "radarr": {
        "not_configured_title": "Radarr non configuré",
        "not_configured_body": "L'intégration Radarr est désactivée. Pour l'activer, ouvre les réglages et configure la section Radarr (URL, clé API, candidats d'upgrade).",
        "open_settings": "Ouvrir les réglages Radarr",
        "kpi_status": "Statut",
        "kpi_server": "Serveur",
        "kpi_version": "Version",
        "status_connected": "Connecté",
        "status_disconnected": "Déconnecté",
        "actions_title": "Actions",
        "btn_test": "Tester la connexion",
        "btn_status": "Voir le rapport",
        "loading": "Chargement…",
        "network_error": "Erreur réseau.",
        "test_ok": "OK — {{name}}",
        "test_fail": "Échec",
        "kpi_matches": "Matches",
        "kpi_not_in_radarr": "Pas dans Radarr",
        "kpi_upgrades": "Upgrades",
        "upgrade_candidates_title": "Candidats upgrade",
        "col_title": "Titre",
        "col_score": "Score",
        "col_action": "Action",
        "btn_upgrade": "Upgrade",
        "btn_upgrade_running": "...",
        "btn_upgrade_ok": "Lancé !",
        "btn_upgrade_fail": "Échec",
    },
    "errors": {
        "generic": "Erreur : {{detail}}",
    },
}

LEGACY_EN = {
    "login": {
        "token_required": "Enter your access key.",
        "connection_refused": "Connection refused.",
        "network_error": "Network error. Check the server address.",
    },
    "plex": {
        "not_configured_title": "Plex not configured",
        "not_configured_body": "Plex integration is disabled. To enable it, open the settings and configure the Plex section (URL, token, auto-refresh).",
        "open_settings": "Open Plex settings",
        "kpi_status": "Status",
        "kpi_server": "Server",
        "kpi_version": "Version",
        "status_connected": "Connected",
        "status_disconnected": "Disconnected",
        "info_title": "Information",
        "info_url": "URL: {{url}}",
        "info_refresh": "Auto-refresh: {{value}}",
        "btn_test": "Test connection",
        "btn_sync": "Cross-validation",
        "loading": "Loading…",
        "network_error": "Network error.",
        "test_ok": "OK — {{name}}",
        "test_fail": "Failed",
        "kpi_matches": "Matches",
        "kpi_missing": "Missing",
        "kpi_ghosts": "Ghosts",
    },
    "radarr": {
        "not_configured_title": "Radarr not configured",
        "not_configured_body": "Radarr integration is disabled. To enable it, open the settings and configure the Radarr section (URL, API key, upgrade candidates).",
        "open_settings": "Open Radarr settings",
        "kpi_status": "Status",
        "kpi_server": "Server",
        "kpi_version": "Version",
        "status_connected": "Connected",
        "status_disconnected": "Disconnected",
        "actions_title": "Actions",
        "btn_test": "Test connection",
        "btn_status": "View report",
        "loading": "Loading…",
        "network_error": "Network error.",
        "test_ok": "OK — {{name}}",
        "test_fail": "Failed",
        "kpi_matches": "Matches",
        "kpi_not_in_radarr": "Not in Radarr",
        "kpi_upgrades": "Upgrades",
        "upgrade_candidates_title": "Upgrade candidates",
        "col_title": "Title",
        "col_score": "Score",
        "col_action": "Action",
        "btn_upgrade": "Upgrade",
        "btn_upgrade_running": "...",
        "btn_upgrade_ok": "Started!",
        "btn_upgrade_fail": "Failed",
    },
    "errors": {
        "generic": "Error: {{detail}}",
    },
}


def set_nested(target: dict, dotted_key: str, value) -> None:
    parts = dotted_key.split(".")
    cur = target
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


def deep_merge(target: dict, source: dict) -> None:
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            deep_merge(target[key], value)
        else:
            target[key] = value


def flatten(d: dict, prefix: str = "") -> dict:
    items: dict = {}
    for k, v in d.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            items.update(flatten(v, full))
        else:
            items[full] = v
    return items


# --------------------------------------------------------------------------- #
# Patches des vues JS                                                         #
# --------------------------------------------------------------------------- #
def patch_login_js() -> int:
    path = VIEWS_DIR / "login.js"
    src = path.read_text(encoding="utf-8")
    n = 0

    # Import i18n
    if 'from "../core/i18n.js"' not in src:
        src = src.replace(
            'import { navigateTo } from "../core/router.js";',
            'import { navigateTo } from "../core/router.js";\nimport { t } from "../core/i18n.js";',
            1,
        )
        n += 1

    # 3 messages a remplacer
    replacements = [
        ('"Saisissez la clé d\'accès."', 't("login.token_required")'),
        ('"Connexion refusee."', 't("login.connection_refused")'),
        ('"Erreur reseau. Verifiez l\'adresse du serveur."', 't("login.network_error")'),
    ]
    for old, new in replacements:
        if old in src:
            src = src.replace(old, new, 1)
            n += 1

    path.write_text(src, encoding="utf-8")
    return n


def patch_plex_js() -> int:
    path = VIEWS_DIR / "plex.js"
    src = path.read_text(encoding="utf-8")
    n = 0

    if 'from "../core/i18n.js"' not in src:
        src = src.replace(
            'import { skeletonKpiGridHtml, skeletonLinesHtml } from "../components/skeleton.js";',
            'import { skeletonKpiGridHtml, skeletonLinesHtml } from "../components/skeleton.js";\nimport { t } from "../core/i18n.js";',
            1,
        )
        n += 1

    block_old = """    if (!s.plex_enabled) {
      el.innerHTML = `<div class="card"><h3>Plex non configure</h3>
        <p class="text-muted mt-4">L'integration Plex est desactivee. Pour l'activer, ouvrez les reglages et configurez la section Plex (URL, token, refresh automatique).</p>
        <a href="#/parametres#integrations-plex" class="btn btn-primary mt-4">Ouvrir les réglages Plex</a></div>`;
      return;
    }"""
    block_new = """    if (!s.plex_enabled) {
      el.innerHTML = `<div class="card"><h3>${escapeHtml(t("plex.not_configured_title"))}</h3>
        <p class="text-muted mt-4">${escapeHtml(t("plex.not_configured_body"))}</p>
        <a href="#/parametres#integrations-plex" class="btn btn-primary mt-4">${escapeHtml(t("plex.open_settings"))}</a></div>`;
      return;
    }"""
    if block_old in src:
        src = src.replace(block_old, block_new, 1)
        n += 3

    kpi_old = """    let html = kpiGridHtml([
      { label: "Statut", value: ok ? "Connecte" : "Deconnecte", color: ok ? "var(--success)" : "var(--danger)" },
      { label: "Serveur", value: conn.server_name || "—", color: "var(--accent)" },
      { label: "Version", value: conn.version || "—", color: "var(--info)" },
    ]);

    html += '<div class="card mt-4">';
    html += '<h3>Informations</h3>';
    html += `<p class="mt-2 text-secondary">URL : ${escapeHtml(s.plex_url || "—")}</p>`;
    html += `<p class="text-secondary">Refresh auto : ${s.plex_refresh_on_apply ? "Oui" : "Non"}</p>`;
    html += `<div class="mt-4"><button class="btn btn--compact" id="btnPlexTest">Tester la connexion</button>`;
    html += ` <button class="btn btn--compact" id="btnPlexSync">Validation croisee</button></div>`;"""
    kpi_new = """    let html = kpiGridHtml([
      { label: t("plex.kpi_status"), value: ok ? t("plex.status_connected") : t("plex.status_disconnected"), color: ok ? "var(--success)" : "var(--danger)" },
      { label: t("plex.kpi_server"), value: conn.server_name || "—", color: "var(--accent)" },
      { label: t("plex.kpi_version"), value: conn.version || "—", color: "var(--info)" },
    ]);

    html += '<div class="card mt-4">';
    html += `<h3>${escapeHtml(t("plex.info_title"))}</h3>`;
    html += `<p class="mt-2 text-secondary">${escapeHtml(t("plex.info_url", { url: s.plex_url || "—" }))}</p>`;
    html += `<p class="text-secondary">${escapeHtml(t("plex.info_refresh", { value: s.plex_refresh_on_apply ? t("common.yes") : t("common.no") }))}</p>`;
    html += `<div class="mt-4"><button class="btn btn--compact" id="btnPlexTest">${escapeHtml(t("plex.btn_test"))}</button>`;
    html += ` <button class="btn btn--compact" id="btnPlexSync">${escapeHtml(t("plex.btn_sync"))}</button></div>`;"""
    if kpi_old in src:
        src = src.replace(kpi_old, kpi_new, 1)
        n += 8

    test_old = """    $("btnPlexTest")?.addEventListener("click", async () => {
      const r = await apiPost("integrations/test_plex_connection", { url: s.plex_url, token: s.plex_token });
      alert(r.data?.ok ? `OK — ${r.data.server_name}` : (r.data?.error || "Echec"));
    });

    $("btnPlexSync")?.addEventListener("click", async () => {
      const container = $("plexSyncResult");
      if (!container) return;
      container.innerHTML = '<p class="text-muted">Chargement...</p>';
      let r;
      try { r = await apiPost("integrations/get_plex_sync_report"); }
      catch { container.innerHTML = '<p class="text-muted">Erreur reseau.</p>'; return; }
      const d = r.data || {};
      if (!d.ok && d.message) { container.innerHTML = `<p class="text-muted">${escapeHtml(d.message)}</p>`; return; }
      container.innerHTML = `<div class="kpi-grid mt-2">
        <div class="kpi-card" style="border-left:3px solid var(--success)"><div class="kpi-label">Matches</div><div class="kpi-value">${d.matched || 0}</div></div>
        <div class="kpi-card" style="border-left:3px solid var(--warning)"><div class="kpi-label">Manquants</div><div class="kpi-value">${(d.missing_in_plex || []).length}</div></div>
        <div class="kpi-card" style="border-left:3px solid var(--danger)"><div class="kpi-label">Fantomes</div><div class="kpi-value">${(d.ghost_in_plex || []).length}</div></div>
      </div>`;
    });

  } catch (err) {
    el.innerHTML = `<p class="text-muted">Erreur : ${escapeHtml(err.message || String(err))}</p>`;
  }"""
    test_new = """    $("btnPlexTest")?.addEventListener("click", async () => {
      const r = await apiPost("integrations/test_plex_connection", { url: s.plex_url, token: s.plex_token });
      alert(r.data?.ok ? t("plex.test_ok", { name: r.data.server_name }) : (r.data?.error || t("plex.test_fail")));
    });

    $("btnPlexSync")?.addEventListener("click", async () => {
      const container = $("plexSyncResult");
      if (!container) return;
      container.innerHTML = `<p class="text-muted">${escapeHtml(t("plex.loading"))}</p>`;
      let r;
      try { r = await apiPost("integrations/get_plex_sync_report"); }
      catch { container.innerHTML = `<p class="text-muted">${escapeHtml(t("plex.network_error"))}</p>`; return; }
      const d = r.data || {};
      if (!d.ok && d.message) { container.innerHTML = `<p class="text-muted">${escapeHtml(d.message)}</p>`; return; }
      container.innerHTML = `<div class="kpi-grid mt-2">
        <div class="kpi-card" style="border-left:3px solid var(--success)"><div class="kpi-label">${escapeHtml(t("plex.kpi_matches"))}</div><div class="kpi-value">${d.matched || 0}</div></div>
        <div class="kpi-card" style="border-left:3px solid var(--warning)"><div class="kpi-label">${escapeHtml(t("plex.kpi_missing"))}</div><div class="kpi-value">${(d.missing_in_plex || []).length}</div></div>
        <div class="kpi-card" style="border-left:3px solid var(--danger)"><div class="kpi-label">${escapeHtml(t("plex.kpi_ghosts"))}</div><div class="kpi-value">${(d.ghost_in_plex || []).length}</div></div>
      </div>`;
    });

  } catch (err) {
    el.innerHTML = `<p class="text-muted">${escapeHtml(t("errors.generic", { detail: err.message || String(err) }))}</p>`;
  }"""
    if test_old in src:
        src = src.replace(test_old, test_new, 1)
        n += 11

    path.write_text(src, encoding="utf-8")
    return n


def patch_radarr_js() -> int:
    path = VIEWS_DIR / "radarr.js"
    src = path.read_text(encoding="utf-8")
    n = 0

    if 'from "../core/i18n.js"' not in src:
        src = src.replace(
            'import { skeletonKpiGridHtml, skeletonLinesHtml } from "../components/skeleton.js";',
            'import { skeletonKpiGridHtml, skeletonLinesHtml } from "../components/skeleton.js";\nimport { t } from "../core/i18n.js";',
            1,
        )
        n += 1

    block_old = """    if (!s.radarr_enabled) {
      el.innerHTML = `<div class="card"><h3>Radarr non configure</h3>
        <p class="text-muted mt-4">L'integration Radarr est desactivee. Pour l'activer, ouvrez les reglages et configurez la section Radarr (URL, cle API, candidats d'upgrade).</p>
        <a href="#/parametres#integrations-radarr" class="btn btn-primary mt-4">Ouvrir les réglages Radarr</a></div>`;
      return;
    }"""
    block_new = """    if (!s.radarr_enabled) {
      el.innerHTML = `<div class="card"><h3>${escapeHtml(t("radarr.not_configured_title"))}</h3>
        <p class="text-muted mt-4">${escapeHtml(t("radarr.not_configured_body"))}</p>
        <a href="#/parametres#integrations-radarr" class="btn btn-primary mt-4">${escapeHtml(t("radarr.open_settings"))}</a></div>`;
      return;
    }"""
    if block_old in src:
        src = src.replace(block_old, block_new, 1)
        n += 3

    kpi_old = """    let html = kpiGridHtml([
      { label: "Statut", value: ok ? "Connecte" : "Deconnecte", color: ok ? "var(--success)" : "var(--danger)" },
      { label: "Serveur", value: conn.server_name || "—", color: "var(--accent)" },
      { label: "Version", value: conn.version || "—", color: "var(--info)" },
    ]);

    html += '<div class="card mt-4">';
    html += '<h3>Actions</h3>';
    html += `<div class="mt-4"><button class="btn btn--compact" id="btnRadarrTest">Tester la connexion</button>`;
    html += ` <button class="btn btn--compact" id="btnRadarrStatus">Voir le rapport</button></div>`;"""
    kpi_new = """    let html = kpiGridHtml([
      { label: t("radarr.kpi_status"), value: ok ? t("radarr.status_connected") : t("radarr.status_disconnected"), color: ok ? "var(--success)" : "var(--danger)" },
      { label: t("radarr.kpi_server"), value: conn.server_name || "—", color: "var(--accent)" },
      { label: t("radarr.kpi_version"), value: conn.version || "—", color: "var(--info)" },
    ]);

    html += '<div class="card mt-4">';
    html += `<h3>${escapeHtml(t("radarr.actions_title"))}</h3>`;
    html += `<div class="mt-4"><button class="btn btn--compact" id="btnRadarrTest">${escapeHtml(t("radarr.btn_test"))}</button>`;
    html += ` <button class="btn btn--compact" id="btnRadarrStatus">${escapeHtml(t("radarr.btn_status"))}</button></div>`;"""
    if kpi_old in src:
        src = src.replace(kpi_old, kpi_new, 1)
        n += 6

    test_old = """    $("btnRadarrTest")?.addEventListener("click", async () => {
      const r = await apiPost("integrations/test_radarr_connection", { url: s.radarr_url, api_key: s.radarr_api_key });
      alert(r.data?.ok ? `OK — ${r.data.server_name}` : (r.data?.error || "Echec"));
    });

    $("btnRadarrStatus")?.addEventListener("click", async () => {
      const container = $("radarrStatusResult");
      if (!container) return;
      container.innerHTML = '<p class="text-muted">Chargement...</p>';
      let r;
      try { r = await apiPost("integrations/get_radarr_status"); }
      catch { container.innerHTML = '<p class="text-muted">Erreur reseau.</p>'; return; }
      const d = r.data || {};
      if (!d.ok && d.message) { container.innerHTML = `<p class="text-muted">${escapeHtml(d.message)}</p>`; return; }
      const candidates = d.upgrade_candidates || [];
      let h = `<div class="kpi-grid mt-2">
        <div class="kpi-card" style="border-left:3px solid var(--success)"><div class="kpi-label">Matches</div><div class="kpi-value">${d.matched_count || 0}</div></div>
        <div class="kpi-card" style="border-left:3px solid var(--warning)"><div class="kpi-label">Pas dans Radarr</div><div class="kpi-value">${(d.not_in_radarr || []).length}</div></div>
        <div class="kpi-card" style="border-left:3px solid var(--info)"><div class="kpi-label">Upgrades</div><div class="kpi-value">${candidates.length}</div></div>
      </div>`;
      if (candidates.length) {
        h += '<h4 class="mt-4">Candidats upgrade</h4><table class="tbl mt-2"><thead><tr><th>Titre</th><th>Score</th><th>Action</th></tr></thead><tbody>';
        for (const c of candidates.slice(0, 20)) {
          h += `<tr><td>${escapeHtml(c.title || "")}</td><td>${c.score || "?"}</td>`;
          h += `<td><button class="btn btn--compact btn-radarr-upgrade" data-rid="${c.radarr_id || 0}">Upgrade</button></td></tr>`;
        }
        h += '</tbody></table>';
      }
      container.innerHTML = h;

      // Hook upgrade buttons
      container.querySelectorAll(".btn-radarr-upgrade").forEach(btn => {
        btn.addEventListener("click", async () => {
          btn.disabled = true;
          btn.textContent = "...";
          const rid = parseInt(btn.dataset.rid, 10);
          const res = await apiPost("integrations/request_radarr_upgrade", { movie_id: rid });
          btn.textContent = res.data?.ok ? "Lance !" : "Echec";
        });
      });
    });

  } catch (err) {
    el.innerHTML = `<p class="text-muted">Erreur : ${escapeHtml(err.message || String(err))}</p>`;
  }"""
    test_new = """    $("btnRadarrTest")?.addEventListener("click", async () => {
      const r = await apiPost("integrations/test_radarr_connection", { url: s.radarr_url, api_key: s.radarr_api_key });
      alert(r.data?.ok ? t("radarr.test_ok", { name: r.data.server_name }) : (r.data?.error || t("radarr.test_fail")));
    });

    $("btnRadarrStatus")?.addEventListener("click", async () => {
      const container = $("radarrStatusResult");
      if (!container) return;
      container.innerHTML = `<p class="text-muted">${escapeHtml(t("radarr.loading"))}</p>`;
      let r;
      try { r = await apiPost("integrations/get_radarr_status"); }
      catch { container.innerHTML = `<p class="text-muted">${escapeHtml(t("radarr.network_error"))}</p>`; return; }
      const d = r.data || {};
      if (!d.ok && d.message) { container.innerHTML = `<p class="text-muted">${escapeHtml(d.message)}</p>`; return; }
      const candidates = d.upgrade_candidates || [];
      let h = `<div class="kpi-grid mt-2">
        <div class="kpi-card" style="border-left:3px solid var(--success)"><div class="kpi-label">${escapeHtml(t("radarr.kpi_matches"))}</div><div class="kpi-value">${d.matched_count || 0}</div></div>
        <div class="kpi-card" style="border-left:3px solid var(--warning)"><div class="kpi-label">${escapeHtml(t("radarr.kpi_not_in_radarr"))}</div><div class="kpi-value">${(d.not_in_radarr || []).length}</div></div>
        <div class="kpi-card" style="border-left:3px solid var(--info)"><div class="kpi-label">${escapeHtml(t("radarr.kpi_upgrades"))}</div><div class="kpi-value">${candidates.length}</div></div>
      </div>`;
      if (candidates.length) {
        h += `<h4 class="mt-4">${escapeHtml(t("radarr.upgrade_candidates_title"))}</h4><table class="tbl mt-2"><thead><tr><th>${escapeHtml(t("radarr.col_title"))}</th><th>${escapeHtml(t("radarr.col_score"))}</th><th>${escapeHtml(t("radarr.col_action"))}</th></tr></thead><tbody>`;
        for (const c of candidates.slice(0, 20)) {
          h += `<tr><td>${escapeHtml(c.title || "")}</td><td>${c.score || "?"}</td>`;
          h += `<td><button class="btn btn--compact btn-radarr-upgrade" data-rid="${c.radarr_id || 0}">${escapeHtml(t("radarr.btn_upgrade"))}</button></td></tr>`;
        }
        h += '</tbody></table>';
      }
      container.innerHTML = h;

      // Hook upgrade buttons
      container.querySelectorAll(".btn-radarr-upgrade").forEach(btn => {
        btn.addEventListener("click", async () => {
          btn.disabled = true;
          btn.textContent = t("radarr.btn_upgrade_running");
          const rid = parseInt(btn.dataset.rid, 10);
          const res = await apiPost("integrations/request_radarr_upgrade", { movie_id: rid });
          btn.textContent = res.data?.ok ? t("radarr.btn_upgrade_ok") : t("radarr.btn_upgrade_fail");
        });
      });
    });

  } catch (err) {
    el.innerHTML = `<p class="text-muted">${escapeHtml(t("errors.generic", { detail: err.message || String(err) }))}</p>`;
  }"""
    if test_old in src:
        src = src.replace(test_old, test_new, 1)
        n += 14

    path.write_text(src, encoding="utf-8")
    return n


# --------------------------------------------------------------------------- #
# Test parite                                                                 #
# --------------------------------------------------------------------------- #
PARITY_TEST = '''# -*- coding: utf-8 -*-
"""Test parite cles i18n : locales/fr.json et locales/en.json doivent avoir
exactement le meme ensemble de cles plates.

Cette parite est critique : le frontend essaye t("foo.bar") en FR, et si la
cle n'existe pas, le fallback EN doit fonctionner — donc EN doit contenir
toutes les cles FR, et vice-versa.

Ce test echoue si :
- Une cle existe en EN mais pas en FR (l'utilisateur FR verra la cle brute)
- Une cle existe en FR mais pas en EN (l'utilisateur EN verra la cle brute)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EN_PATH = ROOT / "locales" / "en.json"
FR_PATH = ROOT / "locales" / "fr.json"


def _flatten(d: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for k, v in d.items():
        if k == "_meta":
            continue
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys |= _flatten(v, full)
        else:
            keys.add(full)
    return keys


@pytest.fixture(scope="module")
def en_keys() -> set[str]:
    return _flatten(json.loads(EN_PATH.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def fr_keys() -> set[str]:
    return _flatten(json.loads(FR_PATH.read_text(encoding="utf-8")))


def test_en_keys_present_in_fr(en_keys: set[str], fr_keys: set[str]) -> None:
    """Toute cle EN doit avoir un equivalent FR."""
    missing = sorted(en_keys - fr_keys)
    assert not missing, (
        f"{len(missing)} cles EN sans equivalent FR (fallback FR echoue) : "
        f"{missing[:10]}..."
    )


def test_fr_keys_present_in_en(en_keys: set[str], fr_keys: set[str]) -> None:
    """Toute cle FR doit avoir un equivalent EN."""
    missing = sorted(fr_keys - en_keys)
    assert not missing, (
        f"{len(missing)} cles FR sans equivalent EN (fallback EN echoue) : "
        f"{missing[:10]}..."
    )


def test_parity_count(en_keys: set[str], fr_keys: set[str]) -> None:
    """Symetrie complete : meme nombre de cles dans les deux langues."""
    assert len(en_keys) == len(fr_keys), (
        f"FR={len(fr_keys)} vs EN={len(en_keys)} : ecart de "
        f"{abs(len(en_keys) - len(fr_keys))} cles."
    )
'''


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #
def main() -> int:
    en = json.loads(EN_PATH.read_text(encoding="utf-8"))
    fr = json.loads(FR_PATH.read_text(encoding="utf-8"))

    en_flat_before = flatten(en)
    fr_flat_before = flatten(fr)
    missing = sorted(set(en_flat_before) - set(fr_flat_before))
    print(f"AVANT : EN={len(en_flat_before)}  FR={len(fr_flat_before)}  manquantes_FR={len(missing)}")

    # 1) Traductions FR pour cles deja en EN
    added_fr_trans = 0
    for key in missing:
        if key in FR_TRANSLATIONS:
            set_nested(fr, key, FR_TRANSLATIONS[key])
            added_fr_trans += 1

    # 2) Sections legacy dans les deux
    deep_merge(fr, LEGACY_FR)
    deep_merge(en, LEGACY_EN)

    # Bump meta FR
    if isinstance(fr.get("_meta"), dict):
        fr["_meta"]["version"] = "1.2.0"

    FR_PATH.write_text(
        json.dumps(fr, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    EN_PATH.write_text(
        json.dumps(en, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    fr2 = json.loads(FR_PATH.read_text(encoding="utf-8"))
    en2 = json.loads(EN_PATH.read_text(encoding="utf-8"))
    en_flat = flatten(en2)
    fr_flat = flatten(fr2)
    print(f"APRES : EN={len(en_flat)}  FR={len(fr_flat)}")
    print(f"  EN-FR diff : {sorted(set(en_flat) - set(fr_flat))}")
    print(f"  FR-EN diff : {sorted(set(fr_flat) - set(en_flat))}")
    print(f"  Traductions FR ajoutees    : {added_fr_trans}")

    # 3) Patch des vues JS
    n_login = patch_login_js()
    n_plex = patch_plex_js()
    n_radarr = patch_radarr_js()
    print(f"  t() ajoutes login.js   : {n_login}")
    print(f"  t() ajoutes plex.js    : {n_plex}")
    print(f"  t() ajoutes radarr.js  : {n_radarr}")
    print(f"  Total t() ajoutes      : {n_login + n_plex + n_radarr}")

    # 4) Test parite
    test_path = TESTS_DIR / "test_phase6_i18n_parity.py"
    test_path.write_text(PARITY_TEST, encoding="utf-8")
    print(f"  Test cree : {test_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

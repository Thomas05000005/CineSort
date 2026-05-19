# Spec — Accueil refondu

Statut : **VALIDÉE** par Thomas le 2026-05-17.
Position dans la refonte : **Écran 5 / N**.
Cible : `web/dashboard/` (ESM uniquement, après migration B).
Inspirée de : `docs/internal/design/11-key-screen-mockups.md` Variante A "Hub editorial de pilotage".

## Pourquoi cette spec

Test perso 2026-05-17 sur EXE v1.2.0-beta : l'Accueil actuel a **18 widgets simultanés** dont 4 chiffres différents pour le "nombre de films" (40 / 2 / 853 / 901), une cascade de "0%" et "—", graphiques vides, podiums à 0% détectés, etc. → impression de "dashboard admin technique non fonctionnel" alors que la lib a 901 films scannés.

Décisions validées par Thomas :
- **7 widgets virés** de l'Accueil (workflow étapes, podiums, films/mois, points d'attention, accès distant, etc.)
- **5 widgets fusionnés** (vue d'ensemble + Aperçu V2 + compteur 40 → carte unique "Dernier run")
- **6 widgets gardés** (services connectés, santé, activité, suggestions, distribution qualité, CTA scan)
- **Hero éditorial** "Bonjour Thomas + résumé dynamique selon état"
- **Suggestions toujours visibles** triées par sévérité

## 1. Layout cible

```
┌────────────────────────────────────────────────────────────────────────┐
│  ENVIRONMENT BAR (slim, persistante 32 px)                             │
│  📂 \\NAS\Media\Films, \\NAS\Media\downloads                          │
│  ☑ TMDb    ☑ Jellyfin    ☐ Plex    ☐ Radarr    ☐ OMDb (à configurer) │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  Bonjour Thomas                                                        │
│  Ta bibliothèque va bien.                                              │
│  ─────────────────────────────────────────                             │
│                                                                        │
│  ╔════════════════════════════════════════════════╗                   │
│  ║  DERNIER RUN                                   ║                   │
│  ║  Run 20260517_151 · Aujourd'hui 15:11          ║                   │
│  ║                                                ║                   │
│  ║  40 films analysés                             ║                   │
│  ║  Score moyen : —  (pas calculé)                ║                   │
│  ║  Confiance moy : 78%                           ║                   │
│  ║                                                ║                   │
│  ║  [▶ Reprendre la validation]  [📊 Voir détail] ║                   │
│  ╚════════════════════════════════════════════════╝                   │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  🚀 LANCER UN NOUVEAU SCAN                                       │ │
│  │     Sur \\NAS\Media\Films + \\NAS\Media\downloads               │ │
│  │     [▶ Démarrer]    [⚙ Options...]                              │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  ⚠️  3 POINTS À TRAITER                                                │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  🔴  22 doublons probables détectés                              │ │
│  │      Avatar de feu et de cendres, Bienvenue chez les Ch'tis, ... │ │
│  │      [→ Voir les doublons]                                       │ │
│  ├──────────────────────────────────────────────────────────────────┤ │
│  │  🟡  1 film non identifié par TMDb                               │ │
│  │      La Cuisine au Beurre HD1080                                 │ │
│  │      [→ Identifier manuellement]                                 │ │
│  ├──────────────────────────────────────────────────────────────────┤ │
│  │  🟡  901 films sans sous-titres FR                               │ │
│  │      [→ Voir la liste]    [⚙ Configurer recherche subs]         │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  📚 SANTÉ BIBLIOTHÈQUE (853 films classés)                            │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  Platinum   ▏                       0                            │ │
│  │  Gold       ▏                       0                            │ │
│  │  Silver     ▓▓▓▓▓                  273                           │ │
│  │  Bronze     ▓▓▓▓▓▓▓▓▓▓▓            525                           │ │
│  │  Reject     ▓                       55                           │ │
│  │  [→ Audit qualité complet]                                       │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  📜 ACTIVITÉ RÉCENTE                                                  │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │  Aujourd'hui 15:11   Run 20260517_151   40 films    ● Done       │ │
│  │  Hier 13:13          Run 20260515_131   855 films   ● Done       │ │
│  │  Hier 11:12          Run 20260515_112   855 films   ● Done       │ │
│  │  [→ Voir l'historique complet]                                   │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

## 2. Détail des 6 sections

### Section 1 — Environment bar (slim, persistante)

Bande horizontale de 32 px de haut, fond surface 1 (légèrement plus claire que le canvas).

| Élément | Contenu | Action |
|---|---|---|
| Roots actifs | `📂 <root1>, <root2>` (tronqué si >2) | Hover → tooltip avec liste complète + tailles |
| Pastilles intégrations | `☑/☐ TMDb / Jellyfin / Plex / Radarr / OMDb` | Clic sur une pastille → Paramètres > Intégrations > section concernée |

Source : `settings.roots[]` + `settings.<service>_enabled` + statut connexion via `get_global_stats()`.

**Style** :
- Pastille cochée ☑ vert si configurée + en ligne
- Pastille vide ☐ grise si non configurée (avec annotation "à configurer")
- Pastille rouge ⚠ si configurée mais hors ligne (Plex/Jellyfin/Radarr injoignable)

### Section 2 — Hero éditorial + carte Dernier run

#### Hero

```
Bonjour Thomas
Ta bibliothèque va bien.
```

- Police **Newsreader** pour le titre (display) — accent éditorial
- Police **Manrope** pour la phrase de statut

**Résumé dynamique selon état** (mapping backend) :

| Statut | Phrase de résumé |
|---|---|
| Tout OK, run récent, 0 alerte | "Ta bibliothèque va bien." |
| 1-3 alertes mineures | "Ta bibliothèque va bien, quelques points à voir." |
| 4+ alertes ou alerte critique | "Ta bibliothèque demande ton attention." |
| Run en cours | "Scan en cours sur 901 films. ~5 min restant." |
| Premier lancement, pas de run | "Bienvenue. Lance ton premier scan pour commencer." |
| Erreur critique (DB inaccessible, etc.) | "Problème : la base de données n'est pas accessible." |

#### Carte Dernier run

| Donnée | Source backend |
|---|---|
| Titre du run | `get_run_summary(latest).run_id` |
| Date | `get_run_summary(latest).started_at` formaté "Aujourd'hui 15:11" / "Hier 13:13" / "Il y a 3 jours" |
| Compteur films | `get_run_summary(latest).total_rows` |
| Score moyen | `get_run_summary(latest).avg_score_v2` (peut être `null` si pas calculé) |
| Confiance moyenne | `get_run_summary(latest).avg_confidence_pct` |
| Bouton "Reprendre la validation" | Visible si `status === "AWAITING_VALIDATION"` ou similaire — navigue vers Traitement |
| Bouton "Voir détail" | Toujours visible — navigue vers Historique > détail du run |

**État "pas de run"** : la carte est remplacée par un placeholder "Aucun run encore. [▶ Lance ton premier scan]".

### Section 3 — CTA Lancer un nouveau scan

Bandeau large, bord coloré accent froid à gauche.

| Élément | Contenu |
|---|---|
| Icône + titre | `🚀 LANCER UN NOUVEAU SCAN` |
| Sous-titre | `Sur <root1> + <root2>` (les roots actifs) |
| Bouton principal | `[▶ Démarrer]` (variant primary, accent froid) |
| Bouton secondaire | `[⚙ Options...]` ouvre un drawer avec options avancées (dry-run, profil, exclure dossiers, etc.) |
| Raccourci | Ctrl+S également déclenche [▶ Démarrer] |

**État "scan en cours"** : remplacé par un compteur progression :

```
🔄 SCAN EN COURS sur 901 films
   Étape 3/5 — Vérification (450/901 films)
   ~5 min restant
   [⏸ Pause]  [⏹ Annuler]  [→ Voir détail]
```

Source : `get_run_status(active_run_id).phase` + `.progress` + `.eta_seconds`.

### Section 4 — Points à traiter (suggestions actionnables)

Toujours visibles. Triés par sévérité (rouge > jaune > info).

#### Structure d'une suggestion

```
🔴/🟡/🔵  <Titre court>
          <Exemples concrets : "Avatar de feu et de cendres, Ch'tis, ...">
          [→ Bouton action principale]    [⚙ Bouton secondaire optionnel]
```

#### Mapping des suggestions

| Code | Sévérité | Titre | Action |
|---|---|---|---|
| `duplicates_probable` | 🔴 | "X doublons probables détectés" | Navigue vers Doublons |
| `films_not_identified` | 🟡 | "X films non identifiés par TMDb" | Navigue vers Bibliothèque filtrée |
| `films_low_confidence` | 🟡 | "X films avec confiance < 70%" | Navigue vers Bibliothèque filtrée |
| `subs_missing_fr` | 🟡 | "X films sans sous-titres FR" | Navigue vers liste + bouton "Configurer recherche subs" |
| `omdb_disagreements` | 🟡 | "X désaccords OMDb à arbitrer" | Navigue vers Bibliothèque filtrée |
| `quality_reject` | 🔴 | "X films en tier Reject (à remplacer)" | Navigue vers Qualité |
| `health_low` | 🟡 | "Santé bibliothèque < 50%" | Navigue vers Qualité avec onglet santé |
| `sagas_incomplete` | 🔵 | "X sagas incomplètes (Y films manquants)" | Navigue vers Bibliothèque > sagas |

Source : nouveau endpoint `get_home_suggestions(run_id)` qui agrège tout en une réponse :

```python
{
  "ok": True,
  "data": {
    "suggestions": [
      {"code": "duplicates_probable", "severity": "danger", "count": 22, "samples": [...], "action_url": "#doublons"},
      ...
    ]
  }
}
```

(Si l'endpoint n'existe pas encore, l'agréger côté frontend depuis `get_global_stats()` + `check_duplicates()` + `library/get_library_filtered({not_identified: true})`.)

#### Affichage des "samples"

Pour les codes avec des exemples (doublons, non identifiés, etc.) : afficher max 3 titres + "..." si plus. Les titres sont cliquables et ouvrent le détail dans la vue concernée.

### Section 5 — Santé bibliothèque

Bargraph horizontal des 5 tiers (Platinum / Gold / Silver / Bronze / Reject).

| Données | Source |
|---|---|
| Compteur total | `get_global_stats().library.total_classified` |
| Compteur par tier | `get_global_stats().library.tier_distribution[tier]` |
| Pourcentage par tier | `count[tier] / total_classified` |
| Couleur barre | Tier color (cf design tokens : platinum doré, gold jaune, silver gris clair, bronze marron, reject rouge) |
| Bouton "Audit qualité complet" | Navigue vers vue Qualité |

**État "0 film classé"** : remplacé par "Lance ton premier scan pour voir la distribution."

### Section 6 — Activité récente

Liste de 3 derniers runs (max).

| Élément | Source |
|---|---|
| Date relative ("Aujourd'hui 15:11", "Hier 13:13") | `formatRelativeTime(run.started_at)` (utilitaire JS) |
| ID du run | `run.run_id` |
| Compteur films | `run.total_rows` |
| Statut | `run.status` (DONE/PARTIAL/ERROR) avec icône colorée |
| Clic sur ligne | Navigue vers Historique > détail du run |
| Bouton "Voir l'historique complet" | Navigue vers Historique (full) |

Source : `get_recent_runs(limit=3)` (existant via `run/list_runs?limit=3` ou similaire).

## 3. Inspecteur droit sur l'Accueil

Conformément au [Shell 3 zones](./04-shell-3-zones.md), **replié par défaut** sur l'Accueil (vue de synthèse).

**Si l'utilisateur l'ouvre manuellement** (Ctrl+I ou clic sur le bouton ▶), l'inspecteur affiche :

```
┌──────────────────────────┐
│  ▼ Inspecteur            │
├──────────────────────────┤
│                          │
│  Contexte                │
│  ──────────────          │
│  Bibliothèque : 901      │
│  Run actif : aucun       │
│  Dernier scan : 2 h      │
│                          │
├──────────────────────────┤
│                          │
│  Rappels opérateur       │
│  ──────────────          │
│  • Pense à valider la    │
│    run de ce matin       │
│  • OMDb non configuré —  │
│    -25% confidence sur   │
│    les matchs douteux    │
│  • Backup DB datant de   │
│    3 jours               │
│                          │
├──────────────────────────┤
│                          │
│  Raccourcis              │
│  ──────────────          │
│  Ctrl+S    Nouveau scan  │
│  Ctrl+K    Recherche     │
│  Ctrl+,    Paramètres    │
│  ?         Aide          │
│                          │
└──────────────────────────┘
```

## 4. États dynamiques (gestion des cas particuliers)

| Cas | Comportement |
|---|---|
| **Premier lancement (aucun run, lib vide)** | Hero : "Bienvenue Thomas." + résumé "Lance ton premier scan pour commencer." Section Dernier run remplacée par placeholder. Sections Santé/Activité masquées. CTA Scan en très grand. |
| **Scan en cours** | Section CTA Scan devient un compteur de progression. Le reste de la page reste lisible. Polling auto toutes les 2s pour mise à jour. |
| **Aucune alerte** | Section "Points à traiter" remplacée par message positif "✅ Aucun point à traiter. Tout va bien." |
| **DB inaccessible** | Page entière remplacée par message d'erreur + bouton "Réessayer" + lien "Diagnostiquer dans Aide". |
| **Mode démo actif** | Bandeau jaune en haut "Mode démo activé — les données ne sont pas réelles. [Quitter le mode démo]". |
| **Premier lancement après update** | Toast en bas à droite "v1.3.0-beta — Voir les nouveautés [Lire les notes]" (autoclose 10s). |

## 5. Source backend par section (récap)

| Section | Endpoint |
|---|---|
| Environment bar | `settings.get_settings()` + `get_global_stats()` (statut intégrations) |
| Hero résumé | À calculer côté frontend depuis l'état agrégé |
| Carte Dernier run | `get_run_summary("latest")` ou `run/list_runs?limit=1` |
| CTA Scan (état idle) | Action via `run/start_plan` |
| CTA Scan (état actif) | `run/get_run_status(active_run_id)` |
| Points à traiter | `get_home_suggestions(run_id)` (NOUVEAU à créer, ou agrégation frontend) |
| Santé bibliothèque | `get_global_stats().library.tier_distribution` |
| Activité récente | `run/list_runs?limit=3` (existant) |
| Inspecteur > rappels | Logique frontend (alertes locales basées sur l'état) |

## 6. Effort estimé

| Tâche | Effort |
|---|---|
| Backend `get_home_suggestions(run_id)` agrégation (peut être 100% frontend en v1) | 0.3 j |
| Frontend layout Accueil (6 sections + responsive) | 1.2 j |
| Frontend hero + résumé dynamique selon état | 0.4 j |
| Frontend carte Dernier run + états (run actif / pas de run / scan en cours) | 0.5 j |
| Frontend CTA Scan + Options drawer + état "scan en cours" avec polling | 0.6 j |
| Frontend Points à traiter (3-N suggestions cliquables) | 0.5 j |
| Frontend Santé bibliothèque (bargraph tiers) | 0.3 j |
| Frontend Activité récente (liste cliquable) | 0.2 j |
| Frontend Inspecteur droit Accueil (rappels + raccourcis) | 0.3 j |
| États dynamiques (premier lancement, scan, alertes, erreur DB) | 0.5 j |
| Tests E2E (navigation + états) | 0.4 j |
| **Total Accueil** | **~5.2 jours** |

## 7. Hors scope v1

- ❌ Personnalisation par utilisateur (réordonner les sections, masquer certaines)
- ❌ Widgets de tendance (Score 30J, Films par mois) — virés
- ❌ Podiums (Release Groups / Codecs / Sources) — déplacés vers Bibliothèque
- ❌ Card "Quoi de neuf" (note de release) — peut-être en v2
- ❌ Notification system avancé (juste toast simple en v1)
- ❌ Mode focus/cinéma (full screen sans chrome)

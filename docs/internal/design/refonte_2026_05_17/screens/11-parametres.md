# Spec — Paramètres (vue d'ensemble + 10 catégories)

Statut : **VALIDÉE** par Thomas le 2026-05-17.
Position dans la refonte : **Écran 11 / N**.
Cible : `web/dashboard/` (ESM uniquement, après migration B).

## 1. Layout général (sub-sidebar gauche — décision Thomas)

```
┌────────────────────────────────────────────────────────────────────────┐
│  Paramètres                  ☐ Mode expert  [🔍 Rechercher (Ctrl+K)] │
├──────────┬─────────────────────────────────────────────────────────────┤
│          │                                                              │
│ Sources  │  [Contenu de la catégorie sélectionnée]                    │
│ Analyse  │                                                              │
│ Nommage  │                                                              │
│ Biblio   │                                                              │
│ Intég.   │                                                              │
│ Notif.   │                                                              │
│ Serveur  │                                                              │
│ Apparence│                                                              │
│ Profils Q│                                                              │
│ Avancé   │                                                              │
│          │                                                              │
│ [Reset]  │                                                              │
└──────────┴─────────────────────────────────────────────────────────────┘
```

- **Sub-sidebar gauche** : 10 catégories cliquables (largeur ~200px)
- **Zone centrale** : champs de la catégorie sélectionnée
- **Pas d'inspecteur droit** (vue de config — replié par défaut selon spec 04 Shell)
- **Mode expert toggle** en haut à droite (cf section 3)
- **Recherche globale** dans tous les champs paramètres

## 2. Les 10 catégories

### 2.1 Sources

- **Roots** : liste des dossiers racines avec bouton ajouter/supprimer
- **Exclusions** : patterns glob d'exclusion (`*.tmp`, `_review/*`, etc.)

### 2.2 Analyse

- **Probe** : `ffprobe_path`, `mediainfo_path`, bouton "Tester / Installer"
- **Perceptuel** : `perceptual_enabled`, `perceptual_timeout`, `perceptual_parallelism_mode`
- **Sous-titres** : détection auto, langues attendues

### 2.3 Nommage

- **Templates** : `naming_movie_template` (default `{title} ({year})`), `naming_tv_template`
- **Options** : `windows_safe_names`, `lowercase_extensions`, séparateurs

### 2.4 Bibliothèque

- **Organisation** : `collection_folder_enabled`, `enable_tv_detection`
- **Nettoyage** : `move_empty_folders_enabled`, `cleanup_residual_folders_enabled`

### 2.5 Intégrations

5 services en cards séparées :

- **TMDb** : clé API + bouton Test + TTL cache (existant)
- **Jellyfin** : URL + clé API + Test + options refresh + sync watched (existant)
- **Plex** : URL + token + Test + options refresh (existant)
- **Radarr** : URL + clé API + Test (existant)
- **OMDb** : ✅ **maintenant visible** (cf spec 03). Toggle activer + clé + Test + seuil confidence

### 2.6 Notifications

- **Desktop** : toggles par événement (scan/apply/undo/erreurs)
- **Email** : SMTP host/port/user/password (advanced), destinataire, événements
- **Plugins** : hooks externes, timeout

### 2.7 Serveur distant

- **API REST** : activer, port, token (DPAPI), bouton restart
- **QR dashboard** : QR code + URL pour accès LAN
- **HTTPS** (advanced) : certificats path

### 2.8 Apparence

- **Thème** : Studio / Cinéma / Luxe / Neon (mais à reconsidérer après refonte design tokens v5)
- **Effets visuels** : sliders speed/glow/light (advanced)

### 2.9 Profils Qualité (catégorie dédiée — décision Thomas)

Vue dédiée pour éditer les seuils de tier et les poids des composantes du Score V2 :

```
┌────────────────────────────────────────────────────────────────────────┐
│  Profils Qualité                                                      │
│                                                                        │
│  Profil actif : [▾ CineSort V2]                                      │
│  Disponibles : Standard / CineSort V2 / Compact / Custom              │
│                                                                        │
│  ──── Seuils de tier ────                                            │
│  Platinum  : score >= [90]                                            │
│  Gold      : score >= [80]                                            │
│  Silver    : score >= [65]                                            │
│  Bronze    : score >= [45]                                            │
│  Reject    : score < 45                                               │
│                                                                        │
│  ──── Poids des composantes ────                                     │
│  Résolution     × [0.25]                                             │
│  Bitrate        × [0.20]                                             │
│  Codec          × [0.15]                                             │
│  Audio bitrate  × [0.20]                                             │
│  Audio channels × [0.10]                                             │
│  Subtitle FR    × [0.10]                                             │
│  Total = 1.00 ✓                                                       │
│                                                                        │
│  [💾 Sauvegarder comme nouveau profil]                                │
│  [↻ Re-calculer les scores avec ce profil]                           │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

- **Validation auto** : la somme des poids doit faire 1.00 (warning si != 1.00, save bloqué si > 1.05 ou < 0.95)
- **Bouton "Re-calculer"** : déclenche la même action que dans la vue Qualité (cf spec 10)

### 2.10 Avancé

- **Parallélisme** : `perceptual_parallelism_mode` (Auto / Max / Safe / Serial)
- **Onboarding** : `onboarding_completed` (toggle pour relancer le wizard)
- **MAJ** : `update_github_repo` + bouton "Vérifier maintenant"
- **Rétention historique** : slider 7-365 j (default 90 j selon spec 09)
- **Logs** : niveau de verbosité (DEBUG/INFO/WARNING)

## 3. Mode expert (toggle global)

- Position : en haut à droite de la vue Paramètres
- État persisté : `settings.expert_mode_enabled` (default `false` — décision Thomas)
- OFF : masque tous les champs taggés `advanced: true` (SMTP, parallelism, certificats HTTPS, slider effets, log level, etc.)
- ON : tout visible

## 4. Recherche globale

Champ "Rechercher" en haut. Filtrage live de tous les champs visibles + highlight des matches + ouverture auto de la catégorie qui contient le 1er match.

## 5. Persistance

- **Save automatique avec debounce 500ms** par champ (réutilise le pattern existant)
- Indicateur "✓ Sauvegardé à l'instant" en haut à droite après chaque save
- En cas d'erreur de save : toast "Erreur sauvegarde" + bouton Réessayer
- DPAPI géré côté backend (transparent côté UI) pour tous les `type: "api-key"`

## 6. Sécurité — actions dangereuses (cf [[feedback-cinesort-actions-dangereuses]])

| Action | Confirmation |
|---|---|
| **Reset des paramètres** (par catégorie ou tout) | Modale "Vraiment réinitialiser <catégorie> ? Action irréversible." + bouton danger |
| **Reset de la base de données** (Avancé) | Modale extra "Cela supprime TOUS les runs, l'historique, les scores et les analyses. Action TOTALEMENT irréversible." + bouton danger + countdown 3s |
| **Supprimer un root** des Sources | Modale "Vraiment supprimer ce root ? Les films de ce root resteront en DB mais ne seront plus scannés." |
| **Désactiver une intégration** | Toast d'info, pas de confirmation (réversible) |
| **Changer le thème** | Pas de confirmation (cosmétique) |
| **Re-calculer scores** (Profils Qualité) | Modale "Cette opération va re-scorer les 853 films classés (~5-10 min)." (cf spec 10) |

## 7. Source backend

| Donnée | Endpoint |
|---|---|
| Toutes les settings | `settings/get_settings()` (existant) |
| Save settings | `settings/save_settings(patch)` (existant) |
| Test connexion (TMDb/Jellyfin/Plex/Radarr/OMDb) | `integrations/test_<service>_connection(...)` (existants) |
| Reset settings | `settings/reset_settings(scope)` (NOUVEAU avec scope par catégorie) |
| Reset DB | `settings/reset_database()` (NOUVEAU) |
| Profils qualité | `quality/get_profiles()` + `quality/save_profile(profile)` + `quality/set_active_profile(name)` (NOUVEAU) |

## 8. Effort

| Tâche | Effort |
|---|---|
| Backend reset_settings(scope) + reset_database | 0.4 j |
| Backend profiles get/save/set_active | 0.5 j |
| Frontend layout sub-sidebar + zone centrale + state nav | 0.5 j |
| Frontend 10 catégories (champs + validation + save auto) | 2 j |
| Frontend mode expert (toggle + masquage advanced) | 0.2 j |
| Frontend recherche globale dans paramètres + highlight | 0.3 j |
| Frontend Profils Qualité (édition seuils + poids + validation total = 1.00) | 0.8 j |
| Frontend modales danger (reset settings / reset DB / supprimer root) | 0.4 j |
| Frontend test connexion inline pour chaque intégration | 0.4 j |
| Tests E2E | 0.4 j |
| **Total Paramètres** | **~5.9 jours** |

## 9. Hors scope v1

- ❌ Import/export de profils utilisateur (futur)
- ❌ Plugins externes (juste hooks notifications)
- ❌ Synchronisation des paramètres cloud
- ❌ Multi-utilisateurs avec paramètres par profil
- ❌ Onboarding wizard interactif au premier lancement (futur)
- ❌ Édition fine des templates de nommage (parsing custom, hors templates pré-définis)

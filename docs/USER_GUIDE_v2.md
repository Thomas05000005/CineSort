# Guide utilisateur CineSort v2

> Version : v1.2.0+ (refonte UI 2026-05) · Mise à jour : 2026-05-19
>
> Ce guide remplace l'ancien `MANUAL.md` pour la nouvelle interface (Shell 3 zones,
> écrans refondus, raccourcis FR). Le manuel legacy reste disponible pour
> rétrocompat le temps que les workflows soient entièrement portés.

---

## 1. Premier lancement

CineSort est une application desktop Windows distribuée sous forme d'un EXE
unique (~50 Mo, PyInstaller). Aucune installation, aucun service en arrière-plan.

### Démarrage

1. Double-cliquez sur `CineSort.exe`.
2. Au premier lancement, un wizard vous demande :
   - **Dossier racine** : où sont stockés vos films (ex. `\\NAS\Media\Films`)
   - **Clé API TMDb** : optionnelle mais fortement recommandée pour l'identification
   - **Profil qualité** : par défaut "CinemaLux" (équilibré). Modifiable plus tard.
3. La fenêtre principale s'ouvre sur l'**Accueil**.

### Mode REST API seul (sans UI desktop)

Pour ouvrir CineSort dans un navigateur ou contrôler depuis un autre appareil :

```cmd
CineSort.exe --api
```

Un QR code et un token REST s'affichent. Scannez avec votre téléphone ou ouvrez
l'URL indiquée dans un navigateur. Voir [§8 Serveur distant](#8-serveur-distant).

---

## 2. Layout général : Shell 3 zones

L'interface est divisée en 3 zones :

```
┌──────────┬──────────────────────────────────┬──────────┐
│ Sidebar  │      Vue centrale (Accueil,      │Inspecteur│
│  rail    │      Bibliothèque, etc.)         │  droit   │
│ 7 vues   │                                  │ contextuel│
└──────────┴──────────────────────────────────┴──────────┘
```

- **Sidebar gauche** : navigation entre 7 vues principales. Réductible (rail) ou
  étendue (texte + icônes). Pin/unpin avec Ctrl+B.
- **Vue centrale** : la vue active (Accueil, Traitement, etc.).
- **Inspecteur droit** : affiche le contexte de la sélection (groupe de doublons,
  film sélectionné, run cliqué dans Historique, etc.). Toggle avec Ctrl+I.

### Raccourcis clavier essentiels

| Raccourci | Action |
|---|---|
| Ctrl+B | Toggle sidebar (collapse / expand) |
| Ctrl+I | Toggle inspecteur droit |
| Ctrl+K | Palette de recherche globale |
| Ctrl+, | Ouvrir Paramètres |
| Alt+1 | Accueil |
| Alt+2 | Traitement |
| Alt+3 | Bibliothèque |
| Alt+4 | Qualité |
| Alt+5 | Historique |
| Alt+6 | Paramètres |
| Alt+7 | Aide |

---

## 3. Les 7 vues principales

### 3.1 Accueil

Vue d'arrivée avec :
- **Hero** : compteur films totaux + score moyen + tier dominant.
- **Dernier run** : carte avec date, status, films traités.
- **Activité 7 jours** : timeline visuelle des derniers scans.
- **CTA scan** : bouton "▶ Lancer un nouveau scan" → ouvre Traitement.
- **Santé bibliothèque** : bargraph répartition Platinum/Gold/Silver/Bronze/Reject.
- **Suggestions** : 3 priorités d'action (subs FR manquants, sagas incomplètes, films à re-acquérir).
- **Inspecteur droit** : version + onboarding + raccourcis clavier.

### 3.2 Traitement (workflow 5 étapes)

```
Analyse → Vérification → Validation → Doublons → Apply
```

Chaque étape a son propre compteur (films scannés, conflits, validés, doublons groupes, appliqués).
La nav est libre entre étapes passées via fragment URL `#step-X`.

**Aujourd'hui** : la version refondue affiche les compteurs et redirige vers le
workflow Bibliothèque legacy pour l'édition fine (drawer scan options, table
dense, validation rapide, apply avec confirmation countdown 3 s). Le portage
complet du workflow natif arrive en itération future.

### 3.3 Bibliothèque

Grille de posters TMDb (auto-fill responsive) + chips de filtres par tier +
recherche + tri + toggle Grille/Tableau.

- **Filtre tier** : 1 chip "Tous" + 6 chips par tier avec compteurs.
- **Recherche** : debounced 250 ms, filtre par titre.
- **Tri** : 8 options (titre A→Z/Z→A, année, score, durée).
- **Clic carte** : ouvre la page film (`/film/<row_id>`).
- **Sélection multi** : checkbox + barre Espace. Toolbar contextuelle avec
  Analyser perceptuel / Re-scanner / Exporter / Marquer pour suppression.
- **Modal Détail Film** : poster + alertes humanisées (cf §5) + candidats TMDb + actions.

### 3.4 Qualité

Audit transverse en 6 sections :
1. **Distribution tiers** : bargraph horizontal cliquable (→ filtre Bibliothèque).
2. **À remplacer** : top Reject (lien vers `/bibliotheque?filter=tier_reject`).
3. **Sagas incomplètes** : compteur + suggestions du Librarian.
4. **Subs FR** : combien de films sans sous-titres FR + CTA "Configurer".
5. **Décennies** : histogramme cliquable (→ filtre Bibliothèque par décennie).
6. **Évolution 30 j** : delta Score moyen sur les 30 derniers jours.

### 3.5 Historique

Timeline groupée par jour (Aujourd'hui, Hier, "5 mai") des runs.
- **Filtres** : statut, période, type (plan/apply), recherche.
- **Toggle** Timeline / Tableau dense.
- **Inspecteur droit** : 4 onglets (Films / Apply / Doublons / Log) avec liens
  directs vers les vues correspondantes.
- **Actions** sur le run sélectionné : voir rapport, reprendre, **annuler l'apply** 
  (confirmation), **supprimer le run** (confirmation, rétention auto 90 j).

### 3.6 Paramètres (sub-sidebar 10 catégories)

- **Sources** : dossiers racines + exclusions.
- **Analyse** : ffprobe, mediainfo, analyse perceptuelle, sous-titres.
- **Nommage** : templates de renommage + Windows-safe.
- **Bibliothèque** : collection folder, détection TV, nettoyage.
- **Intégrations** : TMDb, Jellyfin, Plex, Radarr, OMDb.
- **Notifications** : desktop, SMTP, hooks.
- **Serveur distant** : REST API, QR code.
- **Apparence** : thèmes Studio / Cinéma / Luxe / Neon.
- **Profils Qualité** ⚡ : édition des **seuils de tier** (Platinum/Gold/Silver/Bronze)
  via inputs numériques. Validation Platinum > Gold > Silver > Bronze. Sauvegarde
  via `settings/save_settings`. Les poids et bonus restent dans la vue legacy.
- **Avancé** : parallélisme, MAJ, rétention historique, log level.

### 3.7 Aide

- Documentation 8 sujets : Premier scan, Score V2, Sous-titres, Doublons, Profils
  qualité, Sauvegardes, Paramètres avancés, FAQ.
- Raccourcis clavier (cf §2 ci-dessus).
- Diagnostic : version + plateforme + état des intégrations. Bouton "Copier diagnostic".
- Logs : bouton "Ouvrir dossier logs".
- À propos : version + liens GitHub + licence.

---

## 4. Le Score V2 (système de tiers)

Chaque film est noté de 0 à 100 selon une combinaison pondérée de 6 composantes :

| Composante | Poids | Description |
|---|---|---|
| Résolution | 25 % | 4K > 1080p > 720p > SD |
| Bitrate vidéo | 20 % | Bonus si > seuil pour la résolution |
| Codec | 15 % | HEVC > AV1 > H.264 > MPEG |
| Bitrate audio | 20 % | DTS-HD/TrueHD > DTS > AAC > MP3 |
| Canaux audio | 10 % | 7.1 > 5.1 > 2.0 > mono |
| Sous-titres FR | 10 % | Forced + Full > Full > aucun |

Le score total détermine le **tier** :

| Tier | Seuil par défaut | Couleur |
|---|---|---|
| Platinum | ≥ 85 | violet |
| Gold | 68–84 | or |
| Silver | 54–67 | argent |
| Bronze | 30–53 | bronze |
| Reject | < 30 | rouge |

Les seuils sont **modifiables** dans Paramètres > Profils Qualité.

### Analyse perceptuelle (Modal Score V2)

Pour comprendre pourquoi un film a un score donné, ouvrez la Modal Analyse
Perceptuelle (bouton "▶ Analyser perceptuel" depuis un film ou un groupe de doublons).

5 états :
- **Normal** : score V2 + métriques vidéo + métriques audio + breakdown 6 composantes + verdicts croisés.
- **Missing** : CTA "Lancer l'analyse" (~30 s ffmpeg).
- **Disabled** : redirige vers Paramètres si module désactivé.
- **No ffmpeg** : redirige vers Paramètres > Outils vidéo.
- **Error** : message + retry.

Métriques exposées : SSIM self-ref (détection faux upscale), upscale_verdict,
grain analysis, HDR format, codec efficiency, empreinte Chromaprint, cutoff
spectral (détection audio lossy), dynamic range.

---

## 5. Les alertes humanisées (warning_flags)

Le système d'identification CineSort peut détecter divers problèmes. Chaque
alerte est mappée à un libellé humain + icône + description + niveau de sévérité
(critical / warning / info) + action contextuelle.

### Alertes les plus fréquentes

| Code | Icône | Label | Sévérité |
|---|---|---|---|
| `subtitle_missing_fr` | 💬 | Sous-titres FR manquants | warning |
| `subtitle_missing` | 💬 | Sous-titres manquants | warning |
| `nfo_title_mismatch` | 🏷 | Titre NFO incohérent | warning |
| `nfo_year_mismatch` | 📅 | Année NFO incohérente | critical |
| `title_ambiguity_detected` | 🏷 | Titre ambigu (ex : Dune 1984 vs 2021) | warning |
| `tmdb_year_delta` | 📅 | Année TMDb décalée | info |
| `omdb_disagree` | 🔍 | OMDb en désaccord avec TMDb | warning |
| `root_level_source` | 📁 | Source non identifiée (renommé à la main ?) | info |
| `not_a_movie` | 🎬 | Pas un film ? (peut-être un épisode TV) | critical |
| `integrity_header_invalid` | 🛡 | Intégrité fichier invalide | critical |
| `duplicate_cross_root` | 🔁 | Doublon dans 2 dossiers racines | warning |
| `low_bitrate` | 📉 | Bitrate vidéo anormalement faible | info |
| `runtime_mismatch` | ⏱ | Durée incohérente avec TMDb | critical |

Les alertes apparaissent sur la fiche film, les groupes de doublons, et la grille
Bibliothèque (badge ⚠ avec compteur).

---

## 6. Workflow type : du scan à l'apply

### Étape 1 — Lancer un scan

Depuis **Accueil** ou **Traitement** : "▶ Lancer un nouveau scan". CineSort
parcourt les dossiers racines configurés, identifie chaque film via TMDb,
calcule le Score V2, détecte les doublons.

Durée : ~5-15 min pour 1000 films (selon CPU et nombre de probes ffmpeg).

### Étape 2 — Vérification

CineSort affiche les **cas à vérifier** : faible confiance d'identification,
NFO incohérent, runtime mismatch, etc. Vous pouvez :
- Approuver le candidat proposé
- Changer le candidat TMDb (clic sur un autre candidat avec poster)
- Ignorer une alerte
- Re-scanner ce film seul (re-probe + re-match)
- Marquer pour suppression (déplacé vers `_user_marked_for_deletion/` à l'apply)

### Étape 3 — Validation

Approuvez en masse les films à confiance haute (≥ 90 %). Les conflits sont
remontés en haut de liste.

### Étape 4 — Doublons

CineSort liste les groupes de fichiers identifiés comme doublons (même TMDb id).
Pour chacun : cartes A/B comparées (score, taille, codec, source). Le **winner**
est recommandé automatiquement. Vous pouvez :
- Garder le winner par défaut
- Choisir manuellement A ou B
- "Comparer en détail" → modal avec frames côte-à-côte + audio fingerprint
- "Analyser perceptuel" → Modal Score V2

### Étape 5 — Apply

Renommage + déplacement physique sur disque. **Confirmation modale** avec liste
des opérations + countdown 3 s pour les bulks > 50 fichiers (sécurité anti-clic).

Tout est **réversible** : un undo restaure les fichiers à leur emplacement
initial (tant qu'un nouvel apply n'a pas eu lieu).

---

## 7. Actions dangereuses : confirmations obligatoires

CineSort applique une règle stricte : **toute action destructive demande une
confirmation supplémentaire**, avec liste des éléments concernés, conséquence
claire, et délai 3 s si > 50 éléments.

| Action | Confirmation |
|---|---|
| Marquer un film pour suppression | Modal avec titre + chemin + bouton Confirmer en rouge |
| Marquer N films pour suppression (bulk) | Modal liste 5 + "et N autres" + countdown 3 s si N > 50 |
| Réinitialiser les paramètres | Modal avec "Tous les réglages perdus" + liste scopes |
| Réinitialiser la base de données | Modal danger maximale + saisie du mot "CONFIRMER" |
| Annuler l'apply d'un run | Confirmation avec impact (déplacements inversés) |
| Supprimer un run de l'historique | Confirmation (les fichiers vidéo ne sont pas touchés) |

**Aucun renommage en bulk** : par contrainte de sécurité (cf [CLAUDE.md] :
"Ne JAMAIS modifier le titre des films au-delà du renommage configuré"), il n'y
a pas de bouton "renommer N films" dans l'interface.

Les fichiers marqués pour suppression vont dans un bucket
`_user_marked_for_deletion/` (préfixe `_` pour tri alpha), réversible via undo.
L'utilisateur supprime manuellement ce dossier quand il est sûr.

---

## 8. Serveur distant

CineSort embarque un serveur REST local (port 8642 par défaut). 3 usages :

### 8.1 Dashboard navigateur sur même PC

Ouvrez `http://localhost:8642/dashboard/` dans Edge/Chrome/Firefox.

### 8.2 Dashboard depuis téléphone ou autre PC

Au lancement avec `--api` ou depuis Paramètres > Serveur distant : un QR code
affiche l'URL `http://<IP>:8642/dashboard/?ntoken=<token>`. Scannez-le.

Le token est obligatoire (autorisation native), à durée de vie 24 h.

### 8.3 Automation via API

Toutes les méthodes UI sont exposées en JSON. Voir [`docs/api/`](api/) pour le
catalogue (50+ endpoints).

---

## 9. Sauvegarde et restauration

CineSort stocke ses données dans `%LOCALAPPDATA%\CineSort\` :
- `settings.json` : tous les paramètres (clés API en DPAPI)
- `state.db` : SQLite avec films, probes, runs, doublons, perceptual
- `runs/` : un dossier par scan avec plan.jsonl + reports

### Pour sauvegarder

Copiez le dossier `%LOCALAPPDATA%\CineSort\` entier vers une destination externe.

### Pour restaurer

Remplacez le contenu de `%LOCALAPPDATA%\CineSort\` par votre sauvegarde, puis
relancez l'EXE. **Note** : les clés API DPAPI sont liées au compte Windows ;
elles devront être re-saisies sur un autre profil.

---

## 10. Dépannage rapide

| Symptôme | Solution |
|---|---|
| L'EXE ne se lance pas | Vérifiez que Windows Defender n'a pas mis en quarantaine. Voir Aide > Diagnostic. |
| "ffmpeg introuvable" | Paramètres > Analyse > Outils vidéo > "Installer". |
| Tous les films "Reject" | Profils Qualité a peut-être été modifié avec des seuils trop élevés. Restaurer les défauts. |
| Aucun poster TMDb | Vérifiez la clé API TMDb dans Paramètres > Intégrations. |
| Doublons non détectés | Lancez un nouveau scan (Traitement > ▶ Lancer). Les anciens runs ne sont pas re-analysés. |
| Apply échoue | Vérifiez les permissions d'écriture sur les dossiers racines (UNC + NAS). |

Pour plus de détails : voir [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

---

## 11. Liens utiles

- **Code source** : [github.com/Thomas05000005/CineSort](https://github.com/Thomas05000005/CineSort)
- **Issues / Bugs** : [github.com/Thomas05000005/CineSort/issues](https://github.com/Thomas05000005/CineSort/issues)
- **Releases / Notes** : [github.com/Thomas05000005/CineSort/releases](https://github.com/Thomas05000005/CineSort/releases)
- **Documentation développeur** : [`README_DEV.md`](README_DEV.md)
- **Architecture interne** : [`internal/CLAUDE.md`](internal/CLAUDE.md)
- **Refonte UI 2026-05** : [`internal/design/refonte_2026_05_17/README.md`](internal/design/refonte_2026_05_17/README.md)

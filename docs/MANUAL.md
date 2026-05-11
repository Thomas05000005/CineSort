# CineSort — Manuel utilisateur

> Version v7.7.0 — Mai 2026
> Cible : utilisateur Windows non-développeur. Aucun jargon dev sauf section Concepts.

---

## Table des matières

- [1. Démarrage rapide](#1-démarrage-rapide)
  - [1.1 Installation](#11-installation)
  - [1.2 Wizard premier lancement (5 étapes)](#12-wizard-premier-lancement-5-étapes)
  - [1.3 Lancer son premier scan](#13-lancer-son-premier-scan)
- [2. Concepts de base](#2-concepts-de-base)
  - [2.1 Glossaire métier](#21-glossaire-métier)
  - [2.2 Workflow scan → review → apply → undo](#22-workflow-scan--review--apply--undo)
  - [2.3 Système de scoring (CinemaLux + V2)](#23-système-de-scoring-cinemalux--v2)
- [3. Configuration](#3-configuration)
  - [3.1 Réglages essentiels](#31-réglages-essentiels)
  - [3.2 Intégrations](#32-intégrations)
  - [3.3 Notifications desktop & email](#33-notifications-desktop--email)
  - [3.4 API REST + Dashboard distant](#34-api-rest--dashboard-distant)
- [4. Workflows avancés](#4-workflows-avancés)
  - [4.1 Multi-root scan](#41-multi-root-scan)
  - [4.2 Mode bibliothécaire (suggestions)](#42-mode-bibliothécaire-suggestions)
  - [4.3 Détection séries TV](#43-détection-séries-tv)
  - [4.4 Analyse perceptuelle (LPIPS, grain v2, score V2)](#44-analyse-perceptuelle-lpips-grain-v2-score-v2)
  - [4.5 Watch folder (mode planifié)](#45-watch-folder-mode-planifié)
  - [4.6 Plugin hooks post-action](#46-plugin-hooks-post-action)
  - [4.7 Rapports email](#47-rapports-email)
  - [4.8 Watchlist Letterboxd / IMDb](#48-watchlist-letterboxd--imdb)
- [5. Dépannage rapide](#5-dépannage-rapide)
- [6. FAQ utilisateurs (40+ questions)](#6-faq-utilisateurs-40-questions)
- [7. Raccourcis clavier](#7-raccourcis-clavier)
- [8. Mises à jour & support](#8-mises-à-jour--support)

---

## 1. Démarrage rapide

### 1.1 Installation

CineSort est une application Windows portable. **Aucun installeur, aucun droit administrateur requis.**

1. Va sur la page [GitHub Releases](https://github.com/Thomas05000005/CineSort/releases) du projet.
2. Télécharge le fichier `CineSort.exe` de la dernière version.
3. Place-le dans le dossier de ton choix (par exemple `C:\Tools\CineSort\`).
4. Double-clique pour lancer.

> Pas besoin de Python, ni de droit admin, ni de WebView2 sur Windows 11
> (déjà inclus). Sur Windows 10, l'installeur WebView2 te sera proposé
> automatiquement si manquant.

**Premier démarrage :** un splash screen apparait pendant 3-5 secondes, puis la fenêtre principale s'ouvre.

> Astuce : si ton antivirus bloque le `.exe`, c'est un faux positif courant
> avec PyInstaller. Voir la [FAQ](#installation--lancement).

### 1.2 Wizard premier lancement (5 étapes)

Au tout premier lancement, un assistant 5 étapes te guide :

1. **Bienvenue** — présentation rapide. Clique « Continuer ».
2. **Dossier racine** — indique le chemin de ton dossier qui contient tes films
   (ex. `D:\Films`). Tu peux en ajouter plusieurs ensuite (multi-root). La validation
   te dit en temps réel si le dossier existe et est accessible.
3. **Clé API TMDb** — colle ta clé TMDb (gratuite, voir
   [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api)). CineSort
   teste la connexion en direct. Tu peux sauter cette étape mais l'enrichissement
   métadonnées sera désactivé.
4. **Test rapide** — un mini-scan sur 5 films de ton dossier pour te montrer un
   aperçu : titre détecté, année, score qualité, score de confiance.
5. **Terminé** — récap, lien vers la documentation, bouton « Lancer mon premier scan ».

Le wizard ne réapparait plus ensuite. Tu peux le rejouer via **Paramètres → Avancé → Relancer le wizard**.

### 1.3 Lancer son premier scan

Une fois la config initiale terminée :

1. Va sur la vue **Accueil** (Alt+1) ou **Bibliothèque** (Alt+2).
2. Clique sur **« Analyser ma bibliothèque »** (gros bouton bleu).
3. Le scan démarre en arrière-plan. Une barre de progression affiche :
   - le nombre de films analysés / total,
   - la vitesse (films/seconde),
   - l'ETA (temps restant estimé).
4. Tu peux annuler à tout moment (l'app sauvegarde l'état partiel).

**Combien de temps ?** Compter ~1 seconde par film en moyenne, plus ~5 secondes
pour la première requête TMDb. Pour 1000 films : 15-25 minutes premier scan,
puis ~2 minutes les fois suivantes (cache incrémental).

**À la fin du scan :** tu es redirigé automatiquement vers la vue
**Validation** pour réviser les changements proposés. Voir [§ 2.2](#22-workflow-scan--review--apply--undo).

---

## 2. Concepts de base

### 2.1 Glossaire métier

| Terme | Définition |
|---|---|
| **Tier** | Palier qualité final. 5 niveaux : Platinum > Gold > Silver > Bronze > Reject. |
| **Score V2** | Note composite /100 (CinemaLux v2). Pondère Vidéo 60 %, Audio 35 %, Cohérence 5 %. Inclut le perceptuel. |
| **Score V1** | Ancien système (avant v7.5.0), basé uniquement sur métadonnées. Conservé pour compatibilité. |
| **Confidence** | Certitude du match TMDb (0-1). 0,95+ certain, 0,7-0,95 forte, 0,5-0,7 moyenne, < 0,5 faible. |
| **Probe** | Analyse technique d'un fichier vidéo (codec, résolution, bitrate, audio) via ffprobe/mediainfo. |
| **Run** | Une exécution de scan complète (identifiant unique, journal dédié). |
| **Plan** | Liste des changements proposés (renommages + déplacements) générée à la fin du scan. |
| **Apply** | Exécuter le plan pour de vrai (modifie le disque). |
| **Dry-run** | Simulation : calcule tout sans toucher aux fichiers. Recommandé au 1er passage. |
| **Undo** | Annulation d'un apply (par batch ou par film). Crash-safe via journal write-ahead. |
| **Quarantine** | Dossier `_review/` pour les fichiers non valides (sans match TMDb, doublons, conflits, corrompus). |
| **NFO** | XML métadonnées Kodi/Jellyfin/Emby (titre, année, IMDb/TMDb id) à côté de la vidéo. |
| **TMDb** | The Movie Database. Service gratuit qui fournit titre, année, poster, collection. |
| **Jellyfin / Plex** | Serveurs media. CineSort peut déclencher leur refresh après un apply. |
| **Radarr** | Gestionnaire de films. CineSort peut proposer des upgrades qualité via Radarr. |
| **Edition** | Version particulière (Director's Cut, Extended, IMAX, Theatrical, Unrated). |
| **Saga / Collection TMDb** | Regroupement de films liés (LOTR, MCU). Ranger ensemble dans `_Collection/`. |
| **Perceptual** | Vraie qualité image et son (pas juste métadonnées) : fake 4K, DNR excessif, fake HDR, etc. |
| **LPIPS** | Mesure scientifique de similarité visuelle (modèle ML). Plus fiable que SSIM/PSNR. |
| **Grain era** | Classification du grain pellicule par époque (16mm, 35mm classic/modern, digital, UHD/DV). |
| **DRC** | Dynamic Range Compression audio. Cinema = écarts conservés, broadcast = très comprimé. |
| **SSIM** | Structural Similarity Index. Compare structure+luminance+contraste. Sert à détecter les fake 4K. |
| **Chromaprint** | Empreinte audio (fpcalc). Détecte deux versions partageant la même bande son. |
| **Watch folder** | Mode surveillance : scan automatique quand un nouveau film apparait. |
| **Plugin hook** | Script externe (Python, .bat, .ps1) déclenché après un événement. |
| **Smart playlist** | Filtre sauvegardé dans la bibliothèque (ex. « tous les Nolan en 4K HDR »). |
| **Banding** | Défaut visuel : bandes visibles dans ciels/dégradés. Compression trop agressive. |
| **Upscale suspect** | Fichier annoncé 4K mais bitrate trop bas → 1080p étiré. |
| **Re-encode dégradé** | Fichier ré-encodé avec qualité trop basse (perte visible). |
| **HDR10+ / Dolby Vision** | Standards HDR avancés (contraste, couleurs précises). |

### 2.2 Workflow scan → review → apply → undo

```
+---------+    +----------+    +-------+    +--------+
|  SCAN   | -> |  REVIEW  | -> | APPLY | -> |  UNDO  |
+---------+    +----------+    +-------+    +--------+
   |               |              |              |
   v               v              v              v
 Analyse        Tu valides    Modifie        Annule si
 + propose      ou rejettes   ton disque     besoin (par
 changements    chaque film   (dry-run        batch ou par
                              recommandé      film)
                              au 1er essai)
```

**1. Scan** — analyse chaque film, propose un nouveau nom + un dossier cible.
Pas de modification disque.

**2. Review (Validation)** — tu vois la liste des changements. Tu peux :
- Approuver tout en un clic (« Approuver les sûrs » utilise le seuil de confiance auto).
- Rejeter ce qui te semble douteux.
- Inspecter chaque film en détail (badges qualité, sous-titres, conflits, doublons).
- Sauvegarder tes décisions (Ctrl+S) pour les reprendre plus tard.

**3. Apply** — exécute les changements. **Toujours en dry-run la première fois !**
Décoche « Dry-run » uniquement quand tu es confiant. Le journal write-ahead garantit
que même un crash en plein milieu n'abime pas ta bibliothèque.

**4. Undo** — vue Application → onglet Historique. Tu peux annuler :
- Un batch entier (toutes les modifs d'un apply).
- Sélectivement film par film (Undo v5).
Conflits gérés (fichier modifié depuis) : redirigés vers `_review/_undo_conflicts`.

### 2.3 Système de scoring (CinemaLux + V2)

Chaque film reçoit une **note finale sur 100** + un **tier** parmi 5 paliers :

| Tier | Score | Signification |
|---|---|---|
| **Platinum** | 90-100 | Excellence : 4K HDR Dolby Atmos sans défaut |
| **Gold** | 75-89 | Très bonne version : 1080p propre ou 4K standard |
| **Silver** | 55-74 | Correct : DVD ou 720p |
| **Bronze** | 35-54 | Limite : basse résolution ou encode dégradant |
| **Reject** | 0-34 | À refaire : fake 4K, audio mono, fichier corrompu |

**Score V2 (recommandé, défaut)** combine :

- **Vidéo (60 %)** — résolution, codec, bitrate, HDR, banding, grain
- **Audio (35 %)** — format (Atmos > TrueHD > DTS-HD > FLAC > AC3 > AAC), canaux, langue, commentary
- **Cohérence (5 %)** — sous-titres présents, NFO valide, intégrité fichier

**Score V1 (legacy)** : ancien système basé uniquement sur les métadonnées. Conservé pour les
rapports antérieurs à la migration 011. Toggle dans Paramètres → Score → `composite_score_version`.

**Ajustements contextuels** (V2 uniquement) :

- Bonus patrimoine pré-1970 (+8), classique pré-1995 (+4)
- Malus film récent post-2020 sans codec moderne (-4)
- Pénalités encode (upscale -8, re-encode -6, 4K light -3)
- Pénalité audio commentary-only (-15)

---

## 3. Configuration

### 3.1 Réglages essentiels

Accède aux paramètres via la sidebar (icône engrenage, Alt+8). 9 groupes organisés
par intention.

**Dossiers racine (multi-root)** — Paramètres → Essentiel → Dossiers racine.
Liste éditable : ajoute/supprime des chemins (SSD + NAS + disque externe ensemble).
Validation auto : doublons détectés, imbrications signalées, dossiers inaccessibles
ignorés avec warning.

**Clé API TMDb** — Paramètres → Essentiel → TMDb. Gratuit et indispensable pour
l'enrichissement métadonnées (titre original, année, poster, collection). Ta clé
est protégée par DPAPI Windows (chiffrée avec ton compte utilisateur).

**Profil de renommage** — Paramètres → Essentiel → Renommage. 5 presets disponibles :

| Preset | Exemple |
|---|---|
| `default` | `Inception (2010)` |
| `plex` | `Inception (2010) {tmdb-27205}` |
| `jellyfin` | `Inception (2010) [1080p]` |
| `quality` | `Inception (2010) [1080p hevc]` |
| `custom` | Tu écris ton propre template |

20 variables disponibles : `{title}`, `{year}`, `{resolution}`, `{video_codec}`,
`{hdr}`, `{audio_codec}`, `{channels}`, `{quality}`, `{score}`, `{tmdb_id}`,
`{tmdb_tag}`, `{original_title}`, `{source}`, `{bitrate}`, `{container}`,
`{series}`, `{season}`, `{episode}`, `{ep_title}`, `{edition}`.

Aperçu en temps réel quand tu modifies le template (mock Inception).

### 3.2 Intégrations

**Jellyfin** — Paramètres → Intégrations → Jellyfin.

- URL serveur (`http://192.168.1.10:8096`) + clé API.
- Toggle « Rafraîchir après apply » : déclenche un refresh library Jellyfin
  automatiquement quand tu apply un changement.
- Toggle « Synchroniser le statut vu » (Phase 2) : snapshot avant apply, restauration
  après refresh. Tu ne perds plus tes statuts de visionnage quand tu renommes des films.
- Bouton « Tester la connexion » + bouton « Vérifier la cohérence » (validation
  croisée chemin/tmdb_id/titre).

**Plex** — Paramètres → Intégrations → Plex.

- URL + token X-Plex-Token (récupérable via plex.tv/account).
- Choix de la library à rafraîchir.
- Toggle refresh auto après apply.
- Test connexion, sync report.

**Radarr** — Paramètres → Intégrations → Radarr.

- URL + clé API.
- Test connexion.
- Vue **Bibliothèque distante** : Radarr propose les upgrades qualité (films notés
  Bronze ou Reject avec une meilleure version disponible). Tu peux déclencher
  un MoviesSearch en un clic.

### 3.3 Notifications desktop & email

**Notifications Windows** — Paramètres → Notifications.

Toasts natifs Win32 (zéro dépendance). 5 événements activables individuellement :

- Scan terminé
- Apply terminé
- Undo terminé
- Erreur critique
- Erreur de scan

Les notifications s'affichent **uniquement quand la fenêtre CineSort n'a pas le
focus** (pas de spam quand tu travailles dans l'app).

**Rapport email** — Paramètres → Notifications → Email.

Configuration SMTP standard :

- Hôte SMTP (ex. `smtp.gmail.com`), port (587 STARTTLS ou 465 SSL).
- Utilisateur + mot de passe (chiffré DPAPI).
- Adresse(s) destinataire.
- Triggers : envoi après scan, après apply (chacun toggle).

Bouton « Tester l'envoi » avec données mock pour valider la config.

### 3.4 API REST + Dashboard distant

**Activation** — Paramètres → API REST.

- Toggle « Activer l'API ».
- Port (défaut 8642).
- Token Bearer : génère un token long (≥ 32 caractères) si tu bind sur 0.0.0.0
  (LAN). Si trop court, CineSort retombe sur 127.0.0.1 pour ta sécurité.
- HTTPS optionnel : fournis cert + key (`openssl req -x509 ...`).

**Accès au dashboard** depuis ton téléphone, tablette ou autre PC du réseau :

```
http://<ip-de-ton-pc>:8642/dashboard/
```

L'IP locale est auto-détectée et affichée dans la carte « Accès distant » de la
page Accueil, avec un **QR code à scanner** pour appairer ton téléphone en un coup.

10 vues disponibles à distance : status, logs live, bibliothèque, runs, review,
qualité, Jellyfin, Plex, Radarr, réglages. **Parité quasi-totale avec le desktop.**

> Sécurité : rate limiting 5 échecs / 60s → 429. Aucune action destructive sans
> confirmation. CORS strict.

---

## 4. Workflows avancés

### 4.1 Multi-root scan

Tu as plusieurs sources (SSD principal + NAS + disque externe) ? Tu peux les
scanner ensemble en un seul run.

**Configuration :** Paramètres → Essentiel → Dossiers racine. Ajoute autant de
chemins que tu veux.

**Comportement :**

- Chaque film conserve son `source_root` (le disque d'origine).
- Détection des doublons cross-root automatique (warning `duplicate_cross_root`).
- Chaque root garde ses propres dossiers `_review/`, `_Collection/`, `_Vide/`.
- Si un root est inaccessible (NAS débranché), il est ignoré avec un warning,
  pas d'erreur bloquante.

### 4.2 Mode bibliothécaire (suggestions)

Vue **Qualité → Onglet Bibliothèque** (toggle Run / Bibliothèque).

CineSort agrège l'état global de ta collection et te propose 6 types de
suggestions triées par priorité :

| Suggestion | Priorité | Exemple |
|---|---|---|
| **Codec obsolète** | Haute | « 12 films en xvid/divx à ré-encoder » |
| **Doublons** | Haute | « 3 doublons détectés, 8 GB récupérables » |
| **Sous-titres manquants** | Moyenne | « 47 films sans sous-titres FR » |
| **Non identifiés** | Moyenne | « 5 films sans match TMDb à valider » |
| **Basse résolution** | Basse | « 23 films en SD à upgrader » |
| **Collections info** | Basse | « 3 sagas Marvel détectées dans ta biblio » |

Un **health score** sur 100 indique l'état général de ta bibliothèque.

### 4.3 Détection séries TV

**Activation :** Paramètres → Avancé → Détection TV.

Quand activée, CineSort détecte les séries (au lieu de les ignorer) via 4 patterns :

- `S01E01`, `S01.E01` (avec/sans point)
- `1x01`
- `Episode N` ou `Saison N Episode N` (texte FR/EN)

Structure cible créée par apply :

```
Breaking Bad (2008)/
  Saison 01/
    S01E01 - Pilot.mkv
    S01E02 - Cat's in the Bag.mkv
  Saison 02/
    S02E01 - Seven Thirty-Seven.mkv
```

Métadonnées TMDb TV (titre épisode, etc.) récupérées si match exact série + saison + épisode.

### 4.4 Analyse perceptuelle (LPIPS, grain v2, score V2)

**Activation :** Paramètres → Perceptuel → Activer l'analyse perceptuelle.

L'analyse perceptuelle regarde la **vraie qualité** image et son, pas seulement les
métadonnées du fichier. Elle détecte :

- **Fake 4K** (upscale 1080p étiré, FFT 2D)
- **DNR excessif** (lissage qui efface le grain pellicule)
- **Bruit numérique** vs grain naturel (classifier signature temporelle + spatiale)
- **HDR mal encodé** (HDR10+ Pass 2 multi-frame, Dolby Vision profils 5/7/8)
- **Banding** (bandes visibles dans les ciels)
- **DRC audio** (cinema / standard / broadcast)
- **Clipping audio** (saturation)
- **AAC holes, MP3 shelf** (artefacts compression)
- **Atmos / TrueHD / DTS-HD** validation

**Coût performance :** ~10 à 60 secondes par film selon les options. Privilégie
l'analyse à la demande (bouton « Analyser perceptuellement » dans l'inspecteur)
plutôt qu'en batch sur 5000 films.

**Score V2** intègre ces signaux dans la note finale. Tu peux activer/désactiver
chaque module (LPIPS, grain v2, scene detection, HDR Pass 2, etc.) individuellement.

#### Toggle Composite Score V1 / V2 (depuis v7.7.0)

**Emplacement :** Paramètres → Analyse → Scoring qualité → « Score composite ».

CineSort propose deux moteurs de score composite qui cohabitent :

| Version | Description | Statut |
|---|---|---|
| **V1 (stable)** | Moteur historique, pondération simple Vidéo 60 % + Audio 40 %, 10 verdicts croisés. | Défaut |
| **V2 (avancé)** | Vidéo 60 % + Audio 35 % + Cohérence 5 %, 9 règles d'ajustement contextuel (HDR manquant, AV1 AFGS1, fake lossless, IMAX, DV profil 5, grain partiel DNR, etc.), confidence-weighted scoring, 5 tiers Platinum/Gold/Silver/Bronze/Reject. | Opt-in |

**Comment activer V2 :**

1. Paramètres → Analyse → Scoring qualité.
2. Choisis « Composite Score V2 (avancé) » dans le dropdown « Score composite ».
3. Sauvegarde — la prochaine analyse perceptuelle (ou le prochain scan déclenché)
   utilisera V2 comme score principal.

> **Aucune migration automatique.** Tes scores existants restent calculés en V1
> tant que tu ne relances pas une analyse perceptuelle sur le film concerné. Le
> score V2 est de toute façon stocké en parallèle pour les nouveaux scans, donc
> tu peux basculer V1 ↔ V2 à tout moment sans perdre de données. Pour
> recalculer la totalité de ta bibliothèque en V2, lance un nouveau scan complet
> avec analyse perceptuelle activée.

**Quel choix faire ?**

- Tu utilises CineSort depuis v7.5.0 ou avant → **garde V1** (continuité des
  scores). Bascule V2 quand tu seras prêt à voir tes anciens films re-scorés.
- Nouvelle installation v7.7.0 → tu peux activer V2 dès le départ pour
  bénéficier des règles d'ajustement contextuel (notamment pour les masters
  IMAX, AV1 AFGS1, et la cohérence runtime/NFO).

### 4.5 Watch folder (mode planifié)

**Activation :** Paramètres → Avancé → Surveillance.

- Toggle « Activer la surveillance ».
- Intervalle (1 à 60 minutes, défaut 5).

CineSort vérifie périodiquement tes dossiers racine. Si un nouveau film apparait
(détection par `name|mtime`), il déclenche un scan automatique.

> Comportement : skip si un scan est déjà en cours. Snapshot initial sans scan
> (juste référence). Aucun scan déclenché au démarrage de l'app.

Indicateur dans la barre de santé : « Veille active (5 min) » quand activé.

### 4.6 Plugin hooks post-action

**Activation :** Paramètres → Avancé → Plugins.

Tu peux brancher des scripts externes après chaque événement CineSort :

- `post_scan` — après un scan terminé
- `post_apply` — après un apply réel (pas dry-run)
- `post_undo` — après un undo (si au moins 1 film annulé)
- `post_error` — après une erreur critique

**Conventions de nommage** dans le dossier `plugins/` (à côté de `CineSort.exe`) :

- `post_scan_xxx.py` → réagit à `post_scan` uniquement
- `any_xxx.py` → réagit à tous les événements
- `xxx.py` → réagit à tous les événements

Extensions supportées : `.py` (Python), `.bat` (batch Windows), `.ps1` (PowerShell).

**Données reçues :** JSON sur stdin + variables d'env `CINESORT_EVENT` et `CINESORT_RUN_ID`.

Exemple : envoyer un Discord webhook après chaque scan, démarrer un torrent
client post-apply, etc.

### 4.7 Rapports email

Voir [§ 3.3](#33-notifications-desktop--email).

Email texte brut envoyé via SMTP standard. Contenu typique :

```
Sujet : [CineSort] Scan termine — 142 films traites

Bonjour,

Run cine_20260504_153012 termine avec succes.

Resultats :
- 142 films analyses
- 138 matches TMDb (97%)
- 4 a revoir manuellement
- 12 doublons detectes
- Score moyen : 76 (Gold)

Distribution tiers :
- Platinum : 18 (12%)
- Gold : 67 (47%)
- Silver : 41 (29%)
- Bronze : 12 (8%)
- Reject : 4 (3%)

Cordialement,
CineSort v7.7.0
```

### 4.8 Watchlist Letterboxd / IMDb

**Vue Bibliothèque → bouton « Importer une watchlist ».**

CineSort accepte les exports CSV de :

- **Letterboxd** : Settings → Import & Export → Export Your Data → `watchlist.csv`
- **IMDb** : Lists → ta watchlist → Export → CSV

Le matching combine titre normalisé (lowercase, accents, articles The/Le/La) +
année. Un fallback fuzzy (token_sort_ratio ≥ 85) rattrape les non-matches exact
(ordre mots inversé, traductions, etc.).

**Résultat :**

```
Couverture : 127 / 250 (51%)
Possedes : 127
Manquants : 123
```

Liste des 123 films manquants exportable en CSV pour aller les chercher.

---

## 5. Dépannage rapide

> Pour les détails complets, voir **[docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md)**.

| Symptôme | Première chose à vérifier |
|---|---|
| L'app ne démarre pas | Antivirus → ajouter exception sur `CineSort.exe` |
| Le scan n'avance pas | Dossier racine accessible ? extensions vidéo supportées ? Voir Journaux |
| TMDb ne trouve rien | Clé API valide (Test connexion dans Paramètres) ; quota TMDb non dépassé |
| Probe failed | ffprobe et mediainfo installés ? Paramètres → Outils vidéo → Installer auto |
| Apply bloqué | Espace disque < 100 MB ? Permissions sur le dossier cible ? |
| Undo échoue | Conflits ? Voir `_review/_undo_conflicts/` pour les fichiers déjà modifiés |
| Dashboard inaccessible | API REST activée ? Token ≥ 32 chars pour LAN ? Firewall Windows ? |
| Antivirus bloque .exe | Faux positif PyInstaller. Voir FAQ ci-dessous |

---

## 6. FAQ utilisateurs (40+ questions)

### Installation & lancement

- **Antivirus bloque le `.exe`** — Faux positif PyInstaller. Ajoute une exception pour
  `CineSort.exe`, vérifie la signature numérique (clic droit → Propriétés → Signatures),
  ou compile depuis les sources.
- **L'app ne démarre pas** — Lance `CineSort.exe --dev` pour voir les erreurs. Vérifie
  WebView2 Runtime (Win11 OK, Win10 install parfois requise). Logs :
  `%LOCALAPPDATA%\CineSort\logs\cinesort.log`.
- **Quelle version Windows ?** — Win10 1809+ et Win11 supportés. Win7/8 non testés.
- **Faut-il les droits admin ?** — Non. CineSort écrit uniquement dans
  `%LOCALAPPDATA%\CineSort\`.
- **Plusieurs instances en parallèle ?** — Une seule recommandée (lock SQLite WAL).
  Pour 2 bibliothèques, configure 2 roots dans la même instance.
- **Désinstaller proprement** — Supprime `CineSort.exe` + `%LOCALAPPDATA%\CineSort\`.
  Aucune clé registry, aucun service.

### Scan & matching

- **Scan ne trouve pas de films** — Vérifie : (1) dossier racine accessible ? (2)
  extensions supportées (mkv, mp4, avi, mov) ? (3) fichiers en lecture seule /
  antivirus ? (4) Journaux pour l'erreur exacte.
- **TMDb ne trouve pas mon film** — Renomme en `Titre (Année)` ; ajoute un `.nfo`
  avec `<title>`/`<year>` ; saisis le tmdbid manuellement via l'inspecteur ; vérifie
  que le film existe sur themoviedb.org.
- **Scan très lent** — Normal au 1er passage (~1-2 sec/film + ~5 sec TMDb). 10× plus
  rapide les fois suivantes (cache incrémental). 1000 films : 15-25 min puis 2 min.
- **Interrompre et reprendre** — Bouton « Annuler » sauvegarde l'état partiel. Au
  prochain scan, seules les vidéos non traitées sont analysées.
- **Titre détecté faux** — Vue Validation → inspecteur → « TMDb ID manuel ». ID
  visible dans l'URL TMDb : `themoviedb.org/movie/27205` → `27205`.
- **Noms scene supportés ?** — Oui (ex. `Inception.2010.1080p.BluRay.x264-SCENE`).
  Titre/année/résolution/codec parsés, tag scene retiré.
- **Edition c'est quoi ?** — Version particulière (Director's Cut, Extended, IMAX).
  Détectée depuis nom ou `.nfo`, conservée dans le titre final. Pas considéré comme
  doublon.
- **Détection des doublons** — 4 critères : hash SHA1 identique, même film TMDb
  cross-root, même film+édition à 2 endroits, comparaison 7 critères pondérés
  (résolution, HDR, codec, audio, canaux, bitrate, taille).
- **Détection séries TV ne marche pas** — Active Paramètres → Avancé → Détection TV.
  Patterns : `S01E01`, `1x01`, `Saison N Episode N`.

### Apply & undo

- **Apply par erreur, comment annuler** — Application → Historique → « Annuler ».
  Par batch ou film par film (Undo v5). Préview dry-run obligatoire.
- **Espace disque insuffisant** — Pre-check auto refuse si < max(somme×1.10, 100MB).
  Libère ou change de disque cible.
- **Apply a crashé, j'ai perdu des fichiers ?** — Non. Journal write-ahead
  (`apply_pending_moves`) → réconciliation au démarrage suivant : `completed`,
  `rolled_back`, `duplicated`, `lost`. Notif UI sur conflits.
- **Savoir ce qui a été modifié** — Application → Historique. Détails dans
  `apply_operations`. Export JSON/CSV/HTML.
- **Conflit lors d'un undo** — Fichier modifié entre apply et undo → redirigé vers
  `_review/_undo_conflicts/`. À traiter manuellement.
- **Tester sans rien casser** — C'est le but du **dry-run**. Coche « Mode dry-run »
  avant Apply.
- **Décisions disparues après refresh** — Sauve avec **Ctrl+S** ou « Enregistrer ».
  Avertissement si tu navigues sans sauver. Draft auto (localStorage, TTL 30 j) en
  filet de sécurité.
- **Forcer un re-scan d'un film** — Inspecteur → « Re-scanner ».

### Performance

- **Scan prend longtemps** — Voir Scan ci-dessus. Active le perceptuel uniquement à
  la demande (très lent).
- **Accélérer les scans** — (1) garde le cache (ne supprime pas la BDD) ; (2)
  désactive perceptuel batch ; (3) SSD > HDD/NAS ; (4) v7.7.0 parallélise probe
  (10× plus rapide pour 10k films).
- **Beaucoup de RAM ?** — 1000 films : 200-400 MB. 10 000 films : 800 MB-1.2 GB.
  Au-delà, ouvre une issue.
- **Dashboard distant lent** — Polling adaptatif (2 sec run actif / 15 sec idle).
  Vérifie wifi LAN et charge PC.
- **Pourquoi 60 MB pour un .exe ?** — LPIPS + onnxruntime + numpy + ffmpeg helpers.
  Sans ces features : ~16 MB. Choix : qualité > optimisation taille.

### Bibliothèque & qualité

- **Comment fonctionne le score Tier ?** — Voir [§ 2.3](#23-système-de-scoring-cinemalux--v2).
  5 paliers Platinum/Gold/Silver/Bronze/Reject. Combine résolution, codec, audio,
  sous-titres, perceptuel.
- **C'est quoi le mode perceptuel ?** — Voir [§ 4.4](#44-analyse-perceptuelle-lpips-grain-v2-score-v2).
  Vraie qualité image+son (fake 4K, DNR, fake HDR, audio mono déguisé).
- **Différence Score V1 / V2** — V1 legacy (métadonnées seules). V2 recommandé
  (perceptuel + ajustements contextuels era/codec). Toggle Paramètres → Score.
- **Exporter un rapport** — Application → « Exporter ». 3 formats : HTML autonome
  avec graphiques, CSV 30 colonnes Excel, .nfo XML (Kodi/Jellyfin/Emby).
- **Qu'est-ce qu'un fake 4K ?** — Fichier annoncé 4K mais réellement upscale 1080p.
  Détection par FFT 2D (ratio hautes/basses fréquences). Badge « Upscale ? ».
- **Gestion des sous-titres** — Auto-détection (.srt, .ass, .sub, .sup, .idx). Langue
  par suffixe (`.fr.srt`, `.eng.srt`). Bonus si toutes présentes, malus si
  manquantes/orphelines.
- **Tier Platinum/Gold/Silver/Bronze/Reject ?** — Voir [§ 2.3](#23-système-de-scoring-cinemalux--v2).

### Sécurité & vie privée

- **Données envoyées quelque part ?** — Non. HTTP uniquement vers TMDb (si activé),
  Jellyfin/Plex/Radarr (si configurés), GitHub Releases (si auto-MAJ activé). Zéro
  télémétrie, zéro tracking, zéro analytics.
- **Clés API en clair ?** — Non. Toutes (TMDb, Jellyfin, Plex, Radarr, SMTP)
  chiffrées DPAPI Windows. Logs scrubbés (8 patterns : `api_key=`, `Bearer`,
  `MediaBrowser Token`, `X-Plex-Token`, `X-Api-Key`, JSON keys, `smtp_password`).
- **Dashboard distant sécurisé ?** — Auth Bearer obligatoire. Token ≥ 32 chars
  pour bind LAN (sinon fallback 127.0.0.1). Rate limiting 5/60s → 429. Path
  traversal guardé. CORS strict. HTTPS optionnel.
- **Partager logs pour bug** — Paramètres → Journaux → « Exporter le diagnostic ».
  Zip logs + version + config scrubbée. Joins-le à une issue GitHub.

---

## 7. Raccourcis clavier

### Navigation (fonctionnent même dans un champ texte)

| Raccourci | Action |
|---|---|
| `Alt+1` | Accueil |
| `Alt+2` | Bibliothèque |
| `Alt+3` | Qualité |
| `Alt+4` | Jellyfin |
| `Alt+5` | Plex |
| `Alt+6` | Radarr |
| `Alt+7` | Journaux |
| `Alt+8` | Paramètres |
| `1` à `8` | Navigation directe (hors champ texte) |

### Actions globales

| Raccourci | Action |
|---|---|
| `Ctrl+K` | Ouvrir la palette de commandes (recherche) |
| `Ctrl+S` | Sauvegarder les décisions de validation |
| `F5` | Rafraîchir la vue active |
| `F1` ou `?` | Afficher la modale des raccourcis |
| `Esc` | Fermer la modale ou le drawer actif |

### Vue Validation active

| Raccourci | Action |
|---|---|
| `↑` `↓` ou `j` `k` | Naviguer entre les films |
| `Espace` ou `a` | Approuver le film sélectionné |
| `r` | Rejeter le film sélectionné |
| `i` | Ouvrir l'inspecteur du film |
| `Ctrl+A` | Tout approuver |
| `f` | Basculer le mode focus |

### Drag & drop

| Action | Effet |
|---|---|
| Glisser un dossier dans la fenêtre | Overlay visuel + ajout aux roots |
| Drop sur la page Accueil | Proposition de lancer un scan immédiat |

---

## 8. Mises à jour & support

### Vérification automatique

CineSort vérifie périodiquement la disponibilité d'une nouvelle version sur
**GitHub Releases** (rate-limit 60/h). Si une MAJ est dispo :

- Badge `•` sur l'icône sidebar
- Notification dans Paramètres → Mises à jour
- Lien direct vers la page de release pour télécharger

Toggle « Vérifier les MAJ automatiquement » dans Paramètres → Avancé.

### Mise à jour manuelle

1. Télécharge le nouveau `CineSort.exe` depuis GitHub Releases.
2. Remplace l'ancien (ou garde-le à côté avec un autre nom).
3. Relance.

Tes données (`%LOCALAPPDATA%\CineSort\`) sont conservées entre versions. Les
migrations SQL s'appliquent automatiquement au démarrage (avec backup auto rotation 5).

### Signaler un bug

1. Va sur la page **Issues** du repo GitHub.
2. Choisis le template adapté (Bug report, Feature request, Question).
3. **Joins le diagnostic** : Paramètres → Journaux → Exporter le diagnostic
   (zip logs + version + config scrubbée).
4. Décris : ce que tu attendais, ce qui s'est passé, version, OS, étapes pour
   reproduire.

### Aide en direct

Vue **Aide** dans l'app (icône `?` dans la sidebar) — FAQ + glossaire + raccourcis
+ liens utiles, le tout filtrable en temps réel.

### Documentation supplémentaire

| Document | Contenu |
|---|---|
| [README.md](../README.md) | Présentation, quick start, screenshots |
| [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Dépannage détaillé par catégorie |
| [docs/api/ENDPOINTS.md](api/ENDPOINTS.md) | Référence des 98 endpoints API REST |
| [CHANGELOG.md](../CHANGELOG.md) | Historique des versions |
| [CLAUDE.md](../CLAUDE.md) | Architecture (lecture dev) |

### Communauté

- **GitHub Discussions** — questions ouvertes, propositions de features
- **Issues** — bugs et demandes ciblées

---

## English version

CineSort ships with bilingual support since v7.7.0 (FR by default, EN available).

**Switch the UI to English** : `Settings > Apparence (Appearance) > Locale > English`. The change applies immediately, no restart required. Glossary, FAQ, action labels, error messages and notifications are all translated.

**Coverage** : 30 glossary terms + 15 FAQ entries + commons / errors / sidebar / topbar / danger zone are fully translated. Some advanced settings labels (perceptual fine-tuning, scoring weights) remain in French and will be ported in upcoming releases.

**File** : translations live in `locales/en.json` (mirror of `locales/fr.json`). The infrastructure is described in `cinesort/domain/i18n_messages.py` (backend) and `web/dashboard/core/i18n.js` (frontend).

> Bon film 🎬 et bon tri !

# BACKLOG — v7.5.0 et au-delà

**Date de rédaction :** 2026-04-22
**But :** conserver la trace de tous les points **intéressants mais reportés** hors de v7.5.0, pour y revenir dans v7.6.0+ ou plus tard.

**Principe :** chaque point a un **niveau de maturité** de la réflexion, une **valeur business estimée** et un **effort grossier**. Pas un plan d'exécution — un dépôt d'idées consultable.

---

## Sommaire

1. [Analyses techniques reportées](#1-analyses-techniques-reportées)
2. [Fonctionnalités UI reportées](#2-fonctionnalités-ui-reportées)
3. [Intégrations externes reportées](#3-intégrations-externes-reportées)
4. [Performance et scalabilité](#4-performance-et-scalabilité)
5. [Communauté et partage](#5-communauté-et-partage)
6. [IA et Machine Learning](#6-ia-et-machine-learning)
7. [Plateformes additionnelles](#7-plateformes-additionnelles)
8. [Idées exploratoires](#8-idées-exploratoires)

---

## 1. Analyses techniques reportées

### 1.1 VMAF-CUDA (GPU 37x)
- **Quoi** : utiliser l'implémentation GPU de VMAF via NVIDIA (37x plus rapide).
- **Pourquoi reporté** : nécessite une build FFmpeg custom avec `libvmaf_cuda`, complexité packaging.
- **Valeur** : très élevée pour les utilisateurs avec GPU récent.
- **Effort** : 10-15h (intégration + packaging).
- **Prérequis v7.5.0** : VMAF ONNX déjà en place. Option à activer via setting.

### 1.2 Détection watermarks / logos
- **Quoi** : détecter les logos de chaînes TV (HBO, Netflix, Amazon Prime) ou watermarks gravés.
- **Pourquoi reporté** : nécessite un corpus étiqueté énorme + réseau CNN.
- **Valeur** : moyenne — identifie les sources (leak studio vs rip broadcast).
- **Effort** : 20h+ recherche + 15h implémentation.
- **Dépendance** : probablement un modèle ONNX ~80 MB.

### 1.3 Subtitle quality analysis
- **Quoi** : analyser la qualité des sous-titres (OCR accuracy, sync, typos).
- **Pourquoi reporté** : out of scope v7.5.0, projet distinct.
- **Valeur** : moyenne.
- **Effort** : 15h.
- **Dépendances** : `pysubs2`, `pyspellchecker`.

### 1.4 Audio dialnorm manipulation detection
- **Quoi** : détecter les ré-encodages qui ont changé le `dialog_normalization` AC3/EAC3.
- **Pourquoi reporté** : niche, nécessite calibration empirique.
- **Valeur** : faible.
- **Effort** : 3h.

### 1.5 Détection deepfake / upscale AI
- **Quoi** : détecter les films qui ont été "deepfakés" ou upscalés par IA (Topaz, ESRGAN).
- **Pourquoi reporté** : état de l'art en recherche, modèles lourds.
- **Valeur** : haute pour qualité, mais cas d'usage rare.
- **Effort** : 25h+.
- **Dépendances** : modèle CNN ~100 MB.

### 1.6 Forensics frame-accuracy
- **Quoi** : comparer 2 fichiers frame par frame (pas juste échantillonnage) avec alignement DTW.
- **Pourquoi reporté** : coût calculatoire massif (1h d'analyse pour 1h de film).
- **Valeur** : haute mais niche (détection précise theatrical vs extended).
- **Effort** : 12h.

### 1.7 Détection 3D / stéréoscopie
- **Quoi** : détecter si le fichier est une version 3D (SBS, TAB, MVC).
- **Pourquoi reporté** : format 3D obsolète, peu demandé.
- **Valeur** : faible.
- **Effort** : 4h.

### 1.8 Audio stem separation
- **Quoi** : séparer dialogue / musique / effets via un modèle ML pour analyser chaque stem.
- **Pourquoi reporté** : modèle lourd (Demucs ~200 MB), valeur niche.
- **Valeur** : moyenne.
- **Effort** : 15h.
- **Dépendances** : Demucs ou Open-Unmix.

### 1.9 Color grading style detection
- **Quoi** : identifier le "look" color grade (teal & orange, bleach bypass, warm cinema).
- **Pourquoi reporté** : purement esthétique, pas de valeur qualité objective.
- **Valeur** : faible (curiosité).
- **Effort** : 10h.

### 1.10 VFR frame timing analysis
- **Quoi** : détecter et classifier les variable frame rate files.
- **Pourquoi reporté** : cas rare, géré partiellement par probe standard.
- **Valeur** : faible.
- **Effort** : 5h.

---

## 2. Fonctionnalités UI reportées

### 2.1 Player vidéo intégré dans deep-compare
- **Quoi** : au lieu de frames statiques, un vrai lecteur vidéo avec scrubbing et A/B instant switch.
- **Pourquoi reporté** : complexité UI majeure, pywebview ne supporte pas natif, nécessiterait webview2 avec codecs licenciés.
- **Valeur** : très haute UX.
- **Effort** : 30-40h.
- **Alternative** : lancer VLC en side-by-side via subprocess.

### 2.2 Timeline interactive des différences
- **Quoi** : visualiser où dans le film les différences A vs B sont les plus fortes (heatmap temporelle).
- **Pourquoi reporté** : demande une analyse dense (pas échantillonnage).
- **Valeur** : haute pour films avec coupes/édits.
- **Effort** : 12h.

### 2.3 Export PDF rapport de comparaison
- **Quoi** : générer un PDF professionnel d'un deep-compare (pour audit, archive).
- **Pourquoi reporté** : dépendance reportlab ou weasyprint (~20-30 MB).
- **Valeur** : moyenne pour usage pro (collections privées).
- **Effort** : 8h.

### 2.4 Mode comparaison 3+ fichiers
- **Quoi** : analyser N fichiers doublons en une seule session (pas juste 2).
- **Pourquoi reporté** : UI plus complexe, cas rare (la plupart des doublons = 2 fichiers).
- **Valeur** : moyenne.
- **Effort** : 10h.

### 2.5 Mode "analyse approfondie automatique"
- **Quoi** : toggle pour lancer l'analyse approfondie automatiquement sur tous les doublons détectés.
- **Pourquoi reporté** : tu as explicitement dit "déclenchement manuel uniquement".
- **Valeur** : dépend des préférences user.
- **Effort** : 2h (si on change d'avis).

### 2.6 Historique des comparaisons deep-compare
- **Quoi** : vue "Analyses approfondies récentes" avec replay de la modale.
- **Pourquoi reporté** : demande persistance lourde des assets (JPG, SVG).
- **Valeur** : moyenne (utile pour revenir sur une décision).
- **Effort** : 8h.

### 2.7 Assistant vocal pour l'analyse
- **Quoi** : TTS qui lit le verdict à l'utilisateur pendant que la modale se charge.
- **Pourquoi reporté** : gimmick, pas de valeur pro.
- **Valeur** : très faible.
- **Effort** : 4h (via pyttsx3).

### 2.8 Sparkline animée en live pendant scan
- **Quoi** : le widget espace disque anime en temps réel pendant un scan.
- **Pourquoi reporté** : demande WebSocket ou SSE (pas dans CineSort).
- **Valeur** : moyenne (satisfaction visuelle).
- **Effort** : 15h.

---

## 3. Intégrations externes reportées

### 3.1 Intégration Stremio
- **Quoi** : connecter CineSort à Stremio pour enrichir les infos films.
- **Pourquoi reporté** : écosystème différent, ciblage streaming.
- **Valeur** : faible (concurrent potentiel).
- **Effort** : 10h.

### 3.2 Intégration Emby (à part Jellyfin)
- **Quoi** : support Emby en plus de Jellyfin (forks divergents).
- **Pourquoi reporté** : APIs proches mais divergent, overhead de maintenance.
- **Valeur** : faible (Emby payant, moins utilisé).
- **Effort** : 6h.

### 3.3 Intégration IMDB direct (scraping)
- **Quoi** : enrichir avec les ratings/reviews IMDb, pas juste TMDb.
- **Pourquoi reporté** : IMDb pas d'API publique, scraping fragile.
- **Valeur** : moyenne.
- **Effort** : 12h + maintenance.

### 3.4 Intégration Trakt.tv
- **Quoi** : sync watchlist/watched avec Trakt.
- **Pourquoi reporté** : out of scope scoring, communauté plus petite que Letterboxd.
- **Valeur** : faible.
- **Effort** : 8h.

### 3.5 Intégration AniDB pour anime
- **Quoi** : enrichir les anime avec AniDB (meilleur que TMDb pour anime).
- **Pourquoi reporté** : scope spécifique anime, nécessite parsing différent.
- **Valeur** : haute pour sous-population user.
- **Effort** : 15h.

### 3.6 Synology DSM / QNAP / Unraid apps
- **Quoi** : packager CineSort comme app native pour NAS.
- **Pourquoi reporté** : Windows-first pour l'instant, NAS nécessite adaptation headless.
- **Valeur** : haute pour power users.
- **Effort** : 25-40h.

### 3.7 Webhook générique post-apply
- **Quoi** : système de webhooks pour notifier des services externes (Slack, Discord, Telegram).
- **Pourquoi reporté** : existe partiellement via plugin_hooks.py.
- **Valeur** : moyenne.
- **Effort** : 6h (affiner plugin_hooks).

---

## 4. Performance et scalabilité

### 1.0 NR-VMAF score industrie standard (reporté de v7.5.0 — projet parallèle validé)

**Statut : projet parallèle post-v7.5.0, à lancer une fois l'app stable.**

- **Quoi** : score qualité vidéo no-reference 0-100 reconnaissable internationalement (style NR-VMAF de Netflix).
- **Pourquoi reporté** : aucun modèle NR-VMAF public/ONNX disponible au 2026-04-23. Netflix n'a pas publié le modèle et le papier IEEE 2024 ne distribue ni code ni poids.
- **Valeur** : haute pour le marketing ("score VMAF industrie standard") — mais CineSort v7.5.0 a déjà un scoring différenciateur solide sans cet ajout.

#### Décision utilisateur (2026-04-23) : entraîner notre propre modèle en parallèle

Le user a validé l'idée d'**entraîner un modèle NR-VMAF custom** post-v7.5.0, une fois l'app v7.5.0 stabilisée. C'est un **projet parallèle** indépendant du roadmap produit.

**Avantages de l'approche "custom" :**
1. **Contrôle total** : le modèle est calibré sur notre corpus + use case (films curation).
2. **Communautaire** : branding "CineScore" ou "CineVMAF" comme différenciateur propre.
3. **Évolutif** : ré-entraîné au fil des retours utilisateurs (feedback loop).
4. **Indépendance** : pas de dépendance Netflix/Dolby/Samsung.

**Roadmap du projet parallèle :**

##### Phase T0 — Spec & Architecture (5-10h)
- Définir l'objectif exact : NR-VQA (Video) ou NR-IQA (Image par image) ?
- Choisir l'architecture : CNN léger (ResNet18/MobileNet) ou transformer (Swin-T) ?
- Définir la cible : MOS 1-5 ou 0-100 ?

##### Phase T1 — Collecte du dataset (1-3 mois, effort distribué)
- **Option A — Dataset public** : VideoSet, Waterloo IVC, LIVE-VQC, UGC-VQA → ~2000 vidéos déjà notées MOS. Effort : téléchargement + conversion format CineSort (20-40h).
- **Option B — Collecte communautaire CineSort** : opt-in dans l'app v7.5.0 permettant aux users de noter subjectivement leurs films. Nécessite backend simple. Effort : 20h infra + 3-6 mois collecte naturelle.
- **Option C — Mix A+B** : commencer avec public, enrichir avec communautaire. **Recommandé**.

##### Phase T2 — Preprocessing & feature extraction (10-20h)
- Extraire frames, caractéristiques pixel (déjà fait dans CineSort via `video_analysis.py`).
- Générer les features input du modèle (patches, histograms, FFT, etc.).
- Format training : (features vidéo) → score MOS.

##### Phase T3 — Training (15-40h compute + 10h engineering)
- Infrastructure : PC local avec GPU RTX 4070+ ou Google Colab Pro (~20€ crédit).
- Framework : PyTorch pour training (pas runtime app — runtime reste ONNX).
- Validation : split 80/10/10 train/val/test, cross-validation, early stopping.
- Export : convertir le modèle final en ONNX quantifié INT8 (~15-40 MB).

##### Phase T4 — Validation croisée (5-10h)
- Tester le modèle sur corpus de référence LIVE-VQC.
- Comparer avec VMAF FR Netflix (corrélation Pearson/Spearman).
- Cible acceptable : Spearman ≥ 0.85 avec MOS humain.

##### Phase T5 — Intégration dans CineSort (6-10h)
- Réutiliser le scaffolding prévu originellement pour §10 (déjà documenté).
- Ajouter le modèle dans `assets/models/cinescore_custom.onnx`.
- Nommage clair : "CineScore" (pas "VMAF") pour éviter confusion branding.
- Documentation user expliquant la méthodologie custom.

##### Phase T6 — Amélioration continue (permanent)
- Collecte feedback user via UI "CineScore vous semble juste ?" (👍/👎).
- Re-training trimestriel sur dataset enrichi.
- Publier méthodologie + dataset en open source (contribution à la communauté VQA).

**Effort total estimé (distribué sur 6-12 mois)** :
- 60-80h engineering pur
- 20-40h compute GPU (coût ~50-200€)
- 3-6 mois collecte dataset communautaire (passif, opt-in)
- Prérequis : CineSort v7.5.0 stable + user-base active (pour dataset communautaire)

**Livrable final** : fonctionnalité **"Score CineScore 0-100"** dans la modale deep-compare, avec confidence interval et transparence sur le dataset d'entraînement.

**Impact sur v7.5.0** : **aucun**. Ce projet ne bloque rien et n'affecte pas la roadmap produit. Démarre dès que v7.5.0 est en production stable.

#### Options alternatives de secours (si training custom s'avère trop coûteux)

Ces options restent en backup si le projet custom prend plus que prévu :

1. **Surveiller publication Netflix / académique NR-VMAF** (veille technique active).
2. **Alternative MANIQA (NR IQA)** : ~25 MB modèle ONNX, score image-par-image agrégé en proxy vidéo. Effort 8h. Communication claire "score MANIQA", pas VMAF.
3. **Alternative pVMAF (Synamedia)** : si licence devient accessible (actuellement propriétaire).

#### Référence recherche

- **État recherche complet** : [NOTES_RECHERCHE §10](../plans/NOTES_RECHERCHE_v7_5_0.md#§10--vmaf-no-reference-📦-reporté-v760-pas-de-modèle-public)
- **Impact redistribution pondérations v7.5.0** : §16 score composite ajuste (+10% perceptuel classique, +5% HDR, +10% fake 4K) pour compenser absence VMAF.
- **Datasets publics potentiels** :
  - [LIVE-VQC (UT Austin)](https://live.ece.utexas.edu/research/LIVEVQC/index.html)
  - [YouTube UGC Dataset](https://media.withyoutube.com/ugc-dataset)
  - [Waterloo IVC 4K Video Quality Database](http://ivc.uwaterloo.ca/database/4K_Video_Quality_Database.html)
  - [VideoSet Shanghai Jiao Tong](https://mclab.sjtu.edu.cn/videoset)

### 4.0 GPU hardware acceleration pour décodage frames (reporté de v7.5.0)
- **Quoi** : détection automatique + smoke test des hwaccels disponibles (cuda, qsv, dxva2, d3d11va, vaapi, videotoolbox). Application restreinte à la commande d'extraction de frames dans `frame_extraction.py`. Opt-in utilisateur via setting `perceptual_hwaccel` (défaut `"none"`).
- **Pourquoi reporté** : gain réel mesuré 15-25% seulement, car les filter graphs analytiques (`signalstats`, `blockdetect`, `blurdetect`, `ebur128`, `astats`) sont CPU-only. §1 Parallélisme apporte 2.5x avec moins de risques drivers.
- **Valeur** : moyenne (gain perçu modeste mais symboliquement important pour les power users GPU).
- **Effort** : 6h (5h dev + 1h tests).
- **État recherche** : **déjà fait**. Plan et findings complets dans [PLAN_CODE §2](../plans/PLAN_CODE_v7_5_0.md#§2--gpu-hardware-acceleration-📦-reporté-v760) et [NOTES_RECHERCHE §2](../plans/NOTES_RECHERCHE_v7_5_0.md#§2--gpu-hardware-acceleration-📦-reporté-v760). Peut être repris directement en v7.6.0 sans re-recherche.
- **Dépendances** : builds FFmpeg gyan.dev / BtbN incluent déjà les hwaccels nécessaires. Aucune dépendance Python ajoutée.

### 4.1 Cache compressé perceptuel
- **Quoi** : compresser les perceptual_reports JSON (actuellement ~50 KB chacun).
- **Pourquoi reporté** : gain marginal, SQLite déjà efficace.
- **Valeur** : faible.
- **Effort** : 3h.

### 4.2 Base de données embarquée externe (DuckDB)
- **Quoi** : migrer SQLite vers DuckDB pour analytiques plus rapides.
- **Pourquoi reporté** : coût migration vs gain.
- **Valeur** : faible (SQLite suffit).
- **Effort** : 30h+.

### 4.3 Scan distribué multi-machines
- **Quoi** : orchestrer plusieurs instances CineSort pour scanner un NAS énorme.
- **Pourquoi reporté** : use case rare, complexité élevée.
- **Valeur** : haute mais niche.
- **Effort** : 50h+.

### 4.4 Indexation full-text sur les titres
- **Quoi** : recherche full-text ultra-rapide via FTS5 SQLite.
- **Pourquoi reporté** : recherche actuelle suffit pour la taille typique.
- **Valeur** : moyenne (10k+ films).
- **Effort** : 5h.

### 4.5 Mode low-memory pour NAS
- **Quoi** : fonctionner avec <512 MB RAM (NAS entry-level).
- **Pourquoi reporté** : out of scope Windows desktop.
- **Valeur** : haute si NAS apps sortent.
- **Effort** : 20h.

---

## 5. Communauté et partage

### 5.1 CineSort Cloud (sync profils multi-devices)
- **Quoi** : synchroniser profils qualité entre plusieurs machines du user.
- **Pourquoi reporté** : nécessite backend cloud, out of scope desktop pur.
- **Valeur** : haute pour power users.
- **Effort** : 40h+ backend.

### 5.2 Profile marketplace
- **Quoi** : plateforme d'échange de profils qualité entre utilisateurs CineSort.
- **Pourquoi reporté** : démarrage communauté, nécessite masse critique.
- **Valeur** : très haute (positionnement "communautaire" que tu as voulu).
- **Effort** : 60h+ (backend + UI + modération).

### 5.3 Anonymized telemetry opt-in
- **Quoi** : utilisateurs peuvent partager statistiques anonymes pour améliorer scoring.
- **Pourquoi reporté** : RGPD, confiance à établir.
- **Valeur** : très haute long-terme (calibration empirique des seuils).
- **Effort** : 30h+ (backend + opt-in + doc RGPD).

### 5.4 Leaderboards qualité bibliothèque
- **Quoi** : classement public (opt-in) des bibliothèques par health score.
- **Pourquoi reporté** : gimmick, incentives perverses.
- **Valeur** : faible.
- **Effort** : 15h.

### 5.5 Forum / Discord intégré
- **Quoi** : lien direct Discord CineSort depuis l'app.
- **Pourquoi reporté** : pas d'urgence.
- **Valeur** : moyenne.
- **Effort** : 1h (lien).

---

## 6. IA et Machine Learning

### 6.1 Classification automatique de genre via CNN
- **Quoi** : prédire le genre d'un film via les frames (pas juste TMDb).
- **Pourquoi reporté** : modèle lourd (~200 MB), valeur faible vs TMDb.
- **Valeur** : faible.
- **Effort** : 20h.

### 6.2 Détection automatique theatrical vs director's cut
- **Quoi** : CNN qui détecte si un fichier est la version cinéma ou étendue.
- **Pourquoi reporté** : nécessite dataset rare (paires étiquetées), ROI faible.
- **Valeur** : moyenne (utile pour le flag `version_hint`).
- **Effort** : 30h+ (dataset + training + inference).

### 6.3 Upscale IA local (intégré)
- **Quoi** : proposer d'upscaler les vieux fichiers via Real-ESRGAN intégré.
- **Pourquoi reporté** : out of scope (CineSort curation, pas traitement).
- **Valeur** : moyenne, feature distincte.
- **Effort** : 40h+.

### 6.4 Résumé automatique du film via LLM
- **Quoi** : appeler un LLM pour résumer le film ou analyser les reviews.
- **Pourquoi reporté** : dépendance API externe (Claude, OpenAI), coût, hors scope scoring.
- **Valeur** : faible (redondant avec TMDb).
- **Effort** : 10h.

### 6.5 Chat assistant pour triager les doublons
- **Quoi** : LLM qui dialogue avec l'user pour l'aider à décider sur les doublons complexes.
- **Pourquoi reporté** : gimmick, pas de vrai gain vs UI claire.
- **Valeur** : faible.
- **Effort** : 25h+.

### 6.6 ML personnalisé calibré sur corpus user
- **Quoi** : le scoring s'adapte aux préférences de chaque utilisateur via feedback loop (déjà amorcé en v7.3 calibration).
- **Pourquoi reporté** : partiellement fait en v7.3, à approfondir en v7.6+.
- **Valeur** : très haute.
- **Effort** : 20h (approfondir l'existant).

---

## 7. Plateformes additionnelles

### 7.1 Version macOS native
- **Quoi** : build Mac via pywebview macOS.
- **Pourquoi reporté** : focus Windows, utilisateurs Mac minoritaires.
- **Valeur** : moyenne.
- **Effort** : 20h (packaging + tests).

### 7.2 Version Linux
- **Quoi** : build Linux via pywebview GTK/QT.
- **Pourquoi reporté** : focus Windows.
- **Valeur** : moyenne (utilisateurs power users).
- **Effort** : 15h.

### 7.3 Version mobile (visualisation uniquement)
- **Quoi** : app mobile React Native qui lit le dashboard REST.
- **Pourquoi reporté** : dashboard web mobile-responsive suffit.
- **Valeur** : faible.
- **Effort** : 60h+.

### 7.4 Docker container
- **Quoi** : packager CineSort en Docker (mode REST-only, pas pywebview).
- **Pourquoi reporté** : pywebview nécessite display, complexe en container.
- **Valeur** : haute pour déploiement NAS/serveur.
- **Effort** : 15h.

### 7.5 Web version (sans Electron/pywebview)
- **Quoi** : CineSort 100% web, tourne dans un browser.
- **Pourquoi reporté** : out of scope desktop, limitations filesystem dans browser.
- **Valeur** : faible.
- **Effort** : 80h+ refactor complet.

---

## 8. Idées exploratoires

### 8.1 "CineScore" public badge
- **Quoi** : générer un badge (SVG) "CineSort Platinum" affichable sur blog/forum.
- **Valeur** : faible (branding).
- **Effort** : 2h.

### 8.2 Intégration HDFury / Lumagen (home cinema)
- **Quoi** : exporter profils qualité vers les appareils home cinema.
- **Valeur** : très niche.
- **Effort** : 20h (reverse-engineer APIs).

### 8.3 Import automatique depuis torrent client
- **Quoi** : hook qBittorrent/Deluge pour auto-scanner les nouveaux téléchargements.
- **Valeur** : moyenne.
- **Effort** : 15h.

### 8.4 Détection copy-paste / partial file
- **Quoi** : détecter les fichiers incomplets ou corrompus à mi-téléchargement.
- **Valeur** : moyenne.
- **Effort** : 6h (hash partiel + header check).
- **Note** : déjà partiellement géré par `integrity_check.py`, à approfondir.

### 8.5 Suggestions "compléter la saga"
- **Quoi** : suggérer d'ajouter les films manquants d'une saga TMDb détectée.
- **Valeur** : haute (curation).
- **Effort** : 10h.

### 8.6 Watchlist partagée multi-user (family)
- **Quoi** : plusieurs utilisateurs partagent une watchlist commune.
- **Valeur** : moyenne.
- **Effort** : 20h.

### 8.7 Mode "curator virtuel"
- **Quoi** : IA qui propose des listes thématiques à partir de ta bibliothèque ("Films noirs des années 70 que tu n'as pas vus").
- **Valeur** : haute UX.
- **Effort** : 30h+.

### 8.8 Export vers Plex collections automatique
- **Quoi** : créer automatiquement des collections Plex à partir des tags/sagas.
- **Valeur** : moyenne.
- **Effort** : 10h.

### 8.9 Alerte disque saturé + suggestion purge
- **Quoi** : quand disque > 90%, proposer la liste des films low-tier à supprimer pour libérer X GB.
- **Valeur** : haute (pratique).
- **Effort** : 5h.
- **Note** : s'intègre bien au widget espace disque de v7.5.0 → peut-être à faire en v7.5.1.

### 8.10 Timeline qualité bibliothèque (6 mois / 1 an)
- **Quoi** : graph long-terme de l'évolution de la qualité de la biblio.
- **Valeur** : moyenne (visualisation).
- **Effort** : 6h.

### 8.11 Lecture NFO enrichie (bandes son, crew, budget)
- **Quoi** : parser des champs NFO avancés (bande son, équipe, budget) pour enrichir les decisions.
- **Valeur** : faible.
- **Effort** : 4h.

### 8.12 Archivage froid (cold storage)
- **Quoi** : détecter les films jamais regardés depuis X mois, proposer archivage vers disque externe.
- **Valeur** : haute (power users).
- **Effort** : 12h.

### 8.13 Mode concert / documentaire (scoring adapté)
- **Quoi** : ajuster le scoring pour contenus non-fiction (docus, concerts) où les règles cinéma ne s'appliquent pas.
- **Valeur** : moyenne.
- **Effort** : 10h.

### 8.14 Détection "source x264 vs x265 re-encode"
- **Quoi** : identifier le codec d'origine même après ré-encodage (indices stylistiques).
- **Valeur** : faible.
- **Effort** : 8h.

### 8.15 Gestion des doublons intentionnels (trilogies, éditions)
- **Quoi** : permettre de marquer explicitement certains doublons comme "voulus" (Director's Cut + Theatrical).
- **Valeur** : haute (déjà partiellement géré par `edition`).
- **Effort** : 4h (approfondir).

### 8.16 Mode "inventaire décès" (successoral)
- **Quoi** : générer un inventaire PDF détaillé de la collection (valorisation films rares).
- **Valeur** : très niche.
- **Effort** : 10h.

### 8.17 Détection sous-titres forcés incorrects
- **Quoi** : vérifier que les sous-titres "forced" correspondent bien aux parties non-anglophones.
- **Valeur** : moyenne.
- **Effort** : 15h.

---

## Fin du backlog

**Total items : 75+**

**Tri possible par priorité pour v7.6.0 :**
1. **ML personnalisé calibré sur corpus user** (§6.6) — 20h
2. **Player vidéo intégré dans deep-compare** (§2.1) — 30h
3. **VMAF-CUDA** (§1.1) — 15h (si GPU demandé)
4. **Alerte disque saturé** (§8.9) — 5h
5. **Archivage froid** (§8.12) — 12h

**Tri possible par priorité pour v8.0 (communauté) :**
1. **Profile marketplace** (§5.2) — 60h+
2. **Anonymized telemetry opt-in** (§5.3) — 30h+
3. **Intégration AniDB pour anime** (§3.5) — 15h
4. **Version Linux** (§7.2) — 15h
5. **Docker container** (§7.4) — 15h

---

À réévaluer à chaque fin de cycle. Certains items peuvent être supprimés si perdent pertinence, d'autres ajoutés au gré des retours utilisateurs.

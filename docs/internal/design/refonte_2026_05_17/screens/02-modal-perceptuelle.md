# Spec — Modal Analyse Perceptuelle

Statut : **VALIDÉE** par Thomas le 2026-05-17 (session refonte UI multi-agents).
Position dans la refonte : **Écran 2 / N**.

## Pourquoi cette spec

Test perso 2026-05-17 sur EXE v1.2.0-beta : la modal "Analyse perceptuelle" affiche `non calculée` × 4 (Empreinte audio Chromaprint, SSIM self-ref, Verdict résolution faux 4K, etc.) alors que le backend a calculé et persisté toutes ces données. Thomas perçoit la fonction comme "pacotille / du bluff". Cf [[feedback-cinesort-ui-pacotille]].

**Cause racine** : `web/views/validation.js:_runPerceptualAnalysis` appelle `get_perceptual_report` (qui lance l'analyse et retourne un sous-ensemble) au lieu de `get_perceptual_details` (lecture pure DB qui retourne TOUT). L'endpoint existe déjà — il a été créé pour l'issue #32 (transparence) — mais l'UI ne l'utilise pas.

---

## 0. Mode d'affichage (adaptatif selon contexte — rétro post-Shell 3 zones)

L'analyse perceptuelle a deux modes d'affichage selon la vue active :

### Mode A — Panneau inspecteur élargi (vues expertes)

Quand l'utilisateur est sur **Bibliothèque, Doublons, Qualité, Historique** (vues qui ont déjà un inspecteur droit visible par défaut), cliquer "Analyse perceptuelle" sur un film **élargit le panneau inspecteur** pour afficher le contenu de cette spec dans l'inspecteur, sans ouvrir d'overlay modal.

- L'inspecteur passe de sa largeur normale (360px) à sa largeur élargie (auto-resize jusqu'à 600px max, ou 50% de la fenêtre selon la place dispo)
- Bouton ▶/◀ en haut pour basculer entre largeur normale et élargie
- Le centre reste navigable : tu peux cliquer un autre film dans la liste à gauche, l'inspecteur se met à jour live avec son analyse perceptuelle
- Flow continu : tu balaies 10 films d'affilée sans jamais sortir d'un overlay

### Mode B — Overlay modal fullscreen (vues simples)

Quand l'utilisateur est sur **Accueil, Paramètres, Aide** (vues qui n'ont pas d'inspecteur ou un inspecteur replié par défaut), l'analyse perceptuelle s'affiche en **modal overlay** centré classique (comme dans la spec ci-dessous).

### Choix automatique

| Vue active | Mode |
|---|---|
| Accueil | Overlay |
| Bibliothèque | Inspecteur élargi |
| Traitement | Inspecteur élargi |
| Doublons | Inspecteur élargi |
| Qualité | Inspecteur élargi |
| Historique | Inspecteur élargi |
| Paramètres | Overlay (rare ici, juste pour cohérence) |
| Aide | Overlay (rare) |

### Layout (identique dans les 2 modes)

Le contenu (sections Score V2 / Vidéo / Audio / Breakdown / Verdicts croisés / Frames) est **identique** dans les 2 modes. Seul le conteneur diffère : panneau de droite redimensionné vs overlay centré. Le layout interne décrit ci-dessous (section 1) s'applique aux deux.

---

## 1. Layout du contenu (commun aux 2 modes)

```
┌──────────────────────────────────────────────────────────────────────┐
│  ✕  Analyse perceptuelle — La Doublure (2006)                       │
│      [▾ Comparer avec un autre film du run]                         │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  📊 Score global & tier                                              │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │       ╭────╮                                                   │ │
│  │       │ 23 │     Tier  : Dégradé                              │ │
│  │       │/100│     Vidéo : ▓░░░░░░░░░  0  / 100                 │ │
│  │       ╰────╯     Audio : ▓▓▓▓▓░░░░░ 57  / 100                 │ │
│  │                                                                │ │
│  │   Verdict   "Audio compressé low quality (probable AAC 96kb)"  │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  🎬 Métriques vidéo                                                  │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │   SSIM self-ref      0.87  → authentique (>0.85 = vrai natif)  │ │
│  │   Faux 4K détecté    NON   ← vrai 1080p                        │ │
│  │   Grain              modéré, naturel (film stock)              │ │
│  │   HDR                SDR (aucune métadonnée HDR)               │ │
│  │   Codec efficiency   x264 8-bit @ 4.2 Mbps                     │ │
│  │   Bitrate vs résol.  4.2 Mbps pour 1080p (faible: ~6+ attendu) │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  🔊 Métriques audio                                                  │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │   Empreinte Chromaprint                                        │ │
│  │     ┌──────────────────────────────────────────────────────┐   │ │
│  │     │ AQABcUFCkOZxFD0fXcSXxHySZk_y4_qx4_iPH35y_DjyHN9w...   │   │ │
│  │     └──────────────────────────────────────────────────────┘   │ │
│  │     [📋 Copier]                                                │ │
│  │   Cutoff spectral         17.2 kHz  → lossy_low                │ │
│  │   Verdict audio           Compressé basse qualité              │ │
│  │   Pistes                  FR AAC 2.0 @ 192 kbps                │ │
│  │   Dynamique               8 dB (faible — mastering compressé)  │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  📐 Breakdown détaillé (Score V2)             [▼ Replier]            │
│  Composantes du score 23/100 :                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │   Résolution × 0.25     → 1080p              ✓  18 pts         │ │
│  │   Bitrate × 0.20        → 4.2 Mbps           !   8 pts         │ │
│  │   Codec × 0.15          → x264 8-bit         ◐   6 pts         │ │
│  │   Audio bitrate × 0.20  → 192 kbps           ✗   0 pts         │ │
│  │   Audio channels × 0.10 → 2.0 stéréo         !   3 pts         │ │
│  │   Subtitle FR × 0.10    → forced+full        ✓   8 pts         │ │
│  │   ───────────────────────────────────────────────────          │ │
│  │   Total                                          23 / 100      │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ⚠️  Verdicts croisés                                                │
│  • Pénalité audio sévère : 0 pt sur 20 (limite basse)              │
│  • Suggestion : remplacer par version avec audio FLAC ou DTS        │
│                                                                      │
│  🔬 Frames analysées (3 captures)        [▶ Voir les frames]         │
│  (Bouton manuel — extraction ~10-30s, lazy load PNG base64)         │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│  Dernière analyse : 14/03/2024 21:42                                │
│  [↻ Relancer l'analyse complète]                       [Fermer]     │
└──────────────────────────────────────────────────────────────────────┘
```

## 2. Mapping codes verdicts → langage humain

À factoriser dans `web/dashboard/core/perceptual-labels.js` (nouveau) :

```javascript
export const VERDICT_LABELS = {
  // lossy_verdict
  "lossless": "Sans perte (FLAC, ALAC, PCM)",
  "lossy_high": "Compressé qualité haute (>256 kbps AAC/MP3)",
  "lossy_medium": "Compressé qualité moyenne (~192 kbps)",
  "lossy_low": "Compressé basse qualité (<160 kbps)",
  "lossy_very_low": "Compressé très basse qualité (<96 kbps)",
  
  // upscale_verdict
  "native_4k": "Vrai 4K natif",
  "native_1080p": "Vrai 1080p natif",
  "native_720p": "Vrai 720p natif",
  "upscaled_1080p": "Faux 1080p (upscalé depuis 720p)",
  "upscaled_4k": "Faux 4K (upscalé depuis 1080p)",
  
  // tier_v2
  "platinum": "Platinum (référence)",
  "gold": "Gold (excellent)",
  "silver": "Silver (bon)",
  "bronze": "Bronze (acceptable)",
  "reject": "Reject (à remplacer)",
  "degrade": "Dégradé",
  
  // grain_label
  "clean": "Très propre (denoised)",
  "subtle": "Subtil, naturel",
  "moderate": "Modéré, naturel (film stock)",
  "heavy": "Lourd (grain marqué)",
  "noisy": "Bruité (artefacts encodage)",
};

export function humanize(code, fallback = code) {
  return VERDICT_LABELS[code] || fallback;
}
```

## 3. Source de chaque donnée

| Donnée affichée | Champ backend (via `get_perceptual_details`) |
|---|---|
| Score V2 cercle | `details.global_score_v2` (0-100) |
| Tier | `details.tier_v2` (mappé via `VERDICT_LABELS`) |
| Vidéo / Audio bars | `details.visual_score`, `details.audio_score` |
| Verdict textuel principal | `details.lossy_verdict` + mapping humain |
| SSIM self-ref | `details.ssim_self_ref` (0-1, seuil 0.85) |
| Faux 4K détecté | `details.upscale_verdict` (mappé) |
| Grain | `details.grain_analysis.verdict_label` + mapping |
| HDR | `details.hdr_analysis.is_hdr` + `hdr_format` |
| Codec efficiency | `details.codec`, `details.bit_depth`, `details.bitrate_kbps` |
| Bitrate vs résol. | calcul JS : `bitrate / resolution_area` + interprétation |
| Empreinte Chromaprint | `details.audio_fingerprint` (hex) |
| Cutoff spectral | `details.spectral_cutoff_hz` |
| Verdict audio | `details.lossy_verdict` (mappé) |
| Pistes audio | `details.audio_streams[]` (codec + channels + bitrate) |
| Dynamique audio | `details.audio_perceptual.dynamic_range_db` |
| Breakdown 6 lignes | `details.breakdown` (déjà calculé en JSON, chaque ligne = {component, weight, value_label, status, points}) |
| Verdicts croisés | `details.cross_verdicts[]` (label + severity + suggestion) |
| Date dernière analyse | `details.analyzed_at` (ISO timestamp) |

→ **Aucun nouvel endpoint backend nécessaire.** Tout est déjà dans `get_perceptual_details`. Le travail c'est uniquement frontend.

## 4. États de la modal (5 cas)

### 4.1 Analyse persistée en DB (cas normal)

Affiche tout instantanément. Pas de spinner. Modal s'ouvre immédiatement.

### 4.2 Pas d'analyse persistée (`details.missing === true`) — décision Thomas : CTA explicite

```
┌──────────────────────────────────────────────────────────────────────┐
│  ✕  Analyse perceptuelle — La Doublure (2006)                       │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   📊 Aucune analyse pour ce film                                    │
│                                                                      │
│   Calcul de :                                                       │
│   • Score V2 (composante par composante)                            │
│   • SSIM self-ref (détection faux upscale)                          │
│   • Grain analysis (film stock vs artefacts)                        │
│   • Empreinte Chromaprint (audio)                                   │
│   • Cutoff spectral (détection lossy)                               │
│                                                                      │
│   Estimation : ~30 secondes                                         │
│                                                                      │
│              [▶ Lancer l'analyse maintenant]                        │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

Au clic : appelle `get_perceptual_report(run_id, row_id)` (qui calcule), spinner, puis re-rend la modal en mode 4.1 quand fini.

### 4.3 Module désactivé (settings `perceptual_enabled=false`)

```
┌──────────────────────────────────────────────────────────────────────┐
│  ✕  Analyse perceptuelle — La Doublure (2006)                       │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ℹ️  Analyse perceptuelle désactivée dans les paramètres.          │
│                                                                      │
│         [Aller aux Paramètres > Analyse perceptuelle]               │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.4 ffmpeg manquant

```
┌──────────────────────────────────────────────────────────────────────┐
│  ✕  Analyse perceptuelle — La Doublure (2006)                       │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ⚠️  ffmpeg est introuvable.                                       │
│                                                                      │
│   L'analyse perceptuelle nécessite ffmpeg pour :                    │
│   • Extraction de frames clés                                       │
│   • Calcul d'empreinte Chromaprint                                  │
│   • Analyse spectrale audio                                         │
│                                                                      │
│         [Installer depuis Paramètres > Outils vidéo]                │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.5 Données partielles (certains champs calculés, d'autres non)

Affiche les champs présents normalement. Pour les champs vides, affiche en grisé :

```
SSIM self-ref         Non calculé dans cette passe  [↻ Compléter]
```

Le bouton `[↻ Compléter]` ajoute `force=true` à `get_perceptual_report` pour relancer tous les modules.

## 5. Section "Comparer avec un autre film" (décision Thomas)

En haut de la modal, dropdown qui liste tous les films du run actuel :

```
┌──────────────────────────────────────────────────────────────────────┐
│  ✕  Analyse perceptuelle — La Doublure (2006)                       │
│      [▾ Comparer avec un autre film du run]   ← clic ouvre dropdown │
│      ┌────────────────────────────────────────┐                     │
│      │ 🔍 Filtrer...                          │                     │
│      ├────────────────────────────────────────┤                     │
│      │ Fast & Furious 4 (2009)        Score 87│                     │
│      │ Captain America Civil War (2016) Score 72│                   │
│      │ Inception (2010)               Score 95│                     │
│      │ La Doublure (2006)  ← exclu lui-même  │                     │
│      │ ... (901 films)                        │                     │
│      └────────────────────────────────────────┘                     │
├──────────────────────────────────────────────────────────────────────┤
```

Au choix d'un film :
- Modal devient un **split view** côte-à-côte (même structure que le Comparateur Doublons)
- Pour la v1 : route vers `web/dashboard/views/library/lib-duplicates.js` `_comparePerceptual(rowA, rowB)` existant (donc on réutilise le modal de comparaison déjà fait dans la spec Doublons)

Source des films listés : `library/get_library_filtered(run_id)` retourne déjà la liste.

## 6. Estimation effort

| Tâche | Effort |
|---|---|
| Frontend `validation.js` : passer de `get_perceptual_report` à `get_perceptual_details` | 0.3 j |
| Frontend rendu des 4 sections (Score V2, Vidéo, Audio, Breakdown) | 1 j |
| Frontend mapping codes → labels humains (`perceptual-labels.js` nouveau) | 0.3 j |
| Frontend dropdown "Comparer avec autre film" + intégration au Comparateur existant | 0.4 j |
| Frontend 5 états (normal / missing / disabled / no-ffmpeg / partial) | 0.4 j |
| Bouton "Relancer l'analyse" qui appelle `get_perceptual_report(force=true)` | 0.2 j |
| Bouton "Voir les frames" lazy (déjà existant côté backend) | 0.2 j |
| **Dual-mode renderer (inspecteur élargi sur vues expertes vs overlay sur Accueil)** | **0.3 j** |
| **Resize handler du panneau inspecteur (360 → 600px max, drag handle)** | **0.2 j** |
| Tests E2E (les 2 modes) | 0.3 j |
| **Total Modal Perceptuelle** | **~3.6 jours** (était 3 j sans dual-mode) |

(Plus rapide que les Doublons : 0 backend, juste du câblage frontend + mapping cosmétique + 2 conteneurs.)

## 7. Hors scope v1

- ❌ Visualisation spectrogramme intégrée (juste cutoff spectral textuel pour v1)
- ❌ Comparaison historique (évolution du score V2 dans le temps si re-analysé)
- ❌ Export PDF du rapport perceptuel (futur)
- ❌ Annotations utilisateur sur le verdict (genre "j'ai écouté, je suis d'accord" / "pas d'accord")

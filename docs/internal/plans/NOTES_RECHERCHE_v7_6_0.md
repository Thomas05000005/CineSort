# Notes de recherche — CineSort v7.6.0

**Date :** 2026-04-23
**Objet :** synthese + decisions design pour la refonte UI complete.

---

## 1. Etat des lieux (audit UI v7.5.0)

### Volume code frontend
| Zone | Fichiers | Lignes |
|---|---|---|
| Desktop vues (`web/views/`) | 6 | ~3800 |
| Dashboard vues (`web/dashboard/views/`) | 16 | ~5500 |
| Desktop composants (`web/components/`) | 17 | ~1500 |
| Dashboard composants (`web/dashboard/components/`) | 15 | ~1500 |
| CSS total | 5 | ~4800 |
| **Total** | **~59 fichiers** | **~17000L** |

### Constat cle : **duplication massive** (~900L identiques entre desktop IIFE et dashboard ES modules).

### Top 5 pain points confirmes
1. **Settings 900L, 22 sections empilees** — aucun groupement, 5000 px de scroll, toggles cachent des sections sans indication.
2. **Duplication desktop/dashboard** — 900L+ code quasi-identique, maintenance x2.
3. **Table validation 50+ colonnes** — scroll horizontal obligatoire, zero priorite visuelle.
4. **Couleur/profondeur manque de vivant** — 4 themes tous identiques en structure, glassmorphism subtil, animations en mode "restreint" par defaut.
5. **Navigation eparpillee** — Jellyfin/Plex/Radarr dans 3 endroits des settings, Notifications cachees, pas de vue "Integrations" unifiee.

### Points forts a conserver
- Architecture JS modulaire (`core/` + `components/` + `views/`)
- Tokens CSS complets (colors, spacing, typography, motion)
- Modales accessibles (focus trap, Escape, aria)
- API REST bridge propre (77 endpoints, dispatch generique)
- Responsive 3 breakpoints (dashboard)

---

## 2. Inspirations externes

### Linear (https://linear.app)
**A prendre** : Command Palette omnipresent (Cmd+K), keyboard-first, density sans surcharge, sidebar collapse, hierarchie vues (Inbox > My Issues > Projects > Views), tokens typography/spacing stricts, **Cycles** (time-based grouping).
**A ignorer** : scope management (irrelevant pour CineSort).

### Letterboxd (https://letterboxd.com)
**A prendre** : **page film standalone exemplaire** (poster heros + metadata dense + actions contextuelles), ratings visuels (etoiles en V2 cercle), timeline personnelle, filters par decennie/realisateur/genre.
**A ignorer** : reseau social.

### Plex / Jellyfin
**A prendre** : library grid view (poster posters), hero background blur, detail page avec metadonnees riches, continue watching, recently added.
**A ignorer** : streaming playback.

### Height (https://height.app)
**A prendre** : **filters composables** (tags × assignee × status multiple combines), saved views, density control (compact/comfortable), smart lists.

### Raycast / VSCode Command Palette
**A prendre** : search fuzzy global (actions + entities + settings), recent items, keyboard shortcuts inline, **categories inline** (Action, Film, Setting).

### Notion Database Views
**A prendre** : **vues sauvegardees** (Table / Board / Calendar / Gallery), filters composables avec AND/OR, sort multi-criteres, properties hideable.

### Arc Browser
**A prendre** : sidebar glass + subtle depth, focus mode, command bar plein ecran, **cards qui respirent** (padding, shadows, hover lift).

### Vercel Dashboard
**A prendre** : KPIs en grid 4 colonnes, sparklines inline, gradients subtils, **stagger animations** au load.

### Supabase Studio
**A prendre** : data-first UI (tables rendent 10k rows sans lag), inspector drawer lateral, breadcrumb trail, **table actions bar** contextuelle.

### macOS System Settings (Ventura+)
**A prendre** : **sidebar categories + contenu a droite**, search bar top, sections collapsibles, **groupement par intention utilisateur**.

### MediaInfoNET / MKVtoolnix
**A prendre** : densite data sans saturer (tabs horizontaux pour regrouper), export/import profils.

---

## 3. Decisions par axe

### A1 — Architecture information (sitemap v5)

**Decision** : 7 vues principales + 1 settings refondu.

```
Home                 Tableau de bord biblio (overview-first)
Traitement           F1 fusion scan + review + apply (3 steps)
Bibliotheque         Explorateur film-centric (table + grid, filters composables)
Film (/film/:id)     Page dediee standalone (4 onglets : Apercu / Analyse V2 / Historique / Comparaison)
Qualite              Distribution globale + tendance 30j + top insights + scoring par realisateur/franchise
Journal              Runs historiques + exports (CSV/HTML/NFO)
Integrations         Jellyfin / Plex / Radarr unifies (nouveau)
Parametres           9 groupes d'intention (refondus)
```

**Disparaissent** : vues separees Validation / Execution (absorbees dans Traitement), Jellyfin / Plex / Radarr dashboard (unifies dans Integrations).

**Nouveautes** :
- **Film detail** standalone (route dediee, pas modale) — axe majeur.
- **Integrations** comme vue top-level (pas cache dans Settings).
- **Traitement** fusion 3 steps avec breadcrumb visuel.

### A2 — Design system v5 data-first

**Approche** : palette commune data-first (X) + 4 themes atmospheriques (Y) qui ne touchent **QUE** les surfaces/accents atmospheriques. Les **tier colors restent invariables** dans les 4 themes.

**Palette noyau (invariante dans tous les themes)**
```
--tier-platinum: #FFD700  (or, halo chaud)
--tier-gold:     #22C55E  (vert, validation forte)
--tier-silver:   #3B82F6  (bleu, standard)
--tier-bronze:   #F59E0B  (orange, a ameliorer)
--tier-reject:   #EF4444  (rouge, action requise)

--severity-info:    #60A5FA
--severity-success: #34D399
--severity-warning: #FBBF24
--severity-danger:  #F87171
--severity-critical:#DC2626
```

**Surfaces 3 niveaux + glass raffine**
```
--bg:        base (noir profond / selon theme)
--surface-1: card, modal (glass 12% opacity)
--surface-2: accent area, nested cards (glass 18%)
```

**Motion tokens enrichis**
```
--ease-out:   cubic-bezier(0.16, 1, 0.3, 1)    # bounce leger
--ease-in:    cubic-bezier(0.7, 0, 0.84, 0)
--ease-in-out: cubic-bezier(0.76, 0, 0.24, 1)

--dur-quick:   120ms
--dur-base:    240ms
--dur-smooth:  400ms
--dur-complex: 600ms  (transitions vues)

--stagger-base: 60ms  (delay par element)
```

**Typography** : conserver Manrope (deja embedded, economie bundle), ajouter tabular-nums pour donnees numeriques.

**Shadows** : 4 niveaux au lieu de 2 actuels (elevation-1 hover, elevation-2 card, elevation-3 modal, elevation-glow pour tier badges).

### A3 — Home overview-first

**Decision** : 4 zones verticales.

```
1. HERO BAND (top, pleine largeur)
   Titre biblio + bouton "Lancer un scan" + indicateur "Watch folder actif" + derniere sync
   KPIs grid 5 cards : Total films / Score moyen V2 / % Platinum+Gold / % Reject / Trend 30j

2. INSIGHTS ACTIFS (3-5 cards)
   "3 nouveaux Reject detectes dans le dernier scan"
   "12 doublons a trancher"
   "5 films DNR partiel (grain supprime)"
   "8 films Platinum ajoutes ce mois"
   "Run en cours : 45/120 films" (si applicable)

3. GRAPHS (2 colonnes)
   Distribution 5 tiers (donut) | Tendance 30j (line chart score moyen + delta)

4. RECENT (bandeau horizontal)
   "5 derniers films ajoutes" (poster + score badge + warnings)
   "5 derniers apply" (liste compacte avec timestamp)
```

### A4 — Refonte settings (9 groupes)

**Structure** :
```
[Sidebar categories]          [Contenu droit]
┌──────────────────┐    ┌────────────────────────────────┐
│ 🔍 Search...      │    │ Section : Sources              │
│                   │    │ ┌────────────────────────┐      │
│ ◉ Sources         │    │ │ Dossiers racines       │      │
│ ○ Analyse         │    │ │ [liste editable]       │      │
│ ○ Nommage         │    │ └────────────────────────┘      │
│ ○ Bibliotheque    │    │ ┌────────────────────────┐      │
│ ○ Integrations    │    │ │ Surveillance (watcher) │      │
│ ○ Notifications   │    │ │ [toggle + intervalle]  │      │
│ ○ Serveur distant │    │ └────────────────────────┘      │
│ ○ Apparence       │    │ ...                            │
│ ○ Avance          │    │                                │
│                   │    │ [Reset section] [Save]         │
└──────────────────┘    └────────────────────────────────┘
```

**Fonctionnalites nouvelles** :
- Search fuzzy via rapidfuzz (deja dispo) sur labels + descriptions
- Badge "configure" (vert check) / "a configurer" (jaune warning) par section
- Preview live (theme, renaming template, perceptual params visibles en panel droit si applicable)
- Reset par section (pas globalisant)
- URL state : `/settings/sources` accessible direct
- Breadcrumb sticky

### A5 — Vue Bibliotheque / Explorateur

**Decision** : vue duale Table (defaut) + Grid (poster TMDb).

**Filtres composables** (sidebar gauche pliable) :
```
Tier             [ Platinum ][ Gold ][ Silver ][ Bronze ][ Reject ]
Warnings         [ DV5 ][ HDR manq. ][ Fake 4K ][ DNR partiel ][ ... ]
Codec video      [ HEVC ][ H264 ][ AV1 ][ VP9 ][ MPEG ][ VC1 ]
Resolution       [ 4K ][ 1080p ][ 720p ][ SD ]
HDR              [ SDR ][ HDR10 ][ HDR10+ ][ DV P5 ][ DV P8.1 ]
Ere grain (§15)  [ UHD DV ][ Blu-ray digital ][ Digital transition ][ Modern film ][ ... ]
Nature grain     [ Film grain ][ Encode noise ][ Post added ][ DNR partiel ]
Annee            [ slider 1920-2026 ]
Duree            [ slider 30min-4h ]

+ Smart Playlists (persistence dans settings)
  "Films a re-acquerir"    (Bronze + Reject + popularite TMDb > 50)
  "Platinum 2024+"         (Platinum, annee >= 2024)
  "Mes films IMAX"         (IMAX expansion + full_frame_143)
  "DNR problematiques"     (is_partial_dnr + score V2 < 70)
```

**Table columns (par defaut, configurable)** :
```
[✓] Titre (Annee)     Cercle V2  Tier   Resolution  Codec   HDR    Warnings  Actions
```

**Grid view** (poster layout) :
- Posters 180×270 en grille responsive
- Overlay bottom : titre + score V2 (mini cercle)
- Hover : lift + shadow + warnings preview en tooltip
- Click : ouvre /film/:id

### A6 — Page Film standalone

**Route** : `/film/:row_id` ou `/film/:tmdb_id`.

**Layout** :
```
┌─ Hero band (fond poster flou) ──────────────────────────────┐
│ [poster] Titre original (Annee)                              │
│           "Subtitle original title" • Director • Duration    │
│           [Cercle V2 gros] [Tier badge]  [Actions]          │
│                                                               │
└──────────────────────────────────────────────────────────────┘
┌─ Tabs : Apercu | Analyse V2 | Historique | Comparaison ─────┐
│                                                               │
│ APERCU                                                        │
│  - Metadonnees (codec, resolution, HDR, audio tracks, subs)  │
│  - Source (path actuel, taille, date ajout)                  │
│  - Tags / Warnings top                                       │
│                                                               │
│ ANALYSE V2                                                    │
│  - Cercle V2 + 3 jauges Video/Audio/Coherence               │
│  - Accordeon complet (sous-scores, tooltips FR, tier badges)│
│  - 7 warnings visibles en encarts                            │
│  - Contexte grain historique FR (§15)                        │
│  - Comparaison avec signature attendue de l'ere              │
│                                                               │
│ HISTORIQUE                                                    │
│  - Timeline : scan / score / apply (deja implemente §9.13)   │
│  - Evolution score sur re-scans                              │
│                                                               │
│ COMPARAISON                                                   │
│  - Action : "Comparer avec un autre fichier" (selector)      │
│  - Vue cote-a-cote LPIPS + criteres                          │
└──────────────────────────────────────────────────────────────┘
```

### A7 — Command Palette v2

**Invocation** : Cmd+K (Mac) / Ctrl+K (Win) partout.

**Contenu** :
```
Categorie     Actions
─────────────────────────────────
ACTIONS       Lancer un scan
              Appliquer les decisions
              Annuler le dernier apply
              Exporter le run courant
              Ouvrir les parametres

RECHERCHE     Films (search fuzzy par titre)
              Reglages (search fuzzy par label)
              Runs historiques (search par date)

NAVIGATION    Home
              Traitement
              Bibliotheque
              Qualite
              Integrations
              Parametres / Sources, Analyse, etc.

VUES SAUVEES  Playlists persistees
```

**Search fuzzy** via rapidfuzz (deja installe). Limit 8 resultats par categorie, stagger fadeIn.

### A8 — Motion & micro-interactions

**Principes** :
- Transitions vues : crossfade 240ms (pas de slide, trop lourd)
- KPIs stagger : 60ms par element
- Hover cards : `translateY(-2px) + shadow-elevation-2`, 120ms
- Buttons : scale 0.97 active state
- Accordeon : max-height transition + chevron rotate
- Toast : slide-in top-right 300ms + auto-dismiss 4s
- Score circle : stroke-dashoffset animation 1.2s cubic-bezier custom
- Gauges : width animation 1s avec delay variable par categorie
- Reduced-motion : respect `prefers-reduced-motion`, fallback instant

### A9 — Notifications & insights actifs

**3 couches** :
1. **Toast** (transitoire, 4s) : actions user confirmees
2. **Notification center** (persistant, dismissible) : decouvertes apres scan (nouveaux Reject, Platinum ajoutes, doublons trouves)
3. **Desktop notifications** (deja livre v7.4, a rafraichir) : runs finis, erreurs critiques

**Badge counter** dans sidebar sur l'icone cloche.

### A10 — Parite dashboard

**Strategie** : **fusion du code UI** via build pipeline.
- Composants shareable : `web/shared/components/` (ES modules)
- Adapter IIFE pour desktop via wrapper minimal
- CSS commun : `web/shared/styles.css`
- Settings, pages, routing restent separes (desktop pywebview vs dashboard REST)
- Resultat : 1 seul score-v2.js au lieu de 2, 1 seul badge.js, etc.

**Effort integration** : ~6-8h dedies a la consolidation + tests parite.

---

## 4. Decisions transversales

### Migration tiers v1 -> v2
- Tous les badges, scores, vues, exports affichent **V2 uniquement**
- Rows historiques (pre-v7.5.0) sans V2 : affichees avec tier "unknown" (grise) + CTA "Re-scanner pour score V2"
- Pas de migration script : recalcul au prochain scan

### Backward compat API
- Endpoints existants conservent leurs champs (`global_score`, `global_tier` v1 toujours exposes)
- Frontend prefere `global_score_v2_payload` s'il existe, fallback graceful sur v1 si absent

### Abandon wizard onboarding
- Remplace par **onboarding progressif** : tooltips contextuels sur premiere visite de chaque vue, dismissibles
- Setup initial : redirige vers Settings > Sources avec highlight

### Navigation header vs sidebar
- **Sidebar gauche** (desktop + dashboard) : 7 icones Lucide + labels (collapsable)
- **Top bar** : search, command palette trigger, notifications, theme switch, user (si auth dashboard)
- **Breadcrumb** pour vues nested (Film detail, Settings/category)

### Accessibility
- WCAG AA respecte partout (contrast > 4.5:1 texte, > 3:1 UI)
- Keyboard navigation complete
- `aria-*` sur tous les interactive elements
- Reduced-motion fallback
- Focus visible (2px outline accent)

---

## 5. Smart defaults retenus

| Choix | Valeur |
|---|---|
| Palette base | Noir profond #06090F + accents theme |
| Tier colors | Platinum or / Gold vert / Silver bleu / Bronze orange / Reject rouge |
| Surfaces | 3 niveaux glass + border subtle |
| Font | Manrope variable (embedded) |
| Icon system | Lucide (inline SVG) |
| Sidebar width | 240px desktop, collapsable 64px |
| Grid columns (KPI) | 5 sur desktop, 2 sur tablet, 1 sur mobile |
| Grid columns (Biblio grid) | auto-fill minmax(180px, 1fr) |
| Default view Biblio | Table (power user) |
| Page size table | 50 rows + pagination (pas infinite scroll) |
| Command palette shortcut | Cmd+K / Ctrl+K |
| Table row height | 48px default, 40px compact |
| Stagger delay | 60ms |
| Transition vue | crossfade 240ms |

---

## 6. Risques identifies

1. **Refonte CSS massive** (~4800L -> ~4000L neufs) : risque regressions visuelles si pas de comparaison baseline.
2. **Duplication desktop/dashboard** : tentative fusion peut casser pywebview si IIFE wrapper mal fait. **Mitigation** : phase progressive, commencer par 2-3 composants.
3. **Migration 15 sections settings -> 9 groupes** : mapping a faire soigneux pour ne pas perdre de reglages.
4. **Table validation 50 col -> 8 col** : user power peut regretter la densite. **Mitigation** : mode "advanced" toggle avec colonnes custom.
5. **Maquettes jamais validees visuellement** : l'utilisateur n'a pas de bibliotheque test. On fera des screenshots avec preview mode si besoin.

---

## 7. Livrables de cette phase (en cours)

- [x] `PLAN_RECHERCHE_v7_6_0.md`
- [x] Audit UI (dans ce document section 1)
- [x] Inspirations externes (section 2)
- [x] Decisions par axe A1-A10 (section 3)
- [ ] `design-system-v5.md` (tokens complets)
- [ ] Maquettes ASCII (home, biblio, film, settings, traitement)
- [ ] `PLAN_v7_6_0.md` (vagues)
- [ ] `PLAN_CODE_v7_6_0.md` (signatures)

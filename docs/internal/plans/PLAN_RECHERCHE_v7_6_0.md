# Plan de recherche — CineSort v7.6.0 (refonte UI/UX complete)

**Date :** 2026-04-23
**Version cible :** v7.6.0
**Motivation :** apres v7.5.0 (14 sections backend + §16b), l'UI est desalignee avec la richesse du moteur.
L'utilisateur a exprime un besoin de refonte complete (Option C) : navigation, organisation,
visibilite, settings, profondeur visuelle.

---

## Contexte

### Ce qu'on a livre en v7.5.0 (backend mature, UI marginale)

- 14 sections perceptuelles (§3 §4 §5 §6 §7 §8 §9 §11 §12 §13 §14 §15 §16a §16b)
- Score composite V2 (`platinum/gold/silver/bronze/reject`) avec 9 regles d'ajustement
- 7 warnings auto-collectes : runtime mismatch, DV5, HDR metadata, fake lossless, short file, low confidence, category imbalance
- Grain Intelligence v2 (6 eres + contexte historique FR)
- LPIPS ONNX, Chromaprint, Mel, DRC, HDR10+, DV profiles, FFT fake 4K, SSIM self-ref,
  metadata filters (interlacing/crop/judder/IMAX), scene detection, spectral cutoff
- 20+ nouvelles metriques perceptuelles par film
- Schema SQLite v18 (4 nouvelles migrations)
- 2723 tests, 0 regression

### Ce qui ne va pas cote UI (feedback utilisateur 2026-04-23)

Citations directes :

> "on voie pas tout d'un coup d'oeuil"
>
> "on s'ai pas ce qu'il a sans tout fouiller"
>
> "c'est l'app entiere on est obliger de fouiller y a rien de claire"
>
> "c'est pas asser ordonner"
>
> "les parametre sont horrible c'est entirement a revoir"
>
> "couleur profondeur il manque un truc egallment manque de vivant"

### Pain points traduits en constats techniques

| # | Pain point | Constat technique actuel |
|---|---|---|
| 1 | Pas d'overview biblio | Vue Home minimaliste, pas de KPI V2, pas de top insights |
| 2 | Info perceptuelle cachee | Accessible uniquement via Inspecteur > bouton "Analyser" |
| 3 | Warnings invisibles | 7 warnings calcules mais non surfaces dans la table principale |
| 4 | Pas de vue film-centric | Tout passe par liste -> modale (pas de page film dediee) |
| 5 | Settings 15 sections empilees | Pas de groupement fonctionnel, pas de recherche, pas d'apercu live |
| 6 | Design CinemaLux v4 pas data-first | 4 palettes atmospheriques mais ne parlent pas des indicateurs metier |
| 7 | Workflow fragmente | Scan/Validation/Execution/History sont 4 vues alors que c'est 1 parcours continu |
| 8 | Pas d'explorateur | Impossible de filtrer par tier/warning/grain nature/codec/HDR de maniere composable |
| 9 | Manque de profondeur visuelle | Peu de shadows, peu de couches, peu de motion |
| 10 | Decouvrabilite zero | Les 14 nouvelles features ne sont pas mises en avant, l'utilisateur ne les voit jamais |
| 11 | Coexistence tiers v1/v2 | Utilisateur voit deux systemes simultanement (transitoire mais perturbant) |
| 12 | Pas de vue temporelle | Tendance qualite sur 6 mois, evolution apres re-scan : invisible |
| 13 | App passive | L'app ne dit jamais "hey, 3 nouveaux films en Reject" |

---

## Principes directeurs v7.6.0 (valides par l'utilisateur)

### P1. Overview-first
L'utilisateur doit comprendre l'etat de sa biblio **en 3 secondes** sur la home.
- KPIs V2 globaux : total films, distribution 5 tiers, % DNR detecte, % fake 4K, % lossless audio, % HDR correct
- Top insights proactifs : "3 nouveaux Reject detectes", "5 films en DNR partiel", "12 doublons a trancher"
- Tendance 30 jours : line chart score moyen + delta vs periode precedente

### P2. Information architecture stricte
Hierarchie visuelle claire : **general -> thematique -> detail**, pas de mix.
- Home = vue agregee (generale)
- Bibliotheque = vue film-par-film filtrable (thematique)
- Film detail = fiche complete (detail)
- Settings par domaine (Sources / Qualite / Integrations / Avance)

### P3. Refonte settings radicale
- Groupement par **intention utilisateur**, pas par module technique
- Search bar : "trouve le reglage Jellyfin API key"
- Apercu live : changement de palette, preview renommage, test connexion instantane
- Reset par section
- Sections repliables avec memoire d'etat
- Badge "configure" / "a configurer" par section

### P4. Decouvrabilite active
- **Command Palette** (Cmd+K) : acces tout-en-un aux actions + films + reglages
- Insights proactifs sur la home (non-bloquants, dismissibles)
- Raccourcis contextuels : dans chaque vue, bouton "Voir aussi" vers vue connexe
- Onboarding progressif : tooltip sur les nouvelles features (1x)

### P5. Profondeur visuelle + motion
- Design system v5 **data-first** : palette unique (fini les 4 themes atmospheriques qui brouillent),
  tier colors = source de verite (Platinum or / Gold vert / Silver bleu / Bronze orange / Reject rouge)
- Couches : 3 niveaux de surface (bg / surface-1 / surface-2) avec shadows progressives
- Glass morphism retravaille (backdrop-filter blur + subtle border + inner shadow)
- Micro-animations : hover cards leger lift + shadow grow, transitions vues 200ms ease,
  stagger des KPIs au load (delay decale)
- Iconographie coherente (SVG Lucide deja partiel, a finaliser)

### P6. Film-centric (nouveau point d'entree)
- Page Film standalone (pas modale) : route /film/:id
- 4 onglets : Apercu / Analyse V2 / Historique / Comparaison
- Affichage complet : poster TMDb, metadonnees, cercle V2, accordeon, warnings, timeline, actions contextuelles

### P7. Workflow lineaire consolide
- Fusion eventuelle "Scan / Validation / Execution / History" en 1 parcours continu avec steps visuels
- OU : garder separe mais avec breadcrumb et actions "Suivant" fluides
- A trancher en phase design

### P8. Explorateur puissant
- Vue "Bibliotheque" avec filtres composables (tier × warning × grain nature × resolution × codec × era × HDR)
- Sauvegarde de filtres comme "Smart Playlists" (ex: "Films a re-acquerir", "Films DNR 2010-2015")
- Vue table + vue grille (affiche / poster TMDb)

### P9. App active (vs passive)
- Notifications desktop proactives (apres scan, apres apply, sur decouvertes)
- Digest email optionnel (deja livre en v7.4, a rafraichir)
- Widget home : "5 derniers apply", "3 warnings critiques", "Prochain scan dans X h (si watch folder)"

### P10. Coherence v1/v2 -> **v2 uniquement**
- Abandon definitif des tiers v1 (Premium/Bon/Moyen/Mauvais)
- Tous les badges, vues, exports -> Platinum/Gold/Silver/Bronze/Reject
- Migration progressive des rows historiques (recalcul V2 au prochain scan)

---

## Axes de recherche

### A1. Architecture information (vues et routes)

**Questions** :
- Combien de vues au total ? (aujourd'hui 6 : Home/Validation/Execution/Quality/History/Settings)
- Fusion possible Validation + Execution ? (c'est le meme flux review -> apply)
- Vue "Bibliotheque" (nouvelle) vs "Validation" (existant) : 2 vues distinctes ou 1 seule ?
- Page film standalone : route dediee vs drawer plein ecran ?
- Sidebar vs top nav vs mix ?

**Livrable** : proposition de sitemap a 6-8 vues avec justification.

### A2. Design system v5 data-first

**Questions** :
- Palette unique : on part de quelle base ? (Studio bleu deja dominant dans CinemaLux v4)
- Tier colors : comment les integrer au design system sans ecraser l'identite ?
- Surfaces (bg/surface-1/surface-2) : nombre optimal ?
- Typography : conserver Manrope ou migration Inter / Geist ?
- Icon system : Lucide partout ? (actuellement partiel)
- Tokens CSS : nomenclature (--bg, --surface, --text, --accent, --tier-*, --severity-*)

**Livrable** : `docs/internal/design-system-v5.md` avec tokens complets + exemples.

### A3. Home page overview-first

**Questions** :
- Quels KPIs afficher en priorite ?
- Quel format : cards, sparklines, donuts, bar charts ?
- Top insights : combien (3-5) ? Severite ? Actionnabilite (cliquable -> vue filtree) ?
- Graphe tendance 30 jours : score moyen, distribution tiers, new arrivals ?
- Widget "run en cours" : conserver mais refondu

**Livrable** : maquette home v5 (ASCII wireframe + spec composants).

### A4. Refonte settings

**Questions** :
- Grouper 15 sections en **4-5 categories** d'intention : lesquelles ?
- Search bar fuzzy : implementation (rapidfuzz deja la) ?
- Apercu live : pour quels reglages (themes oui, TMDb API key non) ?
- Indicateur "configure" : criteres ?
- Reset granulaire : par section ? par champ ?

**Livrable** : sitemap settings v5 avec groupes et sections.

### A5. Vue Bibliotheque / Explorateur

**Questions** :
- Table vs Grille (poster view) : toggle user ?
- Filtres composables : quels dimensions ? (tier, warnings, codec, resolution, era grain, HDR, DNR, source, annee, duree)
- Smart Playlists : persistence (settings ? table dediee ?)
- Tri : quels champs (titre, score V2, taille, date ajout, annee, duree) ?
- Pagination : infinite scroll vs pagine ?

**Livrable** : specs filtres + maquette table + grid view.

### A6. Page Film detail (nouvelle)

**Questions** :
- Layout : 2 colonnes (poster / data) vs tabs ?
- Onglets : Apercu, Analyse V2, Historique, Comparaison ? Autres (NFO, Sous-titres) ?
- Actions contextuelles : approve/reject/edit renaming/compare/delete ?
- Integration poster TMDb : fetch au load + cache ?
- Vue responsive : stacked sur mobile

**Livrable** : maquette film detail + specs.

### A7. Command Palette (Cmd+K)

**Questions** :
- Actions accessibles : combien (10 ? 50 ?) ?
- Search unifie : films + actions + reglages ?
- Shortcuts custom : configurables ?
- Deja present actuellement (web/components/command-palette.js) : ameliorer ou refondre ?

**Livrable** : inventaire actions + maquette UI palette v5.

### A8. Motion & micro-interactions

**Questions** :
- Quelles transitions entre vues (slide, fade, morph) ?
- Stagger des KPIs : delay optimal (50ms ? 100ms) ?
- Hover states : lift + shadow ? scale subtil ?
- Loading states : skeletons (deja partiel) + shimmer ?
- Toast notifications : position, duree, style ?

**Livrable** : spec animations + timings + reduced-motion fallback.

### A9. Notifications & insights actifs

**Questions** :
- Desktop notifications (deja livre) : extensions V2 (top warnings, new reject, new platinum) ?
- In-app notification center : nouveau composant ?
- Digest quotidien : format ? contenu (top 5 insights) ?
- Dismissible + "ne plus afficher" : mecanisme ?

**Livrable** : spec systeme notifications + maquette center.

### A10. Parite dashboard distant

**Questions** :
- Dashboard reste-t-il calque 1:1 du desktop ? Ou simplifie (mobile-first) ?
- Meme design system v5 ? Adaptation mobile des composants ?
- Page Film detail : meme experience ? Nav bottom tabs ?

**Livrable** : strategie parite v7.6.0.

---

## References a etudier

### Apps de media server (UX lib video)
- **Plex** : library view (grid poster), details page, filters
- **Jellyfin** : home cards, search, settings
- **Infuse** : cinematic transitions, poster hover effects
- **Letterboxd** : film detail page exemplaire, ratings, social

### Apps de tri / analyse media
- **MediaInfoNET / StaxRip** : dense data UIs (inspiration pour accordeon V2)
- **Hybrid / MKVtoolnix** : settings par intention
- **Sonarr / Radarr** : calendar view, wanted list, queue (inspiration workflow lineaire)

### Design systems data-first
- **Linear** : clarity, keyboard-first, density
- **Height** : filters composables, saved views
- **Vercel Dashboard** : KPIs, gradients subtils, motion
- **Supabase Studio** : surfaces + glass, table filters
- **Arc Browser** : sidebar, command bar

### Patterns specifiques
- **Filters composables** : Notion database filters, Airtable views
- **Command Palette** : VSCode, Raycast, Linear
- **Settings** : macOS System Settings (groupement par intention), Linear settings
- **Data visualization** : Observable notebook, D3 examples

---

## Livrables de la phase recherche

### Obligatoires
1. **`NOTES_RECHERCHE_v7_6_0.md`** (~2000-3000 mots) — synthese par axe A1-A10
   avec decisions prises et alternatives ecartees
2. **`PLAN_v7_6_0.md`** (~2000 mots) — vision produit, vagues, effort, risques
3. **`PLAN_CODE_v7_6_0.md`** (~3000-5000 mots) — par vague, fichiers touches, signatures, constantes, tests, ordre d'implementation

### Optionnels (utiles si on a le temps)
- Maquettes ASCII/SVG pour chaque vue v5
- `docs/internal/design-system-v5.md` autonome
- Mapping complet des composants existants a migrer/supprimer/refondre

### Hors scope phase recherche
- Coder quoi que ce soit
- Decisions finales sur le backend (v7.6.0 = UI principalement)
- Migration de donnees (rows v1 -> v2 via re-scan progressif, pas de migration script dedie)

---

## Timeline phase recherche

| Etape | Effort | Livrable |
|---|---|---|
| 1. Audit UI existante (inventaire composants, vues, settings) | 2h | Section "Etat des lieux" dans NOTES |
| 2. Recherche references externes (Linear, Letterboxd, Plex, etc.) | 2h | Section "Inspirations" |
| 3. Decisions design system v5 (tokens, palette, typography) | 2h | `design-system-v5.md` + section NOTES |
| 4. Sitemap + information architecture | 1h | Diagramme + justifications |
| 5. Maquettes principales (home, bibliotheque, film, settings) | 2h | Wireframes ASCII + spec |
| 6. Redaction `PLAN_v7_6_0.md` | 1h | Vision + vagues |
| 7. Redaction `PLAN_CODE_v7_6_0.md` | 2h | Signatures + ordre |
| **Total** | **~12h** | |

---

## Principes de recherche (contraintes)

1. **Ne rien recommencer de zero** : reutiliser les composants deja bons (modal, badge, table, skeleton, etc.), refondre leur apparence si besoin
2. **Ne pas casser le backend** : l'API REST existante continue de fonctionner. La refonte UI consomme les memes endpoints
3. **Backward compat lecture** : les rows v7.4 / v7.5 doivent s'afficher correctement dans la UI v7.6 (avec tier v1 converti en v2 a la volee si besoin)
4. **Tests** : maintenir 0 regression sur les tests backend existants
5. **Dashboard** : parite 100% maintenue (pas de feature desktop-only)
6. **Accessibilite** : WCAG AA, keyboard nav, reduced-motion, aria-*
7. **Performance** : temps d'affichage initial < 500ms meme sur 5000 films (virtualisation table si besoin)

---

## Validation requise avant execution

Avant de partir en recherche, l'utilisateur doit valider :

1. **La liste des axes A1-A10** (en ajouter ? en retirer ?)
2. **Les principes P1-P10** (lesquels sont non-negociables ?)
3. **Le scope hors phase recherche** (ce qui arrive dans v7.7 ou jamais)
4. **L'abandon des tiers v1** (P10 — confirmation)
5. **Le choix design system** (palette unique data-first vs conserver les 4 themes atmospheriques)

Une fois valide, je pars sur la Phase 2 (recherche reelle) puis rends NOTES_RECHERCHE + PLAN + PLAN_CODE pour validation finale avant d'ecrire du code.

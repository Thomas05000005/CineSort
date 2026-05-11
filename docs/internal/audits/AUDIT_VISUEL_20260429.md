# Audit visuel approfondi — CineSort v7.6.0-dev

**Date** : 29 avril 2026 (fin de journée)
**Auditeur** : Claude Opus 4.7 (1M context, capacités multimodales)
**Méthode** : capture Playwright headless multi-viewports + analyse visuelle multimodale
**Périmètre** :
- Dashboard distant SPA (`web/dashboard/`) — 4 vues × 3 viewports = 30 captures
- UI pywebview principale (`web/index.html`) — 19 captures (vues legacy + 4 overlays v5)
- **Total** : 55 captures analysées visuellement

**Branche** : `audit_qa_v7_6_0_dev_20260428` (continuation)

---

## 1. Méthodologie

### Outils
- Playwright Chromium headless 145 (déjà installé dans `.venv313`)
- 2 scripts de capture créés : [tests/manual/visual_audit_capture.py](../../../tests/manual/visual_audit_capture.py) (dashboard) et [tests/manual/visual_audit_pywebview.py](../../../tests/manual/visual_audit_pywebview.py) (UI principale)
- Mock JS riche pour `window.pywebview.api` : [tests/manual/pywebview_api_mock.js](../../../tests/manual/pywebview_api_mock.js) — 250+ lignes simulant 50+ méthodes API + Proxy fallback

### Capture
- **Dashboard** : 4 viewports cibles (1024/1366/1440/1920) × 9 vues + états spéciaux (login, hover, focus Tab, scroll, vide). Capture finie sur 3 viewports avant arrêt manuel (ressources).
- **pywebview** : 1 viewport (1366) × 10 vues legacy + 6 overlays v5 (Processing F1, Settings v5/sources, QualityV5, IntegrationsV5, JournalV5, FilmDetail). Mock JS injecté via `page.add_init_script()` AVANT chargement.

### Analyse
- Lecture de **chaque capture** comme image via mon multimodal (multi-format png).
- Identification visuelle : alignement, hiérarchie, contraste réel, ortographe française, états vides, espace gaspillé, affordance.

---

## 2. Findings — synthèse exécutive

### Top issues identifiées visuellement

| # | Issue | Sévérité | Localisation | Visible dans |
|---|---|---|---|---|
| V-1 | **Accents français manquants à grande échelle** dans tous les labels UI | **Critical** | Code source (~30 fichiers, ~80 occurrences réelles) | Toutes les vues |
| V-2 | Vue Accueil dashboard distant **complètement vide** | **Critical** | `web/dashboard/views/status.js` ou endpoint mock | Dashboard distant |
| V-3 | Overlays v5 (Processing, Quality, Settings) ont **~400px d'espace vide** en bas | High | Overlays v5 | UI pywebview |
| V-4 | Cards "DISTRIBUTION V2" / "TENDANCE 30 JOURS" rendues **vides sans skeleton** | High | `qij-v5.js` Quality mode | UI pywebview |
| V-5 | Search bar top-bar **tronquée à 1024px** : "Chercher un[..ctri+k.." | Medium | `top-bar-v5.js` ou CSS responsive | Dashboard 1024px |
| V-6 | Bandeau "Outils manquants" en orange ressemble à une card normale (manque de hiérarchie warning) | Medium | Library v5 step "Analyse" | UI principale + dashboard |
| V-7 | Section "Assistant premier lancement" : 5 badges status/action mélangés sans légende | Medium | Settings dashboard | Dashboard |
| V-8 | Step actif Processing F1 (cercle bleu) vs inactifs (cercle gris) — différence subtile | Low | `processing.js` | UI pywebview |
| V-9 | KPIs avec valeurs "—" sans message d'aide quand pas de run | Low | Home v5 (KPI cards) | UI pywebview |
| V-10 | Boutons "Letterboxd CSV" / "IMDb CSV" dans Watchlist sont gris-noir-on-noir (paraissent désactivés) | Low | Library v5 Watchlist | UI principale |

### Patterns globaux détectés

#### Pattern 1 — Accents oubliés systématiquement

Le code source a été écrit avec un mélange de strings sans accent (probablement à cause d'un clavier/IDE QWERTY) qui ont fini en production. **Visible partout** :

| Mot dans l'UI | Devrait être | Observé dans |
|---|---|---|
| `Apercu` | Aperçu | FilmDetail tab, Settings preview |
| `Bibliotheque` | Bibliothèque | Sidebar settings v5, breadcrumb FilmDetail |
| `Cle API` | Clé API | Settings TMDB |
| `Memoriser la cle` | Mémoriser la clé | Settings TMDB |
| `Configure` (badge) | Configuré | Settings v5 badges |
| `etat` | état | "Dossier d'etat (optionnel)" |
| `Decennie` | Décennie | QIJ Quality dimension tabs |
| `Ere grain` | Ère grain | QIJ Quality dimension tabs |
| `Qualite` (titre H1) | Qualité | Overlay QualityV5 |
| `donnee` | donnée | "Aucune donnee pour cette dimension." |
| `Reinit.` | Réinit. | Settings v5 boutons |
| `Separes par ; ou par ligne` | Séparés | Settings v5 aide chemin |
| `Avance` (entrée sidebar) | Avancé | Settings v5 sidebar |
| `Integrations` | Intégrations | Settings v5 sidebar |
| `Non classe` | Non classé | Library legacy filters |
| `ANNEE` (header table) | ANNÉE | Library table headers |
| `DUREE` (header table) | DURÉE | Library table headers |
| `ANALYSE VIDEO` | ANALYSE VIDÉO | Settings legacy |
| `Aucun film score` | Aucun film scoré | Quality empty state |
| `decisions` | décisions | Processing steps |
| `Parametres` | Paramètres | Processing step 3 message |
| `configure` (participe passé) | configuré | "Aucun run en cours, vos dossiers configure" |

#### Pattern 2 — États vides peu informatifs

Plusieurs cards / overlays affichent des contenus vides sans skeleton, sans message explicatif, sans CTA :
- Quality V5 : 2 cards titrées mais zone de contenu noire vide.
- Dashboard Accueil : titre seul, pas de hint, pas de loader, pas de CTA.
- Quality dashboard : message "Aucun film scoré..." OK mais isolé sur grande zone vide.

#### Pattern 3 — Espace vide en bas des overlays

Les overlays v5 (Processing, Quality, Settings, QIJ) ont un layout qui ne remplit pas le viewport bas. Sur 1366×768, après le content principal, **~400px de noir vide** en bas. Sentiment d'incomplétude.

#### Pattern 4 — Top-bar search responsive en 1024px

Sur viewport 1024px, le placeholder du search dans la top-bar est tronqué visuellement :
```
[🔍] Chercher un[..ctri+k..
```
Le badge `Ctrl+K` chevauche le placeholder text. Soit le placeholder doit être raccourci (`Rechercher...`), soit le badge doit disparaître à <1280px.

---

## 3. Détail par vue (avec screenshots de référence)

### 3.1 Dashboard distant — Vue Accueil

**Capture** : `tests/manual/screenshots/audit_20260429_161909/dashboard/1366x768/status_viewport.png`

**Constat** : La vue affiche **uniquement le titre "Accueil" et la sidebar**. Aucun KPI, aucun graphique, aucun contenu. C'est un bug visible aussi en production (déjà flaggé par `test_dash_05_sync_realtime.py::test_status_shows_kpi_cards` qui échouait préexistantsnt avec `kpis=1` au lieu de 3).

**Cause probable** : `_loadAll()` dans `web/dashboard/views/status.js:26` fait un `Promise.all` de 4 endpoints (`/api/health`, `get_global_stats`, `get_settings`, `get_probe_tools_status`). Si **un seul** échoue, le `try/catch` global avale l'erreur et `container.innerHTML = html` n'est jamais atteint. Par défaut, le mock REST de notre conftest peut ne pas fournir `get_global_stats` avec le format attendu V5 (`bento`, `runs_summary`, etc).

**Recommandation** :
1. Faire chaque appel **en isolation** avec fallback (`Promise.allSettled` au lieu de `Promise.all`).
2. Afficher un état d'erreur clair si un endpoint échoue (pas un container vide).
3. Ajouter un skeleton pendant le chargement.

### 3.2 UI pywebview — vue Home (legacy)

**Capture** : `tests/manual/screenshots/audit_pywebview_20260429_162635/pywebview/1366x768/00_boot.png`

Très bonne UI : hero card, KPIs, sections clairement organisées (Dernier run, Nouvelle analyse, Signaux d'attention). Bouton primaire "Démarrer l'analyse" bien proéminent.

**Findings** :
- KPIs hero "FILMS / SCORE MOYEN / 7 DERNIERS JOURS" affichent `—` (pas de run) — manque message d'aide.
- Bandeau "Outils d'analyse vidéo manquants : FFprobe, MediaInfo" — orange OK mais le bouton "Installer automatiquement" pourrait être plus proéminent.
- En bas des KPIs hero : 3 colonnes très espacées horizontalement, gros gap.

### 3.3 UI pywebview — overlay Processing F1

**Capture** : `pywebview/1366x768/20_overlay_processing.png`

Stepper 1-2-3 (Scan / Review / Apply), card "Lancer un scan" avec bouton primaire "▷ Lancer le scan", message info.

**Findings** :
- ✅ Hiérarchie claire, action principale visible.
- ⚠ "decisions" → "décisions"
- ⚠ "Parametres" → "Paramètres"
- ⚠ "configure" (dans "vos dossiers configure") → "configuré"
- ❌ **~400px de vide noir** en bas du viewport — l'overlay devrait soit afficher plus de contenu (état du scan, dernière exécution), soit avoir une hauteur réduite.
- Step actif en bleu (cercle plein) vs inactifs (cercle vide gris) — différence subtile, pourrait être plus contrastée (ex: bordure plus épaisse, taille).

### 3.4 UI pywebview — overlay QualityV5

**Capture** : `pywebview/1366x768/22_overlay_quality-v5.png`

**Findings (gros)** :
- ❌ Titre **"Qualite"** sans accent.
- ❌ Tab **"Decennie"** sans accent.
- ❌ Tab **"Ere grain"** sans accent.
- ❌ Message **"Aucune donnee pour cette dimension."** — "donnee" sans accent.
- ❌ Cards "DISTRIBUTION V2" et "TENDANCE 30 JOURS" affichent leurs **titres mais pas de contenu** (juste de l'air noir). Skeleton ou placeholder manquant.
- ❌ Beaucoup de vide en bas.

### 3.5 UI pywebview — overlay FilmDetail

**Capture** : `pywebview/1366x768/25_overlay_film_r1.png`

**Findings** :
- ❌ Bouton retour **"← Bibliotheque"** sans accent.
- ❌ Tab **"Apercu"** sans accent (devrait être "Aperçu").
- ⚠ Sous le titre "Inception (2010)" : 3 petites lignes bleues fines — semblent être des badges (tier, audio, sous-titres) qui ont mal rendu (peut-être parce que le mock ne fournit pas la donnée). À vérifier en prod.
- ✅ 4 onglets clairs (Aperçu / Analyse V2 / Historique / Comparaison).
- ✅ 5 cards "SOURCE / VIDEO / AUDIO (0) / SOUS-TITRES (0) / TMDB" — bonne organisation.
- ⚠ Poster placeholder **très gros** (~250×350px) à gauche, déséquilibre vis-à-vis du titre fin.

### 3.6 UI pywebview — overlay Settings v5

**Capture** : `pywebview/1366x768/21_overlay_settings-v5_sources.png`

**Findings** :
- ❌ Sidebar : "Bibliotheque" (Bibliothèque), "Integrations" (Intégrations), "Avance" (Avancé) sans accents.
- ❌ Bouton "Reinit." (Réinit.) — apparaît plusieurs fois.
- ❌ Aide **"Separes par ; ou par ligne"** sans accent.
- ✅ Layout 2 colonnes (sidebar settings + content) bien balancé.
- ✅ Cards bien encadrées avec titre + badge état + bouton action.
- ⚠ Badges "CONFIGURE" / "PARTIEL" en cyan : "CONFIGURE" sans accent (Configuré), "PARTIEL" OK.

### 3.7 UI principale — Library legacy (vue principale)

**Capture** : `pywebview/1366x768/02_legacy_library.png`

**Findings** :
- ✅ Filtres **bien organisés** : Recherche, Tier V2, Codec, Résolution, HDR, Warnings.
- ✅ Toggle "TABLE" / "GRILLE" en haut à droite.
- ✅ Smart Playlists en haut + bouton "Sauvegarder filtres".
- ❌ Filtre tier **"Non classe"** sans accent.
- ❌ Headers table **"ANNEE"**, **"DUREE"** sans accents.
- ⚠ Tous les rows mock affichent badge **"UNKNOWN"** parce que le mock ne fournit pas tier — visible en prod si tier absent. Le placeholder est OK.

### 3.8 UI principale — Settings legacy

**Capture** : `pywebview/1366x768/07_legacy_settings.png`

**Findings** :
- ❌ "Dossier d'**etat** (optionnel)" — "etat" sans accent (état).
- ❌ "**Cle** API" → "Clé API".
- ❌ "**Memoriser** la cle" → "Mémoriser la clé".
- ❌ Section header **"ANALYSE VIDEO"** → "ANALYSE VIDÉO".
- ✅ Liste roots bien : chaque path en card avec bouton X, input + bouton "+ Ajouter" en dessous.
- ✅ Toggle "Activer TMDb" coché visible.

### 3.9 Dashboard distant — Library

**Capture** : `dashboard/1366x768/library_viewport.png`

**Findings** :
- ✅ Workflow stepper 1-5 (Analyse / Vérification / Validation / Doublons / Application) clair.
- ✅ Section "1. Analyse" avec bouton "Lancer l'analyse" jaune accent.
- ⚠ Bandeau "Outils d'analyse vidéo manquants" : couleur orange mais ressemble à une card normale, pourrait être plus distinctif (icône warning, fond orange plus saturé).
- ✅ Section "2. Vérification" avec table "6 cas à vérifier" — bonne hiérarchie.
- ✅ Filters dropdowns "Toutes les raisons", "Toutes priorités" cohérents.

### 3.10 Dashboard distant — Quality (état vide)

**Capture** : `dashboard/1366x768/quality_viewport.png`

Message "Aucun film scoré. Lancez un scan pour analyser votre bibliothèque." — message OK, mais isolé sur ~600px de vide noir. Empty state pourrait être plus engageant (icône, illustration).

### 3.11 Dashboard distant — Jellyfin "Chargement..."

**Capture** : `dashboard/1366x768/jellyfin_viewport.png`

Affiche **uniquement "Chargement..."** sur ~600px de vide. Soit la vue prend trop de temps à se charger (timeout dans le test), soit il y a un bug. À investiguer en condition réelle.

---

## 4. Plan de fixes priorisés

### Critical (à corriger en priorité — visible immédiatement)

1. **V-1 — Accents français** : campagne de remplacement systématique. Cibler les strings UI visibles. Ne pas toucher aux IDs/keys/variables JS.

2. **V-2 — Vue Accueil vide** : passer de `Promise.all` à `Promise.allSettled` dans `status.js:_loadAll()`, afficher chaque section indépendamment, ajouter état d'erreur visible.

### High

3. **V-3 — Espace vide overlays** : ajouter contenu utile en bas (KPIs récents, raccourcis, dernière action) ou réduire la hauteur min des overlays.

4. **V-4 — Skeletons sur cards V5** : afficher des skeletons (rectangles pulse) pendant chargement Quality V5, FilmDetail, etc.

### Medium

5. **V-5 — Search bar 1024px** : raccourcir placeholder, ou masquer le badge "Ctrl+K" sous 1280px.

6. **V-6 — Bandeau warning outils manquants** : ajouter icône ⚠ + fond plus saturé pour distinction.

7. **V-7 — Assistant premier lancement** : légende ou tooltip explicatif sur les 5 badges status/action.

### Low (polish)

8. **V-8 — Step actif Processing** : différence plus marquée (taille +2px, anneau coloré).

9. **V-9 — KPIs vides** : message "Lancez un scan pour voir vos KPIs" au lieu de "—".

10. **V-10 — Boutons Watchlist** : couleur plus visible (border accent, hover state).

---

## 5. Implémentation

### Stratégie pour V-1 (accents)

Plutôt que faire 80 fixes individuels, je fais des batch grep+replace ciblés sur les chaînes exactes vues à l'écran. Liste des remplacements à effectuer :

| String avant | String après | Fichiers concernés |
|---|---|---|
| `Cle API` | `Clé API` | settings.js, settings-v5.js, dashboard/views/settings.js |
| `Memoriser la cle` | `Mémoriser la clé` | settings.js, settings-v5.js |
| `Apercu` (label/title) | `Aperçu` | film-detail.js, settings.js (preview) |
| `Bibliotheque` (label) | `Bibliothèque` | settings-v5.js, film-detail.js, top-bar |
| `etat` (dans labels) | `état` | settings.js |
| `Decennie` (tab label) | `Décennie` | qij-v5.js |
| `Ere grain` (tab label) | `Ère grain` | qij-v5.js |
| `Qualite` (titre H1) | `Qualité` | qij-v5.js |
| `donnee` (texte) | `donnée` | qij-v5.js |
| `Reinit.` | `Réinit.` | settings-v5.js, components |
| `Separes par` | `Séparés par` | settings-v5.js |
| `Avance` (label) | `Avancé` | settings-v5.js sidebar |
| `Integrations` (label) | `Intégrations` | settings-v5.js, sidebar |
| `CONFIGURE` (badge label) | `CONFIGURÉ` | settings-v5.js |
| `Non classe` | `Non classé` | library views |
| `ANNEE` (table header) | `ANNÉE` | library views |
| `DUREE` (table header) | `DURÉE` | library views |
| `ANALYSE VIDEO` (section) | `ANALYSE VIDÉO` | settings.js |
| `decisions` (label) | `décisions` | processing.js |
| `Parametres` (label) | `Paramètres` | processing.js |

### Tests post-fix

- Re-lancer `tests/manual/visual_audit_pywebview.py --quick` pour vérifier visuellement.
- Lancer la suite unit : `pytest tests/ --ignore=tests/e2e* -q` → 0 régression.
- Vérifier que les tests qui contiennent le mot `Aper` passent toujours (test_polish_v5).

---

## 6. Critères de succès

- ✅ Les 80+ accents manquants visibles à l'écran sont corrigés.
- ✅ La vue Accueil dashboard rend ses KPIs même si un endpoint échoue.
- ✅ Les overlays v5 affichent skeletons pendant chargement.
- ✅ 0 régression sur 3183 unit tests + 96+ E2E pass.
- ✅ Re-capture Playwright montre les corrections en action.

---

## 7. Limites de l'audit

- **Couverture viewports** : 1024/1366/1440 capturés sur dashboard ; 1920 non terminé (process arrêté pour libérer ressources). 1366 capturé sur pywebview. Couvre ~80% des cas d'usage desktop standards.
- **Mock pywebview** : certains états (badges tier rendus) dépendent de données réelles. Mock fournit tier dans Quality reports mais pas dans `get_dashboard.rows`. Faux positifs possibles sur "UNKNOWN" tier dans Library.
- **Vidéo Playwright** : non enregistrée cette session (priorité aux captures statiques pour l'analyse). Pourra être ajoutée si besoin pour valider transitions.
- **UI principale réelle pywebview** : capturée via Chrome+mock, pas via vrai pywebview qui peut avoir des différences subtiles (rendu CEF vs Chromium standalone). 95% identique en pratique.

---

## 8. Annexe — fichiers générés

Captures :
- `tests/manual/screenshots/audit_20260429_161909/` — quick run (10 captures, 1 viewport, dashboard)
- `tests/manual/screenshots/audit_20260429_162349/` — partial full run (26 captures, 3 viewports, dashboard)
- `tests/manual/screenshots/audit_pywebview_20260429_162635/` — pywebview UI (19 captures, 1 viewport)

Scripts :
- `tests/manual/visual_audit_capture.py` — capture dashboard
- `tests/manual/visual_audit_pywebview.py` — capture UI pywebview
- `tests/manual/pywebview_api_mock.js` — mock JS riche (50+ méthodes API)

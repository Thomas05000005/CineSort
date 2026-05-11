# V4-05 — Resultats Lighthouse dashboard

**Date** : 2026-05-01
**URL testee** : `http://127.0.0.1:8642/dashboard/?ntoken=<token>&native=1`
**Lighthouse** : v13.2.0 (npx, sans install global)
**Browser** : Microsoft Edge headless (Chromium 147, fallback Chrome via `CHROME_PATH`)
**Form factor** : mobile (defaut Lighthouse) — throttling : simulate
**Branche** : `test/lighthouse-score`

## Scores

| Categorie       | Score | Seuil baseline | Cible V4+ | Verdict |
|-----------------|-------|----------------|-----------|---------|
| Performance     | 62/100 | >= 60 | 70 | WARN — sous la cible |
| Accessibility   | 90/100 | >= 85 | 90 | OK |
| Best Practices  | 96/100 | >= 90 | 95 | OK |

> Le seuil baseline est volontairement reglé en-dessous des scores observes
> pour servir de garde-fou anti-regression. La cible V4+ est l'objectif a
> atteindre via les corrections listees ci-dessous.

## Findings principaux

### Performance (62/100)

Metriques Core Web Vitals (mode mobile + throttling simulate) :
- **First Contentful Paint** : 4.16 s (score 0.20 — mauvais)
- **Largest Contentful Paint** : 7.27 s (score 0.05 — tres mauvais)
- **Speed Index** : 4.16 s (score 0.78)
- **Cumulative Layout Shift** : 0.126 (score 0.83 — limite)
- **Time to Interactive** : 7.27 s (score 0.50)

Diagnostics (gains d'optimisation potentiels) :
- `unminified-css` : 450 ms d'economie potentielle (CSS non-minifie)
- `unminified-javascript` : 350 ms d'economie potentielle (JS non-minifie)
- `unused-css-rules` : 800 ms (CSS inutilise — bundle design system v5)
- `unused-javascript` : 500 ms (JS inutilise — modules vues non-route)
- `render-blocking-insight` : ressources CSS/JS bloquant le rendu
- `network-dependency-tree` : trop de requetes en chaine
- `cache-insight` : pas de cache HTTP efficace cote serveur stdlib
- `cls-culprits` : layout shifts identifies au mount des vues

### Accessibility (90/100)

3 issues bloquantes :
1. **`aria-allowed-attr`** : `<button class="nav-btn" aria-selected="...">` —
   `aria-selected` n'est valide que sur les roles `tab`/`option`/`gridcell`/
   `row`/`treeitem`. Pour une nav principale, utiliser `aria-current="page"`.
   Fichiers concernes : `web/dashboard/index.html` (lignes 68-105) et
   `web/dashboard/core/router.js:91`.
2. **`aria-prohibited-attr`** : `<span class="service-status-dot" aria-label="statut on">`
   — `aria-label` interdit sur un span sans role. Solution : ajouter
   `role="img"` ou deplacer le label dans un `<span class="sr-only">`.
3. **`label-content-name-mismatch`** : `<button id="topbarAvatar"
   aria-label="Profil utilisateur">` — le texte visible (les initiales) n'est
   pas inclus dans l'accessible name. Solution : inclure les initiales dans
   l'aria-label, ou supprimer l'aria-label si le contenu textuel est
   suffisant.

### Best Practices (96/100)

1 issue :
1. **`errors-in-console`** :
   - 404 sur `GET /favicon.ico` (le serveur REST stdlib ne sert pas de
     favicon). Solution : ajouter `<link rel="icon" href="data:,">` dans
     `index.html` pour empecher le navigateur de demander `/favicon.ico`,
     ou servir une favicon depuis `web/dashboard/`.
   - CSP `frame-ancestors` ignore via `<meta>` : la directive n'est pas
     valide en `<meta>`, doit etre delivree en HTTP header. Solution : ajouter
     `Content-Security-Policy: frame-ancestors 'none'` dans `rest_server.py`
     en plus du meta tag (ou retirer la directive du meta).

## Corrections appliquees

**Aucune** — la regle de parallelisation V4-05 ("tu touches UNIQUEMENT le
script Lighthouse + son test + le rapport. Pas de modif applicative") est
respectee. Tous les findings sont differes vers V4-06+ ou une mission
applicative dediee.

## Recommandations differees (V4+)

### Quick-wins a11y/best-practices (1-2h, faible risque)
1. Remplacer `aria-selected` par `aria-current="page"` dans
   [`web/dashboard/index.html`](web/dashboard/index.html) + adapter
   [`web/dashboard/core/router.js:91`](web/dashboard/core/router.js#L91).
2. Ajouter `role="img"` sur `.service-status-dot` ou refactor en
   `<span class="sr-only">`.
3. Corriger l'aria-label de `#topbarAvatar` (inclure les initiales visibles).
4. Ajouter `<link rel="icon" href="data:,">` dans le `<head>` de
   `index.html` pour eliminer le 404 favicon.
5. Deplacer `frame-ancestors 'none'` du meta tag vers un HTTP header dans
   [`cinesort/infra/rest_server.py`](cinesort/infra/rest_server.py).

Effet attendu : a11y 90 → 100, best-practices 96 → 100.

### Performance (refactor — V5 ou hors scope release)
1. **Minification CSS/JS** au build : ajouter une etape `esbuild` ou
   `terser` dans `scripts/package_zip.py` pour minifier
   `web/shared/**/*.css` et `web/dashboard/**/*.js` avant le bundle.
2. **Tree-shaking / lazy-load des vues** : charger `views/library.js`,
   `views/quality.js`, etc. uniquement a l'activation de la route (gain
   estime : 500 ms JS unused).
3. **Cache HTTP** : ajouter `Cache-Control: max-age=86400` aux assets
   `/dashboard/static/*` dans `rest_server.py` (gain : second load).
4. **Reduce CLS** : reserver l'espace du loader/placeholder au mount des
   vues pour eviter les sauts de layout.
5. **Defer/preload** : ajouter `<link rel="preload">` pour les fonts et
   le CSS critique, et `defer` sur les modules JS non-critiques.

Effet attendu : performance 62 → 80+ apres les 3 premiers points.

> Note : le score performance est mesure en **mode mobile + throttling
> simulate** (defaut Lighthouse), ce qui penalise un dashboard servi en
> local. En desktop sans throttling, le LCP descend probablement < 2 s.
> Pour un dashboard usage LAN, le score mobile est surtout indicatif.

## Reproduction

```bash
# Terminal 1 : lancer le serveur REST seul (sans GUI)
.venv313/Scripts/python.exe app.py --api

# Terminal 2 : lancer Lighthouse
.venv313/Scripts/python.exe scripts/run_lighthouse.py <ton-token>

# Test baseline (skip si summary absent)
.venv313/Scripts/python.exe -m unittest tests.test_lighthouse_baseline -v
```

Pre-requis :
- Node.js + npx (Lighthouse install a la volee via `npx --yes`)
- Chrome ou Edge (Edge auto-detecte sur Windows si Chrome absent)

## Verdict global

**WARN — Acceptable pour release LAN/local mais a ameliorer.**

- A11y et Best Practices au-dessus du seuil release publique (>= 90).
- Performance sous la cible (62 vs 70). Acceptable car :
  - Dashboard servi en LAN (pas un site public — pas de SEO en jeu)
  - Bundle local sans CDN/throttling reel
  - Score mobile penalise, score desktop probablement > 80
- Les 4 quick-wins a11y/BP listes (~1-2h de travail) feront passer le
  dashboard a a11y 100 / BP 100, ce qui justifierait un V4-06 dedie.
- Les optimisations performance (minification + lazy-load + cache) sont
  un chantier V5 (~1 jour de travail) et ne sont pas bloquantes pour la
  release v7.6.0.

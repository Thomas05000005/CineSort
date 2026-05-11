# 14 Design To Code Implementation Plan

Contexte:
- lot 10 de la phase UI premium
- `figma-implement-design` n'est pas exploitable ici car le MCP Figma reste bloque par `Auth required`
- le plan s'appuie donc sur la source canonique locale:
  - [12-local-source-of-truth.md](./12-local-source-of-truth.md)
  - [11-key-screen-mockups.md](./11-key-screen-mockups.md)
  - [10-design-system-foundation.md](./10-design-system-foundation.md)
- aucun changement produit dans ce document

## 1. Principe d'implementation

But:
- convertir la direction validee en lots de refonte auditables
- maximiser le gain visuel sans casser la logique produit
- garder une trajectoire incrementalement verifiable dans le preview local

Regles:
- ne pas melanger gros changement de structure et gros changement de primitives dans un meme lot
- ne pas casser les ids HTML, contrats JS et hooks testes tant que ce n'est pas necessaire
- verifier chaque lot via preview local, Playwright, capture et tests avant le suivant
- si un arbitrage reapparait, mettre a jour la source canonique avant implementation

## 2. Lots recommandes

### Lot A - Preparation et garde-fous

But:
- preparer la refonte sans toucher au comportement

Contenu:
- figer la source canonique locale
- lister les zones de code front par responsabilite
- identifier les contrats de tests a ne pas casser
- preparer la strategie de captures avant / apres

Gain visuel:
- nul

Risque:
- tres faible

Fichiers probables:
- `docs/internal/design/`
- `tests/test_ui_logic_contracts.py`
- `tests/test_ui_preview_contracts.py`

### Lot B - Tokens visuels et variables globales

But:
- poser la base `palette A`, `densite A`, typographie et surfaces sans modifier encore fortement les ecrans

Contenu:
- refonte de `:root`
- normalisation:
  - couleurs semantiques
  - rayons
  - ombres
  - bordures
  - echelle d'espacement
  - transitions
- preparation de tokens de surface pour:
  - fond
  - surface par defaut
  - surface subtle
  - surface elevee
  - overlay

Gain visuel:
- fort et transversal

Risque:
- faible a moyen
- risque principal: regressions diffuses sur contraste ou mode clair

Fichiers probables:
- `web/styles.css`

### Lot C - Primitives globales

But:
- monter le niveau de gamme des composants de base sans toucher encore la composition des ecrans

Contenu:
- `Button`
- `Checkbox`
- `Input`
- `Select`
- `Badge`
- `Alert`
- `Card`
- details / accordions
- status messages

Gain visuel:
- tres fort

Risque:
- moyen
- risque principal: perte de lisibilite sur certains etats si les composants sont trop signes

Fichiers probables:
- `web/styles.css`
- `web/ui_shell.js`

### Lot D - Shell global desktop-first

But:
- implementer la structure `B - trois zones avec inspecteur affirme`

Contenu:
- amincir et clarifier le rail gauche
- reposer le header de page
- stabiliser la lecture `centre / droite`
- transformer le panneau droit en vrai inspecteur, pas simple bloc d'aide
- harmoniser le `contextBar`

Gain visuel:
- tres fort

Risque:
- moyen a eleve
- risque principal: collision avec layouts specifiques deja presents et regressions responsive

Fichiers probables:
- `web/index.html`
- `web/styles.css`
- `web/app.js`

### Lot E - Tables premium

But:
- traiter la plus grosse source de perception non premium

Contenu:
- shell de table commun
- hauteur de ligne
- alignements
- zebra et hover
- colonnes fixes
- actions de ligne
- checkboxes integrees
- empty states de table

Zones prioritaires:
- `Decisions`
- `Conflits`
- `Vue du run`
- `Historique`

Gain visuel:
- tres fort sur les vues expertes

Risque:
- moyen
- risque principal: casser du scroll horizontal, des largeurs de colonnes ou des selections clavier

Fichiers probables:
- `web/styles.css`
- `web/ui_shell.js`
- `web/ui_validation.js`
- `web/ui_quality.js`

### Lot F - Formulaires et filtres

But:
- rendre les zones de saisie et de filtrage plus nettes, plus calmes et moins bricolage

Contenu:
- champs texte
- selects
- groupes de filtres
- blocs de formulaires dans `Reglages`
- structure des aides courtes
- logique de densite controlee

Gain visuel:
- moyen a fort

Risque:
- moyen
- risque principal: perte de compacite sur les vues denses

Fichiers probables:
- `web/styles.css`
- `web/index.html`
- `web/ui_quality.js`
- `web/ui_validation.js`

### Lot G - Ecrans cles, passe 1

But:
- appliquer la nouvelle structure sur les vues les plus impactantes

Ecrans:
- `Accueil A`
- `Decisions A`
- `Execution B`
- `Reglages A`
- `Conflits A`

Strategie:
- traiter un ecran a la fois
- ne pas reprendre toute l'application d'un bloc
- laisser `Qualite`, `Vue du run`, `Historique` suivre juste apres avec les memes primitives

Gain visuel:
- maximal

Risque:
- eleve si plusieurs vues changent en meme temps
- a reduire en separant chaque ecran en sous-lot

Fichiers probables:
- `web/index.html`
- `web/styles.css`
- `web/app.js`
- `web/ui_validation.js`
- `web/ui_quality.js`

### Lot H - Etats secondaires et feedback

But:
- monter la qualite percue sur les etats souvent negliges

Contenu:
- empty states
- warnings / errors / success
- disabled
- loading
- modales
- petits panneaux d'aide
- messages inline

Gain visuel:
- moyen mais critique pour le fini premium

Risque:
- faible a moyen

Fichiers probables:
- `web/styles.css`
- `web/ui_shell.js`
- `web/index.html`

### Lot I - QA visuelle et polish

But:
- verifier que la refonte reste fidele a la source canonique et au produit

Contenu:
- captures preview recommandees
- comparaison des vues critiques
- ajustements fins
- mise a jour des baselines si necessaire

Validation:
- `python scripts/capture_ui_preview.py --dev --recommended`
- `python scripts/visual_check_ui_preview.py --dev`
- `check_project.bat`

Fichiers probables:
- `tests/ui_preview_baselines/...`
- `web/styles.css`
- `web/index.html`
- `docs/internal/design/`

## 3. Fichiers produits probablement touches

Front principal:
- `web/styles.css`
- `web/index.html`
- `web/app.js`
- `web/ui_shell.js`
- `web/ui_validation.js`
- `web/ui_quality.js`

Preview et verification:
- `web/preview/preview.css`
- `web/preview/README.md`
- `tests/ui_preview_baselines/critical/manifest.json`
- `tests/ui_preview_baselines/premium_sober/manifest.json`
- `tests/ui_preview_baselines/synthese_quality/manifest.json`

Tests et contrats a surveiller:
- `tests/test_ui_logic_contracts.py`
- `tests/test_ui_preview_contracts.py`
- `tests/test_runtime_ui_policy.py`
- `tests/test_modal_focus_trap_contract.py`

Docs de suivi:
- `docs/internal/design/12-local-source-of-truth.md`
- `docs/internal/design/14-design-to-code-implementation-plan.md`

## 4. Risques principaux

Risque 1:
- casser des contrats UI testes parce que l'HTML est fortement structure et deja surveille par tests

Risque 2:
- refaire trop de CSS d'un coup dans `web/styles.css`, qui est deja massif et multi-couches

Risque 3:
- surcharger le panneau droit et perdre de la largeur utile dans `Decisions` et `Qualite`

Risque 4:
- introduire des accents editoriaux trop visibles dans les vues techniques et perdre la sobriete retenue

Risque 5:
- ameliorer la beaute des tables au prix des usages experts:
  - selection
  - scan rapide
  - edition inline
  - sticky columns

Risque 6:
- casser les captures preview et les baselines visuelles si la structure change sans mise a jour de verification

## 5. Ordre d'implementation recommande

Ordre global:
1. `Lot B` Tokens visuels et variables globales
2. `Lot C` Primitives globales
3. `Lot D` Shell global desktop-first
4. `Lot E` Tables premium
5. `Lot F` Formulaires et filtres
6. `Lot G` Ecrans cles, un ecran par sous-lot
7. `Lot H` Etats secondaires et feedback
8. `Lot I` QA visuelle et polish

Ordre ecrans recommande dans `Lot G`:
1. `Accueil`
2. `Decisions`
3. `Execution`
4. `Reglages`
5. `Conflits`
6. `Vue du run`
7. `Qualite`
8. `Historique`

## 6. Strategie la plus sure

Strategie recommandee:
- faire d'abord un lot purement CSS/tokens
- ensuite un lot primitives
- ensuite un lot shell
- puis avancer ecran par ecran

Pourquoi:
- c'est le meilleur ratio gain / risque
- on obtient vite un saut de qualite visible
- on evite de casser la logique produit en meme temps que le langage visuel

## 7. Strategie la plus ambitieuse raisonnable

Strategie:
- fusionner `Lot C` et `Lot D`
- puis traiter `Accueil` et `Decisions` ensemble

Avantage:
- le produit change vraiment de stature tres vite

Inconvenient:
- debuggage plus dur
- plus de surface de regression

Recommendation:
- ne pas faire plus ambitieux que cela dans ce repo sans Figma et sans maquettes visuelles interactives

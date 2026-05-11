# V5C-03 — `_legacy_globals.js` conserve (cas bloquant)

## Decision

`web/dashboard/_legacy_globals.js` est **conserve** apres V5C-03. La suppression
prevue par le prompt n'est pas applicable sans refactor profond de toutes les
vues v5 portees.

## Pourquoi

Les vues v5 portees en V5bis (`web/views/home.js`, `library-v5.js`,
`processing.js`, `qij-v5.js`, `settings-v5.js`, `film-detail.js`, `help.js`)
referencent encore tres largement les globals helpers du webview legacy via
des references libres (resolues sur `globalThis` en strict mode quand la
propriete existe sur `window`).

Volume des references actuelles dans `web/views/*.js` + `web/dashboard/views/*.js`
(comptage des occurrences `\bNAME\b`) :

| Global              | Occurrences |
|---------------------|------------:|
| `state`             | 212         |
| `setStatusMessage`  |  75         |
| `apiCall`           |  69         |
| `flashActionButton` |  10         |
| `uiConfirm`         |  10         |
| `setPill`           |   9         |
| `setLastRunContext` |   8         |
| `loadTable`         |   4         |
| `shortPath`         |   4         |
| `showView`          |   3         |
| `openPathWithFeedback` | 3        |
| `fmtSpeed`          |   3         |
| `appendLogs`        |   2         |
| `resetRunScopedState` | 2         |
| `fmtEta`            |   2         |

Total : >400 references reparties sur 7 vues v5 + 17 vues v4 dashboard
conservees pendant la coexistence (jellyfin/plex/radarr/logs + library v4 +
quality-simulator + custom-rules-editor + about + demo-wizard + login + etc.).

Migrer ces references vers des imports ESM stricts demande :
1. Re-design de `state` global en module partage (ex. `core/state.js`) avec
   API publique ; aujourd'hui c'est un objet mutable partage par tous les
   helpers.
2. Re-design des helpers UI (`setStatusMessage`, `flashActionButton`, etc.)
   en exports ESM ou en objet de service injecte.
3. Migration de chaque fichier consommateur (suppression de la reference
   libre, ajout d'un import explicite).

C'est l'objet d'une vague ulterieure (V6+, en meme temps que la suppression
totale des vues v4 conservees pour la coexistence).

## Etat du shim apres V5C-03

`_legacy_globals.js` reste **identique** (15 stubs inoffensifs sur `window`),
charge en script classique avant `app.js` dans `web/dashboard/index.html`.

Aucune modification du fichier dans cette tache.

## Tests structurels

Le test `tests/test_v5c_legacy_cleanup.py` introduit par V5C-03 verifie :

- `web/dashboard/_legacy_globals.js` existe **toujours** (pas supprime).
- Le shim reste **minimal** (≤ 16 stubs) — garde-fou contre un re-gonflement.
- Aucun `window.state` / `window.apiCall` direct dans les composants v5
  (`web/dashboard/components/*.js`) — perimetre reduit, suffisamment isole.
- `index.html` continue de charger `_legacy_globals.js` avant `app.js` (sinon
  les vues v5 cassent).

## Migration restante

Suivre dans `BILAN_PHASES.md` (ou un AUDIT futur) :
- `web/views/home.js` : 50+ references aux globals (gros chantier).
- `web/views/processing.js` : 80+ references.
- `web/views/library-v5.js` : 30+ references.
- `web/views/qij-v5.js`, `settings-v5.js`, `film-detail.js`, `help.js` :
  references plus eparses (auto-save + helpers status).

Tant que les vues v4 dashboard (`jellyfin/plex/radarr/logs/library.js v4 ...`)
restent chargees pour la coexistence, le shim doit rester en place.

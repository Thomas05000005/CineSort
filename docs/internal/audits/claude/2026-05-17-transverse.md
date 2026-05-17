# Audit Claude — 2026-05-17 — Couche transverse

**Modele** : Opus 4.7 (thinking budget par defaut)
**Persona dominant** : ARCHITECT (categorie 47 + 10)
**Modules audites** : couche transverse (architecture + dette technique + frontend legacy)
**Categories couvertes** : 10 (dette), 11 (code mort), 47 (architecture invariants)
**Issues creees** : #215, #216, #217
**PRs creees** : cette PR (rapport)

## Resume executif

L'audit transverse 2026-05-17 confirme que les **3 chantiers majeurs documentes dans le prompt d'audit historique** ont avance significativement depuis le dernier run :

1. **Fonctions > 100L** : 14 restantes (vs 49 dans le prompt stale). Concentration sur `apply_support.py` (8/14) et `apply_core.py` (4/14). Issue **#215** ouverte avec inventaire + plan multi-PR ROI.
2. **Composants JS dupliques `web/components/` vs `web/dashboard/components/`** : 22 noms communs confirmes, AUCUN hash identique (drift complet). Mais `web/components/*` + `web/index.html` sont **legacy non-charge en prod** (confirme via `app.py`, `rest_server.py`). Plutot que remutualiser (issue #91 fermee), proposer **suppression du legacy** : issue **#217**.
3. **Imports lazy** : 45 restants (vs 161 dans le prompt stale). Categorisation : 5 `TYPE_CHECKING` (OK), 5 `cleanup.py` (intentionnel cf #83), 5 documente (DI, repositories), ~30 a evaluer un par un. Issue **#216** avec plan multi-PR (5 lots).

**Note importante** : les chiffres "49 / 22 / 161" du prompt utilisateur sont **stales**. La realite 2026-05-17 est significativement meilleure grace aux PRs #205-211 (lazy imports), #169 (facades), et la refonte continue de `apply_support`/`apply_core`.

## Findings par categorie

### Categorie 10 — Dette technique (3 findings, severite QUALITY)

1. **#215** — 14 fonctions > 100L, 8 concentrees dans `apply_support.py`. Plan multi-PR propose, 5 PRs etalees.
2. **#216** — 45 imports lazy residuels apres les phases A1-A8 de #83. 30 candidates au top-level, 15 justifies a annoter.
3. **#217** — 22 composants JS legacy + `web/index.html` non charge en prod. Suppression atomique plus simple que mutualisation.

### Categorie 47 — Architecture invariants (verification)

`import-linter` est correctement installe (`.importlinter`) avec 3 contracts :
- `domain_pure` : `cinesort.domain` ne peut importer `app/infra/ui` (1 exception annotee : `domain.core -> infra.tmdb_client` sous `TYPE_CHECKING`).
- `infra_bounded` : `cinesort.infra` ne peut importer `app/ui`.
- `app_bounded` : `cinesort.app` ne peut importer `ui`.

**Aucune regression detectee** dans les imports : tous les `^\s+(import|from) cinesort\.` audites sont soit `TYPE_CHECKING`, soit dans `cleanup.py`, soit avec rationale documentee. Pas de nouvelle violation a signaler.

### Categorie 11 — Code mort (1 finding)

Cf #217. Le legacy `web/components/*` + `web/index.html` represente **22 fichiers JS + 1 HTML** dans la racine `web/` non charges en prod ni en mode dev/pywebview. Estimation rapide : ~50 KB de JS mort + HTML mort + dependances orpheline (`web/views/_legacy_compat.js`, `web/views/_v5_helpers.js` a verifier).

## Statistiques

| Metrique | Valeur |
|----------|------:|
| Modules audites (transverse) | toute la couche |
| Findings totaux | 3 |
| dont severity QUALITY (2) | 3 |
| dont severity BUG (3) | 0 |
| dont severity BLOCKER (4) | 0 |
| Issues nouvelles | 3 (#215, #216, #217) |
| Issues complementees (commentaire) | 0 |
| PRs creees | 1 (cette PR — rapport) |
| Doublons strict detectes | 0 |
| Findings deja connus (#83/#85/#91 closed) | 3 (reframes) |

## Comparaison avec audit precedent

Le dernier audit transverse equivalent etait celui du **2026-05-12** (cf rapports `2026-05-12-all.md` et issues #83-#95). Tendance :

| Metrique | 2026-05-12 | 2026-05-17 | Delta |
|----------|----------:|----------:|------:|
| Fonctions > 100L | 49 (prompt) | 14 (audit) | **-35 (-71%)** |
| Imports lazy | 162 (#83) | 45 (mesure) | **-117 (-72%)** |
| Doublons JS components | 20 (#91) | 22 (mesure) | +2 (drift) |
| Cycle `domain -> app` | actif | **brise** (import-linter CI) | resolu |

**Conclusion architectural** : la couche transverse est en **bien meilleur etat** que le prompt historique suggere. Les findings restants sont du polissage (severity 2), pas du blocant.

## Self-critique pass

**Filtres appliques (cf etape 2.6 audit-prompt.md)** :
- Filtre 1 (realite) : tous les findings ont ete verifies en lisant le code reel (`grep -rn`, `md5sum`, `wc -l`).
- Filtre 2 (idiome) : aucun finding sur du code idiomatique.
- Filtre 3 (confidence) : tous a >0.85 (mesures factuelles + verification croisee).
- Filtre 4 (dedup cross-categories) : #215/216/217 distincts (long-functions / lazy-imports / legacy-cleanup), pas de chevauchement.
- Filtre 5 (severite) : tous a QUALITY (2), aucun escalade artificielle.
- Filtre 6 (actionabilite) : chacun a un plan multi-PR concret.
- Filtre 7 (etat actuel) : les 3 chantiers historiques (#83, #91) ont DEJA bouge significativement — chiffres mis a jour vs prompt stale.
- Filtre 8 (proportionnalite) : chaque issue inclut un plan multi-PR avec PR pilote + tailles < 500 LOC.

Findings supprimes : 0 (audit etroit + cible, peu de bruit).

## Rapport

[docs/internal/audits/claude/2026-05-17-transverse.md] (ce fichier).

## Liens

- Issue #14 — Audit complet par modules (parent)
- Issue #83 — Lazy imports (CLOSED 2026-05-16) — base de comparaison
- Issue #85 — Mixins SQLite -> Repositories (OPEN) — phase B8 pending
- Issue #91 — Doublons JS components (CLOSED) — complete par #217
- Issue #215 — Refactor 14 fonctions > 100L (NEW)
- Issue #216 — Cleanup 45 lazy imports residuels (NEW)
- Issue #217 — Suppression legacy web/components/ + web/index.html (NEW)

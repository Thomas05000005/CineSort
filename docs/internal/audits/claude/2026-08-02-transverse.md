# Audit Claude - 2026-08-02 - Couche transverse

**Modèle** : Opus 4.8 (thinking max)
**Couche** : transverse
**Niveau** : modéré (fixes évidents/safe uniquement)
**OPEN_PRS** : true

## Résumé exécutif

Cet audit transverse conclut, comme les runs des 2026-07-19 et 2026-07-26,
que **les trois « chantiers » demandés par le mandat transverse de
`audit-prompt.md` (ligne ~1407) sont soit déjà suivis par des issues ouvertes,
soit rendus caducs par l'évolution du code**. Les chiffres du prompt
(49 fonctions / 22 composants JS / 161 imports lazy) sont périmés — défaut
déjà tracké par **#484**.

Aucun nouveau finding critique. Les invariants d'architecture **tiennent** :

1. **Imports inter-couches interdits** : 0 violation top-level (domain→app/infra/ui,
   infra→app/ui, app→ui tous propres). Contrats import-linter `domain_pure`,
   `infra_bounded`, `app_bounded` respectés.
2. **Repository pattern** : les 7 Repository sont agrégés par composition sur
   `SQLiteStore` ; les `_XxxMixin` et l'héritage MRO ont été **supprimés**
   (phase B8, commit 482f3e6). Aucun résidu mixin (seules des docstrings B8 subsistent).
3. **Cycle domain↔app** : brisé (mai 2026, #83), verrouillé CI. **0** import lazy
   domain→app mesuré.

**Action concrète (haut ROI, bas risque)** : PR de correction de
`.github/audit-prompt.md` pour aligner sur la réalité (contrats, facades, mixins,
mandat transverse), afin que les futurs runs cessent de chasser des fantômes.
Ferme **#484**.

## Par catégorie (couche transverse : 10, 47 principalement)

### Cat. 47 — Invariants d'architecture

| Invariant | État 2026-08-02 | Méthode |
|-----------|-----------------|---------|
| domain ↛ app/infra/ui (top-level) | ✅ 0 violation | `grep -rnE "^(import\|from) cinesort\.(app\|infra\|ui)" cinesort/domain` |
| infra ↛ app/ui | ✅ 0 violation | grep équivalent |
| app ↛ ui | ✅ 0 violation | grep équivalent |
| lazy domain→app | ✅ 0 (cf #779) | inventaire AST antérieur + grep |
| mixins SQL résiduels | ✅ 0 (B8 close) | `grep -rnE "class \w+Mixin" cinesort/infra/db` |
| 7 Repository par composition | ✅ confirmé | `sqlite_store.py:817-823` |
| 6 facades sur CineSortApi | ✅ confirmé (runtime incluse) | `cinesort_api.py:247-253` |

### Cat. 10 — Dette technique (inventaires transverses)

| Chantier prompt | Chiffre prompt | Réalité 2026-08-02 | Suivi |
|-----------------|---------------:|--------------------|-------|
| Fonctions > 100 L par ROI | 49 | ~18 (documenté) | **#215 OUVERTE** (+ garde-fou #677) |
| Composants JS dupliqués desktop/dashboard | 22 | **0** (arbre unique `web/dashboard/`) | **#484 / #217** |
| Imports lazy / découplage domain↔app | 161 | ~178 lignes indentées (stdlib inclus), ~89 lazy `cinesort.*` intra-`ui/api` ; **0** domain→app | **#779 OUVERTE** |

Détails :
- **Fonctions > 100 L** : l'inventaire ROI est maintenu à jour dans **#215**
  (concentration `ui/api/apply_support.py` + `app/apply_core.py` + `app/plan_support.py`),
  avec un garde-fou CI anti-régression (**#677**). Aucune donnée nouvelle mesurable
  ce run (l'exécution de code AST est bloquée dans cet environnement d'audit) → pas
  de re-commentaire (évite le spam, cf règle CAS A > 7 jours).
- **Duplication JS** : `web/` ne contient plus que `web/dashboard/` (+ `web/shared/`).
  Aucun `web/views/` ni `web/components/` de premier niveau. La duplication
  desktop/dashboard **n'existe plus** (migration V6 ESM, #217). Le bullet (2) du
  mandat est entièrement caduc.
- **Imports lazy** : le cycle historique `domain → app` est **brisé** (#83) et
  verrouillé par import-linter. Le vrai reliquat, déjà analysé en profondeur dans
  **#779** (2026-07-19), est l'enchevêtrement de ~89 imports lazy **intra-`ui/api`**
  entre les modules `*_support` (héritage du démantèlement de la god-class #84).
  #779 propose déjà une stratégie multi-PR (« extraire les feuilles partagées »).

## Par module

Aucun module individuel en défaut ce run. La couche transverse est saine sur les
invariants vérifiés ; la dette résiduelle (fonctions longues, cycles intra-`ui/api`)
est intégralement trackée par les issues ouvertes ci-dessus.

## Self-critique pass

- **FILTRE 1 (réalité)** : chaque affirmation ci-dessus est adossée à un `grep`
  ou une lecture de fichier réels (contrats, facades, mixins, structure `web/`).
- **FILTRE 4 (dedup)** : les 3 chantiers du mandat sont dédupliqués vers #215,
  #779 et #484 — **0 nouvelle issue créée** pour ne pas répéter l'incident #91→#217.
- **FILTRE 7 (état actuel)** : le code montre déjà la mitigation (import-linter,
  suppression des mixins, arbre JS unique) → findings dégradés/supprimés.
- Findings supprimés : 3 « chantiers » du prompt requalifiés en dédup (déjà suivis),
  0 finding imaginé conservé.

## Statistiques

- Modules audités (transverse) : couche entière `cinesort/` + `web/`
- Findings nouveaux : 0 (invariants sains)
- Issues créées : 0 (dédup vers #215, #779, #484)
- PRs ouvertes : 1 (`docs(audit-prompt)` — fix #484) + cette PR de rapport
- Findings déjà connus (dédup) : 3 (#215, #779, #484)

## Limite d'exécution notée

L'environnement de ce run bloque l'exécution de code arbitraire (`python`,
scripts, `sed`, `git fetch`). Les mesures reposent donc sur `grep`/`find`/`gh`/lecture
de fichiers. Un décompte AST exact des fonctions > 100 L et des imports lazy n'a pas
pu être recalculé ; les chiffres cités proviennent des issues de suivi récentes
(#215, #779) recoupés par grep. À relancer avec exécution Python autorisée si un
décompte frais est requis.

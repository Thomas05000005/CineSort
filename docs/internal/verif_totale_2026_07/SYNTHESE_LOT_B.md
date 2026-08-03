# SYNTHÈSE LOT B — Phase 2 : tests de contrat permanents — 2026-07-08

> Branche `verif/totale-2026-07`, commits `88a012b..731da5f` (5 tests, 2 512 lignes).
> **25 tests de contrat, tous verts en 3,9 s.** Collecte globale : 5 909 tests, 0 erreur.
> Go/No-Go Lot C : **GO proposé**.

## Ce qui est maintenant verrouillé (philosophie import-linter étendue)

| Contrat | Fichier | Invariants | KNOWN figées |
|---|---|---|---|
| M1 UI→API | `test_contract_ui_api.py` | endpoint existe sur la façade visée + payload littéral ⊆ signature + sites dynamiques whitelistés | 5 boutons cassés |
| M3 Settings | `test_contract_settings.py` | toute clé canonique a ≥1 lecteur backend OU est figée | 38 UNWIRED + 8 indirections |
| M6 i18n | `test_contract_i18n.py` | clé référencée ∈ fr ∧ en + parité stricte fr/en + fallback ⊆ fr | 0 (déjà propre) |
| M5 CSS | `test_contract_css.py` | hex tiers UNIQUEMENT dans tokens.css + pas de nouvelle classe utilisée-non-définie | 16 hex + baseline 212 classes |
| M2 Façades | `test_contract_facades.py` | pas de nouvelle méthode orpheline / homonyme / multi-façade / classe non instanciée | 68 entrées |

**Mécanique commune** (pattern borné de `test_refactor_84_progress_v77.py`, généralisé) :
- vert AUJOURD'HUI : les violations connues sont figées **nominativement** avec cause et consigne ;
- rouge sur toute **nouvelle** violation, message = quoi + où + comment corriger ;
- rouge sur toute entrée KNOWN **périmée** (corrigée mais pas retirée) → les listes ne peuvent que rétrécir ;
- gardes anti-faux-vert (un scanner qui ne trouve plus le corpus échoue au lieu de passer vide) ;
- clés robustes sans numéros de ligne ; constantes serveur (`_EXCLUDED_METHODS`, `_FACADE_ATTR_NAMES`)
  lues depuis `rest_server` (pas dupliquées) ;
- **gate rouge→vert prouvé pour les 5** : violation synthétique plantée → FAILED nominatif →
  `git checkout` → vert (CSS a aussi prouvé la branche « périmée »).

## 2.6 Câblage CI

Aucune modification de `ci.yml` nécessaire : les 5 fichiers vivent dans `tests/` et sont ramassés
par le job « Tests unitaires avec couverture » existant. Ils s'exécutent en ~4 s au sein de la suite.

## Découvertes du Lot B (au-delà du plan)

1. **2 clés settings non câblées HORS matrice** : `update_check_channel` (défaut 'stable', aucun lecteur)
   et `update_last_check_ts` (écrit par cinesort_api.py:1007, jamais lu). Cause : le générateur
   `m3_settings.py` ignorait les `ast.AnnAssign` de `_LITERAL_DEFAULTS`. Figées en KNOWN_UNWIRED ;
   **corriger m3_settings.py** au prochain re-run de la matrice (noté Phase 5).
2. Les hex tiers de `styles.css:2044-2047` sont des *fallbacks* `var(--tier-X-solid, #hex)` — dette
   bénigne mais comptée en exception KNOWN (2ᵉ occurrence textuelle hors tokens.css).
3. Confirmation d'indépendance : chaque test recalcule ses faits depuis les sources et retombe
   EXACTEMENT sur les chiffres des matrices commitées (193 sites, 53 orphelines, 212 classes, 157 refs).

## Suite — Lot C (Phase 3) : runtime Playwright écran par écran

13 vues vivantes × chaque bouton cliqué, console 0 erreur, `getComputedStyle` invariantes tiers
× 5 thèmes, états vide/petit/gros. Prérequis : `python app.py --api` + bibliothèque virtuelle
(`test_biblio_virtuelle/`), vérifier port 8642 libre avant. Les 50 errors `test_runtime_*` de la
baseline seront réhabilités dans ce lot.

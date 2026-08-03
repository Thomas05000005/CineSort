# RAPPORT FINAL — Campagne « Vérification totale » CineSort — 2026-07-07 → 09

> Branche `verif/totale-2026-07` (base `650d162` = origin/main). ~76 commits, **jamais poussée**
> (push et tag = décision Thomas). Objectif : prouver le câblage A→Z de chaque fonction, le
> verrouiller par des contrats CI permanents, corriger tout ce qui pêche, et laisser une trace
> rejouable de chaque décision. Rapport de synthèse ; le détail par lot est dans les `SYNTHESE_LOT_*.md`.

## 1. Vue d'ensemble

| Lot | Objet | Livrable | Findings |
|---|---|---|---|
| **A** | Assainissement + cartographie | baseline verte, 8 matrices rejouables | — |
| **B** | Verrouillage | 5 tests de contrat CI | — |
| **E** | Boutons cassés + sécurité | 5 boutons + fuite token | 5 + 12 (revue) |
| **C** | Runtime (Playwright, 13 vues) | 6 sweeps permanents | 17 |
| **D** | Métier (7 chaînes bout-en-bout) | 7 tests de chaîne | 18 |
| **5** | Corrections & purge | ~4160 l. JS mort, dedup, docstrings | — |
| **6** | UX / a11y | dead CSS omdb, runtime déjà vert | — |
| **7** | Clôture | CLAUDE.md, ce rapport, mémoire | — |

**Total ~52 findings corrigés**, chacun avec un GATE (test rouge-avant/vert-après ou garde xfail→PASS),
**2-3 rounds de revue adversaire** par vague (ont attrapé des bugs réels dans les fixes eux-mêmes).

## 2. Ce qui était sain (vérifié, pas supposé)

- **Architecture** : couches domain/app/infra/ui verrouillées par import-linter (3 contrats KEPT).
- **Apply → undo** : restauration à l'identique prouvée par snapshots d'arborescence ; idempotence ;
  fichier verrouillé = échec propre ; journal write-ahead.
- **Doublons** : identité cross-racine, losers en bucket (jamais supprimés), compteurs cohérents.
- **REST** : rate-limit réel 5/60s, 413 anti-DoS, 410 legacy, OpenAPI 172 paths / 6 façades.
- **Thèmes** : les 5 thèmes conformes WCAG AA sur les paires critiques (mesuré runtime, pas grep) ;
  invariantes tiers (#E5E4E2/#FFD700/#C0C0C0/#CD7F32) uniquement dans tokens.css.

## 3. Les findings les plus importants (tous corrigés)

1. **Course racine dedup+abort** (`core/api.js`, LOTC-F1) : la dédup servait au 2ᵉ appelant la promesse
   portant le signal de nav du 1ᵉʳ → l'abort d'un appelant tuait la vue d'un autre. Un fix → 5 symptômes
   (accueil vide au boot, historique gelé = 2 échecs baseline, qualité gelée, écran mort
   traitement→doublons, bannière paramètres).
2. **Régression titre « Blade Runner 2049 »** (Lot D-fix, revue R1) : un fix de dédup mutilait le titre
   du film. Corrigé : le titre proposé reste INTACT (renommage disque = seed torrents), la tolérance
   d'année ne vit que dans la clé de dédoublonnage.
3. **5 boutons UI cassés** (Lot E) : Ignorer l'alerte, Ouvrir dossier, Apply /processing, refresh
   jaquette, upgrade Radarr — endpoints/payloads désaccordés.
4. **Exports UI jamais fonctionnels** + **crash `get_quality_report`** en run nominal (Lot D).
5. **Fuite codepoints du token en mode DEBUG** (Lot E, sécurité) — soldée avant la consigne « sécu→Opus ».
6. **R8-085** (dossier saga orphelin), **R8-083** (poll fuyard), **R8-080** (flag Jellyfin perdu) soldés.

## 4. Contrats permanents installés (le vrai héritage)

`tests/test_contract_*.py` (25 tests, ~4 s) verrouillent en CI :
- **UI→API** : tout `apiPost` matche une méthode façade + payload ⊆ signature (aurait attrapé les 5
  boutons cassés) ;
- **settings** : toute clé canonique a un lecteur backend ou est figée nominativement ;
- **i18n** : clés référencées ⊆ fr ∩ en, parité stricte ;
- **CSS** : hex tiers uniquement dans tokens.css, pas de nouvelle classe utilisée-non-définie ;
- **façades** : pas de nouvelle méthode orpheline / homonyme / non instanciée.
Plus **6 sweeps runtime** (Playwright) et **7 chaînes métier** (biblio virtuelle jetable) rejouables.
Chaque liste KNOWN ne peut que RÉTRÉCIR (rouge si nouvelle violation ET si entrée périmée).

## 5. Purge (Phase 5)

- **~4 160 lignes de JS mort** : 6 vues jamais routées (status/help/jellyfin/plex/radarr/logs) + 20
  modules injoignables (BFS du graphe d'imports, dynamiques inclus — demo-wizard préservé) +
  bootstrap-bisect sorti de prod. `web/dashboard/*.js` : ~31k → 27k lignes.
- i18n `qij.*` (144 clés × 2 locales), bloc CSS `.omdb-status*` mort, docstrings B8/6-façades périmées,
  commentaire cycle domain→app (cassé) dans core.py.
- **Réconcilié** : `wip/b4` de Thomas (PAGE_SIZE 200, palier To, label durée, idempotence scroll).
- **Dedup** : `quality_score._determine_tier/_cap_tier` délégués à `tiers_helpers`.

## 6. Reste à trancher / hors périmètre Fable

- **Sécurité → Opus** (`SECURITE_POUR_OPUS.md`) : drain body pré-auth (DoS), rest_api_token en clair,
  DPAPI-NG inachevée, tuning rate-limit 5→20 de wip/b4.
- **Décisions produit → Thomas** (`PHASE5_ARBITRAGES.md`) : i18n FR-only vs câbler (~375 clés
  orphelines), ~21 settings fantômes (auto_approve_* lu par personne…), ~60 méthodes façade sans UI,
  R8-079 (pack TV NxNN), cleanup_orphans/retention_days/{sep} naming.
- **Résiduels acceptés** : faux-positif dédup « Word AAAA (AAAA) » (report-only, rarissime), résidu
  résolution `.1080`/`.720` (LOW, zone seed).
- **Push / tag release R8 → Thomas** : `origin/main` (650d162) n'a aucun tag ; la branche
  `verif/totale-2026-07` n'est pas poussée.

## 7. Comment reprendre / rejouer

- Régénérer une matrice : `python -X utf8 docs/internal/verif_totale_2026_07/scripts_matrices/mX_*.py`.
- Rejouer les contrats : `.venv/Scripts/python.exe -X utf8 -m pytest tests/test_contract_*.py -q`.
- Rejouer un sweep runtime : `... tests/e2e_dashboard/test_lotc_sweep_<x>.py` (1 fichier à la fois si
  regression du bulk rescan revient — cf note isolation).
- Rejouer une chaîne métier : `... tests/test_lotd_chain_<x>.py` (biblio virtuelle, aucun effet disque réel).
- **Toujours** avec `.venv/Scripts/python.exe` (3.13). Baseline nominative : `baseline_tests.txt`.

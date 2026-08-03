# SYNTHÈSE LOT C — Phase 3 runtime : réhabilitation + sweep 13 vues — 2026-07-08

> Branche `verif/totale-2026-07`, commits `0d47260` + `49f6665`.
> 6 sweeps Playwright permanents (`tests/e2e_dashboard/test_lotc_sweep_*.py`), ~110 actions
> réellement cliquées, 26 captures-preuves (`captures_runtime/`), findings figés en xfail/gates nominatifs.

## 1. Réhabilitation du cluster runtime (commit `0d47260`)

Les 50 ERRORS `test_runtime_*` de la baseline étaient **3 instruments cassés** (aucun ne mesurait rien) :
1. fixture `authenticated_page` : attendait l'écran de login que le bypass auth localhost saute → shell d'abord ;
2. `test_qij_kpi_summary` : lisait `views/qij.js` supprimé (R8) → repointé sur `qualite.js` ;
3. `test_runtime_contrast_wcag` : `evaluate(js, [a,b,c])` non destructuré → fg=None, **jamais un ratio mesuré**.
   Après fix : **20/20 verts — les 5 thèmes sont réellement conformes AA sur les paires critiques.**

Résultat : 50 ERRORS → 39 verts + 2 échecs réels (historique, cause racine ci-dessous).

## 2. Vérifications POSITIVES du sweep (les fixes Lot E tiennent en runtime)

E5 apply 0-approuvé **bloqué** (toast + renvoi Review + 0 POST run/apply) ; E6 cancel-run **modale**
(annulation = 0 POST) ; R8-083 **0 tick** get_status >2,5 s après navigation ; E2 alerte ignorée
**disparaît** ; E3 bouton Ouvrir dossier **absent** hors desktop ; delete-run modale + countdown 3 s ;
labels FR ; aller-retour ×3 : 0 erreur console, 0 empilement, 0 poll zombie.

## 3. REGISTRE DES FINDINGS (17, dédupliqués par cause racine)

### ★ FAMILLE RACINE — course dedup+abort de `core/api.js` (1 fix → ≥5 symptômes)

**LOTC-F1 (HIGH)** : `_dedupExec` (api.js:88-96) rend au 2ᵉ appelant la promesse in-flight du 1ᵉʳ,
porteuse du **signal de navigation du 1ᵉʳ** ; la navigation aborte ce signal → le nouvel appelant
reçoit un AbortError partagé et sa vue meurt sans retry. Le commentaire d'apiPost (L316-325) promet
une composition de signaux que `_dedupExec` n'implémente pas. Symptômes prouvés :
- `#/accueil` **VIDE au boot** loopback (get_dashboard jamais requêté, reproduit 3×) [BUG-ACCUEIL-BOOT] ;
- `#/historique` **squelette pour toujours** en navigation immédiate = les 2 échecs baseline
  (fenêtre 800 ms markTokenAbsent) [LOTC-HISTO-01, gate en échec reproductible] ;
- `#/qualite` gelée sur skeleton + `#/doublons` bannière mensongère « Aucun run actif » ;
- `#/traitement` : « Passer aux Doublons » → écran mort (repro 100 %) + race à l'arrivée (7/7) ;
- `#/parametres` : bannière « signal is aborted without reason » en nav rapide (9/9).
**Fix cible** : composer les signaux des appelants dédupliqués (n'aborter le fetch partagé que quand
TOUS ont abandonné) et/ou ne jamais servir une promesse déjà abortée à un nouvel appelant.

### Z-INDEX / EMPILEMENT (2 HIGH + 1 MAJ)

- **LOTC-Z1 (HIGH)** : modale de confirmation danger (z 10000) **SOUS** l'overlay fiche film (z 10001)
  → toute confirmation ouverte depuis la fiche est invisible/incliquable (components.css:7747 vs 8281).
- **LOTC-Z2 (HIGH)** : drawer filtres avancés bibliothèque — le **backdrop peint AU-DESSUS du panneau**
  (2 frères sans z-index, components.css:7311-7343) → les 10 filtres inutilisables à la souris.
- **LOTC-Z3 (MAJ)** : drawer documentation `#/aide` rendu SOUS la topbar → croix incliquable.

### BACKEND / CONTRATS (2 HIGH + 1 MED)

- **LOTC-B1 (HIGH)** : bulk « Re-scanner » (bibliothèque) **vide toute la bibliothèque** pour la
  session : start_job insère un run parasite sans plan, `_resolve_run_id` (library_support.py:778,
  list_runs limit=1) le résout → 0 film partout.
- **LOTC-B2 (MED)** : step Review de /processing lit `payload.rows` que `run/load_validation` ne
  renvoie PAS ({ok, decisions} seulement) → tableau review toujours vide sur la vue legacy.
- **LOTC-B3 (MED)** : reveal token REST (paramètres) révèle **le masque** : le bouton 👁 bascule
  input.type au lieu d'appeler `settings/reveal_rest_token` (R7-10, déjà utilisé par status.js mort).

### CSP / HANDLERS INLINE (1 MED transverse)

- **LOTC-C1 (MED)** : `onclick=`/`onerror=` inline bloqués par la CSP `script-src 'self'` —
  fallbacks poster morts (film-detail, qualite, doublons) + stopPropagation checkbox bibliothèque
  → violations console à chaque fiche + image cassée au lieu du placeholder.

### ROUTER / DIVERS

- **LOTC-R1 (MAJ)** : le router ne strippe pas `?query` → suggestions accueil « Points à traiter »
  rebondissent sur #/accueil sans effet (router.js:111).
- **LOTC-M1 (MIN)** : About lit `res.version` sur l'enveloppe au lieu de `res.data.version` →
  « version indisponible ».
- **LOTC-M2 (MIN)** : suggestions accueil affichent `[object Object]` (filter_hint dict backend
  rendu via String(), accueil.js:626).
- **LOTC-M3 (BASSE)** : `_dominantTier` retourne « Platinum » quand tout est à 0 (qualite.js:586).
- **LOTC-M4 (LOW)** : toggle du panneau droit replié = rect 0×0 (insaisissable souris).
- **LOTC-M5 (LOW)** : bruit `[BOOT-DEBUG] window.error` (bootstrap-debug) sur erreurs de ressources.
- **LOTC-T1 (test-data)** : create_test_data écrit des tiers legacy (Premium/Bon/…) impossibles
  post-migration-011 → KPI qualité E2E faussés (0 classé) ; corriger le mock.

## 4. Ordre de correction proposé (vague Lot C-fix)

1. **LOTC-F1** (le fix racine api.js — débloque 5 symptômes + les 2 échecs baseline + retire les
   workarounds/retry des sweeps) ;
2. LOTC-Z1/Z2/Z3 (z-index — 3 fixes CSS ciblés) ;
3. LOTC-B1 (bulk rescan destructeur de session) ;
4. LOTC-C1 (CSP : remplacer les handlers inline par des listeners délégués) ;
5. LOTC-R1, B3, B2 ; puis les mineurs M1-M5 + T1.
Chaque fix : GATE = retirer le xfail/workaround du sweep correspondant → le test passe en positif.
Revue adversaire 2 rounds avant clôture (règle validée aux Lots E).

## 5. Convention d'exécution des sweeps (revalidation 2026-07-08)

Les 6 sweeps sont **stables exécutés PAR FICHIER** (validé 2× chacun + contre-preuve : qualite-doublons
6/6 seul vs FAILED en groupé). En exécution GROUPÉE (1 processus pytest), la fixture `e2e_server`
est session-scoped → serveur PARTAGÉ, et le sweep bibliothèque déclenche LOTC-B1 (run parasite du
bulk Re-scanner) qui **vide la bibliothèque pour tous les fichiers suivants** → 11 échecs en cascade.
Tant que LOTC-B1 n'est pas corrigé : lancer les sweeps 1 fichier à la fois
(`.venv/Scripts/python.exe -X utf8 -m pytest tests/e2e_dashboard/test_lotc_sweep_<x>.py -q`).
Après le fix LOTC-B1, réévaluer un passage groupé (et éventuellement un scope module de e2e_server).

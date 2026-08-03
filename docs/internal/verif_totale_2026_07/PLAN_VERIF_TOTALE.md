# PLAN VÉRIF TOTALE 2026-07 — câblage A→Z de chaque fonction

> **Objectif** : prouver que CHAQUE fonction de l'app est câblée de bout en bout — clic UI → handler JS →
> endpoint REST → façade → support → app/domain → infra/DB → réponse → rendu → CSS — et que chaque logique
> est claire, cohérente à l'usage, sans chemin mort ni contrat désaccordé. Là où c'est cassé ou incohérent :
> corriger. Là où c'est flou : améliorer la cohérence d'utilisation. À la fin, le câblage est **verrouillé
> par des tests de contrat permanents** (même philosophie que import-linter pour l'architecture).
>
> **Règle d'acceptation** (héritée de R8) : un fix n'est accepté que s'il fait basculer une observation
> « cassé → correct » SANS régresser une observation saine. Toute matrice générée est un artefact rejouable
> versionné dans ce dossier.
>
> **État de départ** : branche `merge/r8-into-main` = `origin/main` (650d162, squash R8). Bugs déjà connus à
> intégrer en Phase 5 : fuite codepoints token DEBUG, 2 boutons UI cassés (mark_alert_ignored, open_path),
> _detect_cloud_sync_folder substring, locks pydantic, R8-083/084/085, 4 LOW R8, différés actés (voir
> `../r8/R8_CORRECTIONS.md`).

---

## 0. PÉRIMÈTRE CHIFFRÉ (inventaire du 2026-07-08, vérifié)

| Surface | Volume | Matrice |
|---|---|---|
| Endpoints appelés côté JS | **118 uniques** (202 sites `apiPost`) | M1 |
| Méthodes façades | **172** (run 37, quality 41, runtime 32, library 25, settings 21, integrations 16) | M1+M2 |
| Modules support | 32 `*_support.py` (CLAUDE.md dit 47 → dérive à corriger) | M2 |
| Clés settings canoniques | **190** | M3 |
| Actions UI (`data-*action`) | **128** boutons/actions | M4 |
| Vues JS | 19 (dont 6 mortes : status, help, jellyfin, plex, radarr, logs) + 36 composants | M4+M5 |
| CSS | **13 952 lignes** (components.css 10 145, styles.css 2 569, tokens/thèmes/typo/anim/util) × 5 thèmes | M5 |
| i18n | **747 clés** × 2 locales (fr/en) | M6 |
| DB | **24 tables**, 11 repositories, 31 migrations découvertes (+032 en tirets = différé D3, NE PAS toucher) | M7 |
| Pollers/timers JS | à inventorier (setInterval/setTimeout + cleanup unmount) | M8 |
| Tests | 5 884 collectés ; 496 fichiers racine dont 74 morts | Phase 0 |

---

## PHASE 0 — Prérequis & assainissement (½ j) — GATE : baseline verte reproductible

Sans ça, toute mesure ultérieure est bruitée.

- [ ] 0.1 Fast-forward `main` local sur `origin/main` (depuis le worktree CineSort-B4 qui le checkout).
- [ ] 0.2 Régénérer `uv.lock` + `requirements.lock` (pydantic absent des deux) ; aligner `requirements-dev.txt`
      sur l'extra `[dev]` (pytest-cov, sqlparse). GATE : install `--frozen` + `python -c "import pydantic"` OK.
- [ ] 0.3 `git rm --cached` des 36 artefacts debug trackés (15 `.err`, `.pid`, `.out`, `_iter7/8_test/`,
      `.tmp_lint_imports_output.txt`) + compléter `.gitignore` (`*.err`, `*.out`, `*.pid`, `_iter*`,
      `_revue_*.json`, ancrer `/settings.json`). Supprimer `:TEMPold_scene_parser.py` (U+F03A) et `data.db` 0 o.
- [ ] 0.4 Supprimer les 74 fichiers tests morts « Legacy frontend removed » (~15 000 lignes) + déclarer
      `[tool.pytest.ini_options]` (testpaths, markers dont `runtime`). GATE : `pytest --collect-only -q` sans
      warning marker, même count qu'avant moins les morts.
- [ ] 0.5 Figer la **baseline verte** : suite complète 1×, échecs tolérés listés nominativement dans
      `baseline_tests.txt` (fini le « ~24 échecs » flou). Tout écart ultérieur = régression.
- [ ] 0.6 Rituel instance : vérifier port 8642 / `app.py --api` avant toute session runtime (mémoire projet) ;
      les tests utilisent des ports éphémères ; `tests/e2e` exclus des sweeps unitaires.

---

## PHASE 1 — Génération des 8 matrices de câblage (1-1½ j) — GATE : artefacts rejouables commités

Chaque matrice = 1 script Python/Node dans `scripts_matrices/` + 1 sortie JSON/CSV figée dans `matrices/`.
Les scripts sont **rejouables** : toute session future peut régénérer et diff.

### M1 — Contrat UI→API (la matrice reine)
Pour chacun des **202 sites `apiPost`** : `fichier:ligne JS | endpoint | payload envoyé (clés) | façade.méthode
réelle | signature Python | verdict {OK, ENDPOINT_INEXISTANT, MAUVAISE_FAÇADE, PAYLOAD_DÉSACCORDÉ, EXCLU}`.
- Outillage : grep AST-ish des `apiPost(` + introspection `dir()` des 6 façades + `inspect.signature`.
- Attrapera d'office : `run/mark_alert_ignored` (traitement.js:2498) et `open_path` (film-detail.js:1212).
- **Sens inverse** : 172 méthodes façades → consommateur web ? Les ~52-54 orphelines sont classées
  {À_CÂBLER_UI, BACKEND_ONLY_ASSUMÉ, À_ÉLAGUER} — classement = décision Thomas en fin de Phase 2.

### M2 — Chaîne interne façade→support→impl
Pour chacune des 172 méthodes : `façade | délègue à (_X_impl god-class OU support direct) | homonymes dupliqués |
profondeur`. Objectifs : lister les 148 `_X_impl` restants, les 14 homonymes god-class/support, les doublons
d'exposition (get_profiles ×2), `SimilarFilmsFacade` orpheline. Verdict par méthode : {PROPRE, DOUBLE_CHEMIN,
DUPLIQUÉ, ORPHELIN}.

### M3 — Settings : write → read → EFFET
Pour chacune des **190 clés** : `écrite par l'UI ? (parametres.js) | lue par le backend ? (grep get) | a un
EFFET runtime prouvable ? | round-trip GET→POST→GET identique ?`. Verdict : {CÂBLÉE, WRITE_ONLY, READ_ONLY,
FANTÔME, ALIAS_MORT}. Rappels mémoire : l'UI POST l'objet settings ENTIER (tout fallback d'alias est mort) ;
lire settings.json en `utf-8-sig` (BOM PowerShell). Les write-only déjà connus (cleanup_empty_folders,
excluded_patterns, retention_days non planifié) alimentent les arbitrages Phase 5.

### M4 — Actions UI : bouton → handler → effet → feedback
Pour chacune des **128 `data-*action`** + soumissions de formulaires + éléments cliquables sans data-action :
`vue | libellé | handler JS | endpoint(s) | état pendant (spinner/disabled ?) | feedback succès | feedback
erreur (res.data.ok géré ?) | confirmation si dangereux (modale + liste + délai 3 s si >50 — règle inviolable)`.
Verdict : {OK, MUET_SUCCÈS, MUET_ERREUR, SANS_CONFIRMATION, CASSÉ}.

### M5 — CSS & rendu
- Classes **utilisées** (JS/HTML) vs **définies** (13 952 l.) : orphelines dans les 2 sens ; doublons de
  définition inter-fichiers ; classes partagées entre composants DOM différents (interdit — mémoire JS).
- Tokens : toute couleur en dur hors `tokens.css` = finding (ex. `.omdb-status--warning/#b45309` connu).
- **Vérif RUNTIME obligatoire** (mémoire : jamais au grep seul) : Playwright `getComputedStyle` sur les
  invariantes tier (Platinum #E5E4E2, Gold #FFD700, Silver #C0C0C0, Bronze #CD7F32) × **5 thèmes** ×
  vues qui les affichent. + contraste WCAG AA 4.5:1 automatisé sur les paires token/fond par thème.
- Fonds/opacité : re-jouer les checks R6-E (modales, drawers, dropdowns `color-scheme`).

### M6 — i18n
747 clés × 2 locales : clés référencées dans le JS mais absentes d'une locale ; clés définies jamais
référencées ; textes en dur dans le JS/HTML qui devraient passer par i18n. Verdict par clé.

### M7 — DB : table → repo → consommateur → UI
24 tables : `migration d'origine | repository | méthodes qui lisent/écrivent | remonte à l'UI où ?`.
Tables write-only (écrites, jamais lues) et read-never = findings. Vérifier `perceptual_reports` ≠
`quality_reports` (règle inviolable). Migrations : idempotence sur base PRÉ-EXISTANTE (mémoire SQLite).

### M8 — Pollers, timers, cleanup
Tous les `setInterval`/`setTimeout`/listeners globaux : `créé où | cleanup au unmount/navigation ? | s'empile
si revisite ?`. R8-083 (poll /processing) et R8-084 (saveTimer reset) en font partie ; chercher les frères.

---

## PHASE 2 — Verrouillage : tests de contrat permanents (1 j) — GATE : CI rouge si câblage cassé

Transformer chaque matrice en test qui vivra dans la CI (le vrai « améliorer » structurel : plus jamais un
bouton qui appelle un endpoint inexistant ne passe inaperçu) :

- [ ] 2.1 `test_contract_ui_api.py` : chaque `apiPost` du JS matche une méthode façade existante + payload ⊆
      signature (M1). Aurait attrapé les 2 boutons cassés.
- [ ] 2.2 `test_contract_settings.py` : chaque clé canonique a lecture backend + effet déclaré, round-trip
      stable (M3).
- [ ] 2.3 `test_contract_i18n.py` : clés JS ⊆ fr.json ∩ en.json (M6).
- [ ] 2.4 `test_contract_css.js` (node --check + script) : classes utilisées ⊆ définies ; 0 hex tier hors
      tokens.css (M5 statique).
- [ ] 2.5 `test_contract_facades.py` : 0 nouvelle méthode orpheline non classée ; 0 nouvel homonyme (M2).
- [ ] 2.6 Brancher dans `ci.yml` à côté de lint-imports.

---

## PHASE 3 — Vérification RUNTIME écran par écran (2-3 j) — GATE : console 0 erreur partout

Playwright sur l'app réelle (`python app.py --api` + dashboard), bibliothèque virtuelle de test
(`test_biblio_virtuelle/`), AUCUNE écriture sur la vraie bibliothèque. Pour **chacune des 13 vues vivantes**
(accueil, bibliothèque, traitement, processing, qualité, doublons, comparateur, historique, inspecteur,
paramètres, film-detail, onboarding, undo/annulation) :

1. Navigation directe + via menu → rendu complet, pas d'écran noir, pas de FOUC.
2. **Chaque bouton/action de M4 cliqué réellement** : réponse réseau 2xx attendue, mutation d'état visible,
   feedback affiché ; erreurs métier (`res.data.ok=false`) affichées, pas avalées.
3. Console : **0 erreur, 0 warning nouveau** (baseline des warnings connus figée en Phase 1).
4. États : vide (0 films), petit (5), gros (500+ virtuel) ; pendant un run actif ; après annulation.
5. Navigation aller-retour ×3 : pas de fuite (M8), pas de doublon de listeners, caches cohérents.
6. Thème ×5 + `getComputedStyle` invariantes tier + focus clavier (tab order, focus-trap modales).
7. Captures avant/après versionnées dans `captures_runtime/` (pattern baseline R8).

---

## PHASE 4 — Logiques métier bout-en-bout (2-3 j) — GATE : parcours complets sans divergence

Sur bibliothèque virtuelle, les chaînes fonctionnelles complètes, avec vérification des invariants à chaque pas :

- [ ] 4.1 **Scan → plan** : multi-root, incrémental (cache v2), TV vs films (inclure R8-079 Show.101),
      NFO/tmdb_id (GAP connu : 0 tmdb_id si NFO matche — décider ici de le solder), exclusions.
- [ ] 4.2 **Apply → undo** : dry-run ≡ apply (divergence saga R8-085 ici), atomicité collection, rollback,
      undo 24 h, undo casse-seule, quarantaine + TTL vs rétention runs, journal write-ahead. Preview = réalité.
- [ ] 4.3 **Doublons** : identité titre+année cross-racine, décisions Garder A/B persistées, losers →
      `_user_marked_for_deletion/`, compteurs cohérents (moved==deleted).
- [ ] 4.4 **Qualité/perceptuel** : scoring probe vs nom, tiers (délégation unique tiers_helpers — supprimer la
      duplication quality_score en Phase 5), perceptuel V1/V2 kill-switch, comparateur (frames/audio),
      seuils BLUR_* (différé R8-096 : au minimum documenter l'échelle).
- [ ] 4.5 **Intégrations** : Jellyfin (sync watched + retry 503 = R8-080), Plex, Radarr, TMDb/OMDb (clés DPAPI,
      circuit breakers — étendre aux 3 manquants en Phase 5), SMTP.
- [ ] 4.6 **Exports/rapports** : CSV (jamais validé — mémoire), HTML, NFO ; encodages ; chemins longs MAX_PATH.
- [ ] 4.7 **REST pur** (`--api` sans UI) : auth, rate-limit, 410 legacy, `http_status`, health/spec.

---

## PHASE 5 — Corrections (volume selon findings, ~2-4 j) — GATE : 1 sujet = 1 commit, cassé→corrigé prouvé

Ordre des familles (le connu d'abord, le découvert ensuite) :

1. **Sécurité** : codepoints token DEBUG (rest_server.py:605/614) ; rest_api_token en clair ; achever DPAPI-NG
   (écritures ET lectures, 5 secrets legacy).
2. **Boutons cassés** : mark_alert_ignored (payload+façade) ; open_path (bridge pywebview ou endpoint validé
   sous library_path — l'exclusion REST est DÉLIBÉRÉE, ne pas ré-exposer).
3. **R8 résiduels** : R8-083, R8-084, R8-085 + faux WARNING cloud-sync (préfixe de segment, pas égalité stricte).
4. **Découvertes M1-M8** : par verdict, priorité {CASSÉ > DÉSACCORDÉ > MUET > ORPHELIN}.
5. **Purge** : ~4 000 l. JS mort (6 vues + 17 composants + conteneurs DOM), bootstrap-bisect hors prod
   (flag ?debug=1), docstrings périmés (« B8 future » ×7, « 5 façades »), commentaire core.py:14-37.
6. **Arbitrages Thomas** (bloqués sans lui) : cleanup_orphans, retention_days, {sep} naming (⚠️ seeding
   torrent — opt-in réversible obligatoire), cleanup_empty_folders, excluded_patterns, sort des ~52 méthodes
   orphelines (câbler/assumer/élaguer), tag release R8.

## PHASE 6 — Cohérence d'utilisation (1-2 j) — GATE : parcours utilisateur racontable sans surprise

Passe UX transverse, avec l'app réelle sous les yeux :

- [ ] 6.1 **Parcours canoniques** rejoués naïvement : « je viens d'installer », « je trie 500 films »,
      « je corrige une erreur d'apply », « je cherche pourquoi ce film est Bronze ». Chaque étape : l'action
      suivante est-elle évidente ? le vocabulaire est-il constant (run/scan/plan/traitement) ?
- [ ] 6.2 **États intermédiaires** : chaque opération >1 s a un état pendant + résultat + chemin de sortie.
- [ ] 6.3 **Danger** : relire chaque action destructive contre la règle inviolable (modale + liste + délai 3 s).
- [ ] 6.4 **Wording i18n** : cohérence fr/en, ton, pas de jargon interne (« QIJ », « seam ») qui fuit dans l'UI.
- [ ] 6.5 a11y : contrastes AA sur 5 thèmes (siblings omdb-status connus), navigation clavier, aria des modales.
- [ ] 6.6 Chaque amélioration = mini-spec avant/après dans `ux_ameliorations.md`, validée puis codée en Phase 5 bis.

## PHASE 7 — Clôture (½ j)

- [ ] 7.1 MAJ `docs/internal/CLAUDE.md` (état réel : R8 poussé, 32 supports, 496→N tests, matrices, contrats CI)
      + `BILAN_PHASES.md` (règle 12).
- [ ] 7.2 Rapport final `RAPPORT_VERIF_TOTALE.md` : findings par matrice, corrigés/différés/arbitrages, diff baseline.
- [ ] 7.3 Tag + release (décision Thomas), notes narratives.
- [ ] 7.4 MAJ mémoire projet.

---

## RÈGLES INVIOLABLES (rappel, s'appliquent à toutes les phases)

1. Ne JAMAIS modifier le titre des films au-delà du renommage configuré (seed torrents).
2. Couleurs tier hex invariantes, définies UNIQUEMENT dans tokens.css — vérif RUNTIME, pas grep.
3. Backward compat absolue (Strangler Fig) ; migrations idempotentes testées sur base pré-existante.
4. `perceptual_reports` ≠ `quality_reports`.
5. Secrets DPAPI, jamais en clair ; settings.json lu en utf-8-sig ; l'UI POST le payload ENTIER.
6. Actions dangereuses = confirmation renforcée.
7. Vérifier l'instance (port 8642) avant toute op serveur ; tests sur ports éphémères ; e2e hors sweeps.
8. Jamais de `stash pop` après stash no-op (15 stashs préexistants) ; pas de push `--force` ; publication
   main public sans logs bruts.
9. Ne pas « corriger » les décisions actées : migration 032 en tirets (D3), exclusion open_path du REST,
   R8-021 rétracté, annexe « latents/réfutés » de BASELINE_R8.

## ORDRE D'EXÉCUTION & BUDGET

| Lot | Phases | Durée estimée | Go/No-Go |
|---|---|---|---|
| A | 0 + 1 | ~2 j | baseline verte + 8 matrices commitées |
| B | 2 | ~1 j | contrats en CI, rouge sur bug planté volontairement |
| C | 3 | ~2-3 j | 13 vues, console 0 erreur, captures figées |
| D | 4 | ~2-3 j | 7 chaînes métier vertes sur biblio virtuelle |
| E | 5 | ~2-4 j | findings soldés ou différés motivés |
| F | 6 + 5bis | ~1-2 j | améliorations UX validées puis codées |
| G | 7 | ~½ j | docs + tag |

**Total : ~10-15 j de sessions.** Multi-agents en worktrees isolés dès que ≥2 lots indépendants (règle mémoire) ;
revue adversaire itérative (find→verify→judge, 2-3 rounds) avant chaque GATE de lot.

# SYNTHÈSE VAGUE LOT D-FIX — 18 findings métier + 2 rounds de revue — 2026-07-08/09

> Branche `verif/totale-2026-07`. La découverte (Lot D, 7 chaînes, 18 findings) est dans
> SYNTHESE_LOT_D.md. Ce document couvre la **vague de correction** et ses 2 rounds de revue.

## Vague initiale (9 commits `6a2c8b5..bde65ec`)

15 findings corrigés + 1 régression E4 attrapée au passage (mocks tmdb `force_refresh`) :
exports UI (les 3 boutons + toast NFO + CSV CRLF), crash `get_quality_report`
(`iter_videos` kwarg), **cause racine des 2 bugs de titre** (`Path.stem` mangeait `.2005`/`.1-GRP`),
GAP-NFO-TMDBID, Jellyfin R8-080 + INT-01, R8-085 A+B + viewer quarantaine élargi, drain body REST +
clé TMDb sanitisée, explain baseline + métriques cache. Différentiel corpus 162 noms = 0 mutilation.

## Revue ROUND 1 (15 findings → 11 confirmés / 1 réfuté / 2 nuancés / 1 échec)

6 commits `ec27fc9..5d05afb` + la sécurité mise de côté :
- **RÉGRESSION titre (MAJ)** `ec27fc9` : mon propre fix de la vague mutilait « Blade Runner 2049 »
  (titre du film, sorti en 2017) en « Blade Runner » quand l'année de sortie était absente du nom.
  → le `proposed_title` reste **INTACT** (renommage disque = titre, seed torrents sauf) ; la tolérance
  « Titre 2005 »|2005 == « Titre »|2005 est portée **uniquement par la clé de dédoublonnage**
  (`title_helpers.strip_trailing_year_if_equal` dans `movie_key` + `film_identity_key`).
- **Quarantaine** `4fb047d` : modale « Vider » annonçait un compte gonflé (buckets runs non purgés) →
  `purge_scope_files_count/size` + échantillon purgeable ; `age_days` stable ; scope excluant `_duplicates_user_decided`.
- **Undo** `7e2962c` : orphelin de dossier saga inter-batch → balayage MKDIR de tous les batches.
- **Export** `72670b7` : CSV téléchargé garde ses CRLF (`read_text(newline='')`).
- **Jellyfin** `5d05afb` : film disparu de l'index → `not_found` au lieu d'`error` figé.
- **Sécurité → Opus** : le drain body pré-auth (DoS de thread) est consigné dans
  `SECURITE_POUR_OPUS.md`, **non corrigé** (décision utilisateur : la sécurité est traitée par Opus).

## Revue ROUND 2 (9 findings → 7 confirmés / 1 réfuté / 1 nuance) — commit `07b976f`

La revue des fixes R1 a encore trouvé 6 vrais défauts **dans les corrections du round 1** :
- **quarantaine C (MED)** : `_sync_arrival_manifest` confondait « persister » et « comment dater » →
  le dry-run purge divergeait du purge réel. Découplé via un flag `stable_arrival` distinct.
- **film_history A (MED)** : la tolérance d'année avait été posée sur `film_identity_key`
  (**fonction morte**) ; le chemin vivant `identity_key_from_dict` était inchangé → no-op. Corrigé.
- **dédup F** : `duplicate_multi_signal._strict_key` réaligné sur `movie_key` (invariant rétabli).
- **undo D** : `list_apply_batches_for_run(limit<=0)` = tous les batches ; le cap DESC 1000 jetait les
  plus anciens → un vieux batch pouvait laisser un dossier saga orphelin.
- **quarantaine E** : `purge_scope_sample` backend (échantillon jamais vide quand total>0).
- **st_ctime anchor** : gardé en repli seulement (le fichier reste prioritaire, test de stabilité vert).
- **Réfuté** : divergence de dossiers cibles (les 2 variantes parsent identiquement, pas de divergence).
- **Résiduel ACCEPTÉ** : faux-positif dédup « Word AAAA (AAAA) » (dossier) vs « Word » (même année) —
  report-only, astronomiquement rare. Le fix proposé (ne pas stripper pour les titres issus de
  dossiers) casserait la cohérence avec les dossiers que l'apply crée lui-même → non appliqué.

**Bilan revues : 2 rounds = 12 vrais défauts corrigés, dont 6 dans les fixes du round 1.**
La règle « 2-3 rounds find→verify avant clôture » a encore payé sur chaque étage.

## Résiduels / différés (documentés, non corrigés)
- **#5 résolution `.1080`/`.720` sans « p »** : `Film.FRENCH.1080` garde « 1080 » (résidu de
  `_REAL_FILE_EXT_RE`). LOW, zone seed-critique → déféré (strip risqué sur les titres-nombre).
- **Sécurité** : voir `SECURITE_POUR_OPUS.md` (drain body DoS, rest_api_token clair, DPAPI-NG).
- **R8-079** : pack TV `Show.101` planifié en films — décision produit (convention NxNN opt-in ?).
- **Faux-positif dédup Word-année** : accepté (cf round 2).

## Gate
7 chaînes métier `test_lotd_chain_*` vertes (findings corrigés → xfails devenus PASS ou gardes
positives), lint propre sur les fichiers touchés, 0 nouveau lint.

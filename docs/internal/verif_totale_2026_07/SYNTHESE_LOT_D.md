# SYNTHÈSE LOT D — Phase 4 : 7 chaînes métier bout-en-bout — 2026-07-08

> Branche `verif/totale-2026-07`, commit `22e612b`. 7 tests de chaîne permanents
> (`tests/test_lotd_chain_*.py`), bibliothèques virtuelles jetables, **42 verts + 16 xfail
> nominatifs** (+ intégrations 11 verts + 3 xfail, ~64 s, jouée séparément).
> **18 findings réels**, chacun figé en garde xfail rejouable. Preuves : `lotd/`.

## Vérifications POSITIVES (le cœur métier tient)

Apply réel conforme (renames/moves + sidecars + ops DB) ; **undo à l'identique** (snapshots
d'arborescence) ; re-apply idempotent ; fichier verrouillé = échec propre ; doublons cross-root
groupés par identité, winner persisté (R8-057 OK), loser déplacé jamais supprimé, compteur R8-018
exact, undo bit-à-bit ; scoring nom-seul monotone (2160p>1080p>720p), tiers canoniques + cap Silver
si probe FAILED, custom rules exactes ; rate-limit RÉEL 5 échecs/60 s + cap global 20 + Retry-After ;
410 legacy ; 413 anti-DoS avec abort avant lecture ; OpenAPI 172 paths/6 façades ; retry GET 503 OK ;
scrubber caviarde les secrets dans les logs ; exports NFO dry/skip/overwrite corrects ; MAX_PATH ok.

## REGISTRE DES 18 FINDINGS (tous en garde xfail nominative)

### HIGH (4)
| ID | Chaîne | Défaut |
|---|---|---|
| **LOTD-EXP-02** | exports | Les 3 boutons JSON/CSV/HTML de #/logs affichent TOUJOURS « export_no_data » : logs.js exige `res.data.content`, le backend renvoie `{path,...}` sans content — **aucun export UI n'a jamais fonctionné** |
| **BUG-LOTD-ITERVIDEOS-KWARG** | rest | `get_quality_report` crashe en TypeError (`iter_videos() missing min_video_bytes`, run_read_support.py:100) dès que la résolution du fichier échoue — se déclenche AUSSI spontanément en run nominal → rapports qualité silencieusement absents |
| **R8-080 confirmé** | intégrations | Flag « vu » Jellyfin PERDU sur 503 transitoire : mark_played retiré de pending sans retry (POST exclu du retry de session) |
| **LOTD-INT-01** | intégrations | La boucle retry de restore_watched ne catch pas JellyfinError → un 404/5xx transitoire sur la liste abandonne TOUTE la restauration |

### MED (10)
- **LOTD-DUP-TITLE-YEAR** (doublons+apply) : `clean_title_guess` garde l'année dans le titre quand
  un tag qualité suit (`Titre.2005.720p` → « Titre 2005 ») mais pas en fin de nom → 2 copies du MÊME
  film = 2 identités → **vrai doublon RATÉ** + dossier « Titre 2005 (2005) ». Touche tout nom scène standard sans TMDb.
- **BUG-TITLE-CHANNEL-RESIDUE** (scoring) : canaux audio avant release group collé →
  « Interstellar 2014 7 » (`TrueHD.Atmos.7.1-GRP`, ordre des strips dans parse_scene_title).
- **LOTD-DUP-BUCKET-VIEWER** (doublons) : losers routés vers `run_dir/_review/` mais le viewer
  quarantaine lit `root/_review/` → récupérable sur disque, **INVISIBLE dans l'UI** (parent R8-002).
- **R8-085 A+B confirmés** (apply) : dossier saga vide orphelin créé même sur film conforme (mkdir
  avant gardes, jamais journalisé) ; l'undo laisse les orphelins (« pas à l'identique »).
- **GAP-NFO-TMDBID confirmé** (scan) : `<tmdbid>` du NFO jamais copié sur le candidat → identité
  TMDb gratuite perdue (build_candidates_from_nfo, core.py:787).
- **LOTD-INT-03** : `test_tmdb_key` en échec réseau renvoie au front le message d'exception avec
  `api_key=<clé en clair>` dans l'URL (logs scrubbés, front PAS).
- **LOTD-EXP-01** : CSV avec fins de ligne `\r\r\n` (write_text sans newline="") → lignes vides.
- **LOTD-EXP-03** : toast NFO « 0 créés » (front lit `created`, backend renvoie `written`).
- **BUG-LOTD-401-RST-BODY** (rest) : réponses d'erreur précoces (401/410/404/413) sans drainer le
  body → TCP RST → sous Windows le client peut perdre le JSON d'erreur (« erreur réseau » au lieu de
  « clé invalide ») — intermittent 1/3.

### LOW (4)
- **R8-079 confirmé** : pack TV `Show.101` → 3 films (looks_tv_like).
- **LOTD-41-01** : métriques cache incrémental auto-polluées (misses fantômes, hits=misses à 100 %
  de cache — finding d'audit connu jamais corrigé, confirmé runtime).
- **BUG-EXPLAIN-BASELINE-CAP** : explain_score ignore le cap Silver (next_tier=null alors que le
  tier affiché est Silver).
- Divers documentés dans les tests (voir gardes).

## Limites explicites
Sans ffprobe/mediainfo/ffmpeg : branches probe FULL/PARTIAL, perceptuel V2, comparaison qualité A/B
des doublons non exercées (dégradation propre VÉRIFIÉE telle quelle). TMDb réel non appelé (zéro
réseau externe). Plex/OMDb/SMTP hors périmètre 4.5. Crash mi-move non simulé.

## Vague Lot D-fix proposée (ordre)
1. **BUG-LOTD-ITERVIDEOS-KWARG** (crash spontané en nominal) + **LOTD-EXP-02** (exports UI morts) ;
2. Titres : LOTD-DUP-TITLE-YEAR + BUG-TITLE-CHANNEL-RESIDUE (⚠️ scene_parser = zone à mémoire
  R4-P2/P3 : différentiel corpus obligatoire, ne pas casser le seed torrents) ;
3. Jellyfin : R8-080 + LOTD-INT-01 (retry POST ciblé + catch JellyfinError) ;
4. LOTD-DUP-BUCKET-VIEWER (aligner bucket sur le viewer ou l'inverse — décision : suivre la spec
  `root/_review/`) + R8-085 (mkdir après gardes + mkdir_counted) ;
5. Exports : EXP-01 newline, EXP-03 written, GAP-NFO-TMDBID, INT-03 message safe ;
6. REST RST (drainer le body avant close), R8-079 (décision produit : convention NxNN opt-in ?),
  LOTD-41-01, EXPLAIN-BASELINE-CAP.
GATE de chaque fix = sa garde xfail devient PASS. Revue adversaire 2 rounds avant clôture.

# AUDIT HORIZONS — CineSort — campagne ultra-profonde READ-ONLY (2026-06-15)

> Découverte + rapport vérifié. **Aucune correction** ici (ce sera la vague R8 sur approbation).
> Règle de preuve : seul un différentiel comportemental mesuré sur état frais vaut preuve. CONFIRMÉ ⇒
> repro live rejouable existe. Réfutés tracés en annexe. Recoupement R6/R7/314 (rien re-signaler de corrigé).
> Plan : `~/.claude/plans/iridescent-weaving-sloth.md`.

## LEDGER DE REPRISE (horizon × phase × statut)

| Phase / Horizon | Statut | Trouvailles (C/R/DM/latent) | Notes |
|---|---|---|---|
| 0.5 Fuite git (P0) | **FAIT** | 1 RÉFUTÉ (secret) + 1 CONFIRMÉ (bloat) | hypothèse leak FAUSSE en live |
| 0.1 Atteignabilité | **PARTIEL** | F-DEAD-01 (qij/quality morts) | reste : balayage modules complet |
| 0.2 Ingestion 314 | À FAIRE | — | 10C/26H/41M/37 contestés |
| 0.3 Baseline | À FAIRE | — | docs/.../baseline/ |
| H4 scoring | **FAIT (vague B)** | 1 CONFIRMÉ | F-H4-01 bitrate audio ≤10000 |
| H5 parsing/TV | **FAIT (vague B)** | 1 C + 2 mineurs | F-H5-01 résidu DD ; F-H5-02/03 |
| H7 intégrations | **FAIT (vague B)** | 1 C + 1 mineur | F-H7-01 cache 200-vide ; F-H7-02 |
| H1 sécurité (vague A) | **FAIT** | 2 CONFIRMÉS | F-SEC-01 GET non gardé ; F-SEC-02 port-ignore |
| Perceptuel (vague A) | **FAIT** | 4 CONFIRMÉS | F-PERC-01/02/03 (ffmpeg) + F-PERC-04 cancel |
| H2/H3 concurrence/intégrité | **PARTIEL** | 1 CONFIRMÉ | F-DB-01 busy_timeout ; reste H3 apply/migrations |
| Piste C (UX/a11y/visuel) | **PARTIEL** | tiers OK + a11y base OK | reste : aria-live async per-vue, focus-trap, double-apply |
| H3 apply / Confiance / Promesse | **FAIT (vague C)** | 7 (1 C-live, 1 C-grep, 5 recettes) | F-CONF-01/02, F-PROM-01/02/03, F-H3-01/02 |
| **— VAGUE 2 —** | | | |
| A/D métamorphique round-trip | **FAIT** | F-META-01 + bounds OK + 314#4 résolu | nfo_runtime perdu au reload |
| B contrats (27 vues) | **FAIT (reprise wf)** | 1 LOW + suspects réfutés | F-H8-01 doublons.js confidence ; surface saine |
| A 314 large + C tests-coverage | **FAIT (reprise wf)** | 1 MEDIUM | F-TEST-01 test-menteur ; 314 résiduel reste |
| MAX_PATH (C) + titre (D) | **FAIT** | 2 réfutés (propres) | guard présent ; 0 mutilation |
| 314 journal per-row | **FAIT** | résolu (re-vérifié) | RecordOpWithJournal actif |
| **D métamorphique** (bornes, monotonie V/B, round-trip settings) | **FAIT** | 4 PROPRES + R5=F-META-01 | core scoring/settings sains sous comparaison loyale |
| E concurrence races + F migrations vieille DB | **NON ÉPUISÉ** | — | fixtures/harnais jetables ; session dédiée |
| C perf/Windows/MAX_PATH/build | À FAIRE | — | profilage + dry-run titre long |
| 0.4 Corpus | **FAIT** | — | probe_cache 1044 + plan dernier run (copie RO) |
| 0.6 Falsifiabilité | **AMORCÉ** | — | gate prouvé sur harness H6 (détecte plant, 0 FP) |
| Socle métamorphique | EN COURS | — | 1er harness (audio) falsifiable validé |
| H6 doublons/audio | **1 trouvaille** | 1 CONFIRMÉ | F-H6-01 codec mislabel (113 films) |
| H1..H5,H7..H13 + Promesse + Confiance | À FAIRE | — | — |

**Taux de faux-positifs du panel (leurres de calibration)** : **0/12 cumulé** (0/9 Vagues 1-2 + **0/3 Vague 3** :
« migrations ordre inverse », « _clamp_0_100 renvoie float », « rollback delete-avant-write » tous réfutés 0/3).
Panel jugé **fiable** sur l'ensemble de la campagne. (Auto-calibration in-vivo : R2 monotonie + [0] « croissance
infinie » ont failli passer faux-positifs — re-dérivés « toutes choses vraiment égales » / « rétention-runs nettoie »
→ corrigés.)

**VAGUE 3 (clôture, workflow `wf_284bcd93-407`)** — statut chantiers :
| Chantier | Statut | Trouvailles |
|---|---|---|
| C1 P0 perte-données (quarantine TTL, rollback QUARANTINE_*) | **CLOS** | bugs 314 corrigés (🔬 repro) — réfutés actifs |
| C1 314 résiduel (37 contestés + 14 non-reconfirmés) | **CLOS** | 0 nouveau réel+vivant (📖) |
| C3-E concurrence | **FAIT** | F-V3-E1 (os.replace), **F-V3-E2 (sqlite cron/probe, HIGH)** |
| C3-F migrations | **FAIT** | sain SAUF [18] paused_at HIGH, [19][20] self-heal/taxonomie |
| C2 contrats H8 (27 vues) | **FAIT** | 2 vues mortes (enrichment, library-workflow), 5 config fantôme, traitement.js |
| Apply statut | **FAIT** | [4] DONE-malgré-errors, [5][7] FAILED-figé |
| **Loop-until-dry K=2** | **NON satisfait** | ronde productive (38) → ≥1 ronde FIND due |
| a11y/i18n/visuel-thème/perf/build/non-loopback | **NON OUVERTS** | horizons restants (Vague 4) |

Légende statut trouvaille : **CONFIRMÉ** (repro live rejouable) · **RÉFUTÉ** · **DONNÉES-MANQUANTES** ·
**latent (code mort)**.

---

## TROUVAILLES (au fur et à mesure)

<!-- chaque entrée : ID · horizon · sévérité · confiance(votes) · fichier:ligne · symptôme · repro · cause · fix suggéré · statut -->

### F-0.5-01 — Fuite de secret dans `docs/internal/observe` tracké — **RÉFUTÉ**
- **Horizon** : 0.5 (sécurité git). **Sévérité hypothétique** : critical (P0). **Statut** : **RÉFUTÉ** (repro live).
- **Hypothèse (prompt maître)** : les 1062 `network.json` trackés capturent le trafic HTTP → fuient le header
  `Authorization: Bearer` / le token REST en clair.
- **Repro live (rejouable)** : `git grep -I -i -c "<motif>" -- 'docs/internal/observe/'` pour
  Bearer / authorization / rest_api_token / api_key / tmdb_api_key / jellyfin_api_key / plex_token /
  radarr_api_key / omdb_api_key / password / X-Plex-Token / X-MediaBrowser-Token / x-api-key →
  **toutes à 0**. Le token REST courant (len=32) recherché en `git grep -F <token>` → **0 fichier**. Un
  échantillon `network.json` (parametres_integrations) = **55 octets** (vide). Le seul `ntoken=`
  (`2026-06-08_ITER10_LISIBILITE/summary.json`) est un **placeholder rédigé** (`<R…D>`, len=10, pas un token).
- **Conclusion** : AUCUN secret (token REST, clés TMDb/Jellyfin/Plex/Radarr/OMDb, mot de passe, header
  d'auth) n'est exposé dans les fichiers trackés. Le harness `observe` n'a pas capté d'en-tête `Authorization`.
- **Leçon (asymétrie d'info)** : l'hypothèse « quasi-certaine » du prompt maître est **fausse en live** —
  exactement le rôle de la repro vs la convergence prématurée.

### F-0.5-02 — Bloat git : 771 Mo / 1608 fichiers `docs/internal/observe` trackés, non ignorés — **CONFIRMÉ**
- **Horizon** : 0.5 (hygiène repo). **Sévérité** : **medium** (santé repo + surface de fuite future, PAS
  une fuite de secret actuelle). **Confiance** : 3/3 (mesuré). **Statut** : **CONFIRMÉ**.
- **Fichier/zone** : `docs/internal/observe/` (1062 `.json` + 516 `.png` + 30 `.txt`).
- **Repro live (rejouable)** : `du -sh docs/internal/observe` → **771 Mo** ; `git ls-files
  docs/internal/observe | wc -l` → **1608** ; `git check-ignore docs/internal/observe` → **non ignoré**.
- **Symptôme** : clones/CI lourds (771 Mo de captures/screenshots versionnés) ; surface de fuite **future**
  (si `observe` capte un jour un en-tête `Authorization`, il sera committé).
- **Correctif suggéré (R8, NON appliqué)** : ajouter `docs/internal/observe/` au `.gitignore` ; purge
  historique via `git filter-repo`/BFG pour récupérer ~771 Mo (action manuelle, hors campagne).

---

### F-H6-01 — `_best_audio_track` (codec-aveugle) mislabel le codec audio + sous-score partiel — **CONFIRMÉ** (calibré)
- **Horizon** : H6 (doublons/scoring audio). **Sévérité** : **medium**. **Confiance** : 3/3 (mesuré sur DB réelle
  + harness falsifiable). **Statut** : **CONFIRMÉ** (étiquette) + impact score **partiellement compensé**.
- **Fichiers** : `cinesort/domain/quality_score.py:637` `_best_audio_track` = `max(channels, bitrate)` (codec-aveugle)
  vs `cinesort/domain/duplicate_compare.py:425` `_best_audio` = `max(codec_rank, channels)`.
- **Symptôme** : sur un film avec piste lossless (TrueHD/DTS-HD MA) **+** piste lossy à canaux ≥ (eac3/dts 7.1
  de compat, fréquent sur remux 4K), `_best_audio_track` choisit la **lossy** (canaux égaux → départage par
  bitrate, codec-aveugle ; aggravé si le bitrate du flux lossless n'est pas reporté = 0). Conséquence :
  `detected.audio_best_codec` affiché = `dts`/`eac3` pour un film TrueHD/Atmos → **étiquette codec fausse**
  (visible Qualité / Détail film).
- **Repro live (rejouable)** : `docs/internal/audit_horizons/proofs/h6_best_audio_divergence.py` →
  GATE falsifiabilité OK (détecte un plant connu, 0 faux positif sur piste unique) ; sur le corpus réel
  (copie RO de `probe_cache`) : **1044 probes, 865 ≥2 pistes, 113 divergences** (quality choisit un codec de
  rang inférieur). Confirmé sur le pipeline réel via `quality_reports.metrics_json` : Expend4bles/1917/Alien
  Romulus → `audio_best_codec='eac3'` ; Evil Dead II/Expend4bles → `='dts'` (films TrueHD/DTS-HD MA).
- **Nuance adversariale (ce qui DÉGRADE la sévérité)** : un *fallback nom de release* (`quality_score.py`,
  « Atmos/DTS:X détecté dans le nom ») **récupère le bonus de score** quand le nom porte le tag audio (cas
  dominant des releases QTZ : « TrueHD 7.1 Atmos »). Donc le **score** n'est sous-évalué que pour les films
  **sans tag audio dans le nom** (ex. `Predator.Badlands…x265-SESKAPiLE` → `eac3`, pas de récupération). Le
  préjudice **étiquette codec** reste large (113 films) ; le préjudice **score** est étroit.
- **Cause racine** : tri `(channels, bitrate)` non codec-aware dans `_best_audio_track`. **Correctif suggéré
  (R8, NON appliqué)** : aligner sur `(codec_rank, channels, bitrate)` comme `duplicate_compare._best_audio`,
  ou au minimum départager à canaux égaux par rang codec avant bitrate.

### F-H4-01 — Bitrate audio ≤ 10000 bps lu comme kbps → bonus au lieu de malus — **CONFIRMÉ**
- **Horizon** : H4 (scoring). **Sévérité** : **medium** (bande étroite mais inversion de signe). **Confiance** :
  3/3 (panel) + repro live. **Statut** : **CONFIRMÉ**.
- **Fichier** : `cinesort/domain/quality_score.py:563` (`_normalize_audio_bitrate_kbps` divise par 1000 **seulement
  si n > 10000.0 strict**) + 971-976 (usage). Le bitrate audio est stocké en **bps** (`infra/probe/_normalize_ffprobe.py`
  → `conversions.to_optional_bitrate` renvoie la valeur brute).
- **Repro live (rejouable)** : `_normalize_audio_bitrate_kbps(8000)` → **8000** ; `(10000)` → **10000** ;
  `(10001)` → **10** ; `(48000)` → **48**. Donc un flux ~8 kbps (AAC/Opus mono ultra-dégradé) est lu comme
  8000 kbps → `per_channel ≥ 650` → **bonus +4 « Débit audio élevé »** au lieu du **malus -3 « Débit faible »**.
- **Cause** : seuil `> 10000.0` strict + bitrate en bps. Analogue audio du bug vidéo déjà documenté en docstring
  L539-555. **Correctif suggéré (R8)** : diviser quand l'unité est clairement des bps (heuristique cohérente
  vidéo/audio) ou seuil par-canal.

### F-H5-01 — Résidu Dolby Digital (`DD5 1`/`DDP5 1`/`DD7 1`) pollue la query TMDb — **CONFIRMÉ**
- **Horizon** : H5 (parsing). **Sévérité** : **medium** (dégrade le match TMDb → contribue au GAP
  d'identification). **Confiance** : 3/3 + repro live. **Statut** : **CONFIRMÉ**.
- **Fichier** : `cinesort/domain/scene_parser.py:131` (`_NOISE_RE` a `dd5\.?1` chiffres collés) + 200-203
  (`_AUDIO_RESIDUE_RE [257][\s.][01]`). Cause exacte : `name.replace('.',' ')` (L378) transforme `DD5.1`→`DD5 1`
  **avant** `_NOISE_RE` ; `dd5\.?1` ne matche pas l'espace, et `[257][\s.][01]` échoue car le `5` est collé à
  `DD` (pas de `\b`).
- **Repro live (rejouable)** : `clean_title_guess('Joker.2019.DD5.1.1080p.BluRay.x264-GROUP.mkv')` → **'Joker 2019
  DD5 1'** ; `'Gladiator.2000.2160p.DDP5.1.Atmos-RARBG'` → 'Gladiator 2000 DDP5 1' ; `'Tenet.2020.DD7.1.1080p'`
  → 'Tenet 2020 DD7 1'. Contrôle négatif : `'Inception.2010.1080p.BluRay.x264'` → **'Inception 2010'** (propre).
- **Correctif suggéré (R8)** : nettoyer les résidus `DD/DDP[0-9] [01]` après le `.`→espace, ou appliquer
  `_AUDIO_RESIDUE_RE` avec un pattern tolérant le chiffre collé.

### F-H7-01 — Réponse TMDb 200 + `results=[]` empoisonne le cache search 7 jours — **CONFIRMÉ**
- **Horizon** : H7 (intégrations). **Sévérité** : **high** (film non identifié ~7j à travers les re-scans après
  UN seul hoquet TMDb). **Confiance** : 3/3 + repro live. **Statut** : **CONFIRMÉ**.
- **Fichier** : `cinesort/infra/tmdb_client.py:515` (`_cache_set(key, [])` quand vide) + L446 (`if cached is not
  None` → vrai pour `[]` → renvoie `[]` sans refetch). Le fallback stale (L478) ne couvre QUE le bloc `except`
  (erreur réseau), pas le 200-vide. TTL search = 7j (L45).
- **Repro live (rejouable, stub)** : `TmdbClient(api_key="DUMMY", cache_path=tmp)` ; `_http_get` stubé → 200 +
  `{"results":[]}` ; `search_movie("Inception",2010)` → **0** ; puis `_http_get` → vrai résultat ;
  re-`search_movie("Inception",2010)` → **toujours 0** (cache empoisonné). Discriminé du cas erreur-réseau
  (qui passe par `except`, non empoisonnant).
- **Correctif suggéré (R8)** : ne pas mettre en cache (ou TTL court) une liste vide ; ou refetch si cache vide.

### F-DEAD-01 — Features « Simulateur de preset » + « Éditeur de règles custom » inatteignables — **CONFIRMÉ**
- **Horizon** : 0.1 / H8 (code mort fonctionnel). **Sévérité** : **medium** (deux features complètes mais
  inaccessibles + ~1100 l. de code mort). **Confiance** : 3/3 + repro runtime. **Statut** : **CONFIRMÉ**.
- **Fichiers** : `quality-simulator.js:155` (`openQualitySimulator`) et `custom-rules-editor.js:457`
  (`openCustomRulesEditor`) ; leurs **seuls hosts** = `qij.js` (boutons L312/316) et `quality.js` (L271/273),
  tous deux **morts** : `app.js` n'importe jamais `initQij`/`initQuality` ; routes `/qij`→`_legacyRedirect(
  "/accueil")` (app.js:291), `/quality`→`_legacyRedirect("/qualite")` (L293). La vue **vivante** `qualite.js`
  a **0** bouton simulateur/custom-rules (grep = 0).
- **Repro live (rejouable, runtime)** : serveur `--api` + Playwright `goto('#/qij')` → URL devient
  **`#/accueil`** (redirect, 0 rendu). `grep -c btnQualitySimulator|btnCustomRulesEditor web/.../qualite.js` = 0.
  Aucun import vivant de qij.js/quality.js (grep hors bisect/tests = 0).
- **Correctif suggéré (R8)** : soit recâbler les deux boutons dans la vue vivante `qualite.js`, soit
  supprimer le code mort (qij.js/quality.js ~1100 l. + simulator/editor s'ils restent non désirés).

### F-MINEURS (panel-vérifiés, repro recette fournie — à promouvoir/réfuter en vague ultérieure)
- **F-H5-02** `path_utils.py:107` `windows_safe` retire `/ : * ?` **sans séparateur** (`Face/Off`→`FaceOff`,
  `8 1/2`→`8 12`). **MINEUR** : cosmétique, dossier valide, et **délibéré + verrouillé par test**
  (`test_path_utils_v77.py:51-55`). L'exemple `Mission:Impossible` de la claim est inexact (`': '` rend bien).
- **F-H5-03** `core.py:168-170/478-494` : pack TV à convention non-standard (`Show.101.mkv`=S01E01, ou `E01`
  seul, ou ` - 01`) **non détecté** comme série → chaque épisode planifié comme film distinct. **MINEUR**
  (limité à cette convention ; `SxxExx/NxNN/episode/ep` restent détectés).
- **F-H7-02** `jellyfin_sync.py:217-248` : après apply d'un film vu, un échec POST transitoire (503) sur
  `PlayedItems` laisse le flag « vu » non restauré et **non re-tenté** dans ce run (POST exclu de retry, drop
  L248 même si retries restants). **MINEUR** (WARN émis, récupérable par re-sync, pas de perte fichier).

### F-PERC-01/02/03 — L'analyse perceptuelle V2 mesure du VIDE (3 bugs) — **CONFIRMÉ** (vrai ffmpeg)
- **Horizon** : H1/perceptuel. **Sévérité** : **high** (le score perceptuel V2 repose en partie sur des
  mesures jamais effectuées / valeurs par défaut « parfaites »). **Confiance** : 3/3 + repro live binaire réel.
  **Statut** : **CONFIRMÉ**. Recoupe la note 314 « perceptuel mort -v quiet ».
- **F-PERC-01 — loudness EBU R128 jamais mesurée** : `audio_perceptual.py:141-142` force `-v quiet` sur la cmd
  `loudnorm=print_format=json`, or le JSON loudnorm sort sur stderr au niveau INFO → stderr vide → `analyze_loudnorm`
  retourne None. **Repro (tools/ffmpeg.exe)** : `ffmpeg -i a.wav -map 0:a:0 -af loudnorm=print_format=json -f null
  -v quiet -` → stderr **0 octet, 0 input_i** ; `-v info` → **2683 octets, 1 input_i**. Fix : `quiet`→`info`.
- **F-PERC-02 — crest factor + dynamic range jamais mesurés** : `audio_perceptual.py:234` restreint la lecture au
  bloc « Overall » (`_extract_overall_block`), mais astats n'écrit Crest/Dynamic range **que par canal**, pas dans
  Overall. **Repro** : `ffmpeg -i a.wav -af astats=metadata=1:reset=0 -f null -v info -` → « Crest factor » et
  « Dynamic range » apparaissent **2× (par canal) mais 0× après le marqueur Overall** → `crest=dynrange=None` →
  2 des 6 poids audio figés à 50. Fix : lire crest/dynrange par-canal puis agréger.
- **F-PERC-03 — blockiness + blur jamais mesurés → score gonflé** : `video_analysis.py:90` construit
  `select=…,signalstats=stat=tout+vrep,blockdetect,blurdetect` **sans** `metadata=mode=print` → signalstats écrit
  dans les métadonnées de frame, pas sur stderr → 0 ligne parsée → `blockiness_mean=blur_mean=0.0` →
  `_score_blockiness(0.0)=95` et `_score_blur(0.0)=95` (quasi-parfait fabriqué) gonflent le score visuel.
  **Repro** : cmd exacte sur testsrc → **0 ligne YAVG=** ; avec `signalstats…,metadata=mode=print,…` → **4 lignes**.
  Fix : insérer `metadata=mode=print` après signalstats.

### F-PERC-04 — Le batch perceptuel auto post-scan est NON annulable — **CONFIRMÉ** (grep décisif)
- **Horizon** : H2 (concurrence). **Sévérité** : **medium**. **Confiance** : 3/3 (panel + grep). **Statut** :
  **CONFIRMÉ** (preuve statique décisive ; repro runtime = recette fournie).
- **Fichier** : `run_flow_support.py:564` `analyze_perceptual_batch(...)` ne transmet pas `should_cancel` ;
  le batch dérive son annulation de `api._perceptual_cancel_event` (`perceptual_support.py:1642`) qui **n'est
  JAMAIS assigné un Event en prod** (seulement dans 2 tests, à None) → `cancel_event=None` → tous les checks
  d'annulation `parallelism.py` (gardés par `cancel_event is not None`) sont **inertes**. `request_cancel` n'arrête
  donc pas l'analyse ; le run reste `running` jusqu'au bout. **Repro recette** : `perceptual_auto_on_scan=True`,
  scanner ≥2 rows, annuler pendant l'analyse → les films restants continuent. Fix : propager le `should_cancel`
  du run jusqu'à `run_batch_parallel`.

### F-SEC-01 — Les routes GET ne passent AUCUNE garde (auth/CSRF/rate-limit) — **CONFIRMÉ** (live)
- **Horizon** : H1 (sécurité). **Sévérité** : **medium** (abus de ressource/quota + CSRF cache-eviction, pas
  d'exfiltration). **Confiance** : 3/3 + repro live. **Statut** : **CONFIRMÉ**.
- **Fichier** : `rest_server.py:886-999` `_handle_get` n'appelle ni `_check_auth`, ni `_is_rate_limited`, ni
  `_is_forbidden_cross_site` (les 3 ne sont invoquées que dans `_handle_post`). Conséquences : (a) en bind 0.0.0.0
  (mode LAN opt-in) un client non authentifié énumère l'existence de films (200 vs 404) + brûle le quota TMDb ;
  (b) `/api/poster?…&force=1` (param ajouté en R7-8) **supprime le cache disque + re-DL TMDb**, exploitable en
  CSRF via `<img src=…&force=1>` même en bind 127.0.0.1 (les GET d'`<img>` n'ont pas d'Origin/preflight).
- **Repro live (rejouable)** : Python, Origin forgé cross-site → `POST /api/run/get_dashboard` Origin=evil → **403**
  (CSRF OK) **mais** `GET /api/poster?id=550&size=w500` Origin=evil → **200** (servi, GET non gardé). Anti-SSRF
  solide par ailleurs (whitelist size, URL CDN serveur-side, no-redirect, 5 Mo). Fix : appeler
  `_check_auth/_is_rate_limited/_is_forbidden_cross_site` en tête des routes GET sensibles.

### F-SEC-02 — `_allowed_origin` ignore le PORT → CSRF entre ports localhost frères — **CONFIRMÉ** (live)
- **Horizon** : H1 (sécurité, defense-in-depth). **Sévérité** : **low** (prérequis : 2ᵉ app locale hostile sur un
  autre port). **Confiance** : 3/3 + repro live. **Statut** : **CONFIRMÉ**.
- **Fichier** : `rest_server.py:417-421` `_allowed_origin` compare `host=urlsplit(o).hostname` (port+scheme
  **ignorés**) pour 127.0.0.1/localhost/::1, alors que la branche same-origin (L425) compare le Host complet. Avec
  le bypass loopback de l'auth, la garde CSRF est l'unique défense → une page sur `http://localhost:9999` POST sur
  l'API sans token.
- **Repro live** : `POST /api/run/get_dashboard` Origin=`http://localhost:9999` → **200** (non bloqué) ;
  Origin=`http://evil.example:80` → **403**. Fix : exiger port+scheme identiques au serveur dans la branche loopback.

### F-DB-01 — busy_timeout NAS écrasé à 8000 ms (profil 30000/60000 ignoré) — **CONFIRMÉ** (panel, recette)
- **Horizon** : H2/H3 (concurrence/intégrité). **Sévérité** : **high** (SQLITE_BUSY prématuré sur NAS, y compris
  pendant les ALTER/CREATE INDEX de migration). **Confiance** : 3/3 (panel + chemin tracé). **Statut** :
  **CONFIRMÉ** (preuve statique ; repro runtime = recette).
- **Fichier** : `infra/db/connection.py:110-112` — le store de prod passe `busy_timeout_ms=8000`
  (`runtime_support.py:305`) ; comme `8000 != _DEFAULT_BUSY_TIMEOUT_MS(5000)`, le bloc back-compat **réécrase** le
  `busy_timeout` du profil NAS (30000 nas_smb / 60000 nas_smb_slow) par 8000 (dernière instruction). **Repro
  recette** : DB sur partage SMB (ou `storage_profile_override='nas_smb'`), booter, `PRAGMA busy_timeout` sur une
  connexion store → 8000. Fix : ne pas appliquer l'override back-compat quand un profil NAS est résolu.

---
# VAGUE 2 (découverte restante) — append

### F-META-01 — Round-trip `plan.jsonl` perd `nfo_runtime` (2 désérialiseurs divergents) — **CONFIRMÉ** (métamorphique)
- **Horizon** : D (métamorphique round-trip) / chantier A. **Sévérité** : **medium** (dégrade après redémarrage la
  détection « durée → autre film » + la désambiguïsation par durée, pas de perte fichier). **Confiance** : 3/3 +
  harness falsifiable. **Statut** : **CONFIRMÉ**.
- **Fichiers** : `run_data_support.py:132` `row_from_json` (chemin de reload apply après redémarrage — celui du fix
  TV 314 `_parse_tv_fields`) **ne parse PAS** `nfo_runtime`, alors que l'autre désérialiseur `plan_support_core.py:110`
  le parse. Asymétrie entre deux reload paths.
- **Repro live (rejouable)** : `docs/internal/audit_horizons/proofs/meta_roundtrip_planrow.py` — construit une PlanRow
  avec les 31 champs à valeur distinctive, `plan_row_to_jsonable` (asdict, écrit tout) → `row_from_json` → diff :
  **seul `nfo_runtime` est perdu** (écrit 4242 → rechargé `None`). Les 30 autres champs (TV/sous-titres/edition/
  source_root) survivent.
- **Impact** : `nfo_runtime` est consommé par `quality_report_support.py:29` (détection mismatch durée = « autre
  film »), `title_ambiguity.py:134-138` (désambiguïsation ±10 min), `runtime_probe_check.py:135`. Après un
  redémarrage de l'app, ces gardes se dégradent (nfo_runtime=None). Même FAMILLE que le bug TV 314 (corrigé), instance
  non couverte. **Fix suggéré (R8)** : ajouter `nfo_runtime` aux champs parsés par `row_from_json` (miroir de
  `plan_support_core.py:110`).

### F-META-VERIF — bornes & cohérence tier du scoring : SAINES (concern réfuté)
- **Horizon** : D (métamorphique). **Statut** : **vérifié propre** (transparence). Sur les **965 scores réels** du
  dernier run : **0** score hors [0,100], **0** NaN, **0** tier incohérent avec les seuils. L'invariant
  bornes/monotonie de tier tient sur le corpus réel.

### 314 #4 (perte champs TV au reload) — **DÉJÀ CORRIGÉ** (re-vérifié)
- `run_data_support.py:113` `_parse_tv_fields` restaure tv_season/episode/series_name/episode_title/tmdb_series_id
  (docstring « AUDIT 2026-06-10 REAL 2/2 »). Le round-trip préserve les 5 champs TV (vérifié par F-META-01). Ce P0
  du 314 est donc **résolu** ; F-META-01 est l'instance *sœur* non couverte (`nfo_runtime`).

### Vague 2 — vérifications propres (transparence) + re-vérif 314
- **MAX_PATH (chantier C) : garde PRÉSENTE (concern réfuté)**. `check_path_length_killswitch` (naming.py:425, VQ-3)
  appelé dans apply (apply_core.py:1910/2099/2229) → un chemin cible > 259 ch est **skip** (`skip_path_too_long`),
  pas d'échec silencieux. Repro : `check_path_length_killswitch(<270 ch>)` → erreur PATH_TOO_LONG ; `<35 ch>` → None.
- **Mutilation titre à nombre en tête (chantier D) : 0 (réfuté)**. `clean_title_guess` préserve « 21 Jump Street »,
  « 50 First Dates », « 300 », « 1917 », « 8 Mile », « 12 Angry Men », « 300 Rise of an Empire » (le fix R1a tient).
  Le seul résidu parsing réel reste F-H5-01 (`DD5 1`).
- **314 : journal write-ahead par-row (apply_core.py:1368) — DÉJÀ CORRIGÉ**. En apply réel, `record_op` est
  `RecordOpWithJournal` (apply_support.py:1432-1438) ; commentaire « AUDIT 2026-06-10 (HIGH, REAL 2/2) : conserver
  journal_store/batch_id … sinon shutil.move sans journal ». Le P0 est résolu.

### F-TEST-01 — Test-menteur : assertion tautologique `assertTrue(x or True)` — **CONFIRMÉ**
- **Horizon** : C (tests-menteurs). **Sévérité** : **medium** (faux sentiment de couverture ; masquerait une
  régression R8). **Confiance** : 3/3 + repro. **Statut** : **CONFIRMÉ**.
- **Fichier** : `tests/test_auto_install.py:37` `self.assertTrue(d.exists() or True)  # peut ne pas exister en CI`.
  `X or True` vaut **toujours** True (court-circuit Python ; `d.exists()` jamais décisif) → `test_creates_dir` passe
  quoi qu'il arrive. **Repro** : commenter `tools_dir.mkdir(exist_ok=True)` (auto_install.py:169) → le test reste
  **vert** alors que le dossier n'est plus créé. **Fix (R8)** : `assertTrue(d.exists())` + skip conditionnel CI, ou
  tolérer une `OSError` explicite.

### F-H8-01 — Inspecteur Doublons : ligne « Confiance X% » jamais rendue (champ inexistant) — **CONFIRMÉ**
- **Horizon** : H8 (contrats front↔back, vue VIVANTE). **Sévérité** : **low** (cosmétique, info manquante).
  **Confiance** : 3/3 + repro. **Statut** : **CONFIRMÉ**.
- **Fichier** : `web/dashboard/views/doublons.js:617` lit `c.confidence`, mais la dataclass `Candidate`
  (`core.py:379-386`) n'a **aucun** champ `confidence` (0 occurrence) — seulement `score: float (0..1)`. Donc
  `c.confidence` est toujours `undefined` → la ligne « Confiance » de l'inspecteur droit (panneau Candidats TMDb) ne
  s'affiche **jamais** (et serait fausse : `*100` sur un déjà-pourcent). Contraste : `film-detail.js:326` gère
  correctement le même objet via `candidate.score * 100`. **Fix (R8)** : aligner doublons.js sur ce fallback.

### Vague 2 — suspects RÉFUTÉS par le panel (transparence, largeur saine)
- Migration **032 nommée en tirets** (ignorée par `_MIGRATION_FILE_RE`) → **latent (code mort)** : `SqliteVecAdapter`
  est un scaffold (`NotImplementedError`), flag `similar_films` OFF. Pas un bug actif.
- `_normalize_video_bitrate_kbps` seuil 500000 → analogue F-H4-01 mais zone 10-500 kbps **irréaliste pour de la
  vidéo** → réfuté. · `disk_space_check`, `radarr_sync` (metrics), `watcher` (secrets masqués gérés),
  `doublons._autoDecideAll` (mapping a/b garanti par `_build_comparison_payload`) → **tous PROPRES**.

## CHANTIER D — Socle métamorphique (oracles de relation, exécuté en direct)
> Harnais falsifiables purs (lecture seule ; écriture sur `state_dir` jetable uniquement). Preuves :
> `docs/internal/audit_horizons/proofs/meta_score_bounds_monotonic.py` et `meta_settings_roundtrip.py`.

| Relation | Verdict | Détail |
|---|---|---|
| **R1 Bornes** score∈[0,100], int, sans NaN, tier valide | **PROPRE** | 36 probes (3 rés × 4 bitrate × 3 ch) : 0 violation. |
| **R2 Monotonie résolution** (bitrate abondant/proportionnel) | **PROPRE** | 720→1080→2160 = 32→49→57. La « violation » à bitrate FIXE (1080<720 @4000k) = **pénalité d'inadéquation bitrate↔résolution intentionnelle** (`penalty_4k_light`, malus low-bitrate) → R2 mal spécifiée, **réfutée comme bug**. |
| **R3 Monotonie bitrate** (résolution fixe) | **PROPRE** | séquences 800→80000 kbps non décroissantes. |
| **R4 Round-trip settings** save→load identité | **PROPRE** | 99 clés mutées, **2 diffs = normalisations légitimes** : `composite_score_version 3→2` (clamp version valide) ; `remember_key True→False` (dérivé du secret TMDb absent). Clé non-canonique (canary) droppée = normalisation attendue. |
| **R5 Round-trip PlanRow** (rappel) | **F-META-01 CONFIRMÉ** | `row_from_json` (run_data_support.py:132) ne reparse pas `nfo_runtime` → perdu (4242→None). Seule violation métamorphique réelle. |

**Lecture** : le cœur métier (scoring, sérialisation settings) **respecte ses invariants** sous comparaison loyale.
Seule fuite métamorphique réelle = F-META-01 (déjà CONFIRMÉE). Calibration : R2 a failli être un faux-positif — la
re-dérivation « toutes choses VRAIMENT égales » (bitrate proportionnel) l'a réfutée.

## ═══ VAGUE 3 — CLÔTURE DE DÉCOUVERTE (3 chantiers restants) ═══

### CHANTIER 1 — 314 RÉSIDUEL, P0 PERTE-DE-DONNÉES (repro live sur fixtures jetables)
> Les 2 P0 les plus dangereux de toute la campagne ont été **trouvés par le 314 PUIS CORRIGÉS** (commits
> citant « AUDIT 2026-06-10/06-11 »). La repro fraîche tranche : **fixes COMPLETS, réfutés comme bugs actifs.**
> Preuves : `proofs/c1_quarantine_ttl_fix.py`, `proofs/c1_rollback_quarantine_revert.py`.

| ID | Hypothèse 314 | Repro live (état frais) | Statut |
|---|---|---|---|
| **V3-Q1** | TTL quarantaine basé sur `st_mtime` → film vieux purgé dès le 1er cycle (perte) | `quarantine_ttl.py` : manifest `.cinesort_ttl_manifest.json` (first-seen=now). **T1** fichier mtime=100j, 1re obs → `deleted=0` (NON purgé). **T2** manifest first_seen=100j → `deleted=1` (falsifiable). **T3** ttl=0 → no-op. | **RÉFUTÉ comme bug actif (fix complet)** |
| **V3-Q2** | Purge morte (TypeError, kwargs manquants) → danger latent | `cinesort_api.py:2726` appelle `purge_review_bucket(cfg, ttl_days=int(...), dry_run=bool(...))` — **signature exacte**, aucun kwarg manquant. Purge **LIVE**. | **RÉFUTÉ** (purge câblée) |
| **V3-R1** | Rollback ne revert PAS `QUARANTINE_*` mais renvoie `ok=True` (FS non restauré) | `apply_rollback.py:118` les inclut au switch. **T1** op QUARANTINE_FILE → `status=DONE`, fichier **revenu dst→src** (src existe, dst supprimé). **T2** DELETE → SKIPPED (switch discrimine). **T3** dst absent → SKIPPED dst_missing. | **RÉFUTÉ comme bug actif (revert réel)** |
| **V3-R2** | Batch demi-appliqué marqué `COMPLETED` (kill mid-apply indistinguable) | `apply_batches_reconciliation.py:120-150` (AUDIT 2026-06-11 R3e) exige **preuve** `expected_ops` ET `total>=expected_ops`, sinon défaut `ROLLED_BACK`. `rollback_forward` met `ok=False`/`ROLLBACK_PARTIAL` sur échec partiel (L452-453). | **RÉFUTÉ comme bug actif (preuve exigée)** |

**Lecture chantier 1** : la zone perte-de-données la plus critique est **saine en runtime** — les P0 du 314 ont été
corrigés ET les correctifs tiennent sur état frais (vérifié, falsifiable). Aucun P0 actif résiduel sur ces 4 axes.
Reste à passer : 37 contestés + 14 non-reconfirmés du 314 (en cours via workflow Vague 3 `wf_284bcd93-407`).

### CHANTIER 3-F — MIGRATIONS sur vraie DB peuplée (repro live, copies jetables)
> Preuve : `proofs/c3_migrations_old_db.py`. Source = DB peuplée réelle (`cinesort.sqlite`, 1027 films) + backup
> **vieux schéma réel** `bak_avant_v162` (user_version=27). Toutes les opérations sur **COPIES jetables**.

| Test | Résultat | Verdict |
|---|---|---|
| **T4** ordre d'application | `list_migrations()` trie ASCENDANT 1→31 | leurre « ordre inverse » **RÉFUTÉ** |
| **T5** migration 032 (tirets) | `_MIGRATION_FILE_RE = ^(\d+)_.*\.sql$` ne matche pas `032-...` → absente | confirme **latent** (déjà Vague 2) |
| **T1/T2** DB courante | apply→v31, 23 tables, 0 perte ; 2e run no-op | idempotent OK |
| **T3** self-healing (user_version=0 sur DB peuplée) | rejoue tout, 0 perte | idempotent (IF NOT EXISTS) OK |
| **T6** VRAI vieux schéma v1.6.2 (v27, données réelles) | **upgrade v27→v31, 19→23 tables, ZÉRO perte, idempotent** | **upgrade vieux schéma SOLIDE** |

**Lecture chantier 3-F** : le système de migration est **sain** — ordre garanti, idempotent, upgrade lossless depuis
un vrai ancien schéma peuplé, backup-avant-migration (`db/backups/*.pre_migration.bak` observés). Aucun bug actif ;
seul 032-tiret reste latent. **F-DB-01** (busy_timeout NAS, Vague 1) demeure le seul finding migration/DB confirmé.

### CHANTIER 3-E — CONCURRENCE (repro live, state_dir jetable)
> Preuve : `proofs/c3_concurrent_settings_save.py`.

#### F-V3-E1 — `atomic_write_json` : `os.replace` sans retry → écriture perdue sous lecture concurrente (Windows) — **CONFIRMÉ**
- **Horizon** : E concurrence (Windows-spécifique). **Sévérité** : **low** (PAS de corruption — l'atomicité tient ;
  écriture *perdue/échouée*, recouvrable). **Confiance** : repro live falsifiable. **Statut** : **CONFIRMÉ**.
- **Fichier** : `cinesort/infra/state.py:82` `atomic_write_json` fait `os.replace(tmp, p)` **sans retry**. Sur Windows,
  `os.replace` lève `PermissionError`/WinError 5 si un autre handle (lecteur concurrent) tient `p` ouvert → la save
  échoue, le `.tmp` est nettoyé en `finally`, l'ancienne valeur reste. **Repro** : 8 writers + 8 readers en boucle sur
  un `settings.json` jetable → I1/I2/I3 (atomicité) **OK, jamais de JSON corrompu**, mais **les writes lèvent
  PermissionError** (write perdu). **8 appelants** dont chemins concurrents : `dashboard_cache_support.py:79`
  (cache lu par le dashboard + écrit par un run), `settings_support.py:712` (GET+POST settings), `*_support.py`
  validation_json. Le `_settings_write_lock` (Vague-1) sérialise writer↔writer mais **pas** reader↔writer (angle NEUF).
- **Atteignabilité honnête** : probabilité **faible** en usage mono-utilisateur normal (saves rares) ; mon test force
  ~100 % de collision. Mais **non nulle** (2 onglets dashboard / webview+navigateur / job de fond lisant pendant un
  save), et Windows-spécifique. **Correctif (R8)** : boucle de retry courte (3–5×, backoff ms) autour de `os.replace`
  sur `PermissionError` ; ne change pas l'atomicité.

#### F-V3-E2 — Crons retention/quarantaine + lot de probe MEURENT sur `sqlite3.OperationalError` (tuple d'except incomplet) — **CONFIRMÉ**
- **Horizon** : E concurrence / robustesse DB. **Sévérité** : **high** (perte de service : purge/retention s'arrêtent
  **définitivement** → croissance non bornée jusqu'au restart ; lot de probe avorté → films scorés au nom seul).
  **Confiance** : repro live falsifiable + panel 3/3. **Statut** : **CONFIRMÉ**. (Workflow V3 #15 + #16, recoupés.)
- **Cause racine partagée** : trois sites attrapent `(AttributeError, OSError, RuntimeError, TypeError, ValueError)`
  mais **PAS** `sqlite3.OperationalError`/`DatabaseError` (preuve T3 : `OperationalError` n'hérite ni d'`OSError` ni de
  `RuntimeError`, base = `DatabaseError`). Un verrou DB transitoire (« database is locked », rendu plus probable par
  **F-DB-01** busy_timeout NAS) **échappe** :
  - `retention_cleanup.py:48` `_run_cleanup_once` → l'exception sort de `_worker` (L107-116) → **thread cron mort**.
  - `quarantine_ttl.py:553` `_run_purge_once` → idem (`_worker` L605-612) → **purge TTL morte**.
  - `infra/probe/service.py:723` boucle `as_completed` : `except (OSError, RuntimeError, TypeError, ValueError)`
    par-future omet sqlite3.Error → une écriture de cache probe qui échoue sur verrou fait sortir de la boucle
    `with ThreadPoolExecutor` → **tout le lot de probe restant est abandonné**.
- **Repro** : `proofs/c3e_cron_db_error_escape.py`. **T1** `cleanup_old_runs` lève `sqlite3.OperationalError` →
  `_run_cleanup_once` **RE-LÈVE** (« cron meurt »). **T2** (contrôle) OSError → **swallow** (« cron survit ») →
  harnais falsifiable. **T3** taxonomie confirmée. **Correctif (R8)** : ajouter `sqlite3.Error` (ou `Exception` large
  + log) aux 3 tuples ; pour les crons, boucler le `_run_*_once` dans un `try/except Exception` qui ne tue jamais le
  thread.

### CHANTIER 2 + 3 (workflow `wf_284bcd93-407`) — INVENTAIRE DES 38 SURVIVANTS
> Panel à asymétrie : **0/3 leurres** (fiable). 44 findings bruts → 38 survivants (≥2/3 votes). Statut de vérif :
> 🔬 repro live par moi (harnais falsifiable) · 📖 confirmé par lecture/grep décisif · 🗳️ panel 3/3 (repro live R8-prep) ·
> ↩️ réfuté/intentionnel après ma re-dérivation. **NON re-signalé** : tout ce qui recoupe Vagues 1-2 / R6 / R7.

**A. 314 RÉSIDUEL — CLOS.** Les 2 P0 (quarantaine TTL, rollback QUARANTINE_*) = **bugs corrigés** (🔬 ci-dessus).
Les **37 contestés** (2 moitiés) + **14 non-reconfirmés** → **AUCUN finding réel+vivant+neuf** (📖 [9] : tous morts
au runtime ou prémisse fausse ; réfutations du 314 confirmées une à une).

**B. ROBUSTESSE DB / taxonomie d'exceptions (cause racine récurrente : `sqlite3.Error` hors des tuples attrapés)**
| ID | votes | sév | st | Trouvaille |
|---|---|---|---|---|
| E2 [15+16] | 3/3 | **high** | 🔬 | crons retention/quarantaine + lot probe meurent sur `OperationalError` (cf F-V3-E2). |
| [20] | 3/3 | medium | 📖 | `migration_manager.py:254` `_is_idempotent_error` ne couvre que `OperationalError` → un `IntegrityError` (rebuild 021/023/025) bloque tout le boot. Même famille. |
| [18] | 3/3 | **high** | 📖 | `sqlite_store.py:334` self-heal rejoue 025 (`DROP TABLE runs`+`SELECT …,NULL`) → **`paused_at` écrasé à NULL** → resume_run incohérent. *(Mon test migration comptait les LIGNES, pas les valeurs de colonne — manqué ; panel l'attrape.)* |
| [19] | 3/3 | medium | 📖 | `_bootstrap_schema_latest` pose `user_version` mais n'insère jamais dans `schema_migrations` → désync après self-heal (diagnostic d'incident 023 impossible). |

**C. APPLY — statut trompeur (observabilité, pas de corruption FS)**
| ID | votes | sév | st | Trouvaille |
|---|---|---|---|---|
| [4] | 2/3 | medium | 📖 | `apply_support.py:1565` `close_apply_batch(status="DONE")` **codé en dur** malgré `result.errors>0` (non fatal) → apply partiellement échoué affiché « terminé ». |
| [5][7] | 3/3·2/3 | medium | 📖 | batch atomique qui lève → `status='FAILED'` figé (L2213) **avant** `rollback_forward` ; le verdict `ROLLBACK_PARTIAL/FAILED` (+`ok=False`) ne va que dans `apply_batch_modes.rollback_status` (table annexe), jamais dans `apply_batches.status` → impossible de savoir si le FS est restauré ou à moitié reverti. |
| [6] | 3/3 | — | ↩️ | revert QUARANTINE_* SKIP si src réapparaît = **garde TOCTOU intentionnel** (anti-écrasement fichier user, avec WARN) → pas un bug net. |
| [8] | 2/3 | low | 🗳️ | batch PENDING-zombi complet sans `expected_ops` classé `ROLLED_BACK` (libellé « inconsistant ») — prudent, cosmétique. |

**D. QUARANTAINE TTL (au-delà des P0 corrigés)**
| ID | votes | sév | st | Trouvaille |
|---|---|---|---|---|
| [0] | 3/3 | **medium** | 🔬📖 | la TTL purge `cfg.root/_review` mais l'apply réel écrit conflicts/sidecars/duplicates_identical/leftovers dans `run_dir/_review` (sous `%LOCALAPPDATA%/runs/`) → **la TTL configurée (30j) ne gouverne PAS 4/5 buckets**. *(Sévérité corrigée HIGH→MEDIUM : pas de croissance infinie — `clean_old_runs(keep_last=20)` rmtree les vieux run_dirs ; mais lifecycle = rétention-runs, pas la TTL.)* |
| [1] | 2/3 | medium | 🗳️ | manifest keyé par chemin → un fichier renommé/redéplacé dans le bucket reçoit `first_seen=now` (TTL repart à 0). Path-bound, pas identity-bound. |
| [2] | 3/3 | low | 📖 | `_save_ttl_manifest` `write_text` sans `os.replace`/lock → viewer + cron daemon = last-writer-wins (recoupe F-V3-E1). |
| [3] | 2/3 | low | ↩️ | fallback `st_mtime` (L290) présent mais **inerte** sur le chemin TTL réel → latent (code piège futur). |

**E. CONTRATS / VUES MORTES (front↔back)**
| ID | votes | sév | st | Trouvaille |
|---|---|---|---|---|
| [33][34][35] | 3/3·3/3·2/3 | **high** | 📖 | vue **Enrichissement IA** jamais accessible (aucune route/menu dans app.js) ET ses 3 appels façade échoueraient (`enrichment_facade` n'expose pas `get_status`/`apply_bulk`). Vue morte complète. |
| [36] | 3/3 | medium | 📖 | page **Bibliothèque workflow 5 sections** (`initLibraryWorkflow`) inatteignable : `/library` redirige vers `/bibliotheque`, `initLibraryWorkflow` jamais monté (famille F-DEAD-01). |
| [21] | 3/3 | medium | 🗳️ | `traitement.js:243` lit `k.duplicates_groups` → stat « Groupes de doublons » toujours 0 + fallback estimation moves faussé. |
| [22][23] | 3/3 | medium·low | 🗳️ | `traitement.js:1865` `r.display_tier` ; `:1357` aperçu rename TV affiche le nom de fichier vidéo. |
| [37] | 3/3 | low | 📖 | `index.html:92` commentaire de maintenance trompeur (routage inexistant). |
| [24][25][26] | 3/3 | — | ↩️ | transparence : contrats `get_status`/`build_apply_preview` **INTACTS** ; `r.decision` undefined dégrade proprement. |

**F. ÉTATS UI / PHANTOM CONFIG / a11y**
| ID | votes | sév | st | Trouvaille |
|---|---|---|---|---|
| [10] | 3/3 | medium | 🗳️ | `parametres.js:2029` reset des params juste après édition → autosave debounce (500ms) ré-écrit après le reset (reset silencieusement annulé). |
| [11] | 3/3 | medium | 🗳️ | naviguer vers `/processing` pendant un run laisse une **boucle de polling fuyante** (`run/get_status`). |
| [27] | 3/3 | medium | 🗳️ | toggle « Activer les animations » inerte. |
| [28] | 3/3 | medium | 📖 | champ « Nombre de workers globaux » inerte (`global_workers` = **0 consommateur**). |
| [29] | 3/3 | medium | 🗳️ | toggle « notifications desktop » inerte (pilote en fait `notifications_enabled`). |
| [30] | 3/3 | medium | 📖 | « Rétention scores et analyses (jours) » (`retention_days`) ne purge rien : seul consommateur `prune_disk_cache` **jamais appelé** en prod ; les crons lisent `history_retention_days`. |
| [31] | 3/3 | low | 📖 | « Template général » (`naming_template`) persisté mais non lu (moteur lit `naming_movie_template`/`naming_tv_template`). |
| [32] | 3/3 | low | 📖 | gap inverse : `effects_mode` appliqué par app.js sans contrôle dans parametres.js. |
| [12] | 3/3 | low | 🗳️ | `mkv_title_check.py:53` warning `mkv_title_mismatch` sur quasi tout fichier portant un tag title de conteneur. |
| [13] | 3/3 | low | 🗳️ | `components.css:7634` statut OMDb critique rouge sur fond sombre, contraste ~3:1 (a11y). |
| [14] | 2/3 | low | 🗳️ | `quality_score.py:1888` `probe_quality:null` → UNKNOWN (permissif) au lieu de FAILED → contourne le cap Silver. |
| [17] | 3/3 | — | ↩️ | transparence : worker recompute rattrape correctement son boundary (robuste). |

**Synthèse Vague 3** : sur 38 survivants — **3 live-reproduits** (🔬 : E1, E2, [0]), **~14 confirmés lecture/grep** (📖),
**~15 panel-3/3 à repro** (🗳️), **6 réfutés/intentionnels** (↩️). Nouveaux HIGH confirmés : F-V3-E2 (cron/probe sqlite),
[18] paused_at, [33-35] enrichment mort. Cause racine transverse : **taxonomie d'exceptions sqlite incomplète**
(E2/[20]) + **config fantôme** accumulée (5 champs) + **2 vues mortes** supplémentaires.

## VERDICT DE DÉCOUVERTE (FINAL Vague 3 — 2026-06-16)
**Taux de faux-positifs panel cumulé : 0/12** (0/9 Vagues 1-2 + 0/3 Vague 3). Panel à asymétrie jugé fiable.

**Bilan total campagne : ~50 trouvailles RÉELLES** (Vagues 1-2 : ~23 ; Vague 3 : +27 survivants nets après
réfutés/intentionnels). Sévérité agrégée : **~7 HIGH** (perceptuel mesure rien ×3, TMDb cache empty-200,
busy_timeout NAS, **F-V3-E2 cron/probe sqlite**, **[18] paused_at self-heal**, enrichment vue morte),
~22 MEDIUM, ~21 LOW/INFO. **Code 100 % intact** (0 commit, lecture seule ; repros sur fixtures jetables).

Les 3 chantiers de largeur de Vague 3 ont été **balayés** : 314 résiduel **clos** (P0 corrigés, 37 contestés +
14 non-reconfirmés tous morts/faux), concurrence (E1+E2), migrations (saines hors self-heal [18]/[19]/[20]),
contrats H8 (2 vues mortes + config fantôme).

### ⚠️ DÉCOUVERTE NON EXHAUSTIVE — il reste :
1. **Loop-until-dry NON satisfait** : cette ronde Vague 3 a été **productive (38 survivants)**, donc par la règle
   K=2 rondes vides consécutives, **au moins une ronde FIND supplémentaire** est due sur les mêmes périmètres
   (apply/migrations/contrats) avant de déclarer le tarissement.
2. **~15 survivants panel-3/3 non encore repro-live (🗳️)** : [1] TTL path-reset, [8], [10] reset↔autosave,
   [11] polling fuyant /processing, [21][22][23] contrats traitement.js, [27][29] toggles, [12] mkv warning,
   [13] contraste OMDb (a11y), [14] probe_quality null→cap Silver. Chacun a une cause-racine citée mais doit
   passer le harnais falsifiable / l'appel endpoint réel avant promotion CONFIRMÉ.
3. **Horizons jamais ouverts en repro live** (cités au plan, non couverts) : **H10 a11y** complet (Tab/Escape,
   focus-trap, aria-live async par vue), **H11 i18n** (parité EN, race boot i18n, placeholders), **H12 visuel**
   par thème au-delà des tiers (overlays, z-index/@layer), **perf/mémoire** (`virtual-table` 1000+ films, heap
   froid vs chaud), **build/CI/packaging** (`locales/`, EXE onefile cold-start).
4. **Sécurité non-loopback** (bind 0.0.0.0 + Origin forgé sur instance jetable) : la chaîne CSRF documentée
   n'a PAS été rejouée hors loopback (sous-test sécurité du plan non exécuté).

**Condition R8** : les trouvailles 🔬/📖 (live ou grep-décisif) sont **prêtes pour R8 dès maintenant** — prioriser
les HIGH : F-V3-E2 (taxonomie sqlite, 3 sites) · [18] paused_at · perceptuel · TMDb empty-200 · busy_timeout ·
enrichment vue morte. Les 🗳️ et les horizons 2-4 ci-dessus restent à épuiser (Vague 4) avant un « EXHAUSTIVE » net.

**Pour passer à EXHAUSTIVE** (Vague 4) : repro-live les ~15 🗳️ ; 1+ ronde FIND vide (×2) sur apply/migration/
contrats ; ouvrir a11y/i18n/visuel-thème/perf/build ; rejouer la chaîne CSRF non-loopback.

## ═══ VAGUE 4A — CLÔTURE FRONTS À ENJEU ═══

### FRONT 1 — Repro DÉFIANTE des survivants panel-3/3 (trace du chemin de prod obligatoire)
> Règle V3 intériorisée : un 3/3 panel = hypothèse forte, PAS confirmé. Chaque verdict prouve (a) où le code
> lit/écrit vraiment, (b) état frais réel, (c) chemin = prod. Repros : `proofs/v4a_front1_*`.

#### [12] `mkv_title_mismatch` — warning quasi toujours actif (bruit) — **CONFIRMÉ** (repro défiante corpus réel)
- **Horizon** : H6/qualité (vue VIVANTE : `quality_report_support.py:313`, sur le chemin rapport qualité). **Sévérité**
  **low** (faux signal, pas de perte). **Confiance** : 3/3 + repro corpus. **Statut** : **CONFIRMÉ**.
- **Chemin de prod prouvé** : `quality_report_support.py:311` `container_title = normalized.get("container_title")` (tag
  MKV/MP4 du probe réel) ; L313 `check_container_title(container_title, str(row.proposed_title or ""))`. `mkv_title_check.py:53`
  fait une **égalité exacte case-insensitive** → flag dès la moindre différence.
- **Mesure défiante (copie corpus 1044 entrées, `probe_cache.normalized_json`)** : 832 films ont un `container_title` ;
  **88% mismatchent même contre une version nettoyée d'eux-mêmes** (borne basse, le vrai `proposed_title` est encore plus
  éloigné) ; 87% contiennent une année, 77% des tokens qualité (1080p/x265/MULTI…), 71% sont des release-names à points.
  → le warning fire sur la quasi-totalité des fichiers à tag conteneur = **signal inutile** (et noie les vrais warnings).
- **Correctif (R8)** : normaliser/fuzzy-matcher (titre+année) avant comparaison, ou ne flaguer que sur divergence de
  *film* réelle (pas un release-name attendu).

#### [14] `probe_quality: null` → UNKNOWN (contourne cap Silver) — **LATENT (jamais atteint en prod)**
- **Repro défiante (corpus réel)** : distribution `probe_quality` sur 1044 entrées = **`{FULL: 1042, PARTIAL: 2}`**,
  **0 null/absent**, 0 « FULL + null ». La dataclass `probe_models.py:261` force `probe_quality: str = FAILED` et le
  normaliseur le remplit toujours. La branche `is None → UNKNOWN` (quality_score.py:1888) **n'est jamais déclenchée par
  les données de production** ; elle ne le serait que par un cache legacy/corrompu inexistant ici. → **latent (code piège
  futur)**, PAS un bug actif. *(Per la leçon : chemin de prod prouvé ne produisant jamais null.)*

#### Front 1 — batch contrats/toggles (repro défiante par trace de prod)
| ID | fichier:ligne | verdict | preuve (chemin de prod tracé) |
|---|---|---|---|
| [21] | `traitement.js:245` ← `data.kpis` | **CONFIRMÉ** medium | producteur kpis live = `dashboard_support.py:542-558` (12 clés) **sans `duplicates_groups`** → `k.duplicates_groups` toujours `undefined` → 0. Seul l'historique (`history_support.py:361`) l'émet. Stat step-4 toujours 0 + fallback estim. moves faussé. |
| [22] | `traitement.js:1865` `r.display_tier` | **RÉFUTÉ (bug actif)** | get_plan **n'émet pas** `display_tier`, mais le row porte `"tier"` (`run_flow_support.py:1669`) et le code fait `display_tier \|\| tier_v2 \|\| r.tier` → **fallback propre**. Lecture morte (code smell), pas un défaut user-facing. |
| [27] | `parametres.js:277` `animations_enabled` | **CONFIRMÉ** medium | persisté (`settings_support.py:1705`) mais **0 consommateur DOM/CSS** : les animations ne sont coupées que par `@media prefers-reduced-motion` (OS), jamais par le toggle app. Hint « interface 100% statique » mensonger. |
| [29] | `parametres.js:215` `desktop_notifications_enabled` | **CONFIRMÉ** medium | persisté (`settings_support.py:1703`) mais **0 consommateur** hors persistance/définition → toggle inerte (les notifs sont pilotées par `notifications_enabled`). |

#### Front 1 — batch états UI (repro défiante par trace de prod)
| ID | fichier:ligne | verdict | preuve (chemin de prod tracé) |
|---|---|---|---|
| [11] | `app.js:281` `/processing` | **CONFIRMÉ** medium | `processing.js:485` poll `run/get_status` toutes les 2 s ; cleanup `unmountProcessing()` (L876) **existe mais jamais câblé** : grep → orpheline ; le routeur (`router.js:148`) prend le **retour de `init()`** comme cleanup, or `initProcessing` est **`async`** → retourne une Promise (pas une fonction) → cleanup ignoré. Route atteignable (`status.js:449`, `qij.js:126`). Poll fuit à chaque sortie, s'empile à chaque visite. |
| [10] | `parametres.js:2029` reset | **DONNÉES-MANQUANTES** (gap réel) | le callback debounce (L1794) POST `_state.settings` **relu au fire-time** ; le reset fait `_loadSettings()` (async, round-trip) **sans `clearTimeout(_state.saveTimer)`**. Fenêtre de course : si le debounce (500 ms) fire pendant le round-trip avant que `_loadSettings` écrase `_state.settings`, l'ancienne valeur est re-postée → reset annulé. **Gap défensif réel** (pas d'annulation), mais déclenchement timing-dépendant non reproduit déterministe (Playwright timing requis). Correctif évident : `clearTimeout(_state.saveTimer)` en tête du reset. |
| [23] | `traitement.js:1355` `video_rename_tv` | **RÉFUTÉ (intentionnel)** | `video_rename_tv` est une **action explicite** ; l'aperçu `folderOld/video → folderNew/dst_filename` reflète fidèlement un renommage d'épisode TV (la sécurité torrent « ne jamais renommer le fichier vidéo » vise les **films**, action dédiée distincte pour TV). Aperçu correct, pas un défaut. |

#### Front 1 — batch backend (repro défiante)
| ID | fichier:ligne | verdict | preuve (chemin de prod tracé) |
|---|---|---|---|
| [8] | `apply_batches_reconciliation.py:170` | **CONFIRMÉ** low (intentionnel) | un batch zombie réellement complet sans `expected_ops` → `expected is None` → `"rolled_back"`. Mais `_close_batch` ne fait qu'**un UPDATE de statut** (note summary), **aucune action FS** → mislabel d'observabilité, pas de perte. Choix « ROLLED_BACK prudent » délibéré ; portée = batches legacy sans expected_ops. |
| [1] | `quarantine_ttl.py:137` | **LATENT** | `move_to_review_bucket` applique un **suffixe de collision** (`unique_path_dup`, `_2`/`__DUP1`) → une re-quarantine crée un NOUVEAU fichier ; l'original garde son rel + `first_seen`. **Aucun flux vivant ne déplace un fichier déjà suivi** vers un nouveau rel (seule une réorg utilisateur hors-bande le ferait) → reset non reproduit en prod. |

### FRONT 2 — Sécurité non-loopback (garde de bypass prouvée + CSRF loopback rejoué)
#### F-V4A-SEC1 — Le bypass loopback est correctement gaté sur `bind_host=="127.0.0.1"` — **MODÈLE SAIN (réfute la fuite d'auth LAN)**
- **Preuve (code `rest_server.py:498-505`)** : le bypass exige `client_ip ∈ _LOCAL_CLIENT_IPS` **ET** `bind_host == "127.0.0.1"` **ET** `CINESORT_DISABLE_LOCAL_AUTH != "1"`. Le commentaire L495-497 : *« bypass volontairement DÉSACTIVÉ quand bind 0.0.0.0 … sécurité critique »*. Donc tout bind LAN (0.0.0.0 ou IP spécifique) **force l'auth Bearer** ; un client LAN (IP hors loopback) échoue aussi la condition 1. **Aucune fuite d'auth en non-loopback.** *(Choix méthodo : NE PAS binder réellement 0.0.0.0 sur le réseau domestique de l'utilisateur — la garde est prouvée par le ET logique des 2 conditions, exposer le LAN n'apporterait aucune info.)*
#### F-V4A-SEC2 — Chaîne CSRF : POST protégés, GET non (re-confirme F-SEC-01) — repro live
- **Test live forgé (instance test 8642, lecture seule)** : POST `run/get_status` Origin=`evil.example.com` **→ 403** ;
  même Origin **→ 200** ; OPTIONS `start_plan` **→ 204 SANS `Access-Control-Allow-Origin`** (navigateur bloque) ;
  GET `/api/poster` cross-site **→ 400** (atteint le handler, **pas 403**).
- **Couverture POST** : `rest_server.py:1027` `_handle_post` appelle `_is_forbidden_cross_site` (→ `_allowed_origin(origin)
  is None`, L442) **avant dispatch** → **tous** les POST à effet de bord (start_plan / apply / save_settings) CSRF-bloqués.
- **Surface résiduelle** = **F-SEC-01** (GET non CSRF : poster relay/SSRF + cache-eviction `?force=1`) + **F-SEC-02**
  (`_allowed_origin` ignore le port), **déjà CONFIRMÉS Vague 1**. **Aucun trou auth/CSRF neuf** hors-loopback.

## ═══ VAGUE 4B — HORIZONS CONFORT (repro runtime Playwright) ═══

### B3 — Visuel / thèmes (getComputedStyle RUNTIME, pas grep)
- **Invariant tiers : SAIN dans les 5 thèmes** (aaa, cinema, luxe, neon, studio). Mesuré en runtime
  `getComputedStyle(documentElement)` après `setAttribute('data-theme', X)` : `--tier-platinum`/`-gold`/`-silver`/
  `-bronze` résolvent **exactement** #E5E4E2 / #FFD700 / #C0C0C0 / #CD7F32 dans **chaque** thème. Le `:root` secondaire
  (`styles.css:2044`) référence `var(--tier-X-solid, #hex)` → ne casse plus rien. **RÉFUTÉ** (duplication tier inoffensive).
- **[13] CONFIRMÉ (low, a11y/contraste)** : élément `.omdb-status--error` injecté, mesure WCAG runtime sur fond effectif
  (blend rgba(185,28,28,0.12) sur body) → **ratio 2,94:1 dans les 5 thèmes**, sous AA (4.5) **et** AA-large (3.0).
  Le message critique « Clé API invalide » est peu lisible partout. Correctif : assombrir le texte ou opacifier le fond.

### B2 — i18n / locales (parité statique + bascule EN runtime)
- **Parité clés : PARFAITE** — fr.json **746** == en.json **746**, **0 clé manquante** dans un sens ou l'autre. Mécanisme
  i18n sain (`_FALLBACK_FR` couvre la sidebar au boot, retry fetch, `STORAGE_KEY="cinesort_locale"`).
- **F-V4B-I18N CONFIRMÉ (low)** : bascule runtime `import('/dashboard/core/i18n.js').setLocale('en')` → toute la nav passe
  en anglais SAUF **« Doublons »** (seul item non traduit : Home/Processing/Library/Quality/**Doublons**/History/Settings/
  Help). **Cause racine prouvée** : la clé `sidebar.nav.doublons` est **absente des DEUX locales** (fr.json ET en.json) ;
  elle n'existe QUE dans `_FALLBACK_FR` (`i18n.js:38 = "Doublons"`) → en EN, `t()` retombe sur le fallback FR. **La parité
  statique 746/746 ne le voyait PAS** (clé absente des deux fichiers) — seul le test runtime l'attrape (leçon repro-défiante).
  Correctif : ajouter `sidebar.nav.doublons` aux 2 locales (fr="Doublons", en="Duplicates").
- Les 94 valeurs « EN==FR » sont quasi toutes des cognats/noms propres (Actions, Code, Score, Tier, Version, Jellyfin,
  Date, Run ID…) → pas un défaut. **RÉFUTÉ** sauf le cas Doublons ci-dessus.

### B1 — a11y / WCAG (survey DOM + nav clavier)
- **Posture SAINE** sur la vue Accueil : **14 régions `aria-live=polite`** (badge sidebar, `libraryContent`,
  `qualityContent`, `view-qij`, `dashSettingsContent`, `helpContent`, `jellyfinContent` — couvrent les zones async),
  4 `role=status/alert`, **0/21 bouton sans nom accessible**, **0 img sans alt**, Escape ferme + restaure le focus.
- **Mineur** : 1 input sans label associé (champ recherche, s'appuie sur `placeholder` — ajouter `aria-label`).
  Focus-trap modal non testé en profondeur (command-palette ne s'ouvre pas via event synthétique ; `modal.js:105`
  porte un trap par lecture). → couverture a11y **bonne**, pas de finding bloquant ; reste DONNÉES-MANQUANTES sur le
  focus-trap modal réel (nécessite ouverture UI réelle).

### B4 — perf / mémoire — **DONNÉES-MANQUANTES** (2 raisons indépendantes)
- **(1) Corpus absent dans le test instance** : la vue `/bibliotheque` du serveur `--api` de test est **vide** (302 nœuds
  DOM totaux, 0 ligne film, ~4 MB heap), stable sur 8 + 16 scrolls/oscillations. Impossible de mesurer la virtual-table
  sur 1000+ films ici (le chemin de prod « 1000+ films » n'est pas atteint → mesurer serait hors-prod).
- **(2) GC non forçable** : `browser_evaluate` n'expose pas `--expose-gc` ni le CDP `HeapProfiler`, donc le protocole exigé
  (GC forcé avant mesure + seuil pré-défini) **n'est pas satisfiable** → tout delta heap serait du bruit, non promouvable.
- **Mesure GC-indépendante faite** (croissance DOM virtual-table) : **non concluante car liste vide**. À refaire sur une
  instance pointée sur le corpus réel (films chargés dans la vue) avec CDP HeapProfiler. **NON un bug, NON un sain** —
  données manquantes assumées.

### A1 — RONDE FIND VIDE (Round 1) : workflow ENTIER mais **PRODUCTIVE (5 NOUVEAUX)** → K=2 NON commencé
> **Intégrité workflow** (`wf_0610c5ad-02a`) : finders **4/4 vivants + 4/4 complets**, panel verify **3/3 votes partout**,
> **RELIABLE=true**, leurres **0/2**. Donc ce n'est PAS un instrument cassé (≠ Front 3 V3). Le résultat compte — et il
> est **productif** : 5 survivants NEUFS. La ronde-vide n'est donc **pas atteinte** (compteur rondes vides = 0).

**Chemin TV-apply (jamais audité avant) — 2 findings data-intégrité CONFIRMÉS par lecture défiante :**
| ID | votes | sév | fichier:ligne | trouvaille (chemin de prod prouvé) |
|---|---|---|---|---|
| F-V4B-TV1 | 3/3 | **medium** | `apply_core.py:2253` | `apply_tv_episode` renomme la vidéo en `SxxExx - Titre.ext` (L2240) mais déplace les sidecars (srt/nfo/jpg) avec `dst_side = target_dir / sidecar.name` → **nom d'origine conservé, jamais réaligné sur le nouveau stem** → tous les sous-titres/nfo des épisodes TV renommés **orphelins** (Jellyfin/Kodi/Plex ne les associent plus). Asymétrie avec apply_single (ne renomme que le dossier). DISTINCT de F-H3-02. |
| F-V4B-TV2 | 3/3 | **medium** | `apply_core.py:2241-2262` | les ops MOVE_FILE TV (vidéo + sidecars) sont enregistrées **sans `src_sha1`/`src_size`** (contraste : apply_single les calcule L753-754 + passe L800-812). À l'undo, `preverify_undo_operations` les classe `legacy_no_hash` → le garde-fou « UNDO refuse : fichiers modifiés depuis l'apply » est **INERTE pour tout le chemin TV** (filet P1.2 absent uniquement pour TV). Le commentaire L37 prévient lui-même du risque. |

**Rollback op-level + contrat doublons — 3 findings (2 à 2/3, 1 à 3/3) :**
| ID | votes | sév | fichier:ligne | trouvaille |
|---|---|---|---|---|
| F-V4B-RB1 | 2/3 | medium | `apply_rollback.py:335-340` | après revert FS réussi, `rollback_forward` ne marque JAMAIS `apply_operations.undo_status` (seul `apply_batch_modes.rollback_status` est touché) → un batch atomiquement reverti apparaît `pending_ops=total, undone_ops=0` = « jamais annulé, entièrement undoable » alors que le FS est déjà revenu à src. DISTINCT de [5][7] (batch-level). NEW (grep `undo_status` dans l'audit = 0). |
| F-V4B-RB2 | 2/3 | medium | `apply_rollback.py:378-380` | process tué PENDANT le revert (après `ROLLBACK_IN_PROGRESS`, avant le statut final) → `rollback_status` figé `IN_PROGRESS` à vie, FS à moitié reverti ; `reconcile_pending_batches` ne scanne que `apply_batches.status='PENDING'` (le batch est `FAILED`) → aucun chemin de récupération. NEW. |
| F-V4B-DUP1 | 3/3 | medium | `doublons.js:367` | les lignes **Codec/Résolution/Audio** des cartes A/B doublons ne s'affichent JAMAIS : le front lit `quality_a.{codec,resolution,audio_codec}` mais `_quality_info_for_row` (`run_flow_support.py:1446`) ne renvoie que `{score, tier}`. Endpoint `run/check_duplicates`. Route VIVANTE. NEW. |

## ═══ VAGUE 10 — CLÔTURE DÉCOUVERTE : 4 GRILLES DE PARITÉ + K=2 INTÉGRITÉ ═══

### PARTIE A — LES 4 GRILLES DE PARITÉ (fermeture par construction = specs d'unification R8)

#### GRILLE A1 — Jumeau `views/film-detail.js` (standalone) ↔ `components/film-detail.js` (corrigé)
> La vue standalone échoue sur **CHAQUE** champ que le composant gère — elle n'a reçu **aucun** fix (R7-2, F-H8-01).
| Champ | Composant (corrigé) | Vue standalone (jumeau) | Écart |
|---|---|---|---|
| Specs techniques | `probe.detected.*` (L441) | `probe.video`/`probe.audio`/`probe.subtitles` (L261-263) | sections Vidéo/Audio/ST vides (F-V8-FILMVIEW-PROBE) |
| Durée | `det.duration_s` (L444) | `probe.duration_s` (L142) — clé inexistante | durée « — » |
| Confiance candidat | `candidate.confidence ?? score*100` (L324) | `topCandidate.confidence_label` (L333) — inexistant | « ? » (F-V8-FILMVIEW-CAND) |
| Synopsis | `data.overview ?? candidate.overview` (L256) | `topCandidate.overview` (L334) — inexistant (data.overview ignoré) | jamais rendu |
| Réalisateur | `data.director ?? topCand.director` (L155) | `candidates[0].director` (L139) — inexistant | jamais affiché (F-V8-FILMVIEW-DIR) |
> **Reco unification R8** : supprimer le doublon — `views/film-detail.js` doit réutiliser le render du composant (source unique). Aucun écart résiduel neuf (la vue est intégralement obsolète).

#### GRILLE A2 — Perceptual display-path : `get_perceptual_details` (affichage) ↔ `PerceptualResult.to_dict` (analyse)
> La modale lit une forme APLATIE (chemin analyse) ; le chemin d'affichage par défaut sert le report DB nu (formes divergentes).
| Champ lu par la modale | `to_dict` (analyse) | `get_perceptual_details` (affichage, repo:357) | écart |
|---|---|---|---|
| `grain_analysis`/`audio_perceptual`/`cross_verdicts` | top-level | **sous `metrics`** (nesté) ou absent | grain/audio/verdicts vides |
| `codec`/`bit_depth`/`width`/`height`/`bitrate_kbps` | (probe enrichi) | **absents** (report DB = scores+verdicts only) | Detail technique vide, bloc bitrate-vs-réso `return null` |
| `audio_streams`/`video_streams` | (probe) | **absents** | pistes vides |
| `breakdown`/`analyzed_at` | présents | **absents** (horodatage = `ts`) | breakdown vide |
> **Reco unification R8** : `get_perceptual_details` doit renvoyer la MÊME forme aplatie que `to_dict` (+ join probe), ou la modale lit explicitement `d.metrics.*` + un probe. Une seule forme de sortie perceptuelle. (Corrige le verdict V7 [10].)

#### GRILLE A3 — Rendu doublons : `duplicate_compare`/`check_duplicates` ↔ {carte `doublons.js`, modale comparateur, `lib-duplicates`}
| Donnée | Producteur back | Carte doublons.js | Modale comparateur | lib-duplicates | Passe / écart |
|---|---|---|---|---|---|
| Score comparaison | `total_score_a/b` = points h2h (duplicate_compare:142) | `${score}/100` (L297) **faux %** | masque le perdant (showScoreB) | — | **sémantique** : échelle points≠/100 (F-V9-DUP-SCALE) |
| État décidé | `winner_row_id` en DB (apply.py) ; `winner_decided` **0 hit** back | `g.winner_decided` (L194) jamais joint au refresh | — | — | **sémantique** : décision invisible (F-V9-DUP-DECISION) |
| Taille/économie | octets | `_fmtSize` « Go » décimal/binaire (L100) | `_fmtSize` « Gio » binaire (L57) | `fmtBytes` locale-aware (L215) | **sémantique** : **3 formateurs divergents** (F-V9-DUP-UNITS) |
| Codec/Réso/Audio | `_quality_info_for_row` = `{score,tier}` (1446) | `qualityA.codec/...` (L367) absent | n'utilise pas ces clés | — | **structurel** : lignes jamais rendues (= F-V4B-DUP1) |
> **Reco unification R8** : (1) échelle de score unique (ou libellé « points » assumé) ; (2) `check_duplicates` joint `duplicate_decisions` → `winner_decided`/`winner_side` ; (3) les 3 renderers adoptent `core/format.js fmtBytes` (helper centralisé EXISTANT).

#### GRILLE A4 — Sérialiseur cache : `stats_snapshot_for_cache` (écrit) ↔ `stats_apply_cached_delta` (relu)
| Compteur Stats | Capturé au snapshot (L168) | Ré-appliqué sur cache HIT | écart |
|---|---|---|---|
| 13 champs « delta » (films_seen, moves_planned…) | ✓ | ✓ | OK |
| `films_rejected_ext`/`_size`/`_name` (888-893) | ✗ omis | ✗ perdu | sous-compte « Diagnostic scan » |
| `root_level_films_seen` (685) | ✗ omis | ✗ perdu | warning « films à la racine » supprimé à tort |
| `tv_episodes_seen` (662) / `folders_rejected_scandir_error` (894) | ✗ omis | ✗ perdu | compteurs faux |
> **Reco unification R8** : aligner le set de champs snapshot/replay (round-trip sans perte) — F-V9-CACHE-STATS.

**→ Les 4 seams détectés sont CARTOGRAPHIÉS en grilles de parité complètes (specs d'unification R8).** Aucun écart
résiduel neuf débusqué en confrontant les grilles (A1 vue obsolète intégrale ; A2/A3/A4 = les findings V8/V9 positionnés).

### PARTIE B — 2e ronde K=2 intégrité : **RELIABLE=true mais PRODUCTIVE (2 neufs)** → K=2 NON atteint (0/2)
> Intégrité (`wf_6ca2d143-0b3`) : finders **3/3 + 3/3 complets**, panel **3/3 votes**, leurres **0/2**, RELIABLE=true.
> Même l'« intégrité pure » (0 survivant en V9) **re-produit** : 2 survivants 3/3 → compteur rondes vides intégrité **remis à 0**.
> Micro-pattern : les helpers loser/marked-for-deletion (ajoutés R7-4 « Phase 6 doublons ») ont été **greffés avant la
> boucle apply sans la résilience per-row ni les compteurs du pattern existant** — un seam de plus, dans la couche intégrité.

| ID | votes | sév | fichier:ligne | trouvaille (CONFIRMÉE code) |
|---|---|---|---|---|
| F-V10-LOSER-ATOMIC | 3/3 | **medium** | `apply_core.py:1303,1320` | `move_duplicate_losers_to_user_decided` + `move_marked_for_deletion_to_bucket` appelés **avant la boucle row, HORS try/except** → un loser/marked verrouillé (.mkv ouvert) lève une exception non rattrapée → **avorte TOUT le batch** (winners + rows non traitées) = FAILED, travail partiel (sidecars/losers déjà déplacés) laissé en place = état incohérent. Asymétrie : une row normale verrouillée est attrapée per-row (L1650, batch PARTIAL). |
| F-V10-LOSER-COUNTER | 3/3 | medium | `apply_core.py:1042,1056,1077` | les helpers loser incrémentent `duplicates_identical_moved_count` (compteur des doublons **byte-identiques**, incrémenté en lockstep avec `_deleted_count` L690-691). Les losers user-decided **cassent l'invariant `moved==deleted`** + atterrissent dans `_duplicates_user_decided` alors que l'UI (« Duplicats identiques déplacés ») pointe vers `_duplicates_identical` → **chemin de récupération mensonger**. Pas de compteur loser dédié (alors que `marked_for_deletion_moved_count` existe pour le miroir). |

### ═══ VERDICT VAGUE 10 (2026-06-17) ═══
- **Leurres** : 0/2 (RELIABLE=true). **Cumulé campagne : 0/28.**
- **FAIT cette vague** : ✅ **les 4 seams détectés sont CARTOGRAPHIÉS en grilles de parité complètes** (A1 film-detail jumeau,
  A2 perceptual display-path, A3 rendu doublons, A4 sérialiseur cache) = **specs d'unification R8**.
- **K=2 intégrité pure : NON atteint (0/2)** — la 2ᵉ ronde FIABLE a livré **2 nouveaux 3/3** (F-V10-LOSER-ATOMIC/COUNTER),
  compteur remis à 0. L'horizon intégrité **n'est pas tari**.
- **⚠️ NON CLOS.** Raisons précises :
  1. **K=2 intégrité NON atteint** : 2ᵉ ronde RELIABLE=true mais **productive** (2 neufs confirmés) → 0/2, il faut 2 rondes
     vides fiables consécutives (raison : **nouveaux bugs intégrité réels** — seam loser/marked greffé sans le pattern).
  2. **Résidu sémantique hors-seams** : la passe sémantique (UPGRADE 2) reste un gisement à chaque couple → **basculé en
     FILET post-R8** (PAS une condition de clôture, décision actée V10) — mais donc la découverte sémantique exhaustive
     n'est **pas** revendiquée (raison : espace sémantique non énumérable, par construction).
  3. Les 4 seams sont **cartographiés mais pas FERMÉS** (fermeture = R8, hors périmètre read-only) — la découverte de
     leurs écarts est close, l'unification reste due.
- **Acquis structurel** : la famille des contrats **structurels** est close par construction (couples finis, jumeau borné
  à 1, 4 grilles complètes). Seuls restent (a) la convergence K=2 intégrité (tail de bugs apply/migration), (b) le filet
  sémantique post-R8. **La phase découverte des COUTURES STRUCTURELLES est close ; l'intégrité pure et le sémantique non.**

## ═══ VAGUE 9 — CARTOGRAPHIE SYSTÉMATIQUE DE LA FAMILLE DES CONTRATS ═══

### PARTIE A2 — recensement des JUMEAUX composant↔vue (structurel)
- **Un seul jumeau exact** components/↔views/ : `film-detail.js` (= seam #3, connu). Les 35 composants + 24 vues n'ont
  **aucune autre paire de même nom** → la classe « jumeau standalone exact » a **exactement 1 membre** (convergence
  structurelle). Quasi-jumeaux à formes divergentes (comparateur, perceptual-modal, home-charts) couverts par le finder A-twins.

### PARTIE C — F-V8-COLL-ATOMIC : **CONFIRMÉ comportementalement** (+ amplification dedup)
- Harnais `proofs/v9_coll_atomic_repro.py` : vrai `apply_collection_item`, move vidéo patché → `PermissionError`
  (mkv verrouillé, cas reconnu fréquent par le code). **Différentiel FS mesuré** : exception **non gérée intra-row** ;
  sidecars `.srt`/`.nfo` déjà dans `sub_dir/`, **vidéo bloquée en source** = item collection **à moitié appliqué**,
  **0 op de rollback**. **Amplification confirmée** : le ledger `dedup_seen_ops` a marqué la vidéo « vue »
  (`collection_video`) AVANT le move → **un retry skipperait la vidéo → demi-application PERMANENTE** (irrécupérable
  sans intervention manuelle). Falsifiable (le harnais compte les ops rollback + l'état FS). Chemin=prod. **CONFIRMÉ high.**
  → Preuve vivante d'UPGRADE 1 : la « référence saine » (chemin film) **n'est ni atomique ni récupérable** sur les collections.

### PARTIE A+D — cartographie (workflow `wf_2d4bf17c-bf5`, RELIABLE=true) : **6 survivants 3/3** — seam #4 doublons
> Intégrité : finders **6/6 + 6/6 complets** (séquentiel → 0 rate-limit), panel **3/3 votes**, leurres **0/2**, RELIABLE=true.
> **La PASSE SÉMANTIQUE (UPGRADE 2) a été décisive** : 4 des 6 findings sont des dérives sémantiques qu'un contrôle
> structurel seul aurait ratées (échelle, unité, forme). Aucune référence présumée saine, verdicts antérieurs masqués.

### 🔴 SEAM #4 DÉTECTÉ — rendu des comparaisons de doublons (3 renderers dérivés + dérives sémantiques)
| ID | votes | sév | passe | fichier:ligne | trouvaille |
|---|---|---|---|---|---|
| F-V9-DUP-SCALE | 3/3 | **high** | sémantique | `doublons.js:297` ↔ `duplicate_compare.py:142` | la carte rend `total_score_a/b` en `${score}/100`, MAIS ce sont des **points head-to-head partitionnés** (`sum(points_delta>0)` vs `sum(<0)`, pool ~95-110, perdant ~toujours 0) — PAS un score 0..100. → gagnant « 30/100 », perdant « 0/100 » même pour 2 bons fichiers. Dérive d'échelle/sémantique. |
| F-V9-DUP-DECISION | 3/3 | **high** | sémantique | `doublons.js:194` ↔ `run_flow_support.py:1744` | après « Garder A/B », le badge « Décidé » disparaît au refresh : `check_duplicates` (seul builder de groupes) **ne joint jamais** les décisions (`winner_decided`/`winner_side` = **0 hit backend**) ; `_applyGroupsData` écrase l'état local → `decidedCount=0`. Décision pourtant persistée (`winner_row_id`) + honorée à l'apply → **invisible en UI**. |
| F-V9-DUP-UNITS | 3/3 | medium | sémantique | `doublons.js:100` ↔ `duplicate-comparator-modal.js:57` ↔ `lib-duplicates.js:215` | **3 formateurs de taille divergents pour 1 donnée** : carte « 1.5 Go » (toFixed1, label décimal sur math binaire), modale « 1.50 Gio » (label binaire, fix reçu), lib-duplicates `core/format.js fmtBytes` (locale-aware FR/EN). En locale EN, l'économie disque reste FR dans Doublons. Le helper centralisé EXISTE mais 2/3 ne l'adoptent pas. |
| (DUP1 recoup) | 3/3 | high | struct | `doublons.js:367` ↔ `run_flow_support.py:1446` | lignes Codec/Résolution/Audio jamais affichées (`_quality_info_for_row` renvoie `{score,tier}`). **= F-V4B-DUP1 déjà listé** — positionné ici dans le seam, PAS compté neuf. |

### Autre survivant — sérialiseur (A5)
| ID | votes | sév | passe | fichier:ligne | trouvaille |
|---|---|---|---|---|---|
| F-V9-CACHE-STATS | 3/3 | medium | sémantique | `plan_support_core.py:168` (snapshot) ↔ `:208` (apply delta) | `stats_snapshot_for_cache` capture 13 champs mais **OMET** des compteurs incrémentés par dossier (`films_rejected_ext/size/name`, `root_level_films_seen`, `tv_episodes_seen`, `folders_rejected_scandir_error`). Sur cache HIT incrémental, seul le delta-subset est ré-appliqué → contribution des dossiers cachés **perdue** dans `stats_json` final → carte « Diagnostic scan » sous-compte + warning « films à la racine » supprimé à tort. Round-trip à perte (≠ F-META-01). |

### 🗺️ GRANDE CARTE DES CONTRATS (consolidée, toutes vagues) — état de la famille des coutures
| Couple producteur↔consommateur | Catégorie | Statut découverte |
|---|---|---|
| chemin film ↔ chemin TV (`apply_single`/`apply_collection_item` ↔ `apply_tv_episode`) | A2/intégrité | ✅ **CLOS** (grille parité V7, 13 gardes) |
| insights ↔ {route-map accueil, map librarian, notifications mirror} | A4 | ✅ **CLOS** (grille V8 + F-V8-LIBRARIAN-ROUTE + F-V8-INSIGHT-NOTIF) |
| `components/film-detail.js` ↔ `views/film-detail.js` (jumeau standalone) | A2 | 🔴 **DÉTECTÉ** (F-V8-FILMVIEW-PROBE/CAND/DIR) — 1 seul jumeau exact (borné) |
| `PerceptualResult.to_dict` ↔ `get_perceptual_details` (chemin affichage) | A3 | 🔴 **DÉTECTÉ** (F-V8-PERCEPT-DISPLAY, corrige V7 [10]) |
| comparaison doublons ↔ {carte doublons, modale comparateur, lib-duplicates} | A1/A3 | 🔴 **DÉTECTÉ cette vague** (seam #4 : SCALE/DECISION/UNITS + DUP1) |
| `stats_snapshot_for_cache` ↔ `stats_apply_cached_delta` (cache incrémental) | A5 | 🔴 **DÉTECTÉ cette vague** (F-V9-CACHE-STATS, round-trip à perte) |
| `PlanRow → plan.jsonl → PlanRow` (nfo_runtime) | A5 | 🟡 connu (F-META-01) |
| vues × endpoints (passe structurelle) | A1 | ✅ balayé V8/V9 (écarts isolés catalogués) |

### ═══ VERDICT VAGUE 9 (2026-06-17) ═══
- **Leurres** : 0/2 (RELIABLE=true). **Cumulé campagne : 0/26.**
- **CLOS cette vague** : ✅ **F-V8-COLL-ATOMIC** confirmé+amplifié (repro fixture) ; ✅ classe « jumeau standalone exact »
  bornée à 1 (A2).
- **Seam #4 détecté** (rendu doublons) + **seam sérialiseur cache** (F-V9-CACHE-STATS). La **passe sémantique** s'avère
  un gisement actif (4/6 findings sémantiques).
- **⚠️ DÉCOUVERTE NON EXHAUSTIVE.** Raisons précises :
  1. **Seam #4 (rendu doublons) détecté, non fermé par cartographie** : 3 renderers à mettre à parité (SCALE/DECISION/UNITS)
     (raison : **nouveau sous-système systématique**, passe sémantique).
  2. **Famille des contrats NON close par construction** : la passe **sémantique** (UPGRADE 2) reste productive à chaque
     couple (échelle/unité/forme/décision) — l'énumération des couples converge mais l'espace sémantique par couple
     continue de livrer (raison : **dérive sémantique**, pas seulement structurelle).
  3. **Seams #3 (film-detail jumeau) + perceptual display-path + sérialiseur cache** détectés, **non fermés par grille**
     (raison : cartographie de parité à finir, V10).
  4. **K=2 intégrité pure** : les 2 finders intégrité (D-integrite-1/2) ont contribué **0 survivant** cette ronde (signal de
     tarissement) MAIS c'est **1 seule ronde** — il en faut **2 consécutives FIABLES vides** (raison : K=2 non atteint, 1/2).

## ═══ VAGUE 8 — FERMER SEAM #2 (INSIGHTS) + CONTRATS SYSTÉMATIQUES ═══

### PARTIE A — GRILLE DE CONTRAT INSIGHTS → **seam #2 CLOS EN DÉCOUVERTE par construction**
> 2 producteurs back (`stats.insights` = `_compute_active_insights` ; `stats.librarian.suggestions` = `librarian.py`)
> vs consommateur front (`accueil.js` : `_INSIGHT_ROUTE_BY_TYPE` + map librarian ; `qualite.js` : panneau subs).
> Défiant : `_routeFromInsight` (accueil.js:516) lit `action_url` EN PREMIER — vérifié : les insights back **n'ont pas
> `action_url`** (clés = type/severity/count/label/filter_hint/icon) → la type-map est bien le chemin réel. Confirmé F-V7-ROUTE.

**Côté `stats.insights` (5 types émis) — route front `_INSIGHT_ROUTE_BY_TYPE` (8 types attendus) :**
| type émis back (dashboard_support.py) | dans la route-map front ? | conséquence |
|---|---|---|
| `run_in_progress`/`new_rejects`/`duplicates_to_resolve`/`dnr_partial`/`new_platinum_month` | **AUCUN** (front attend duplicates_probable/films_not_identified/films_low_confidence/subs_missing_fr/omdb_disagreements/quality_reject/health_low/sagas_incomplete) | **0/5 match** → tout clic → `/bibliotheque` (F-V7-INSIGHT-ROUTE). Le back fournit `filter_hint` mais le front l'**ignore**. Les 8 routes front sont **mortes**. |

**Côté `stats.librarian.suggestions` (6 ids émis) — map librarian front :**
| id émis back (librarian.py) | id attendu front | match ? | conséquence |
|---|---|---|---|
| `codec_obsolete` (L92) | codec_obsolete | ✓ | route OK |
| `duplicates` (L115) | duplicates | ✓ | route OK |
| `missing_subtitles` (L168) | subs_missing/subs_missing_fr | ✗ | → `/bibliotheque` (défaut) + panneau subs `qualite.js` mort (`'missing_subtitles'.includes('subs_missing')`=false → F-V7-INSIGHT-SUBS) |
| `unidentified` (L189) | not_identified/films_not_identified | ✗ | → `/bibliotheque` au lieu de not_identified |
| `low_resolution` (L213) | low_confidence | ✗ | → `/bibliotheque` (sémantique différente) |
| `collections_info` (L234) | sagas/sagas_incomplete | ✗ | → `/bibliotheque` au lieu de sagas |

**F-V8-LIBRARIAN-ROUTE — NOUVEAU (low) — CONFIRMÉ par grille** : 4/6 suggestions librarian (`missing_subtitles`,
`unidentified`, `low_resolution`, `collections_info`) ont un id **divergent** de la map front → routent vers le défaut
`/bibliotheque` au lieu de leur filtre ciblé. Distinct de F-V7-INSIGHT-ROUTE (qui couvre la type-map insights, pas la map librarian).

**→ SEAM #2 (insights) CLOS EN DÉCOUVERTE** : les deux vocabulaires (front ~15 type/id ; back 5 types + 6 ids) sont
énumérés exhaustivement. Cause racine : le front a été écrit pour un vocabulaire « catégorie » riche que le back
(vocabulaire « événement » + ids librarian voisins-mais-différents) n'a jamais implémenté. La grille = **SPEC de mise à
parité contrat R8**. Findings : F-V7-INSIGHT-ROUTE + F-V7-INSIGHT-SUBS + **F-V8-LIBRARIAN-ROUTE (neuf)**. Pas de ronde FIND vide requise.

### PARTIE D — F-V7-COLLMKDIR : **CONFIRMÉ comportementalement** (repro fixture)
- Harnais `proofs/v8_collmkdir_repro.py` : vrai `apply_single`, mode réel, fixture collection jetable, cible dépassant
  MAX_PATH sur le chemin interne (`dst/movie.mkv` = 263 > 259). **Différentiel FS mesuré** : le dossier saga
  `lib/_Collection/SSS…(150)/` est **créé VIDE et orphelin** ; le film reste en source (skip) ; **0 op MKDIR journalisée**
  (mkdir brut L1888, pas `mkdir_counted`) → rollback ne le supprimera jamais. Falsifiable (le harnais compare le compte
  d'ops MKDIR + l'existence/vacuité du dossier). Chemin=prod. **Promu 2/3 → CONFIRMÉ (medium)**.

### PARTIE B+C — passe contrats systématique + K=2 : ronde **NON FIABLE (rate-limit dès les finders)** — à relancer
- Workflow `wf_c55583cf-18b` : **0/6 finders vivants** (tous « Server is temporarily limiting requests »), RELIABLE=false,
  survivors=[] **NON FIABLE** (instrument cassé ≠ vide). Le throttle ne couvrait que le panel verify, pas les 6 finders
  parallèles. **Relancé en finders séquentiels.**
- **Relance `wf_b60e3c83-03c`** : finders **4/4 vivants + 4/4 complets** (séquentiel → 0 rate-limit), verify `RELIABLE=false`
  par **1 seul socket-drop transitoire** (verify:R7, ≠ collapse), leurres **0/2**, **productive**. **`seam3_clusters` = 4** →
  réponse à « seam #3 ? » : **OUI**. Findings 3/3 vérifiés par moi en lecture défiante :

### 🔴 SEAM #3 DÉTECTÉ — `views/film-detail.js` (fiche standalone `/film/:id`) = **JUMEAU NON CORRIGÉ** du composant
> Pattern : des correctifs appliqués à `components/film-detail.js` (R7-2 `probe.detected.*`, F-H8-01 `candidate.score`)
> n'ont **jamais été propagés** à la VUE standalone jumelle `views/film-detail.js`. CONFIRMÉ par code (chemin=prod) :

| ID | votes | sév | fichier:ligne | trouvaille |
|---|---|---|---|---|
| F-V8-FILMVIEW-PROBE | 3/3 | **high** | `views/film-detail.js:261` | lit `probe.video`/`probe.audio[]`/`probe.subtitles[]`/`probe.container_format`/`probe.duration_s` ; le producteur `film_support.py:311` (`quality.get("metrics")`) met tout à plat sous `detected.*` → sections Vidéo/Audio/Sous-titres/Conteneur **toujours vides** + durée « — ». R7-2 a corrigé le COMPOSANT, pas cette VUE. |
| F-V8-FILMVIEW-CAND | 3/3 | medium | `views/film-detail.js:333-334` | lit `candidates[0].confidence_label`/`.overview` ; `Candidate` (core.py:379) n'a aucun → confiance toujours « ? », synopsis jamais rendu (alors que `data.overview` existe). Même seam que F-H8-01. |
| F-V8-FILMVIEW-DIR | 3/3 | medium | `views/film-detail.js:137` | hero lit `candidates[0].director` (inexistant) ; réalisateur en top-level `data.director` (film_support.py:418) jamais lu → réalisateur jamais affiché. |

### Autres survivants (extensions de seams + chemin film)
| ID | votes | sév | fichier:ligne | trouvaille |
|---|---|---|---|---|
| F-V8-INSIGHT-NOTIF | 3/3 | **high** | `notifications_support.py:254` | **miroir insights→Centre de notifications MORT** : `emit_from_insights` lit `ins.get("code")` mais les insights n'émettent que `{type,…}` → `code` vide → garde `if not code: continue` saute CHAQUE insight. **3ᵉ consommateur du seam #2** (jamais catalogué). |
| F-V8-PERCEPT-DISPLAY | 3/3 | medium | `perceptual-modal.js:265` ← `repositories/perceptual.py:357` | la modale charge par DÉFAUT `get_perceptual_details` (report DB **brut** : métriques sous `d.metrics`, champs probe absents) mais lit `d.codec`/`d.width`/`d.grain_analysis`/`d.breakdown` au top-level → **sections Detail technique / breakdown / bitrate-vs-résolution VIDES sur film en cache**. **⚠️ CORRIGE V7 [10]** : j'avais testé `get_perceptual_report.to_dict()` (chemin ANALYSE aplati) ; le chemin d'AFFICHAGE par défaut est le report DB nu. |
| F-V8-COLL-ATOMIC | 3/3 | **high** | `apply_core.py:2112-2148` | `apply_collection_item` déplace les sidecars **AVANT** la vidéo (L2112 vs L2148). Échec move vidéo (mkv verrouillé/ENOSPC) → sidecars déjà dans `sub_dir/`, vidéo en source → **item collection à moitié appliqué** ; exception avalée par-row, aucun rollback (rollback_forward non armé). Contraste : `apply_single` atomique (`folder.rename`). Le chemin FILM (réf « saine » V7) **n'est pas atomique intra-row**. |
| F-V8-SCHEMA-REGISTRY | (cluster) | medium | `sqlite_store.py` + migrations 030/032 | dérive de registre : `REQUIRED_SCHEMA_TABLES`/`SCHEMA_GROUPS` non tenus à jour quand 030/032 ajoutent tables/index → **systématique** (recoupe F-V6-SCHEMA-IRC : plusieurs tables hors registre). |

### ═══ VERDICT VAGUE 8 (2026-06-17) ═══
- **Leurres** : 0/2 (relance). **Cumulé campagne : 0/24.**
- **CLOS cette vague** : ✅ **seam #2 (insights)** par cartographie (+ F-V8-LIBRARIAN-ROUTE + F-V8-INSIGHT-NOTIF 3ᵉ
  consommateur) ; ✅ **F-V7-COLLMKDIR** confirmé par repro fixture.
- **Seam systématique #3 détecté : OUI** = `views/film-detail.js` jumeau non corrigé (+ seam perceptual display-path neuf,
  + **correction défiante de V7 [10]**).
- **⚠️ DÉCOUVERTE NON EXHAUSTIVE.** Raisons précises :
  1. **Seam #3 (jumeau film-detail) détecté, NON encore fermé par cartographie** → à clore par grille « composant vs vue
     standalone » en V9 (raison : **nouveau sous-système systématique**).
  2. **Seam perceptual display-path** (`get_perceptual_details` brut vs modale) à cartographier (raison : **chemins
     d'affichage divergents**, corrige V7 [10]).
  3. **F-V8-COLL-ATOMIC** : repro comportementale sur fixture non encore faite (raison : non reproduit live).
  4. **K=2 hors-TV non atteinte** : ronde productive (≥7 neufs) + RELIABLE=false (1 socket-drop) → compteur = 0
     (raison : **nouveaux bugs + nouveaux seams**).

## ═══ VAGUE 7 — CLÔTURE : PARITÉ TV (par construction) + K=2 HORS-TV ═══

### PARTIE A — GRILLE DE PARITÉ TV (chemin film = spec) → **chemin TV CLOS EN DÉCOUVERTE**
> Méthode : extraction EXHAUSTIVE des gardes de `apply_single` (L1842-2035) + `apply_collection_item` (L2036-2167) =
> la référence saine ; confrontation garde-par-garde contre `apply_tv_episode` (L2168-2266) + pipeline TV amont. Chaque
> garde film absent côté TV = écart. Les écarts déjà confirmés V4B-V6 sont **positionnés** dans la grille (pas re-signalés).
> **Résultat : couverture exhaustive atteinte → le TV est fermé par construction, sans rondes FIND vides.**

| # | Garde (chemin film = spec) | Film | TV | Écart | Finding |
|---|---|---|---|---|---|
| 1 | `ensure_inside_root` | ✓ L1891 | ✓ L2217 | — | OK |
| 2 | `_video_ext` / lowercase_extensions | ✓ | ✓ L2210 | — | OK |
| 3 | MAX_PATH kill-switch sur `_longest_inner` (vidéo **ET** sidecars/inner) | ✓ L1902-1910 | ✗ `target_file` seul (L2222) | **high** | F-V6-TV-MAXPATH |
| 4 | Politique de collision (comparaison contenu + quarantaine) | ✓ `move_file_with_collision_policy` | ✗ NOOP `target_file.exists()` (L2232) | medium | F-V5-TV3 |
| 5 | `dedup_seen_ops` (anti double-move sidecar) | ✓ L2114-2148 | ✗ `if not dst_side.exists()` → drop silencieux | medium | F-V6-TV-SIDECOLL |
| 6 | `src_sha1`/`src_size` sur les ops (anti-undo-dangereux) | ✓ L1996-2024 | ✗ (absent, L2241) | medium | F-V4B-TV2 |
| 7 | `record_op` enregistré **en dry_run** (preview UI) | ✓ hors gate | ✗ dans `if not dry_run:` (L2238) | high | F-V6-TV-DRYRUN |
| 8 | `mkdir_counted` (compté + op MKDIR journalisée) | ✓ L2110 | ✗ `target_dir.mkdir()` brut (L2239) | medium | F-V6-TV-MKDIR |
| 9 | Sidecars alignés sur le nom cible | ✓ (vidéo non renommée, stems conservés) | ✗ vidéo renommée + sidecars gardent nom source (L2253) | medium | F-V4B-TV1 |
| 10 | Édition UI titre/année (`new_title`/`new_year` de la décision) | ✓ L1580-1581 | ✗ `row.proposed_*` seul (L2168) | medium | F-V6-TV-UIEDIT |
| 11 | Leftovers + nettoyage dossier source vidé | ✓ `leftovers_root` + `source_dirs_deleted` (L829-909) | ✗ **rien** | low-med | **F-V7-TV-LEFTOVERS (NEW)** |
| 12 | Undo casse-seule restauré (côté undo) | ✓ apply special-case L2003 | ✗ undo classe CONFLIT (apply_support.py:442) | medium | F-V6-UNDO-CASE |
| 13 | Numérotation TV correcte (interne, pas de réf film) | N/A | ✗ anime absolu `season=None`→Saison 00 | medium | F-V6-TV-ANIME |

**F-V7-TV-LEFTOVERS — NOUVEAU (low-medium) — CONFIRMÉ par code (grille)** : `apply_tv_episode` ne reçoit **pas**
`leftovers_root` et n'a **aucune** gestion des fichiers non-matchés ni de nettoyage du dossier source (grep TV
2168-2266 = 0 occurrence `leftover`/`rmdir`/`cleanup`), alors qu'apply_single/collection déplacent les leftovers vers
`_leftovers` + suppriment le dossier source vidé (`move_file_with_collision_policy` L829-909). → après un apply TV, les
fichiers parasites (samples, .txt, images orphelines) restent en source + le dossier source vidé n'est jamais supprimé.

**→ CHEMIN TV CLOS EN DÉCOUVERTE** : les 13 gardes du chemin film ont été confrontés ; ~11 écarts (10 connus + 1 neuf
F-V7-TV-LEFTOVERS) constituent la **SPEC de mise à parité TV pour R8**. Cause racine unique : `apply_tv_episode` =
implémentation parallèle jamais mise à parité. **Aucune ronde FIND vide nécessaire sur le TV** (fermeture par couverture).

### PARTIE C — 3 données-manquantes V5 TRANCHÉES (par lecture défiante)
| ID | fichier:ligne | verdict | preuve (chemin de prod) |
|---|---|---|---|
| [10] perceptual modal | `models.py:382` + `perceptual-modal.js:292` | **RÉFUTÉ-large + 1 narrow CONFIRMÉ-low** | `PerceptualResult.to_dict()` **produit** `grain_analysis`(L389), `audio_perceptual`(L390), `cross_verdicts`(L395) → 3/4 reads OK (réfute la claim large). **Mais `hdr_analysis` absent** de to_dict ET non ajouté en `perceptual_support` → `d.hdr_analysis` undefined → **champ HDR de la modale toujours « sdr »** même sur un film HDR. CONFIRMÉ-low (narrow). |
| [11] historique Doublons | `history_support.py:337` + `historique.js:764` | **CONFIRMÉ-low** | le builder `duplicates_decided` ne produit que `{title, year, winner}` → le front lit `g.winner_label` + `g.size_savings` = **undefined** → label du gagnant + gain d'espace jamais affichés dans l'onglet Doublons de l'Inspecteur Historique. |
| [12] historique Films | `history_support.py:317` + `historique.js:651` | **CONFIRMÉ-low** | le builder `films` ne produit que `{film_id, title, year, tier, score}` → le front lit `film.decision`/`film.status`/`film.is_duplicate` = **undefined** → statut (Doublon/Suppression/Rejeté/Approuvé) toujours au défaut dans l'onglet Films. |

**Bilan Part C** : 3 DM tranchées → **[11][12] CONFIRMÉS-low** (2 contrats neufs : sous-champs Inspecteur Historique
absents backend), **[10] réfuté-large** (3/4 clés produites) **+ 1 narrow CONFIRMÉ-low** (`hdr_analysis` absent → HDR « sdr »).

### PARTIE B — K=2 HORS-TV : ronde **FIABLE (RELIABLE=true)** mais **PRODUCTIVE (3 NEUFS)** → K=2 non atteinte
> Intégrité (`wf_2379e7e2-737`) : finders **4/4 + 4/4 complets**, panel **3/3 votes (throttle séquentiel → 0 rate-limit)**,
> **RELIABLE=true**, leurres **0/2**. Ronde VALIDE — mais **productive** : 3 survivants NEUFS → compteur rondes vides hors-TV = 0.

| ID | votes | sév | fichier:ligne | trouvaille (confirmée code, chemin=prod) |
|---|---|---|---|---|
| F-V7-INSIGHT-SUBS | 3/3 | **medium** | `qualite.js:333` | section « Subs FR manquants » affiche **toujours « — »** / « Tous les films ont des sous-titres FR détectés » : le front cherche un insight `.includes("subs_missing")` mais `_compute_active_insights` (`dashboard_support.py:1493-1569`) n'émet QUE `run_in_progress`/`new_rejects`/`duplicates_to_resolve`/`dnr_partial`/`new_platinum_month` ; la suggestion librarian a l'id `missing_subtitles` (≠ `subs_missing`). `finalCount` toujours null. |
| F-V7-INSIGHT-ROUTE | 3/3 | low | `accueil.js:507-524` | `_INSIGHT_ROUTE_BY_TYPE` keyé sur `duplicates_probable`/`films_not_identified`/`subs_missing_fr`/`quality_reject`/`sagas_incomplete` — **aucun** ne matche les 5 types réellement émis → tout clic insight route vers `/bibliotheque` (fallback). Dégrade proprement (LOW). |
| F-V7-COLLMKDIR | 2/3 | medium | `apply_core.py:1888` | (chemin FILM) `coll_dir.mkdir(parents=True, exist_ok=True)` créé **AVANT** le killswitch MAX_PATH (L1910) + NOOP conform (L1920) + `_fs_equivalent` (L1949). Si un garde `return`/skip → **dossier saga vide orphelin** ; `mkdir` brut (pas `mkdir_counted`) → aucune op MKDIR → rollback ne le supprime jamais ; gated `if not dry_run` → divergence preview/apply. Reachable au re-apply idempotent d'un film saga conforme. |

### 🔴 2ᵉ SEAM SYSTÉMATIQUE — contrat « insights » front↔back désaccordé
Comme le chemin TV, le système d'**insights/suggestions** présente un désaccord de vocabulaire **systématique** : le
front (accueil.js, qualite.js) est écrit pour un vocabulaire riche (`duplicates_probable`, `subs_missing_fr`,
`quality_reject`, `sagas_incomplete`, `films_not_identified`, `omdb_disagreements`, `health_low`…) que le backend
`_compute_active_insights` **n'a jamais implémenté** (5 types seulement). → plusieurs features insight-driven sont
mortes (panneau subs FR, routage des clics insight). C'est un **chantier de mise à parité contrat** distinct pour R8,
et un **horizon hors-TV encore productif** (la ronde FIABLE l'a fait surgir).

### ═══ VERDICT VAGUE 7 (2026-06-17) ═══
- **Leurres** : Part B **0/2** (throttle OK). Parts A/C = lecture défiante (0 panel). **Cumulé campagne : 0/22.**
- **~7 NOUVEAUX CONFIRMÉS cette vague** : F-V7-TV-LEFTOVERS (A) ; [11][12] + [10]-hdr (C) ; F-V7-INSIGHT-SUBS,
  F-V7-INSIGHT-ROUTE, F-V7-COLLMKDIR (B).
- **CLOS cette vague** : ✅ **chemin TV** (par construction — grille de parité 13 gardes, spec R8) ; ✅ **3 DM** tranchées ;
  ✅ **perf** (limite outillage, V6).
- **Part B FIABLE mais PRODUCTIVE** : K=2 hors-TV **non atteinte** (compteur = 0) + **2ᵉ seam systématique** (insights) découvert.
- **⚠️ DÉCOUVERTE NON EXHAUSTIVE.** Raisons précises :
  1. **K=2 hors-TV non atteinte** : ronde Part B **FIABLE** mais **productive** (3 neufs) → ≥2 rondes FIABLES vides
     consécutives restent dues sur apply/migrations/contrats (raison : **nouveaux bugs réels**, dont un 2ᵉ seam).
  2. **2ᵉ seam systématique « insights »** (front↔back désaccordé) à fermer par cartographie de contrat comme le TV
     (raison : **sous-système entier non mis à parité**, productif).
  3. F-V7-COLLMKDIR (2/3) : repro comportementale sur fixture jetable non encore faite (raison : non reproduit live).

## ═══ VAGUE 6 — VIDER LE FILON TV + RE-JUGER 12 BRUTS V5 ═══

### PARTIE A — 12 bruts V5 re-jugés par LECTURE DÉFIANTE (sans panel → 0 risque rate-limit)
> Les 13 bruts V5 extraits des transcripts finder (`wf_2e379e5a-8c2`). [7]=F-V5-TV3 déjà tranché. 12 re-jugés par moi.
> **5 NOUVEAUX CONFIRMÉS, 2 RÉFUTÉS, 3 DONNÉES-MANQUANTES.**

| ID | sév | fichier:ligne | verdict (preuve défiante) |
|---|---|---|---|
| F-V6-UNDO-CASE | **medium** | `apply_support.py:442` | **CONFIRMÉ** : apply_single special-case la casse-seule (`folder.name.lower()==dst.name.lower()` → `_case_only_rename_with_rollback`, `apply_core.py:2003`), mais l'undo fait `if target_path.exists()` → sur Windows case-insensitive, l'undo d'un rename casse-seule (`Film`→`film`) est classé CONFLIT (déplacé en `_undo_conflicts`+FAILED) au lieu de restaurer. Asymétrie apply/undo. |
| F-V6-SCHEMA-IRC | **medium** | `sqlite_store.py:85-86,110` | **CONFIRMÉ** : `incremental_row_cache` (migration 008) absent de `REQUIRED_SCHEMA_TABLES` ET de `SCHEMA_GROUPS['incremental']` (= seulement file_hashes+scan_cache) → hors du filet self-heal : si la table est droppée/manquante, ni `_ensure_required_schema` ni `_with_schema_group('incremental')` (scan.py:238-363) ne la recréent → accès en OperationalError. Distinct de [18][19]. |
| F-V6-TV-SIDECOLL | **medium** | `apply_core.py:2253` | **CONFIRMÉ** : sidecar TV déplacé seulement `if not dst_side.exists()` → si 2 épisodes du même dossier ont un sidecar de nom collidant (générique : poster.jpg…), le 2ᵉ est **silencieusement abandonné** (ni move ni quarantaine ni log). Famille collision TV. |
| F-V6-TV-ANIME | **medium** | `tv_helpers.py:92-96` | **CONFIRMÉ** : `parse_tv_info` cas « Episode N » (numérotation absolue anime, sans saison) → `season=None` → `apply_tv_episode` force `Saison 00` + `S00E{ep}` → anime mis dans le dossier des **specials** (Jellyfin/Kodi). Mauvais classement. |
| F-V6-MKDIR-REV | low | `apply_core.py:438` + `apply_rollback.py:97` | **CONFIRMÉ-low (conservateur)** : ops MKDIR `reversible=False` → SKIP au revert → dossiers destination créés jamais supprimés au rollback (résidu de dossiers vides). Probablement intentionnel (ne pas supprimer un dossier potentiellement non-vide). |
| [5] ordre revert | — | `apply_rollback.py:420` | **RÉFUTÉ** : `ops_reversed = list(reversed(ops))` → revert LIFO (enfants avant parent) = correct pour le nesting. Claim « ordre cassé » fausse. |
| [6] partial orphelins | — | `apply_rollback.py:438-457` | **RÉFUTÉ-bug** : l'état mixte est **signalé `ROLLBACK_PARTIAL`+ok=False** (pas silencieux) ; absence de re-move d'orphelins = limite inhérente au partial, pas un défaut. |
| [10] perceptual modal | — | `perceptual_support.py:463` | **DONNÉES-MANQUANTES** : backend produit bien `audio_perceptual`+`grain_analysis` (L463-464) → ≥2/4 clés OK ; `cross_verdicts`/`hdr_analysis` non tracées entièrement. Pas promu. |
| [11][12] historique | — | `history_support.py` | **DONNÉES-MANQUANTES** : `winner_label`/`size_savings`/`decision`/`is_duplicate` absents de history_support (grep) mais sous-builders R7-6 non tracés entièrement → LOW non promu. |

### PARTIE B — VIDER LE FILON TV : ronde **FIABLE (RELIABLE=true)** mais **PRODUCTIVE (4 NOUVEAUX)** → filon NON drainé
> Intégrité (`wf_b1e62728-81f`) : finders **3/3 + 3/3 complets**, panel **3/3 votes (throttle séquentiel → AUCUN
> rate-limit, le correctif a marché)**, **RELIABLE=true**, leurres **0/2**. Ronde VALIDE — et **productive** : 4 survivants
> NEUFS, tous des asymétries TV vs chemin film. → la ronde-vide TV n'est **pas atteinte** (compteur = 0).

| ID | votes | sév | fichier:ligne | trouvaille (asymétrie TV vs film, confirmée code) |
|---|---|---|---|---|
| F-V6-TV-MAXPATH | 3/3 | **high** | `apply_core.py:2222` | kill-switch MAX_PATH TV ne vérifie QUE `target_file` ; les sidecars (L2253, nom source verbatim) ne passent jamais `check_path_length_killswitch`. apply_single vérifie `_longest_inner` (L1900-1910), apply_collection_item le path vidéo final → le TV omet ce garde → sidecar long (release+`.fr.forced.sdh.srt`) dépasse 260 → OSError/move partiel (épisode déplacé, sidecar bloqué). |
| F-V6-TV-UIEDIT | 3/3 | **medium** | `apply_core.py:1567` | apply_tv_episode nomme depuis `row.proposed_title/tv_series_name/proposed_year` ; apply_single reçoit `new_title/new_year` de la décision UI (L1580-1581, `dec.title/dec.year`). → **toute correction titre/année saisie sur un épisode TV en validation est silencieusement ignorée** à l'apply (honorée pour les films). |
| F-V6-TV-DRYRUN | 2/3 | **high** | `apply_core.py:2238-2247` | en dry_run, `atomic_move` ET `record_apply_op` sont tous deux dans `if not dry_run:` → **aucune op enregistrée pour les épisodes TV en preview**, alors que `res.moves += 1` est incrémenté inconditionnellement (L2266). apply_single/move_file_with_collision_policy enregistrent l'op MÊME en dry_run (preview UI). → preview TV vide + compteur faux. |
| F-V6-TV-MKDIR | 2/3 | medium | `apply_core.py:2239` | `target_dir.mkdir(...)` brut au lieu de `mkdir_counted` (utilisé partout sur le chemin film : apply_collection_item L2110, collision_policy L741) → `res.mkdirs` jamais incrémenté pour TV + aucune op MKDIR journalisée pour les dossiers Série/Saison TV. |

### 🔴 SYNTHÈSE STRUCTURELLE — `apply_tv_episode` est une implémentation parallèle SOUS-ÉQUIPÉE
Sur les Vagues 5-6, le chemin TV-apply a livré **~10 findings confirmés**, TOUS des **asymétries** avec le chemin film
(apply_single / apply_collection_item, la référence saine) : TV1 (sidecars non réalignés), TV2 (pas de src_sha1/size →
undo inerte), TV3 (pas de politique de collision sur la cible), TV-SIDECOLL (collision sidecar abandonnée),
TV-ANIME (numérotation absolue → Saison 00), TV-MAXPATH (pas de check inner), TV-UIEDIT (édition titre/année ignorée),
TV-DRYRUN (pas d'op en preview), TV-MKDIR (mkdir non compté/journalisé). **Cause racine commune** : `apply_tv_episode`
a été écrit comme une copie parallèle qui n'a JAMAIS reçu les ~9 gardes/fonctionnalités du chemin film. **Ce n'est pas
une liste de bugs isolés — c'est un sous-système entier à mettre à parité avec le chemin film en R8.** Le filon reste
**ouvert** (chaque ronde FIABLE y trouve du neuf).

### PARTIE D — C2 perf/mémoire : **FERMÉ DÉFINITIVEMENT (limite d'outillage assumée, retiré des horizons)**
- Mode démo = **16-18 films hardcodés** (`demo_support.py:DEMO_FILMS`) → insuffisant pour stresser la virtual-table
  (besoin 1000+). Peupler 1000+ exigerait injection DB + restart de l'instance (hors read-only) ou scan réel (effet de
  bord). `browser_evaluate` ne peut pas forcer le GC ni accéder au CDP HeapProfiler. → conformément à la directive Partie D :
  **angle NON FERMABLE avec cet outillage, assumé définitivement, RETIRÉ des horizons de découverte ouverts** (limite
  d'instrumentation documentée, plus un trou). À refaire hors-campagne avec Chrome DevTools (CDP) + corpus réel chargé.

### PARTIE C — K=2 apply/migrations/contrats (hors TV) : **NON ATTEINTE cette vague**
- Non lancée comme ronde dédiée : le verdict est déjà tranché par la Partie A (5 nouveaux CONFIRMÉS) → la découverte ne
  peut pas être close cette vague de toute façon. Reste due : ≥2 rondes FIND FIABLES vides consécutives sur
  apply/migrations/contrats (hors TV), après traitement des nouveaux F-V6-*.

### ═══ VERDICT VAGUE 6 (2026-06-17) ═══
- **Leurres** : Part A 0 panel (lecture défiante) ; Part B **0/2** (throttle OK). **Cumulé campagne : 0/20.**
- **9 NOUVEAUX CONFIRMÉS cette vague** : Part A (5 : UNDO-CASE, SCHEMA-IRC, TV-SIDECOLL, TV-ANIME, MKDIR-REV) +
  Part B (4 : TV-MAXPATH, TV-UIEDIT, TV-DRYRUN, TV-MKDIR). Dont **6 sur le chemin TV**.
- **Part B FIABLE (RELIABLE=true) mais PRODUCTIVE** : le throttle séquentiel a résolu le rate-limit V5, la ronde est
  valide — et elle a quand même livré 4 TV neufs → **filon TV NON drainé**, ronde-vide TV compteur = 0.
- **Synthèse** : `apply_tv_episode` = sous-système parallèle sous-équipé (~10 asymétries vs chemin film) → chantier R8.
- **Part D (C2 perf)** : fermé définitivement (limite outillage, retiré des horizons).
- **Part C (K=2 hors TV)** : non atteinte.
- **⚠️ DÉCOUVERTE NON EXHAUSTIVE.** Raisons précises :
  1. **9 nouveaux bugs confirmés** cette vague (raison : **nouveaux bugs réels**, surtout filon TV) → découverte non close.
  2. **Ronde-vide K=2 NON atteinte sur le TV-apply** : la ronde Part B fut **FIABLE** mais **productive** (4 neufs) →
     compteur rondes vides = 0 ; ≥2 rondes FIABLES vides consécutives restent dues sur le TV (raison : **filon fertile non
     tari**).
  3. **K=2 hors-TV (apply/migrations/contrats)** : non relancée cette vague (raison : non exploré jusqu'au tarissement).
  4. **3 bruts V5 en DONNÉES-MANQUANTES** ([10][11][12]) à tracer complètement (raison : non reproduit).
  5. **C2 perf** : non un trou de découverte mais **limite d'outillage** documentée (CDP/GC indisponibles).

## ═══ VAGUE 5 — TRAITEMENT TV-APPLY + REPRO 5 FINDINGS ═══

### PARTIE B — repro comportementale des 5 findings 4B → **TOUS CONFIRMÉS**
- **F-V4B-TV1 (sidecars TV orphelins) — CONFIRMÉ (repro comportementale)**. Harnais `proofs/v5_tv_apply_repro.py` :
  vrai `apply_tv_episode`, mode réel, fixture jetable. **Différentiel FS mesuré** : vidéo
  `Showname.S01E01.1080p.HDTV.x264-GRP.mkv` → `Showname (2020)/Saison 01/S01E01 - Pilot.mkv` ; mais `.srt` ET `.nfo`
  → `…/Showname.S01E01.1080p.HDTV.x264-GRP.{srt,nfo}` (**nom source conservé**). Stems : video=`S01E01 - Pilot`,
  sidecars=`Showname.S01E01.1080p.HDTV.x264-GRP` → **orphelins** (media servers ne les associent plus). Falsifiable :
  si le code réalignait, le harnais comparerait les stems et virerait sain. **Chemin=prod** (fonction de prod appelée).
- **F-V4B-TV2 (garde-fou undo inerte sur TV) — CONFIRMÉ (repro comportementale)**. Même harnais : **3 ops MOVE_FILE
  capturées (vidéo+nfo+srt), toutes sans `src_sha1`/`src_size`** (keys = dst_path/op_type/reversible/row_id/src_path/ts).
  Contraste : apply_single calcule+passe l'empreinte (apply_core.py:753-754,800-812). → à l'undo, `preverify_undo_operations`
  classe ces ops `legacy_no_hash` → le garde-fou « fichiers modifiés depuis l'apply » est **inerte pour tout le chemin TV**.
- **F-V4B-DUP1 — CONFIRMÉ (lecture, sole producteur)**. `_quality_info_for_row` (`run_flow_support.py:1446`) renvoie
  `{score, tier}` uniquement, et c'est le **seul** producteur de `quality_a`/`quality_b` (L1477-1478) → `doublons.js:367`
  `quality_a.{codec,resolution,audio_codec}` toujours `undefined` → lignes Codec/Résolution/Audio jamais affichées.
- **F-V4B-RB1 — CONFIRMÉ (grep décisif, asymétrie)**. `mark_apply_operation_undo_status` appelé partout dans l'undo
  manuel (`apply_support.py:417-522`) mais **jamais dans `apply_rollback.py`** → après revert atomique, op-level
  `undo_status='PENDING'` (FS pourtant déjà à src) → batch affiché « entièrement annulable ».
- **F-V4B-RB2 — CONFIRMÉ (grep décisif, scope reconcile)**. `reconcile_pending_batches` scanne `WHERE status='PENDING'`
  (`apply_batches_reconciliation.py:77`) ; batch reverti = `FAILED` → ignoré au boot → `rollback_status='IN_PROGRESS'`
  figé à vie si kill pendant revert. Aucun reconcile sur `apply_batch_modes.rollback_status`.

### PARTIE A — ronde FIND (Vague 5) : **NON FIABLE (verify rate-limité) + PRODUCTIVE (3ᵉ bug TV)**
> Intégrité (`wf_2e379e5a-8c2`) : finders **5/5 vivants + 5/5 complets** (13 findings bruts) MAIS **panel verify
> rate-limité** (« Server is temporarily limiting requests ») → `verify_all_3votes=false`, **RELIABLE=false**. Per la règle
> 4B/5 : ce **n'est PAS une ronde valide** (≠ vide). leurres 0/2 (sur les vérifiés). **12 findings bruts NON vérifiés**
> (statut inconnu — à re-vérifier après reset du rate-limit). 1 survivant a passé le panel 3/3 avant le rate-limit :
- **F-V5-TV3 — CONFIRMÉ par code (défiant), medium-high** : `apply_tv_episode` (appelé `apply_core.py:1567` **sans
  `conflicts_root` ni dedup**) skippe NOOP « déjà conforme » dès `target_file.exists()` (L2232-2235) **sans comparer le
  contenu**. Deux épisodes TV distincts mappant la même cible (2 versions/release-groups, ou parse S00E05 identique) →
  le 2ᵉ fichier différent est **silencieusement laissé en source, jamais quarantiné**. Contraste : single/collection
  passent par `move_file_with_collision_policy` (L629, quarantaine sur collision) ; le chemin TV ne l'utilise pas.
  **4ᵉ défaut du chemin TV-apply** (avec TV1/TV2 + ce round 13 bruts) → le seam TV est riche en bugs non découverts.

### PARTIE C — données-manquantes
- **C1 [10] reset↔debounce — CONFIRMÉ (gap, repro partielle déterministe)**. Playwright : édition de `watch_interval_minutes`
  → debounce armé ; **le `save_settings(watch_interval=99)` a tiré à t=514 ms** (500 ms après l'édition) **bien que le
  « Confirmer » du reset ait été cliqué à ~370 ms** → le chemin reset **n'annule PAS** le debounce (confirme le code :
  `parametres.js:2029` sans `clearTimeout(_state.saveTimer)`). Harm = écrasement post-reset quand round-trip reset > 500 ms
  (disque lent/NAS). *(Le POST reset n'a pas tiré dans le test — scope non sélectionné — mais le point décisif, timer non
  annulé, est prouvé.)* Upgrade du DONNÉES-MANQUANTES 4A → **CONFIRMÉ-mécanisme**.
- **C3 focus-trap modale — partiel** : `modal.js` partagé **A un focus-trap** (`trapFocus` L30 + restore focus L15 + Esc
  L27) → modales standard **saines**. MAIS `_openResetModal` (`parametres.js:1896`) construit un **overlay custom**
  (`document.body.appendChild`) **sans `trapFocus`** → la modale reset n'a vraisemblablement **pas de piège de focus**
  (focus s'échappe vers le fond). **Gap a11y LOW** (modale reset custom), code-indiqué.
- **C2 perf/mémoire — ANGLE NON FERMABLE avec cet outillage (assumé)**. L'instance `--api` de test a une biblio **vide**
  (0 film) → pas de virtual-table à mesurer ; `browser_evaluate` ne peut pas forcer le GC ni accéder au CDP HeapProfiler.
  Peupler 1000+ films synthétiques exigerait un scan réel (effet de bord) ou une DB injectée hors-tooling. **Assumé non
  fermable** — ni bug ni sain, à refaire avec une instance pointée sur le corpus réel + CDP.

### ═══ VERDICT VAGUE 5 (2026-06-17) ═══
- **Leurres panel** : 0/2 (Vague 5, partiels). **Cumulé campagne : 0/18.**
- **Part B** : les **5 findings 4B CONFIRMÉS** (TV1/TV2 repro comportementale ; DUP1/RB1/RB2 code décisif).
- **Part C** : C1 CONFIRMÉ ; C3 partiel (reset modal sans trap, LOW) ; C2 assumé non fermable.
- **Part A** : ronde **NON FIABLE** (verify rate-limité) ET **PRODUCTIVE** (F-V5-TV3 neuf + 12 bruts non vérifiés).
- **⚠️ DÉCOUVERTE NON EXHAUSTIVE.** Raisons précises :
  1. **Nouveau bug confirmé** F-V5-TV3 (chemin TV-apply) → discovery non close par définition.
  2. **Ronde FIND vide K=2 NON atteinte** : la ronde Vague 5 fut **NON FIABLE** (panel verify rate-limité, RELIABLE=false)
     ET **productive** ; compteur rondes vides **= 0**. Raison = **rate-limit serveur** (à relancer) + **vrais nouveaux bugs**.
  3. **12 findings bruts Vague 5 non vérifiés** (panel tombé) : statut inconnu, à re-passer au panel après reset rate-limit.
  4. **C2 perf** : angle non fermable avec l'outillage actuel (assumé).
  5. **Seam TV-apply ouvert et fertile** : 3 findings confirmés (TV1/TV2/TV3) + 13 bruts en 1 ronde → forte présomption
     de bugs TV résiduels ; ≥2 rondes vides FIABLES y sont dues avant tout « EXHAUSTIVE ».

### ═══ VERDICT VAGUE 4B (2026-06-17) ═══
- **Leurres panel 4B** : 0/2 (A1, workflow entier). **Cumulé campagne : 0/16.**
- **Bilan 4B** : B3 tiers SAINS (5 thèmes runtime) ; **[13] contraste OMDb CONFIRMÉ** (2,94:1) ; B2 i18n parité parfaite +
  **1 gap CONFIRMÉ** (`sidebar.nav.doublons` absent des 2 locales) ; B1 a11y posture saine (focus-trap modal = données-
  manquantes) ; B4 perf = **données-manquantes** ; A1 ronde-vide = **PRODUCTIVE, 5 NOUVEAUX** (TV-apply jamais audité).
- **⚠️ DÉCOUVERTE NON EXHAUSTIVE.** Raisons précises :
  1. **Ronde FIND vide K=2 NON atteinte** — Round 1 FIABLE (workflow entier) mais **PRODUCTIVE** (5 findings réels neufs,
     dont 3 confirmés 3/3 par lecture) → compteur rondes vides **= 0**. Raison = **nouveaux bugs réels** (pas limite session).
     Il faut ≥2 rondes vides consécutives à workflow entier après traitement de ces 5.
  2. **5 findings A1 à repro-live complète** : F-V4B-TV1/TV2 (orphelins sidecars TV / undo inerte) confirmés par lecture,
     **pas encore repro comportementale sur fixtures jetables** ; RB1/RB2 (2/3) à durcir ; DUP1 confirmé lecture.
  3. **A2 [10]** reset↔debounce : repro timing déterministe Playwright **non faite**.
  4. **B4 perf/mémoire** : données-manquantes (corpus absent du test instance + GC non forçable via browser_evaluate).
  5. **B1 focus-trap modal réel** : données-manquantes (modal non ouvrable par event synthétique).

### ═══ CLÔTURE VAGUE 4A ═══
- **Front 1** (survivants 3/3, repro défiante) : **11/12 tranchés**. CONFIRMÉS : [11] (poll /processing fuit),
  [12] (mkv warning bruit, corpus), [21] (duplicates_groups=0), [27] (animations inert), [29] (notif desktop inert),
  [8] (low intentionnel). RÉFUTÉS-bug : [22] (display_tier fallback), [23] (TV rename intentionnel). LATENTS : [1], [14]
  (jamais en prod). DONNÉES-MANQUANTES (gap réel non déterministe) : [10] (reset n'annule pas le debounce). **[13]
  (contraste OMDb) → 4B** (a11y, getComputedStyle requis).
- **Front 2** : auth non-loopback **prouvée saine** (bypass gaté `bind_host`) + CSRF POST **rejouée 403** ; surface GET
  connue (F-SEC-01/02). Pas de trou neuf.
- **Front 3** (ronde FIND vide K=2) : **NON atteinte** — workflow tué par limite de session (3/5 finders + verify morts) ;
  `survivors=[]` NON fiable, leurres 0/2. À RELANCER après reset quota.
- **Faux-positifs panel 4A** : 0/2 (Front 3 partiel). **Cumulé campagne : 0/14.**

- **Leurre L1** « rest_server bind 0.0.0.0 par défaut exposant le LAN » → **RÉFUTÉ** par le panel (le défaut est
  127.0.0.1). **Leurre L2** « score ×2 si 4K » / **L3** « tout titre à chiffre rejeté » → **RÉFUTÉS**.
- **Leurre L4** « apply supprime les perdants sans bucket _review » → **RÉFUTÉ** (le bucket existe, sécurité
  apply en place). **Leurre L5** « rate-limiter jamais appliqué (toujours bypass) » → **RÉFUTÉ**.
- **Bilan panel : 0/5 faux-positifs sur 2 vagues** → panel adversarial à asymétrie jugé fiable.

---

### F-CONF-01 — `ffprobe_path` arbitraire exécuté par le flux perceptuel (asymétrie de validation) — **CONFIRMÉ**
- **Horizon** : Horizon-Confiance (frontière subprocess). **Sévérité** : **medium** (defense-in-depth ; threat model
  = settings.json relique/altéré ou API localhost). **Confiance** : 3/3 + repro live (fonctions pures). **Statut** :
  **CONFIRMÉ**.
- **Fichiers** : `settings_support.py:1374` `_save_section_probe` persiste `ffprobe_path` avec un simple `.strip()`
  (dispatcher L1925 sans validation) ; `infra/probe/tooling.py:30` `_binary_name_allowed` (fail-closed) le
  **refuserait** côté `get_tools_status` ; mais `perceptual_support.py:296-297/333-335` exécute `ffprobe_path`
  directement en `argv[0]` (`extract_av1_film_grain_params`/`detect_hdr10_plus_multi_frame`) **sans** ce garde.
- **Repro live (rejouable, 0 écriture réelle)** : `_save_section_probe({'ffprobe_path':'C:/Windows/System32/calc.exe'},
  default_probe_backend='auto')` → persiste `calc.exe` sans validation ; `_binary_name_allowed('ffprobe',
  '…/calc.exe')` → **False**. Asymétrie : accepté au save + exécuté au perceptuel, refusé par get_tools_status.
- **Corollaire F-CONF-02 (LOW)** : `ffmpeg_runner.py:40-49` `resolve_ffmpeg_path` exécute le **sibling** `ffmpeg.exe`
  du dossier de `ffprobe_path` sans contrôle (garde #71 valide ffprobe mais pas le sibling dérivé). 4 sites.
- **Fix suggéré (R8)** : appliquer `_binary_name_allowed`/`validate_tool_path` au save ET dans le flux perceptuel.

### F-PROM-01/02/03 — Toggles Paramètres FANTÔMES (UI promet, code ne consomme pas) — **CONFIRMÉ** (grep décisif)
- **Horizon** : Horizon-Promesse. **Sévérité** : **medium** (#02) / **medium** (#01) / **low** (#03). **Confiance** :
  3/3 (panel + grep). **Statut** : **CONFIRMÉ** (write-only prouvé) ; effet runtime = recette.
- **F-PROM-02 (medium)** : `cleanup_orphans` + `cleanup_empty_folders` (`parametres.js:151-152`) sont **echo-persistés
  seulement** — grep : **0 consommateur réel** dans `cinesort/`, **absents de la dataclass `Config`** (core.py) et de
  `build_cfg_from_settings`. Cocher « Nettoyer les fichiers orphelins » + « Supprimer les dossiers vides après apply »
  → **rien n'est supprimé** (les frères câblés `move_empty_folders_enabled`/`cleanup_residual_folders_enabled`, eux,
  fonctionnent). Repro : cocher+sauver+apply sur lib avec orphelins/dossiers vides → inaction (non destructif).
- **F-PROM-01 (medium)** : `auto_approve_enabled` (`parametres.js:105`) inerte : `get_auto_approved_summary`
  (run_read_support.py:177) a **0 appelant UI** ; le bouton « Approuver les sûrs » utilise **uniquement**
  `_state.autoThreshold`, jamais `auto_approve_enabled`. Cocher « Approbation automatique » → aucun auto-approve
  post-scan ; le bouton manuel applique le seuil même toggle OFF.
- **F-PROM-03 (low)** : sélecteur « Séparateur » (`parametres.js:128`) inerte en preset **default** : `{sep}` n'est
  émis que si le template le contient littéralement, or aucun des 5 presets ni le défaut `{title} ({year})` ne le
  référence → passer Espace→Point laisse `Inception (2010)`. Jumeau : `subtitle_lang_priority` (phantom ; la vraie
  détection utilise la clé distincte `subtitle_expected_languages`).

### F-H3-01/02 — Apply : collision 8 Mo + sidecar TV avalé en silence — **CONFIRMÉ** (panel, recettes)
- **F-H3-01 (low)** : `apply_core.py:340` `files_identical_quick` = taille + SHA1 des **8 premiers + 8 derniers Mo**
  (full uniquement si < 16 Mo). Deux vidéos distinctes de même taille à en-tête+pied identiques → déclarées
  `duplicate_identical`, source **déplacée** (réversible, bucket `_review/_duplicates_identical`, pas de suppression
  dure ; collision quasi-impossible sur de vraies vidéos). Compromis perf documenté.
- **F-H3-02 (info/low)** : `apply_core.py:2263-2264` `except (PermissionError, OSError): pass` dans `apply_tv_episode`
  avale l'échec de déplacement d'un **sidecar** (.srt verrouillé) → le .mkv est déplacé+journalisé, le .srt reste
  orphelin à la source, et le run rapporte « succès » **sans aucun WARN** (`res.moves += 1` quand même). Le frère
  `apply_collection_item` remonte les échecs via status. Fix : `log("WARN")` + `res.error_messages.append`.

## PISTE C — vérifications runtime (majoritairement SAINES, transparence)
- **F-VIS-01 — invariant couleurs tiers : RESPECTÉ (concern réfuté)**. `getComputedStyle` sur les 5 thèmes
  (studio/cinema/luxe/neon/aaa) : `--tier-platinum`/`-solid`=rgb(229,228,226)=#E5E4E2, gold=#FFD700, silver=#C0C0C0,
  bronze=#CD7F32 — **conformes partout**. La crainte mémoire « duplication `--tier-*` styles.css:2044 casse
  l'invariant » est **réfutée à l'exécution** : l'alias `var(--tier-X-solid, #hex)` résout bien le token canonique.
- **A11y baseline (correcte)** : 13 régions `aria-live=polite` (badges sidebar, section vue), landmarks `main`+`nav`
  présents, **skip-link** présent, `.v5-top-bar-theme-menu` **opaque** (rgb(18,15,10), R7-9 tient à l'exécution).
- **Reste Piste C à approfondir (per-vue)** : `aria-live` sur opérations async spécifiques (scroll-infini biblio,
  polling traitement, tabs lazy comparateur — l'infra globale existe, mais ces flux précis non encore testés en
  interaction) ; focus-trap/restore en modale ouverte ; double-apply au retry mid-error (F-H9, à reproduire).

## SYNTHÈSE PRIORISÉE (barème : atteignable + reproduit + perte-données/sécurité + chemin chaud)

**🔴 HIGH — à corriger en priorité (R8)**
1. **F-PERC-01/02/03 — l'analyse perceptuelle V2 mesure du VIDE** (loudness jamais mesurée ; crest/dynrange figés
   à 50 ; blur/blockiness=0 → score 95 « parfait » fabriqué). Chemin chaud (chaque film analysé), prouvé au vrai
   ffmpeg. Fix : `-v quiet`→`info` ; crest/dynrange par-canal ; `metadata=mode=print`.
2. **F-H7-01 — cache TMDb empoisonné par un `200 + results=[]`** → film non identifié 7 j. Fix : ne pas cacher
   (ou TTL court) une liste vide.
3. **F-DB-01 — busy_timeout NAS écrasé à 8000** (profil 30/60 s ignoré) → SQLITE_BUSY prématuré pendant migrations.

**🟠 MEDIUM**
- F-H6-01 (codec audio mal étiqueté, 113 films) · F-H4-01 (bitrate audio ≤10000 → bonus au lieu de malus) ·
  F-H5-01 (résidu `DD5 1` pollue la query TMDb) · F-DEAD-01 (Simulateur preset + Éditeur règles custom
  inatteignables) · F-SEC-01 (routes GET sans garde CSRF/auth/rate-limit ; `poster?force=1` CSRF cache-eviction) ·
  F-CONF-01 (`ffprobe_path` arbitraire exécuté par le perceptuel, refusé par get_tools_status) · F-PROM-02
  (toggles « nettoyer orphelins / supprimer dossiers vides » **fantômes**) · F-PROM-01 (« approbation automatique »
  inerte) · F-PERC-04 (batch perceptuel non annulable) · F-0.5-02 (bloat git 771 Mo).

**🟡 LOW/INFO**
- F-SEC-02 (`_allowed_origin` ignore le port) · F-CONF-02 (sibling ffmpeg non validé) · F-PROM-03 (sélecteur
  séparateur inerte en preset défaut + `subtitle_lang_priority` fantôme) · F-H3-01 (collision 8 Mo, move réversible)
  · F-H3-02 (sidecar TV avalé en silence) · F-H5-02 (windows_safe sans séparateur, intentionnel+testé) · F-H5-03
  (TV convention non-standard non détectée) · F-H7-02 (flag « vu » Jellyfin non re-tenté).

**Bilan** : ~20 trouvailles RÉELLES (3 HIGH, ~10 MEDIUM, ~8 LOW/INFO) ; **0/7 faux-positifs** sur les leurres
(3 vagues) ; chaque CONFIRMÉ porte une repro rejouable (gate falsifiable, vrai ffmpeg, corpus réel, Origin forgé,
fonctions pures). **Aucune correction appliquée** (R8 sur approbation).

## MATRICE DE COUVERTURE (examiné / NON examiné, explicite)

**Examiné (avec repro/agents)** : `rest_server.py` (GET/CSRF/CORS/rate-limit/static) · `poster_proxy.py` ·
`perceptual/audio_perceptual.py` + `video_analysis.py` + `ffmpeg_runner.py` + `perceptual_support.py` ·
`quality_score.py` (scoring/bitrate/tier) · `scene_parser.py`/`naming.py`/`title_helpers.py`/`core.py` (parsing/TV) ·
`tmdb_client.py` (cache) · `duplicate_compare.py` (audio) · `apply_core.py` (TV sidecar, collision 8 Mo) ·
`settings_support.py`/`tooling.py` (binaire) · `parametres.js` (toggles) · `app.js` (routage/code mort) ·
`themes.css`/`tokens.css`/`styles.css` (tiers runtime) · a11y baseline · `connection.py`/`pragma_profile.py`.

**NON encore examiné (vagues futures, ledger)** : **H8** balayage complet 27 vues × endpoints (contrats clés
lues↔produites) — seuls qij/quality (morts) + KPI traités · **H13** profilage perf/mémoire (scroll-infini 1000+
films), MAX_PATH/`\\?\`, NFC/NFD SMB, démarrage EXE onefile, packaging locales, **matrice couverture tests**, CI ·
**0.2** ingestion 314 **complète** (seuls quelques claims re-vérifiés) · **0.3** baseline de caractérisation ·
**H2** scripts de course réels (cancel/apply concurrent, token-swap) · **migrations** sur copie de vieille DB ·
**socle métamorphique étendu** (seul l'oracle audio-select fait ; reste identité/round-trip/monotonie/titre) ·
**Horizon-Promesse** au-delà des 3 toggles (dry-run, sous-titres, skip_tv, winner doublon).

## RECOUPEMENT R6 / R7 / 314 (anti-doublon)
- **Aucune trouvaille ne re-signale un fix R6/R7** (vérifié : F-* portent sur des zones distinctes). F-SEC-01 mentionne
  le param `force=1` ajouté en R7-8 mais l'expose sous un angle **nouveau** (CSRF cache-eviction sur GET non gardé),
  pas le bug R7-8 corrigé.
- **314 partiellement réconcilié** : sa note « perceptuel mort -v quiet » est **CONFIRMÉE et étendue** (F-PERC-01/02/03,
  désormais reproduite live, ce que le 314 n'avait pas fait) ; le « séparateur perdu » est confirmé sous un angle
  précis (F-PROM-03, inerte en preset défaut). Ingestion 314 **complète** reste à faire (vague future).
- **Index de dédoublonnage** : clé = `fichier:ligne ∪ signature-cause-racine` (à maintenir si vagues additionnelles).

---

## MATRICE DE COUVERTURE (examiné / non-examiné, explicite)

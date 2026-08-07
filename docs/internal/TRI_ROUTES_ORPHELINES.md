# Tri des méthodes de façade sans consommateur web

Livrable de la vague 3.1 du plan. **Aucun code n'a été modifié** : c'est un
verdict par entrée, à valider avant tout câblage ou retrait.

## Ce qui a été mesuré

`KNOWN_ORPHAN_METHODS` (`tests/test_contract_facades.py`) recense les méthodes de
façade qu'aucun `apiPost` du dashboard n'appelle. Le plan annonçait **53** entrées
(état 2026-07-08) ; la mesure du 2026-08-06 en trouve **60**. Le backend existe et
est testé — c'est l'interface qui manque.

| verdict | nombre | sens |
|---|---|---|
| **CÂBLER** | 42 | fonctionnalité utile, il manque l'entrée UI |
| **INTERNE** | 7 | appelée hors web (cron, job, autre façade) : absence normale |
| **RETIRER** | 9 | proposées au retrait — dont **une seule** survit à la réfutation |

## La passe de réfutation a invalidé 8 retraits sur 9

Retirer est irréversible ; câbler ne l'est pas. Chaque verdict RETIRER a donc été
soumis à un relecteur chargé de le **réfuter** — chercher un appelant, une trace,
une valeur produit — et non de le confirmer.

**Une seule proposition sur neuf a survécu.** C'est le rapport qui compte : sans
cette passe, huit méthodes auraient été supprimées sur un raisonnement qui ne
tenait pas.

- runtime.get_event_ts | RETIRER | Absence d'appelant PROUVEE par grep exhaustif (tout le depot, hors .git/node_modules/__pycache__) : 11 fichiers seulement, dont ses 2 sites de DEFINITION (cinesort/ui/api/cinesort_api.py:924, cinesort/ui/api/facades/runtime_facade.py:250), 3 artefacts d'INVENTAIRE sans valeur d'usage (docs/internal/BILAN_ITER5_2026-06-08.md:485 = table d'audit auth/rate-limit, matrices m1/m2 verif_totale, tests/snapshots/facade_methods_v77.json:123) et 4 tests qui ne font que GELER la surface (tests/test_contract_facades.py:111, tests/test_phase4_aide_endpoints.py:422 et :501, tests/test_cinesort_api_misc.py:27) — preuve circulaire, ecartee. Le seul pseudo-appelant, tests/manual/pywebview_api_mock.js:401, renvoie un NOMBRE nu (`Date.now()/1000`) la ou l'API renvoie {ok,last_event_ts,last_settings_ts} : stub perime d'une API top-level disparue, et ce mock a de toute facon un Proxy fallback ligne 405. ZERO occurrence dans web/, scripts/, tools/, app.py, tests/e2e. Supersession totale et INCONDITIONNELLE : `_last_event_ts` et `_last_settings_ts` sont initialises a time.time() des le constructeur (cinesort/ui/api/cinesort_api.py:232-233), donc les gardes `is not None` de /api/health (cinesort/infra/rest_server.py:1137 et :1140) sont toujours vraies et le payload health porte TOUJOURS les deux champs, plus version et active_run_id. Sa raison d'etre est morte : la docstring dit « utilise par le desktop (parite dashboard) » et docs/parity-report.md:235 (P1 item 6) la reclamait pour le front desktop `web/` — ce front n'existe plus (web/ ne contient que dashboard/, shared/, splash.html) et pywebview charge desormais le dashboard en HTTP local (app.py:757-762). Jamais annoncee dans le CHANGELOG (contrairement a runtime.get_tools_status, CHANGELOG.md:1178) : aucun contrat public a casser. NUANCE a corriger dans le verdict d'origine : `checkEventChanged` (web/dashboard/core/state.js:216) n'est appele NULLE PART et /api/health n'est fetche qu'une fois a la connexion (web/dashboard/core/api.js:822) — le front ne consomme donc ni l'un ni l'autre ; la conclusion tient sur les autres appuis, pas sur celui-la. Deux points a tracer au retrait : (a) `_get_event_ts_impl` n'est atteint que par cette methode de facade — le supprimer aussi, sinon l'inscrire dans _IMPLS_DELIBEREMENT_NON_EXPOSES (tests/test_facade_coverage_no_orphan_impl_v77.py:43) ; (b) apres retrait, la seule source de last_event_ts devient /api/health, qui est NON authentifie (docs/internal/BILAN_ITER5_2026-06-08.md:405) et bind sur 0.0.0.0 quand rest_api_enabled=True (app.py:274-275).

> Les huit autres restent listées plus bas sous « proposées au retrait », **à
> titre indicatif seulement** : leur retrait n'est **pas** recommandé en l'état.

## Ce que ce document ne dit pas

- **Il ne hiérarchise pas les 42 « câbler ».** Certaines relèvent d'un écran
  entier à concevoir, d'autres d'un bouton à brancher sur un patron déjà établi
  (le câblage de `/doublons` sert de modèle : entrée `NAV_ITEMS`, libellé dans
  les **deux** locales, alias id→route, mapping inverse, fil d'Ariane,
  `registerRoute`, vue exportant `init`/`unmount`).
- **Il ne remplace pas le cliquet existant.** `test_contract_facades.py` interdit
  déjà toute *nouvelle* orpheline, et fait rougir si l'on câble une méthode sans
  retirer son entrée : la liste ne peut que rétrécir. Ce document dit dans quel
  sens la faire rétrécir, pas comment.
- **Il n'a pas été vérifié en exécutant l'application.** Les verdicts reposent
  sur la lecture du code et la recherche d'appelants, pas sur un essai réel.

## A CABLER

### `integrations.get_jellyfin_sync_report`

Impl vivante et complete (cinesort/ui/api/cinesort_api.py:1363 : rapport matched/missing_in_jellyfin/ghost_in_jellyfin/metadata_mismatch, testee dans tests/test_jellyfin_validation.py) et docs/TROUBLESHOOTING.md:154 la donne comme LA solution utilisateur (« Jellyfin -> Verifier la coherence ») alors que la vue jellyfin.js qui portait ce bouton a ete purgee ; aucun appelant hors web dans cinesort/ ni app.py.

### `integrations.get_plex_sync_report`

Symetrique exact du rapport Jellyfin (cinesort/ui/api/cinesort_api.py:1518, reutilise build_sync_report ; couvert par tests/test_cinesort_api_plex.py), la section Plex existe deja dans l'UI avec URL/token/test de connexion (web/dashboard/views/parametres.js:185-194) : il ne manque que l'entree « Verifier la coherence » ; zero appelant non-web.

### `integrations.refresh_jellyfin_library_now`

La docstring de l'implementation dit explicitement que c'est un geste UI (« l'utilisateur a explicitement clique le bouton », cinesort/ui/api/apply_support.py:2719-2730) et qu'elle se distingue du chemin interne post-apply _trigger_jellyfin_refresh, lequel est bien cable via le toggle « Refresh auto apres apply » (web/dashboard/views/parametres.js:182) — donc pas INTERNE, juste sans bouton (tests/test_refresh_library_now.py couvre le backend).

### `integrations.refresh_plex_library_now`

Meme cas que Jellyfin : fonction a la demande, ignorant dry_run et le toggle, avec ses propres gardes url/token/library_id (cinesort/ui/api/apply_support.py:2746-2767) ; l'automatisme post-apply passe par _trigger_plex_refresh (apply_support.py:2700-2716) et le toggle existe en UI (parametres.js:194), donc seul le bouton manuel manque.

### `integrations.request_radarr_upgrade`

Endpoint fonctionnel qui declenche MoviesSearch cote Radarr (cinesort/ui/api/cinesort_api.py:1660-1678, tests/test_cinesort_api_radarr.py), alimente par le champ upgrade_candidates de _get_radarr_status_impl (cinesort_api.py:1657) qui n'est lui non plus jamais appele (web/dashboard/core/cache.js:25 ne fait que whitelister le nom pour le cache) : a cabler avec la liste des candidats dans la section Radarr existante (parametres.js:196-203).

### `integrations.test_email_report`

Le manque est deja identifie comme dette produit P1 (docs/parity-report.md:116 « Bouton 'Tester l'envoi email' manquant (endpoint test_email_report exists, UI bouton absent) »), la section SMTP complete est en UI (parametres.js:228-237), et cinesort_api.py:1337-1352 rejoue le refus cleartext uniquement pour remonter le motif AU BOUTON « Tester l'envoi » (issue #563) — le backend est ecrit pour une UI qui n'existe pas encore.

### `library.clear_field_lock`

Aucun appelant hors web (library_facade.py:269 -> library_support.py:2375) ; c'est le seul moyen de LEVER un verrou pose (repo.clear_lock, library_support.py:2399) — le retirer rendrait les verrous irreversibles cote utilisateur, alors que le backend est idempotent et pret (removed=False non-erreur, library_support.py:2409).

### `library.get_library_podiums`

Aucun appelant hors web (library_facade.py:178 -> library_podiums_support.py:73) ; l'endpoint calcule les tops release groups / codecs / sources on-demand pour le dashboard (library_podiums_support.py:1-16) et le CSS .podium-grid/.podium-row existe toujours (web/dashboard/styles.css:845-889) sans aucun JS qui l'instancie.

### `library.get_library_timeline`

Aucun appelant hors web (library_facade.py:185 -> library_timeline_support.py:163) ; il produit l'histogramme des films ajoutes par mois avec source Jellyfin DateCreated + fallback mtime (library_timeline_support.py:1-16), fonctionnalite utile dont le CSS .timeline-bars/.timeline-bar-col reste orphelin (web/dashboard/styles.css:898-908).

### `library.get_scoring_rollup`

Aucun appelant hors web : les seules occurrences sont la facade (library_facade.py:89), le passe-plat god-class (cinesort_api.py:2154) et l'implementation (library_support.py:1549) ; l'agregation par franchise/director/decade/codec a une vraie valeur produit et son CSS orphelin subsiste (.qij-rollup, web/shared/components.css:9130), signe d'une vue supprimee et non d'un code sans usage.

### `library.list_field_locks`

Aucun appelant hors web (library_facade.py:280 -> library_support.py:2415) ; c'est la lecture prevue pour afficher les cadenas (docstring library_facade.py:281 « pour render cadenas UI »), le seul autre lecteur etant l'helper interne read-only library_actions_support.py:541/790 qui ne remplace pas l'affichage.

### `library.set_field_lock`

Aucun appelant hors web (seule definition : library_facade.py:250 -> library_support.py:2312) et c'est l'UNIQUE chemin d'ecriture vers FieldLocksRepository.set_lock (library_support.py:2351), donc sans cablage UI aucun verrou ne peut jamais etre cree et la barriere anti-ecrasement merge_metadata (library_actions_support.py:793) tourne toujours sur un ensemble vide.

### `quality.analyze_quality_batch`

Aucun appelant de production (seulement des tests, ex. tests/test_quality_score.py:437) et fonctionnalite non couverte par quality/recompute_all_scores : elle sait analyser une SELECTION ou un scope « validated » (cinesort/ui/api/quality_support.py:216-224), chemin dont l'ancienne vue qij.js etait le consommateur avant sa purge (cf. commentaire cinesort/ui/api/quality_support.py:80).

### `quality.export_shareable_profile`

Fonctionnalite produit reelle et sans equivalent cable — export communautaire avec metadata name/author/description et filename_suggestion « *.cinesort.json » (cinesort/ui/api/cinesort_api.py:2466-2508) — aucun appelant hors web et zero occurrence de « shareable » dans web/dashboard/**/*.js.

### `quality.get_calibration_report`

L'UI collecte deja les feedbacks (web/dashboard/components/film-detail.js:927) et PROMET a l'utilisateur que « votre feedback alimente le rapport de calibration » (film-detail.js:551), mais l'agregation de biais + suggestion de poids (cinesort/ui/api/cinesort_api.py:2655-2690) n'est affichee nulle part : il manque uniquement l'ecran.

### `quality.get_custom_rules_catalog`

L'impl expose fields/operators/actions explicitement « pour le builder UI (G6) » (cinesort/ui/api/cinesort_api.py:1946-1955) et les regles custom sont bel et bien appliquees au scoring (cinesort/domain/quality_score.py:2504), or « custom_rules » n'apparait dans aucun fichier de web/dashboard : le builder n'a jamais ete construit.

### `quality.get_custom_rules_templates`

Les 3 templates starter (cinesort/ui/api/cinesort_api.py:1942-1945) sont le point d'entree pedagogique du meme builder de regles absent de l'UI ; aucun appelant hors web dans cinesort/ ni app.py.

### `quality.get_quality_profile`

Seule lecture du profil actif faisant autorite en DB, avec profile_version, is_active et surtout les « toggles » (cinesort/ui/api/quality_profile_support.py:16-27 ; toggles definis en cinesort/domain/quality_score.py:123) — or « toggles » n'apparait dans aucun JS de web/dashboard : ces bascules de scoring sont aujourd'hui invisibles et inaccessibles.

### `quality.import_shareable_profile`

Contrepartie de l'export communautaire, avec validation de schema, extraction de metadata et activation optionnelle (cinesort/ui/api/cinesort_api.py:2509-2568) ; aucun appelant hors web (la seule mention externe est un commentaire de cinesort/domain/profile_exchange.py:161) et aucun bouton d'import dans web/dashboard.

### `quality.reset_quality_profile`

Le bouton « Réinitialiser » du panneau Profils est purement client-side et recopie les defauts en JS (web/dashboard/views/parametres.js:3303-3309, avec la mise en garde de derive en parametres.js:505) alors que le backend detient la reference default_quality_profile() (cinesort/ui/api/quality_profile_support.py:95-100) : cabler ce bouton supprime la duplication des seuils.

### `quality.save_custom_quality_preset`

Volet « sauvegarder ce preset » du simulateur G5 : il slugifie, valide et ACTIVE le profil en base (cinesort/ui/api/quality_simulator_support.py:113-140), ce que settings/save_profile ne fait pas (celui-ci ecrit dans settings.custom_quality_profiles sans activer, cinesort/ui/api/profiles_support_crud.py:227) ; a cabler avec le simulateur, en tranchant au passage la coexistence des deux stockages.

### `quality.save_quality_profile`

Unique chemin d'ecriture qui valide et persiste les regles custom (cinesort/ui/api/quality_profile_support.py:74-84) et les toggles du profil actif — le settings/save_profile cable par l'UI ne transmet ni l'un ni l'autre (payload construit en web/dashboard/views/parametres.js:1638-1651) : sans elle, aucune regle custom n'est creable depuis l'application.

### `quality.simulate_quality_preset`

L'UI ORDONNE deja d'utiliser cette fonction sans l'offrir — « utilisez la simulation avant d'activer » (web/dashboard/views/parametres.js:1309) — alors que le moteur avant/apres complet existe, avec cache et top_winners/top_losers (cinesort/ui/api/quality_simulator_support.py:53-110) et aucun appelant hors web.

### `quality.validate_custom_rules`

Validation sans persistance prevue pour le builder de regles (cinesort/ui/api/cinesort_api.py:1957-1961), indispensable des lors que les regles custom modifient reellement score et tier (cinesort/domain/quality_score.py:2504) ; hors web, seul l'homonyme domaine validate_rules est importe (cinesort/ui/api/quality_profile_support.py:12), pas la methode de facade.

### `run.check_duplicates_fusion`

Aucun appelant hors web ; l'endpoint est gate par CINESORT_FUSION_DOUBLONS et renvoie un stub `{ok, enabled:false, pairs:[]}` si le flag est off (cinesort/ui/api/run_flow_support.py:2520-2522), et le module d'orchestration dit explicitement que le flag pilote « l'exposition de l'endpoint check_duplicates_fusion cote UI » (cinesort/app/duplicate_pipeline.py:12) : le cablage prevu (a cote du `run/check_duplicates` deja pose en web/dashboard/views/doublons.js:1295) n'a jamais ete livre.

### `run.export_apply_audit`

Aucun appelant hors web ; lit le journal JSONL d'audit ecrit a chaque apply et le rend en json/jsonl/csv (cinesort/ui/api/apply_support.py:3273-3320, journal produit par cinesort/app/apply_audit.py:49) — le fichier est deja ecrit sur disque a chaque apply, seul l'acces utilisateur manque.

### `run.export_run_nfo`

Aucun appelant hors web ; genere de vrais .nfo Kodi/Jellyfin par film (cinesort/ui/api/cinesort_api.py:2295 -> cinesort/app/export_support.py:362) avec `dry_run` et `overwrite`, et le produit s'integre deja a Jellyfin — meme cause d'orphelinat que ci-dessus (tests/test_contract_facades.py:59-62,69, vue morte purgee), pas une perte de valeur.

### `run.export_run_report`

Zero appelant hors web (seule cinesort/ui/api/cinesort_api.py:2271 delegue vers dashboard_support.export_run_report:1385) ; la fonction produit json/csv/html avec `content` pret pour un download Blob (dashboard_support.py:1412-1422 : « l'UI (#/logs) telecharge via Blob et exige content ») — c'est la vue #/logs supprimee en Phase 5 qui l'a orpheline (tests/test_contract_facades.py:59-62,68), la valeur produit est intacte.

### `run.get_cleanup_residual_preview`

Aucun appelant hors web (cinesort/ui/api/run_read_support.py:209) ; il previsualise exactement l'effet des reglages deja exposes a l'utilisateur (web/dashboard/views/parametres.js:158-160 : dossiers vides, _Vide, fichiers residuels .nfo/images/sous-titres), or ces options s'appliquent aujourd'hui sans aucun apercu prealable — regle n3 du CLAUDE.md (action destructive) plaide pour le cabler.

### `run.import_watchlist`

Aucun appelant hors web, et le mot « watchlist » n'apparait NULLE PART dans web/ : le parseur Letterboxd/IMDb + le comparateur fuzzy avec la bibliotheque locale (cinesort/ui/api/cinesort_api.py:1434-1454 -> cinesort/app/watchlist.py:45,63,86) sont entierement ecrits et testes mais 100 % inatteignables — fonctionnalite complete sans porte d'entree.

### `run.list_apply_history`

Aucun appelant hors web ; retourne les 20 derniers batches annotes du mode atomique (cinesort/ui/api/apply_support.py:1277-1296) alors que la vue Historique ne lit que le DERNIER batch (cinesort/ui/api/history_support.py:562-566 `_last_batch`, appelee par web/dashboard/views/historique.js:930) : c'est le selecteur de batch qui manque a l'UI, pas le backend.

### `run.list_pending_runs`

Aucun appelant hors web (cinesort/ui/api/run_control_support.py:149) ; l'UI cable deja pause/resume/save_for_later (web/dashboard/views/traitement.js:1875, 1889, 1903) mais rien ne LISTE les runs PAUSED/SAVED/AWAITING_VALIDATION — un run mis de cote est donc actuellement irrecuperable depuis l'interface, c'est un trou fonctionnel net.

### `runtime.get_log_paths`

Fonctionnalite utile sans entree UI : l'ecran Aide ne cable que le jumeau `runtime/open_logs_folder` (web/dashboard/views/aide.js:894), or celui-ci est REFUSE des qu'on est sur un client REST distant (cinesort_api.py:2966-2975 `is_remote_request()`) — afficher/copier les chemins retournes par `_get_log_paths_impl` (cinesort_api.py:2953-2961) est le seul acces au support pour un utilisateur LAN ; aucun appelant interne.

### `runtime.get_probe`

Aucun appelant hors facade (seul cinesort_api.py:1908 -> probe_support.py:382), et l'UI n'affiche aujourd'hui que le resume PLAT `probe.detected.*` issu de get_film_full (web/dashboard/components/film-detail.js:447-467, commentaire L449-451 : « pas dans probe.video/probe.audio/probe.subtitles ») : la probe normalisee par piste (audio/sous-titres) manque donc reellement a l'onglet detail.

### `runtime.purge_probe_cache`

La docstring prescrit elle-meme l'emplacement UI manquant (cinesort/ui/api/facades/runtime_facade.py:230-238 : « A exposer sous Parametres > Outils "Purger le cache probe" »), l'impl est complete et renvoie un compte exploitable (cinesort_api.py:1873-1901, `entries_deleted`), aucun appelant interne — a cabler avec la confirmation renforcee due aux actions destructives.

### `runtime.reset_incremental_cache`

La docstring nomme un bouton « Forcer le rescan complet » (runtime_facade.py:258-262) et docs/parity-report.md:185 le pretend cable dans home.js, mais un grep sur web/ ne trouve ZERO occurrence : le bouton n'existe plus alors que l'impl 3 tables est vivante (cinesort_api.py:1098-1150) et sans appelant interne — l'entree UI manque bel et bien.

### `runtime.run_nas_benchmark`

Le moteur existe et est isole (cinesort/infra/db/nas_validation.py:195), son unique point d'entree est l'API (cinesort_api.py:1229) et aucun script/CLI ne l'appelle (grep vide sur scripts/, tools/, app.py) : diagnostic non destructif (DROP TABLE en finally) directement utile aux bibliotheques sur NAS, a exposer dans Aide/Diagnostic.

### `runtime.set_probe_tool_paths`

Non seulement il n'a aucun appelant, mais l'UI ecrit aujourd'hui `ffprobe_path`/`mediainfo_path` par le formulaire generique (web/dashboard/views/parametres.js:71-73 -> save_settings -> settings_support.py:1565-1566, simple `.strip()`), ce qui CONTOURNE la whitelist de binaires appliquee uniquement ici (probe_support.py:191-208 via validate_tool_path) — cabler ces deux champs sur cet endpoint ferme le trou decrit dans docs/internal/AUDIT_RELECTURE_2026-06-10.md:255.

### `settings.get_naming_presets`

L'UI code EN DUR les 5 presets dans parametres.js:117-119 avec des libelles qui ont deja derive du backend (« Defaut/Qualite/Custom » cote JS contre « Standard/Qualite/Personnalise » dans cinesort/domain/naming.py:163-193), et l'endpoint renvoie en plus movie_template/tv_template (cinesort/ui/api/cinesort_api.py:1708-1718) que l'utilisateur ne peut pas voir avant de choisir, alors que save_settings reecrit ses templates a sa place (cinesort/ui/api/settings_support.py:1467-1473) ; aucun appelant non-web (seuls tests/test_naming.py:667 et les codemods scripts/migrate_js_to_facades_84.py).

### `settings.get_user_data_size`

Methode ecrite explicitement « pour affichage UI Danger Zone » (cinesort/ui/api/facades/settings_facade.py:11, cinesort/ui/api/reset_support.py:263) et la Danger Zone existe bel et bien (web/dashboard/views/parametres.js:2048-2090) mais n'affiche ni taille ni nombre d'items, alors que la regle projet impose d'annoncer la consequence d'une action destructive ; le backend renvoie size_mb + items (cinesort/ui/api/reset_support.py:277-280) et n'est appele par aucun code non-web.

### `settings.preview_naming_template`

Les deux champs de template sont de la saisie libre sans aucun retour (web/dashboard/views/parametres.js:122-123) alors que l'endpoint valide le template et retourne les erreurs plus le rendu sur le contexte Inception (cinesort/ui/api/cinesort_api.py:1720-1759 via validate_template) ; le seul appelant UI historique (web/views/settings.js) a ete supprime en PR #257, pas remplace — c'est une regression d'UI, pas du code mort, et le bug de sample_row_id a deja ete purge (#460, commentaire cinesort_api.py:1734-1751) donc le chemin restant est sain.

### `settings.reset_all_user_data`

Aucun des 12 scopes de la modale de reset ne couvre son perimetre (web/dashboard/views/parametres.js:2033-2046 : settings par categorie, ou __database__ seul) alors que cette methode efface aussi runs/, cache TMDb et rapports perceptuels en preservant logs/ et en creant un ZIP de securite (cinesort/ui/api/reset_support.py:198-256) : elle n'est donc ni remplacee ni redondante, il manque une entree « remise a zero usine » — a cabler en notant que le jeton attendu est « RESET » (reset_support.py:210) et non le « CONFIRMER » de la modale actuelle (parametres.js:2176).

## INTERNE — absence normale

### `library.get_film_history`

Appelant non-web confirme : cinesort/ui/api/film_support.py:510 appelle film_history_support.get_film_history(api, fid) a l'interieur de get_film_full et injecte le resultat dans la cle history, que l'UI rend deja dans l'onglet Historique du modal film (web/dashboard/components/film-detail.js:561) — l'endpoint dedie est donc normalement absent de l'UI, la donnee arrivant par library/get_film_full (film-detail.js:107).

### `quality.analyze_perceptual_batch`

La variante synchrone est appelee par l'orchestration interne (cinesort/ui/api/run_flow_support.py:615 et cinesort/ui/api/quality_audit_support.py:387 via perceptual_support.analyze_perceptual_batch) et l'UI l'a deliberement remplacee par la variante asynchrone (commentaire web/dashboard/views/bibliotheque.js:1641 : « Avant : appel BLOQUANT quality/analyze_perceptual_batch -> requete suspendue », desormais quality/queue_perceptual_batch).

### `quality.compare_perceptual`

L'appel synchrone est fait par le worker de fond de la file perceptuelle (cinesort/ui/api/perceptual_support.py:1197, dans le thread lance par queue_perceptual_analyses) ; l'UI passe par cette file et par get_perceptual_compare_frames, tous deux deja cables dans web/dashboard/components/duplicate-comparator-modal.js.

### `quality.get_quality_report`

Deux appelants de production hors web utilisent deja la methode de facade : cinesort/ui/api/quality_support.py:99 (boucle interne de analyze_quality_batch) et cinesort/ui/api/quality_audit_support.py:339 (job recompute_all_scores) ; cote UI le rapport arrive embarque dans library/get_film_full (cinesort/ui/api/film_support.py:498, consomme en web/dashboard/components/film-detail.js:107).

### `run.cleanup_old_runs`

Appelee par le cron de retention au boot : cinesort/app/retention_cleanup.py:48 fait `api.run.cleanup_old_runs(retention_days)` dans un thread daemon (docstring facade run_facade.py:251-253 : « automatiquement au boot par le cron retention_cleanup »), donc son absence d'UI est normale.

### `run.purge_quarantine_bucket`

Appelee par le cron TTL quarantaine : cinesort/app/quarantine_ttl.py:797 fait `api.run.purge_quarantine_bucket(ttl_days, dry_run=False)` toutes les 24 h ; la variante utilisateur EST deja cablee (web/dashboard/views/parametres.js:2650 -> `run/purge_quarantine_bucket_all`), c'est la purge par age qui est machine-only.

### `runtime.check_for_updates`

Son impl est deja appelee par du code non-web : cinesort/ui/api/cinesort_api.py:1045 (`_get_update_info_impl` delegue a `_check_for_updates_impl` quand force_refresh=True), et le bouton « Verifier maintenant » passe deja par cette porte unique (web/dashboard/views/parametres.js:2714 `apiPost("runtime/get_update_info", {force_refresh:true})`, commentaire explicite parametres.js:2698-2700) — l'endpoint direct n'a donc pas vocation a apparaitre dans l'UI.

## Proposees au retrait (8 sur 9 refutees)

### `quality.apply_quality_preset`

Strictement supersede par set_active_profile, qui resout deja un preset_id (cinesort/ui/api/profiles_support_crud.py:351-353) puis fait le meme api._save_active_quality_profile avec en plus la persistance settings et le rollback, et qui est le seul appele par l'UI (web/dashboard/views/parametres.js:1601) — a la suppression, deplacer l'effet de bord _sim_clear() de cinesort/ui/api/cinesort_api.py:1923 dans set_active_profile.

### `quality.export_quality_profile`

Marquee « historique » par le code qui la remplace (cinesort/ui/api/cinesort_api.py:2478) : elle ne renvoie que le JSON brut du profil actif (cinesort/ui/api/quality_profile_support.py:104-114), contenu deja couvert par export_shareable_profile (meme profil + metadata) et par quality/export_recyclarr_yaml qui est, lui, deja dans l'UI (web/dashboard/views/parametres.js:3360).

### `quality.get_profiles`

Doublon pur de SettingsFacade.get_profiles (cinesort/ui/api/facades/settings_facade.py:88, meme profiles_support.get_profiles), l'UI n'appelant que la version settings (web/dashboard/views/parametres.js:1550) ; la double exposition est deja figee comme anomalie dans tests/test_contract_facades.py:146.

### `quality.get_quality_presets`

Le catalogue de presets est deja servi ET consomme par l'autre chemin : profiles_support_crud.get_profiles appelle list_quality_presets(include_profiles=True) (cinesort/ui/api/profiles_support_crud.py:180) et l'UI le lit via settings/get_profiles (web/dashboard/views/parametres.js:1550-1553), rendant cinesort/ui/api/quality_profile_support.py:30-39 redondant.

### `quality.import_quality_profile`

Alias strict sans comportement propre : le corps est `return save_quality_profile(api, profile_json)` (cinesort/ui/api/quality_profile_support.py:117-118) ; le cabler ajouterait un second endpoint identique a quality/save_quality_profile, et le cas d'usage « importer un fichier » est couvert par import_shareable_profile (cinesort/ui/api/cinesort_api.py:2520-2523).

### `quality.save_profile`

Doublon pur de SettingsFacade.save_profile (cinesort/ui/api/facades/settings_facade.py:95, meme profiles_support.save_profile), l'UI n'appelant que settings/save_profile (web/dashboard/views/parametres.js:1654) ; double exposition deja recensee en tests/test_contract_facades.py:147.

### `quality.set_active_profile`

Doublon pur de SettingsFacade.set_active_profile (cinesort/ui/api/facades/settings_facade.py:102, meme profiles_support.set_active_profile), l'UI n'appelant que settings/set_active_profile (web/dashboard/views/parametres.js:1601) ; double exposition deja recensee en tests/test_contract_facades.py:148.

### `runtime.get_event_ts`

Remplace : le meme `_last_event_ts` est deja servi dans le payload /api/health (cinesort/infra/rest_server.py:1135-1138) et c'est CETTE source que le front consomme (web/dashboard/core/state.js:213 « Compare le last_event_ts recu du health endpoint », `checkEventChanged`) ; l'endpoint dedie n'a aucun appelant, ni web ni interne (seuls cinesort_api.py:924 et runtime_facade.py:256 le mentionnent).

### `runtime.get_tools_status`

Alias mort : `_get_tools_status_impl` est un pass-through nu vers `_get_probe_tools_status_impl` (cinesort/ui/api/cinesort_api.py:1830-1832, commentaire « Compat endpoint kept for v7.0/v7.1 callers ») et la cible, elle, est deja pleinement cablee (web/dashboard/app.js:797, web/dashboard/views/parametres.js:1047, cache.js:26) — le cabler creerait un doublon d'UI, pas une fonction.

## Non classees

### `run.undo_by_row_preview`

Aucun appelant hors web — cinesort/ui/api/apply_support.py:1109 appelle la FONCTION support `build_undo_by_row_preview`, pas la methode de facade ; c'est l'apercu par film de l'undo selectif, mais son action jumelle a ete retiree de la facade le 2026-08-05 (run_facade.py:537-551 : `undo_selected_rows` atteignable sans modale destructive), donc ne le cabler qu'en livrant DANS LE MEME LOT la modale liste+consequence+delai 3 s et le retour de `undo_selected_rows` — sinon il previsualise une action injouable, l'apercu global etant deja cable (web/dashboard/views/traitement.js:1381).


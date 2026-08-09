# Audit Claude — 2026-08-09 — Couche transverse

**Modele** : Opus 5, effort de raisonnement max. **Niveau** : modere. **Ouverture de PR** : oui.

**Backlog mesure avant toute ouverture** : 7 PR + 8 issues = **15 elements ouverts**.
Tres en dessous du plafond de 150 de `.github/audit-prompt.md` — le budget applicable
est donc « au plus 3 PR, au plus 5 issues ». Consomme : **2 PR, 1 issue de synthese**.

> Ecart avec le repere du prompt (110 PR + 195 issues au 2026-08-03) : le backlog a
> ete massivement resorbe. Le chiffre du prompt est perime, celui-ci se remesure.

**Contrainte d'execution a connaitre pour les prochains runs** : le bac a sable de
l'audit n'autorise ni `python`, ni `node`, ni redirection hors du depot. Aucun test,
aucun `ruff`, aucun `lint-imports` n'a pu etre EXECUTE. Toutes les verifications
ci-dessous sont des lectures de code et des mesures `grep` — elles sont donc
reproductibles, mais la CI reste la premiere execution reelle des PR ouvertes.

---

## Resume executif

L'audit transverse classique (les 5 points du prompt) ressort **propre**. Les deux
findings qui restent viennent d'un angle que le prompt ne couvre pas : le **cycle de
vie des donnees** — ce que l'application garde apres que l'utilisateur a demande a
partir, et ce qu'elle detruit sans le lui demander.

| # | Severite | Persona | Finding | Suite |
|---|---|---|---|---|
| 1 | 3 BUG | SECURITY | `clearToken()` ne purgeait pas le cache d'instantanes : 24 h de bibliotheque restaient dans le navigateur apres la deconnexion. `clearCache()` existait, sans aucun appelant. | **PR #1020** |
| 2 | 3 BUG | RELIABILITY | `run.cleanup_old_runs` est la SEULE frontiere destructive sans `dry_run`. Un `POST /api/run/cleanup_old_runs` au corps vide detruit le journal d'undo de tous les runs > 90 j. | Issue de synthese |
| 3 | 1 STYLE | ARCHITECT | `_CACHEABLE` porte 8 cles legacy inatteignables (Pass 1 desactivee). L'une d'elles, `get_runs_summary`, n'a jamais ete une methode d'API. | Issue de synthese |
| 4 | 1 STYLE | UX | `reloadLocale()` est du code mort de production ; son unique appelant est un test qui verifie surtout qu'il est **exporte**. | Issue de synthese |
| 5 | 1 STYLE | ARCHITECT | Un `patch()` pose au site de DEFINITION dans `test_composite_score_toggle.py` : le mock ne s'applique pas. Sans consequence ici, mais c'est un mock decoratif. | Issue de synthese |

Rien de severite 4. Aucun secret expose, aucune violation d'architecture, aucun XSS.

---

## Les 5 points du prompt transverse

### 1) Fonctions > 100 L par ROI de refactor — SANS OBJET
Issue #215 **fermee le 2026-08-06**. Le prompt la decrit comme ouverte : a corriger
dans `.github/audit-prompt.md`.

### 2) Duplication desktop/dashboard — SANS OBJET
Confirme : `web/dashboard/` est le seul arbre JS. Ni `web/views/` ni `web/components/`.

### 3) Imports inter-couches interdits — 0 VIOLATION

```
grep -rnE "^\s*(from|import)\s+cinesort\.(app|infra|ui)" cinesort/domain/
  cinesort/domain/core.py:55        -> sous `if TYPE_CHECKING:`, deja dans ignore_imports
  cinesort/domain/_runners.py:84    -> FAUX POSITIF : la ligne est dans une DOCSTRING

grep -rnE "^\s*(from|import)\s+cinesort\.(app|ui)" cinesort/infra/    -> aucun
grep -rnE "^\s*(from|import)\s+cinesort\.ui"       cinesort/app/      -> aucun
```

Meme resultat sur les imports **indentes** (lazy). Le piege a signaler aux prochains
runs : `cinesort/domain/_runners.py:84` contient litteralement
`from cinesort.infra.subprocess_safety import tracked_run` — mais dans la docstring de
`tracked_run`, qui documente l'import que le Service Locator a justement remplace. Un
`grep` seul conclut a une violation ; il faut ouvrir le fichier.

### 4) Repository pattern — 0 MIXIN RESIDUEL

`grep -rn "class .*Mixin" cinesort/infra/db/` ne rend **rien**. Les 13 repositories
sont en place (`_base`, `_sql`, `anomaly`, `apply`, `decisions`, `field_locks`,
`film_modal`, `perceptual`, `probe`, `quality`, `run`, `scan`). Issue #85 fermee le
2026-05-17. Phase B8 close, confirme par mesure.

### 5) Pattern module-style pour les modules mockes — 1 CAS, SANS CONSEQUENCE

**88 cibles `patch("cinesort...")` distinctes** recensees dans `tests/`. Methode : pour
chaque cible `cinesort.<mod>.<Symbol>`, determiner si `<mod>` DEFINIT le symbole (le
patch peut alors rater les consommateurs qui l'ont lie par `from ... import`) ou s'il
le CONSOMME (le patch fonctionne, c'est l'idiome « patch where it's used »).

Les gros consommateurs sont sains, et l'intention est ecrite dans le code :

| Cible (occurrences) | Verdict | Pourquoi |
|---|---|---|
| `infra.probe.ProbeService` (31) | OK | les 4 tests exercent `runtime_probe_check.py:181`, import **lazy dans la fonction** -> resolu a l'appel |
| `ui.api.tmdb_support.TmdbClient` (21) | OK | site consommateur |
| `infra.plex_client.PlexClient` (14) | OK | `cinesort_api.py:24` et `apply_support.py:24` font `import ... as _plex_mod` |
| `infra.radarr_client.RadarrClient` (8) | OK | `cinesort_api.py:25` : `as _radarr_mod` |
| `infra.network_utils.get_local_ip` (4) | OK | `cinesort_api.py:23` : `as _network_utils_mod`, avec le commentaire ligne 940 qui dit pourquoi |
| `app.plan_support.replan_single_row` (4) | OK | `library_actions_support.py:729` : import lazy |

Seule exception, finding 5 ci-dessous.

---

## Findings

### 1 — [severite 3 / SECURITY / CWE-524] Le cache d'instantanes survivait a la deconnexion

**Corrige par la PR #1020.**

`apiPost` (`web/dashboard/core/api.js:600`) archive dans `localStorage` un instantane
des reponses de la whitelist `_CACHEABLE` (`core/cache.js:11`) pour servir de repli sur
5xx : `run/get_dashboard` (titres et chemins des films), `settings/get_settings`
(racine de bibliotheque, URL Jellyfin/Plex), `integrations/get_*_libraries`. TTL 24 h.

`clearCache()` (`cache.js:63`) a ete ecrit pour purger ces entrees. Mesure :

```
$ grep -rn "clearCache" web/ --include=*.js
web/dashboard/core/cache.js:63:export function clearCache() {
```

**Une seule occurrence dans tout `web/` : sa definition.** Aucun appelant.

Or `clearToken()` (`core/state.js:191`) est le chemin de deconnexion : commande
« Se deconnecter (token) » de la palette (`command-palette.js:70`) et 401 en mode web
(`api.js:411` / `:555`). Il retire le token, invoque les callbacks de cleanup, et
laisse les donnees.

Ce qui rend le cas concret plutot que theorique : le dashboard LAN existe pour etre
ouvert **depuis un autre appareil**. C'est precisement la que « se deconnecter » doit
tout emporter.

Pas d'exposition de secret : `_mask_secrets` (`settings_support.py:1397`) masque bien
les 7 champs de `_SECRET_FIELDS` — TMDb, Jellyfin, Plex, Radarr, OMDb, mot de passe
SMTP et `rest_api_token` — avant l'envoi. Verifie ligne a ligne. Ce sont les donnees de
bibliotheque qui restaient.

### 2 — [severite 3 / RELIABILITY] `run.cleanup_old_runs` : la seule purge sans `dry_run`

L'issue #991 a pose un invariant explicite, et l'a ecrit dans le code
(`run_facade.py:268`) :

> « `dry_run` vaut **True** par defaut, et c'est delibere : cette methode est exposee en
> REST. Avec un defaut a False, un appel au corps VIDE supprimait des fichiers de
> l'utilisateur. Sur une frontiere destructive, l'omission doit produire l'APERCU,
> jamais l'effet. »

Balayage des 172 methodes de facade a la recherche des frontieres destructives :

| Methode | Garde |
|---|---|
| `run.purge_quarantine_bucket` | `dry_run=True` |
| `run.purge_quarantine_bucket_all` | `dry_run=True` |
| `run.undo_last_apply` | `dry_run=True` |
| `run.export_run_nfo` | `dry_run=True` |
| `settings.reset_settings` | `dry_run=True` |
| `settings.reset_database` | `dry_run=True` |
| `quality.reset_quality_profile` | `dry_run=True` |
| `settings.reset_all_user_data` | `confirmation == "RESET"`, verifie effectif (`reset_support.py:210`) |
| `run.delete_run` | `run_id` obligatoire : un corps vide echoue |
| **`run.cleanup_old_runs`** | **aucune** |

`POST /api/run/cleanup_old_runs` avec `{}` prend `retention_days=90` et supprime tous
les runs plus vieux. `delete_run` (`repositories/run.py:553`) cascade sur `errors`,
`quality_reports`, `anomalies`, `perceptual_reports` et **`apply_batches` — donc
`apply_operations` par FK CASCADE. `apply_operations` est le journal d'undo.**

`{"retention_days": 1}` etend la purge a hier. Le clamp `max(1, ...)`
(`history_support.py:756`) empeche le zero, pas le un.

**Pourquoi pas de PR** : flipper le defaut desactiverait silencieusement le cron de
retention — `retention_cleanup.py:48` appelle `api.run.cleanup_old_runs(retention_days)`
sans `dry_run` — et casserait 5 appels dans `test_phase4_historique_endpoints.py`. Le
correctif est celui de #991 (defaut a True + les appelants qui veulent vraiment
supprimer le disent), mais il change la semantique d'un endpoint public et touche le
cron : c'est un arbitrage, hors du niveau « modere ».

### 3 — [severite 1 / ARCHITECT] 8 cles mortes dans `_CACHEABLE`

`core/cache.js:12-20` liste 8 methodes **sans prefixe de facade** : `get_dashboard`,
`get_global_stats`, `get_settings`, `get_probe_tools_status`, `get_runs_summary`,
`get_jellyfin_libraries`, `get_plex_libraries`, `get_radarr_status`.

Pass 1 est desactivee par defaut depuis la refonte 2026-05 (`rest_server.py:109`,
« Defaut (FINAL phase migration 2026-05) »). Ces chemins renvoient 410 Gone, et
`saveSnapshot` n'est appele que sur succes : les entrees sont inatteignables.

Detail : **`get_runs_summary` n'a jamais ete une methode d'API**. C'est une methode de
repository (`store.run.get_runs_summary`), appelee depuis `dashboard_support.py:1932`,
`export_support.py:178` et 6 autres sites — jamais exposee en REST.

Non retire par la PR #1020 : sous `CINESORT_REST_LEGACY_PASS1_ENABLED=1` (prevu pour
l'E2E natif et le debug), les chemins legacy redeviennent servis et le retrait ferait
perdre le repli hors ligne. Changement de comportement, meme etroit — hors « modere ».

### 4 — [severite 1 / UX] `reloadLocale()` : code mort de production

`core/i18n.js:305`. Unique appelant : `web/dashboard/tests/run_vague_l_tests.mjs:290`.
Ce test verifie d'abord `typeof mod.reloadLocale !== "function"` — c'est-a-dire, pour
l'essentiel, que le symbole est **exporte**.

Le contexte explique le vide : le selecteur de langue a ete **retire** en juillet
(`views/parametres.js:267`, arbitrage FR-only documente — les 9 vues principales sont en
francais en dur). `setLocale` n'a plus qu'un appelant, `app.js:705`, au boot.

Defaut annexe, sans portee tant que l'arbitrage FR-only tient : `setLocale` empoisonne
son cache pour la duree de la session. `_fetchLocale` renvoie `{}` quand ses 3 essais
echouent (`i18n.js:154`) ; le garde d'entree est `if (_state.messages[normalized] == null)`
(ligne 212), et `{} == null` est faux. Aucun nouveau `setLocale` ne retentera le fetch.
L'utilisateur bascule en anglais, `t()` retombe sur le francais, et rien ne le signale.
`reloadLocale()` est exactement la sortie de secours — sans appelant.

### 5 — [severite 1 / ARCHITECT] Un `patch()` pose au site de definition

`tests/test_composite_score_toggle.py:141, 147, 153, 159` :

```python
with mock.patch("cinesort.infra.log_context.normalize_log_level_setting", return_value="INFO"):
    payload = apply_settings_defaults({}, **_defaults_kwargs(Path(".")))
```

`apply_settings_defaults` vit dans `settings_support.py:991`, et ce module a lie le
symbole a l'import : `settings_support.py:31` fait
`from cinesort.infra.log_context import is_remote_request, normalize_log_level_setting`.
Patcher le module de DEFINITION ne remplace pas `settings_support.normalize_log_level_setting`.
**Le mock ne s'applique pas.**

Sans consequence ici : les 4 assertions portent sur `composite_score_version`, la vraie
fonction fait le travail, les tests sont justes. Mais le mock est decoratif — il donne
l'illusion d'une isolation qui n'existe pas. Le retirer, ou le poser sur
`cinesort.ui.api.settings_support.normalize_log_level_setting`.

---

## Verifications negatives — ne pas les re-instruire

Elles ont coute du temps ; les consigner evite de le repayer.

- **XSS / `innerHTML`** — l'invariant sur lequel repose le CSP (`rest_server.py:972` :
  « le risque XSS via `style=` reste theorique tant que cet invariant tient ») **tient**.
  ~140 `innerHTML` dans `web/dashboard/`. Les 6 fichiers qui n'appellent jamais
  `escapeHtml` (`app.js`, `demo-wizard.js`, `core/drop.js`, `toast.js`,
  `command-palette.js`, `scan-banner.js`) n'injectent que du HTML **statique** :
  `toast.js:178` et `command-palette.js:138` posent un squelette puis remplissent par
  `textContent`. `processing.js` (22 `innerHTML`, 4 `escapeHtml`) passe par l'alias
  local `_esc` (ligne 55), qui delegue a `escapeHtml`.
- **`escapeHtml` en contexte attribut** — `core/dom.js:10` echappe les 5 entites, **`"`
  et `'` comprises**. Les `data-row-id="${_esc(...)}"` sont donc surs.
- **Path traversal statique** — `_resolve_static_path` (`rest_server.py:867`) fait
  `(root / relative).resolve()` puis `resolved.relative_to(root)`, avec un `root`
  lui-meme `.resolve()` dans les 3 branches de `_resolve_locales_root`. `resolve()`
  suivant les liens, un symlink interne pointant dehors est attrape. Correct.
- **Appels JS vers un endpoint inexistant** — **0**. 105 endpoints litteraux extraits de
  `apiPost("...")` croises avec les 172 methodes des 6 facades : tous resolvent. Les 2
  appels dynamiques (`parametres.js:1048` et `:2399`) passent des noms construits
  (`runtime/recheck_probe_tools` / `runtime/get_probe_tools_status`), qui existent.
  `apiPost("open_path")` n'apparait plus que dans un **commentaire**
  (`film-detail.js:1302`) ; l'appel reel passe par le pont pywebview.
  L'inverse — endpoints sans appelant JS — reste suivi par l'issue #990, non re-instruit.
- **Secrets** — `_SECRET_FIELDS` couvre les 7 champs sensibles, `_mask_secrets` les
  masque et supprime les enveloppes `_orig_*`. Rien de sensible n'atteint le
  `localStorage`.
- **Migrations** — les 32 fichiers n'utilisent que `CREATE ... IF NOT EXISTS` et
  `ALTER TABLE ADD COLUMN`. Les seuls `CREATE TABLE` nus (021, 025) creent des tables
  `*_new` du pattern 12-etapes. `_IDEMPOTENT_RULES` (`migration_manager.py:40`) apparie
  chaque tolerance au type d'instruction qui peut legitimement la produire.
- **Pieges Python classiques** — 0 argument par defaut mutable, 0 `except:` nu, 0
  `== None` hors commentaire, sur l'ensemble de `cinesort/`.
- **`return {"ok": False}` nu** — 4 occurrences hors `_responses.py`
  (`probe_support.py:378`, `cinesort_api.py:2792/2807/2821`), contre la convention. Trop
  mineur pour une issue ; note ici.

---

## Statistiques

- Modules/zones audites : `cinesort/domain`, `cinesort/infra`, `cinesort/app`,
  `cinesort/ui/api` (+ 6 facades), `web/dashboard` (core, views, components),
  `cinesort/infra/db/migrations` (32), `tests/` (678 fichiers, inventaire des `patch()`).
- Findings retenus : **5** (2 de severite 3, 3 de severite 1).
- Self-critique — supprimes avant redaction : **7**
  - 3 imagines/faux positifs (`domain -> infra` en docstring ; `apiPost("open_path")` en
    commentaire ; `pywebview.api.get_token` en commentaire) ;
  - 2 deja mitiges (XSS `innerHTML` -> squelette + `textContent` ; path traversal ->
    `relative_to` sur root resolu) ;
  - 1 idiomatique (`payload.length` compare a un plafond d'octets : UTF-16 vs octets,
    ecart sans consequence sur un plafond de 2 Mo) ;
  - 1 sans plan proportionne (retrait des 8 cles `_CACHEABLE` : degrade en severite 1).
- PR ouvertes : **#1020** (correctif) + celle-ci (rapport).
- Issues ouvertes : 1 de synthese.
- Findings deja connus, non re-signales : endpoints orphelins (#990), lazy imports
  intra-`ui/api` (#779), fonctions > 100 L (#215, fermee).

## Tendance

Compare au dernier audit transverse (`2026-05-24-transverse.md`) : les 5 points du
prompt sont passes de « chantiers ouverts » a « propres ou fermes ». Les findings qui
restent ne viennent plus de la structure mais du **cycle de vie des donnees** — ce que
l'app garde apres qu'on lui a demande de partir (finding 1), ce qu'elle detruit sans le
demander (finding 2). C'est la ou pointer les prochains runs transverses.

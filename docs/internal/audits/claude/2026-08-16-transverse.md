# Audit Claude — 2026-08-16 — Couche transverse

**Modele** : Opus 5, effort de raisonnement max. **Niveau** : modere. **Ouverture de PR** : oui.

## Budget d'ouverture

Mesure au demarrage, par `gh` :

```
gh pr list    --state open --limit 300   ->  0 PR ouverte
gh issue list --state open --limit 400   -> 14 issues ouvertes
                                    SOMME =  14
```

Tres en dessous du plafond de 150 de `.github/audit-prompt.md`. Budget nominal :
au plus 3 PR, au plus 5 issues. **Consomme : 1 PR (celle-ci, documentaire) et
1 issue.** Le reste n'a pas ete depense — voir « Pourquoi aucune PR de code ».

> Le repere du prompt (110 PR + 195 issues au 2026-08-03) reste **perime**, comme
> le notait deja le rapport du 2026-08-09. Il se remesure, il ne se recopie pas.

## Contrainte d'execution — a lire avant d'interpreter ce rapport

Comme les runs du 2026-08-09 et du 2026-08-15, le bac a sable de cet audit
**refuse toute execution Python**. `python3 <fichier>`, `python3 -c`,
`python -m pytest`, `python -m venv`, `pip`, `uvx ruff@0.16.1` et
`lint-imports` ont tous ete refuses par la politique de permissions. `git`, `gh`
et la lecture de fichiers passent.

Consequences, ecrites pour que personne ne les deduise a tort :

- **tous les findings ci-dessous sont etablis par LECTURE et par `grep`**, pas
  par execution. Ils sont reproductibles — chaque affirmation porte son
  `fichier:ligne` — mais ils n'ont pas ete mesures a l'execution ;
- la regle du CLAUDE.md (« un correctif n'est prouve que si le test a ete vu
  ROUGE sans lui ») **ne peut pas etre honoree** dans ce runner. C'est la raison
  directe pour laquelle ce run n'ouvre aucune PR de code (cf. plus bas) ;
- les `id` du fichier de findings sont des **slugs lisibles** (`t16sav01`, ...),
  pas les prefixes `sha256(module+line+symbol+category)[:8]` du schema : je ne
  pouvais pas les calculer. Meme convention que le run du 2026-08-15.

C'est la **troisieme execution consecutive** dans cet etat. Si la capacite ne
revient pas, l'audit quotidien est structurellement cantonne au role de lecteur.

---

## Resume executif

Les 5 points transverses du prompt ressortent **propres**, comme au 2026-08-09 —
et l'un d'eux est desormais verrouille par un test de contrat (point 5).

Le finding du jour ne vient pas de la structure mais d'une **frontiere de
proprietaire** : plusieurs reglages sont ecrits par des routes DEDIEES, pendant
que l'ecran Parametres continue de re-POSTer l'instantane qu'il a fige a son
ouverture. Le garde ecrit exactement pour ce cas — « cle ABSENTE = silence, cle
presente et VIDE = demande » — **ne peut jamais s'y declencher**, parce que
`_LITERAL_DEFAULTS` garantit que la cle n'est JAMAIS absente du GET.

| # | Severite | Persona | Finding | Suite |
|---|---|---|---|---|
| 1 | 3 BUG | RELIABILITY | Le garde « cle absente = silence » est **inerte sur le seul ecran pour lequel il a ete ecrit**. 3 instances confirmees : profils qualite effaces, chemins d'outils probe effaces apres installation, workers de scan revertis. | Issue |
| 2 | 1 STYLE | ARCHITECT | L'inventaire d'endpoints du 2026-08-09 a ete etabli sur les seuls appels **litteraux**. Il y a 5 sites d'appel **dynamiques**. Aucun n'est casse — mais la methode ne les voyait pas. | Rapport |
| 3 | 1 STYLE | ARCHITECT | Le cliquet `UiApiPatchableImportTests` ne couvre que les cibles `cinesort.ui.api.*`. Les couches `app`/`infra`/`domain` restent tenues par la relecture. Verifiees a la main : saines. | Rapport |

Rien de severite 4. Aucun secret expose, aucune violation d'architecture, aucun
appel JS vers un endpoint inexistant.

---

## Les 5 points du prompt transverse

### 1) Fonctions > 100 L par ROI de refactor — SANS OBJET

Issue **#215 fermee le 2026-08-06**. Le prompt `.github/audit-prompt.md` la
decrit toujours comme OUVERTE (ligne 1484). Correction deja demandee par le
rapport du 2026-08-09, **toujours pas appliquee** au prompt.

### 2) Duplication desktop/dashboard — SANS OBJET

`web/dashboard/` est le seul arbre JS. Ni `web/views/` ni `web/components/` de
premier niveau. Confirme.

### 3) Imports inter-couches interdits — 0 VIOLATION

```
(from|import) cinesort.(app|infra|ui)  dans cinesort/domain/  -> 2 hits, 2 faux positifs
   cinesort/domain/core.py:55       -> sous `if TYPE_CHECKING:`, deja dans ignore_imports
   cinesort/domain/_runners.py:84   -> DANS UNE DOCSTRING (celle de `tracked_run`)
(from|import) cinesort.(app|ui)     dans cinesort/infra/      -> aucun
(from|import) cinesort.ui           dans cinesort/app/        -> aucun
```

Le piege de `_runners.py:84` est le meme qu'au run precedent : la ligne
`from cinesort.infra.subprocess_safety import tracked_run` existe litteralement,
dans la docstring qui documente l'import que le Service Locator a remplace. Un
`grep` seul conclut a une violation ; il faut ouvrir le fichier. **Consigne pour
la troisieme fois** — c'est le faux positif le plus couteux de ce point.

> `lint-imports` n'a PAS pu etre execute (cf. contrainte). Cette verification est
> une lecture des imports, pas un passage du contrat.

### 4) Repository pattern — 0 MIXIN SQL RESIDUEL

`_[A-Za-z]+Mixin` sur tout `cinesort/` rend **11 occurrences, aucune pertinente** :

- 8 sont des **docstrings** de `infra/db/repositories/*.py` qui documentent la
  suppression (« B8 CLOSE (2026-05, commit 482f3e6) : `_ScanMixin` et l'heritage
  MRO supprimes ») ;
- 3 sont `_PeerGuardMixin` dans `cinesort/infra/_http_utils.py:89` — un mixin de
  **connexion urllib3** pour le garde SSRF, sans rapport avec SQL.

Phase B8 close, issue #85 fermee. Confirme par mesure.

### 5) Pattern module-style pour les modules mockes — GARDE PAR LA CI, PERIMETRE PARTIEL

Nouveau depuis le 2026-08-09 : ce point n'est plus tenu par la relecture, il a un
**test de contrat**, `tests/test_architecture_invariants.py::UiApiPatchableImportTests`.
Il croise les cibles `patch("cinesort.ui.api.<module>.<symbole>")` trouvees dans
`tests/` avec les imports de SYMBOLE en tete de `cinesort/ui/api/**`, et gele
4 violations pre-existantes dans `_KNOWN_SYMBOL_IMPORTS`.

**Son perimetre s'arrete a `cinesort.ui.api`** — dans les deux sens : la regex
`_PATCH_TARGET_RE` n'accepte que les cibles `cinesort.ui.api.*`, et
`_collect_top_level_symbol_imports` ne parcourt que `_UI_API_DIR`. Le meme defaut
(« un test VERT QUI NE TESTE PLUS RIEN ») peut donc vivre dans `app/`, `infra/`
et `domain/` sans que rien ne le voie.

Verification a la main des cibles hors `ui/api`, par consommateur :

| Cible patchee | Consommateur | Verdict |
|---|---|---|
| `infra.probe.ProbeService` | `app/runtime_probe_check.py:181` | **OK** — import lazy DANS la fonction, et le commentaire ligne 177 dit pourquoi : « tests patchent `cinesort.infra.probe.ProbeService` au niveau du module source » |
| `app.plan_support.replan_single_row` | `ui/api/library_actions_support.py:767` | **OK** — import lazy dans la fonction |
| `app.plugin_hooks.dispatch_hook`, `app.email_report.*`, `app.watchlist.*`, `app.disk_space_check._row_estimated_size`, `app.move_reconciliation.sha1_quick`, `app.watcher.is_dir_accessible` | — | **OK** — les consommateurs importent un AUTRE symbole du meme module ; le patch porte sur l'attribut du module, resolu a l'appel |
| `infra.log_context.normalize_log_level_setting` | `ui/api/settings_support.py:32` | **KO** — deja signale, issue **#1022** finding 4. Non re-instruit. |

Aucune nouvelle violation. Le finding est donc que le **cliquet a un perimetre
plus etroit que le defaut qu'il garde** — pas qu'il y ait une regression.

---

## Finding 1 — [severite 3 / RELIABILITY] Le garde « cle absente = silence » est inerte sur l'ecran Parametres

C'est la totalite de la valeur de ce run. Le mecanisme est un **enchainement de
quatre faits**, chacun correct isolement.

### Fait 1 — le GET injecte TOUJOURS ces cles

`cinesort/ui/api/settings_support.py:1456` : `get_settings_payload` appelle
`apply_settings_defaults`, qui fait (ligne 1032) :

```python
for key, value in _LITERAL_DEFAULTS:
    payload.setdefault(key, list(value) if isinstance(value, list) else value)
```

`_LITERAL_DEFAULTS` (ligne 836) porte notamment :

```python
("custom_quality_profiles", []),      # ligne 840
("active_quality_profile_id", ""),    # ligne 841
("mediainfo_path", ""),               # ligne 858
("ffprobe_path", ""),                 # ligne 859
("scan_max_workers_mode", "auto"),    # ligne 867
("scan_max_workers_value", 1),        # ligne 868
```

`_mask_secrets` (ligne 1403) ne masque que les 7 champs de `_SECRET_FIELDS` et
retire les `_orig_*` : **ces six cles sortent intactes**, toujours presentes.

### Fait 2 — l'ecran fige ce payload a l'ouverture, et le re-POSTe EN BLOC

`web/dashboard/views/parametres.js:2522` : `_state.settings = res.data.data || res.data || {}`.
`_loadSettings()` n'est appele qu'a **trois** endroits — le montage (4225), apres
un reset (2739) et `_rechargerApresReset` (1808).

`parametres.js:2414` : `apiPost("settings/save_settings", { settings: _state.settings })`,
declenche par `_scheduleSave()` (debounce 500 ms) a **chaque champ modifie**, et
par `_flushPendingSave()` a la sortie de vue.

### Fait 3 — des routes DEDIEES ecrivent ces memes cles derriere l'ecran

| Route appelee par l'ecran | Ce que le backend ecrit dans `settings.json` | Ce que l'ecran met a jour |
|---|---|---|
| `settings/save_profile` (`parametres.js:2175`) | `custom_quality_profiles` (`profiles_support_crud.py:311`) | `_state.profilesList` via `_loadProfiles()` — **pas `_state.settings`** |
| `settings/set_active_profile` (`parametres.js:2119`) | `active_quality_profile_id` (`profiles_support_crud.py:435`) | `_state.activeProfileId` — **pas `_state.settings`** |
| `runtime/auto_install_probe_tools` (`parametres.js:3688`) | `ffprobe_path`, `mediainfo_path` (`probe_support.py:384-386`) | `_state.probeToolsStatus` — **pas `_state.settings`** |
| `settings/set_scan_max_workers` (`parametres.js:3565`) | `scan_max_workers_mode`, `scan_max_workers_value` (`settings_support.py:2736-2737`) | `_state.scanMaxWorkersState` — **pas `_state.settings`** |

Aucune de ces quatre routes n'a de champ de formulaire qui porterait sa valeur
dans `_state.settings` :

- `custom_quality_profiles` / `active_quality_profile_id` : **aucun champ** dans
  tout `parametres.js` (seule mention : un commentaire, ligne 2207) ;
- `scan_max_workers` : le champ declare est la cle **synthetique**
  `__scan_max_workers__` (ligne 320), pas les cles reelles ;
- `ffprobe_path` / `mediainfo_path` : ce sont bien des champs (lignes 78 et 80) —
  et c'est ce qui rend le cas pire, l'input affichant `""` tant que la page n'est
  pas rechargee.

### Fait 4 — le garde ne peut alors PAS se declencher

`_save_section_quality_profiles` (`settings_support.py:1825`, `:1833`) et
`_save_section_probe` (`settings_support.py:1587`) et
`_save_section_scan_max_workers` (`settings_support.py:1603`) portent tous les
trois la meme forme :

```python
if "custom_quality_profiles" in payload:
    out["custom_quality_profiles"] = ...
```

Le commentaire qui la justifie est explicite (`settings_support.py:1805`) :

> **CLE ABSENTE = SILENCE, PAS EFFACEMENT.** [...] C'etait grave : l'ecran
> Parametres fige les reglages a son ouverture, puis les re-POSTe EN BLOC a
> chaque champ modifie (sauvegarde differee). Un profil cree depuis cet ecran
> disparaissait donc a la frappe suivante, sous un « Sauvegarde a HH:MM:SS ».

Le diagnostic est **exact**. Le remede, lui, suppose que la cle puisse etre
absente — or le Fait 1 garantit qu'elle est **toujours** presente sur ce chemin.
Le garde protege les clients REST a charge utile partielle ; il ne protege pas
l'ecran pour lequel il a ete ecrit.

`save_settings` part pourtant bien de l'existant (`settings_support.py:2288` :
`to_save = dict(existing_settings)`), puis `_appliquer_les_sections` **ecrase**
avec les valeurs de la charge utile. C'est cet ecrasement qui repose la valeur
perimee.

### Les trois sequences, telles qu'un utilisateur les produit

1. **Un profil qualite cree disparait.** Ouvrir Parametres → « Sauvegarder sous… »
   un profil → toucher n'importe quel autre reglage → le prochain autosave POSTe
   `custom_quality_profiles` d'AVANT la creation → le profil est efface de
   `settings.json`, sous un « ✓ Sauvegardé à HH:MM:SS ».
2. **Une activation de profil se defait.** Meme sequence avec « Activer » :
   `active_quality_profile_id` revient a sa valeur d'ouverture de page.
3. **Les chemins d'outils installes sont effaces.** Ouvrir Parametres avec
   ffprobe/MediaInfo absents (les deux champs valent `""`) → « Installer
   automatiquement » → `probe_support.py:384-386` ecrit les chemins reels → toucher
   un reglage → l'autosave POSTe `ffprobe_path: ""`, que `_save_section_probe`
   lit comme « cle presente et VIDE = demande » → **les chemins sont effaces**.
   Et le meme scenario revertit `scan_max_workers_*`.

### Pourquoi les tests ne le voient pas

`tests/test_profil_qualite_survit_au_reset.py:185` :

```python
def test_le_profil_survit_a_plusieurs_sauvegardes_partielles_successives(self) -> None:
    """Le cas reel : l'ecran Parametres sauvegarde a chaque champ touche."""
    for champ, valeur in (("theme", "luxe"), ("locale", "en"), ("expert_mode", True)):
        self.api.settings.save_settings({champ: valeur})
```

La docstring annonce « le cas reel : l'ecran Parametres ». **Ce n'est pas la
forme que l'ecran envoie.** `parametres.js:2414` n'envoie jamais `{champ: valeur}` :
il envoie `{settings: <instantane complet>}`. Le test eprouve la charge utile
PARTIELLE — celle d'un client REST — pas celle de l'ecran qu'il nomme.

Le test voisin, `test_un_effacement_EXPLICITE_efface_quand_meme` (ligne 194),
part bien d'un `get_settings()` complet, mais il vide les cles **exprès** et
verifie que l'effacement a lieu : il documente le comportement qui rend le
defaut possible, il ne le detecte pas.

C'est le motif que le CLAUDE.md nomme deja — « UNE SONDE PEUT ETRE JUSTE ET SON
PERIMETRE FAUX », et « un correctif peut ETEINDRE une garde existante ». Ici le
correctif de la bibliotheque de profils (#1042) a **cree** la surface : avant
lui, aucune section ne reclamait ces deux cles, donc `to_save = dict(existing)`
les preservait par omission. Les rendre persistantes les a rendues ecrasables.

### Deux remedes possibles, et leurs risques

Je ne tranche pas — c'est justement ce qui manque pour en faire une PR sure.

- **(A) Cote ecran** : retirer du POST les cles dont l'ecran n'est pas
  proprietaire, dans `_saveSettingsNow` (`parametres.js:2406`). Restaure
  l'efficacite du garde existant sans deviner aucune valeur. Risque : il faut
  etablir la liste exacte des cles « non proprietaires » et la tenir a jour ; et
  `ffprobe_path` / `mediainfo_path` SONT des champs de l'ecran — les retirer
  casserait leur saisie manuelle. Ce cas-la demande plutot un rafraichissement de
  `_state.settings` apres installation.
- **(B) Cote ecran, rafraichir** : appeler `_loadSettings()` apres chacune des
  quatre routes. C'est ce que fait deja `_rechargerApresReset` (ligne 1792).
  Risque nomme : `_loadSettings()` **ecrase `_state.settings`** et n'attend que
  `_state.saveInFlight`, pas le debounce `_state.saveTimer` — une saisie en cours
  non encore partie serait perdue. Il faudrait flusher d'abord.

Un correctif cote BACKEND (par exemple cesser d'injecter ces cles dans le GET)
est a ecarter : il casserait les lecteurs de `get_settings` et la sequence (A)
de `auto_install_probe_tools`, qui fait justement `get_settings` →
modifie → `save_settings`.

---

## Finding 2 — [severite 1 / ARCHITECT] L'inventaire d'endpoints ne voyait que les appels litteraux

Le rapport du 2026-08-09 concluait « 107 endpoints litteraux prefixes […] tous
resolvent » avec, pour methode, un `grep` de `apiPost("<litteral>")`. Cette
methode ne voit pas les appels dont le nom de route est une **variable**.

Il y en a **cinq**, plus un wrapper :

| Site | Provenance de la route | Verdict |
|---|---|---|
| `web/dashboard/views/statistiques.js:390` | table de thunks lignes 363-365 : `library/get_library_podiums`, `library/get_library_timeline`, `library/get_scoring_rollup` | existent |
| `web/dashboard/views/parametres.js:1069` | `runtime/recheck_probe_tools` \| `runtime/get_probe_tools_status` | existent |
| `web/dashboard/views/parametres.js:1821` | `ACTIONS_DE_SECTION` (lignes 1539-1630) : 9 routes | existent |
| `web/dashboard/views/parametres.js:2946` | `field.testMethod` (lignes 176-217) : 5 routes `integrations/test_*` | existent |
| `web/dashboard/components/film-detail.js:1589` | `library/set_field_lock` \| `library/clear_field_lock` | existent |
| `web/dashboard/views/_v5_helpers.js:33` | **wrapper**, delegue a `core/api.js` (pas un second client HTTP) | sans objet |

**Aucun endpoint casse.** Le finding porte sur la methode, pas sur le resultat :
la vue `statistiques.js` a ete ajoutee par #1040 le 2026-08-13, apres le dernier
inventaire, et un `grep` litteral l'aurait declaree « vue sans appel API ».

Commande de remesure a utiliser en complement du grep litteral :

```
rg -n "apiPost\(\s*[^\"'\`]" web/ --glob '*.js'
```

---

## Verifications negatives — ne pas les re-instruire

- **Adjacence decorateur/fonction** (piege du 2026-08-14, ou une aide s'etait
  glissee SOUS `@requires_valid_run_id`) : les 22 `@requires_valid_run_id` de
  `cinesort/ui/api/**` precedent tous immediatement le `def` qu'ils visent.
  Verifie un par un avec 2 lignes de contexte. Idem pour les 4
  `@contextmanager` / `@contextlib.contextmanager` et le `@wraps` de
  `_validators.py:139`.
- **Migrations SQLite** : aucun `CREATE TABLE` / `CREATE INDEX` sans
  `IF NOT EXISTS` en dehors des tables `*_new` du pattern 12-etapes. Inchange
  depuis le 2026-08-09.
- **Deplacements de fichiers hors `atomic_move`** : un seul `rename` nu dans
  `cinesort/app/`, `apply_core.py:775` (`legacy_root.rename(target_root)` de
  `migrate_legacy_collection_root`). Les deux chemins sont sous `cfg.root`, donc
  meme volume : `rename` y est atomique et le journal write-ahead n'apporterait
  rien. `record_apply_op` est bien appele juste apres, l'operation reste
  annulable. Pas un defaut.
- **Endpoints JS vers une methode inexistante** : **0**, inventaire litteral ET
  dynamique (cf. finding 2).
- **`open_path`** : toujours un COMMENTAIRE (`film-detail.js:1350`), l'appel reel
  passe par le pont pywebview. Troisieme audit consecutif a le confirmer.
- **Mixins SQL** : 0 (cf. point 4).

---

## Statistiques

- Zones auditees : `cinesort/domain`, `cinesort/infra`, `cinesort/app`,
  `cinesort/ui/api` (+ les 6 facades), `web/dashboard` (core, views, components),
  `tests/` (inventaire des cibles `patch(...)`, tests de contrat et cliquets).
- Techniques de l'etape 2.5 employees : **(A)** endpoint inventory diffing —
  complete par les appels dynamiques ; **(D)** cache invalidation trace ;
  **(B)** field usage tracing sur les 6 cles de reglages du finding 1.
- Findings retenus : **3** (1 de severite 3, 2 de severite 1).
- Self-critique — **6 findings supprimes avant redaction** :
  - **2 imagines / faux positifs** : la « violation domain → infra » de
    `_runners.py:84` (docstring) et `apiPost("open_path")` (commentaire) ;
  - **1 deja signale** : le `patch()` pose au site de definition dans
    `test_composite_score_toggle.py` (issue **#1022**, finding 4) ;
  - **1 idiomatique** : `_PeerGuardMixin` compte comme « mixin » a la regex du
    point 4, mais c'est un mixin de connexion urllib3, pas de SQL ;
  - **1 deja mitige** : `set_advanced_pragma_settings` ecrit
    `storage_profile_override` et `sqlite_locking_mode_exclusive`, mais ces deux
    cles ne sont **ni dans `_LITERAL_DEFAULTS`, ni reclamees par une
    `_save_section_*`** — `to_save = dict(existing_settings)` les preserve. Elles
    ne subissent donc PAS le finding 1. Verifie avant d'ecrire ;
  - **1 sans plan proportionne** : etendre `UiApiPatchableImportTests` aux
    couches `app`/`infra`/`domain` (point 5). Aucune violation mesuree
    aujourd'hui : ecrire le cliquet reviendrait a geler un etat sain sans defaut
    a montrer. Consigne ici, pas en issue.
- PR ouvertes : **1** (celle-ci, documentaire).
- Issues ouvertes : **1**.
- Findings deja connus, non re-signales : `run.cleanup_old_runs` sans `dry_run`,
  8 cles mortes de `_CACHEABLE`, `reloadLocale()` mort, `patch()` decoratif
  (tous dans **#1022**) ; endpoints de facade sans appelant JS (**#990**) ;
  lazy imports intra-`ui/api` (**#779**).

## Pourquoi aucune PR de code

Le budget en autorisait trois. Le finding 1 est net et localise, et pourtant il
ne donne pas de PR — pour deux raisons cumulatives, pas une :

1. **Aucun test ne peut etre vu ROUGE dans ce runner** (cf. contrainte). Le
   CLAUDE.md fait de cette preuve la condition d'un correctif, et le prompt
   d'audit exige des PR « sures, petites, **testees** ».
2. **Le chemin touche est le plus dangereux du fichier.** `save_settings` est
   partage par l'ecran, le pont pywebview et tout client REST ; son historique
   recent compte deja deux correctifs qui ont **eteint une garde voisine**
   (#1083, documente dans le CLAUDE.md). Le remede (A) et le remede (B) ont
   chacun un effet de bord nomme plus haut. Choisir entre eux est un arbitrage,
   pas une evidence — donc hors du niveau « modere ».

Le finding part en issue avec sa chaine de preuve complete et les deux remedes
chiffres, ce qui est la forme utile ici.

## Tendance

Compare au 2026-08-09 : les 5 points du prompt restent propres, et le point 5 est
passe de « tenu par la relecture » a « verrouille par un test de contrat » — un
progres reel.

Les deux runs pointaient le **cycle de vie des donnees**. Celui-ci deplace la
cible d'un cran : ce n'est plus ce que l'application garde ou detruit toute
seule, c'est **qui est proprietaire d'un reglage**. Les vagues B3/C/D/E ont
multiplie les routes d'ecriture dediees (`set_active_profile`, `save_profile`,
`set_scan_max_workers`, `auto_install_probe_tools`) sans que l'instantane que
l'ecran Parametres re-POSTe en soit informe. C'est la que devraient pointer les
prochains runs transverses : **chaque nouvelle route qui ecrit dans
`settings.json` une cle presente dans `_LITERAL_DEFAULTS` cree une instance de
plus du finding 1.**

# Vague P batch 6 - VP-F Quality profiles facade & UI parametres (TRaSH-compatible)

## Resume technique

Sixieme batch de la Vague P : sub-lot **VP-F**
(`VP-F-QUALITY-PROFILES`) - **extension** de `quality_facade.py`
(zero nouvelle facade, conformement a la recommandation critique) +
**decoupe** de `profiles_support.py` (**421 LOC**) en sous-modules
thematiques avec **backward compat ABSOLUE** des signatures. Apporte
un **round-trip YAML Recyclarr** lossless (cle `cinesort_profile`),
un **preset TRaSH-Guides 2026** embarque (Custom Format Groups) +
presets alternatifs (puriste DV, qualite max audio) tous
**DISABLED par defaut** (AC-3 fix #4), un controle
`upgrade_until_score` (defaut 10000, borne [0..100000]) et un
**breakdown 5-axes** (Source / Codec / HDR / Audio / Group) pour la
transparence des scores cote UI. Bundle PyInstaller etendu pour
embarquer les presets (`preset_datas` glob dans `CineSort.spec`).

## Changements par item

### VP-F : extension QualityFacade + decoupe profiles_support + Recyclarr + TRaSH 2026 + 5-axes

- **VP-F-QUALITY-PROFILES** (`5e91e58`) -
  `feat(VP-F-QUALITY-PROFILES)` : extension facade qualite et split
  thematique des profils sans regression.

  **Backend - decoupe `profiles_support.py`** :
  - `profiles_support_crud.py` (**424 LOC**) : extrait
    `get_profile` / `save_profile` / `set_active_profile` (CRUD pur).
  - `profiles_support_import_export.py` (**832 LOC**) : round-trip
    Recyclarr YAML lossless (cle `cinesort_profile`), loader du
    preset embarque via `importlib.resources`, gestion
    `upgrade_until_score` (defaut 10000, borne [0..100000]),
    breakdown 5-axes.
  - `profiles_support.py` reduit a un **shim de backward-compat**
    qui re-exporte 100% des symboles publics historiques (preserve
    tous les call-sites legacy).

  **Backend - extension `quality_facade.py`** (zero nouvelle facade
  per recommandation critique) :
  - 7 nouvelles methodes ajoutees : `export_recyclarr_yaml` /
    `import_recyclarr_yaml`, `get_embedded_presets`,
    `get_upgrade_until_score` / `set_upgrade_until_score`,
    `get_breakdown_5_axes`.
  - Total : **24 methodes pre-VP-F preservees**, signatures
    inchangees (verifie par contract tests).

  **Preset TRaSH 2026 embarque** :
  - `cinesort/data/presets/tier_preset_trash_2026.json` (**93 LOC**)
    : preset TRaSH-Guides Custom Format Groups + presets
    alternatifs (puriste DV, qualite max audio).
  - **DISABLED par defaut** (`enabled_by_default=false` pour les 3
    presets) - AC-3 fix #4 : l'utilisateur doit explicitement
    activer le preset, jamais d'override automatique de son profil.
  - Bundling PyInstaller : `preset_datas` glob ajoute dans
    `CineSort.spec`.

  **UI - section "Profils qualite" dans parametres.js** :
  - Import / export Recyclarr YAML.
  - Viewer des presets embarques (TRaSH 2026 + alternatifs).
  - Input `upgrade_until_score` (defaut 10000).
  - Barres de breakdown 5-axes (Source / Codec / HDR / Audio /
    Group).
  - `node --check` passe.

## Tests

- `tests/test_quality_profiles_facade_extension.py` (**facade
  extension contract**) : valide les 7 nouvelles methodes
  (`export_recyclarr_yaml`, `import_recyclarr_yaml`,
  `get_embedded_presets`, `get_upgrade_until_score`,
  `set_upgrade_until_score`, `get_breakdown_5_axes`).
- `tests/test_recyclarr_import_export.py` (**YAML round-trip
  lossless**) : verifie que export -> import -> export produit le
  meme YAML (preservation de la cle `cinesort_profile`).
- `tests/test_quality_facade_backward_compat.py` (**24 methodes
  pre-VP-F**) : verifie que les signatures de toutes les methodes
  pre-VP-F sont preservees.
- **Total : 70 nouveaux tests, 100% verts**.

Acceptance criteria (5/5) :

- AC-1 OK : `quality_facade.py` **etendue** (pas dupliquee),
  `profiles_support.py` **decoupee sans regression** (re-exports
  preservent tous les callers legacy).
- AC-2 OK : **Recyclarr YAML round-trip lossless** via cle
  `cinesort_profile`.
- AC-3 OK : preset **TRaSH 2026 embarque mais DISABLED par
  defaut** (fix #4 : zero override automatique du profil
  utilisateur).
- AC-4 OK : **breakdown 5-axes** (Source / Codec / HDR / Audio /
  Group) structure pour affichage UI.
- AC-5 OK : `upgrade_until_score` exposable via UI (defaut
  **10000**, borne [0..100000]).

## 🎁 Pour toi

Ce batch ouvre une **vraie fenetre sur le moteur de qualite** qui
decide quel encodage de tes films est "meilleur" qu'un autre. Avant,
ces reglages etaient internes et opaques ; maintenant, tu peux
les voir, les ajuster, les importer/exporter, et meme reutiliser
les presets de la communaute TRaSH-Guides (la reference pour le
tri de bibliotheques de films).

Concretement, dans **Parametres -> Profils qualite**, tu trouves
maintenant 4 nouveautes :

1. **Import / export Recyclarr YAML** : Recyclarr est l'outil
   standard de la scene mediatheque pour partager des reglages
   de qualite. Tu peux exporter ton profil CineSort vers un
   fichier YAML (compatible Recyclarr) pour le sauvegarder ou le
   partager, ou en importer un. Le round-trip est **lossless** :
   exporter puis re-importer ne change rien. Une cle interne
   `cinesort_profile` preserve les specificites CineSort sans
   casser la compat Recyclarr.

2. **Presets TRaSH-Guides 2026 embarques** : 3 presets sont
   inclus directement dans l'app (pas besoin de telecharger quoi
   que ce soit) : le preset **TRaSH 2026** standard, un preset
   **puriste Dolby Vision** (qui privilegie le DV au max), et un
   preset **qualite audio max** (qui priorise Atmos / TrueHD).
   **Important** : ces presets sont **DESACTIVES par defaut**.
   Ton profil actuel n'est jamais ecrase automatiquement. Si tu
   veux les essayer, tu dois explicitement les activer (clic
   manuel). C'est volontaire : on ne veut surtout pas surprendre
   ton profil patiemment regle.

3. **Upgrade until score** : un champ unique qui te permet de
   dire "arrete de chercher mieux quand on atteint ce score". Par
   defaut **10000** (tres haut = continue toujours a chercher
   mieux). Si tu mets **0**, l'app garde la premiere version
   correcte sans chercher d'upgrade. Borne entre 0 et 100000.

4. **Breakdown 5-axes** : pour chaque film, tu vois desormais
   comment son score est calcule sur **5 dimensions** affichees
   en barres horizontales : **Source** (Blu-ray, WEB-DL, ...),
   **Codec** (H.265, H.264, AV1, ...), **HDR** (DV, HDR10+,
   HDR10, SDR), **Audio** (Atmos, DTS-X, TrueHD, ...) et
   **Group** (qualite du release group). Plus besoin de deviner
   pourquoi un fichier a battu un autre : tu vois la dimension
   qui a fait la difference.

Cote interne (rien de visible directement mais bon a savoir) : on
a aussi nettoye le gros fichier `profiles_support.py` (421 lignes)
en le decoupant en 3 modules plus petits (CRUD pur, import/export,
shim de compat) **sans toucher aux comportements**. Tous les
imports historiques continuent de marcher exactement comme avant
(verifie par **70 tests** dont 24 specifiquement dedies a la
verification que les 24 methodes pre-existantes de `QualityFacade`
ont **strictement la meme signature** qu'avant).

## Notes

- Pas de bump VERSION (decision differee, coherent avec les
  batches Vague N/O/P-1/P-2/P-3/P-4/P-5).
- Tag local uniquement : `vague-p-batch6` (pas de push remote).
- Commits inclus : `5e91e58`.
- **Backward compat ABSOLUE** : les 24 methodes pre-VP-F de
  `QualityFacade` preservent leurs signatures (verifie par
  `test_quality_facade_backward_compat.py`). Tous les symboles
  publics de `profiles_support.py` sont re-exportes par le shim.
- **TRaSH 2026 preset DISABLED par defaut** (fix #4) : aucune
  ecriture automatique du profil utilisateur, activation
  exclusivement manuelle via l'UI.
- **Recyclarr round-trip lossless** : la cle `cinesort_profile`
  preserve les specificites CineSort sans casser la compat
  ecosysteme Recyclarr / TRaSH-Guides.
- Bundle PyInstaller etendu : `preset_datas` glob dans
  `CineSort.spec` pour embarquer
  `cinesort/data/presets/*.json` dans le binaire final.
- Suite Vague P : sub-lots VP-G+ a venir.

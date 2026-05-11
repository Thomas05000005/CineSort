# V7.1 Notes (FR)

## Objectifs v7.1
- Dossier collections configurable avec nouveau defaut `_Collection`.
- Prise en charge des dossiers vides via un dossier cible configurable `_Vide`.
- Correction de la conformite "deja conforme" pour exiger l'annee quand elle est connue.
- Aucun changement `web/*` pour le lot v7.1.0.

## Decisions
- `collection_folder_name` defaut: `_Collection`.
- `empty_folders_folder_name` defaut: `_Vide`.
- `move_empty_folders_enabled` defaut: `false` (securite).
- `empty_folders_scope` accepte `touched_only` ou `root_all` (fallback `root_all`).
- Migration auto du legacy `Collection` vers `_Collection` pendant APPLY.
- En cas de coexistence `Collection` + `_Collection`: merge recursif sans overwrite.

## Fichiers touches (v7.1.0)
- `core.py`
- `cinesort/ui/api/cinesort_api.py`
- `tests/test_merge_duplicates.py`
- `tests/test_v7_1_features.py`
- `check_project.bat`
- `CHANGELOG.md`
- `VERSION`
- `docs/releases/V7_1_NOTES_FR.md`

## Validation executee (v7.1.0)
- `python -m unittest discover -s tests -p "test_*.py" -v` -> OK.
- `pyinstaller --clean --noconfirm CineSortApp.spec` -> OK.

## Journal
- 2026-02-22: Demarrage lot v7.1, branche `v7_1_work` creee, baseline commit effectue.
- 2026-02-22: Implementation coeur v7.1 (`core.py`, `cinesort/ui/api/cinesort_api.py`): `_Collection` configurable, migration legacy `Collection`, dossiers vides `_Vide`, correction NOOP avec annee obligatoire.
- 2026-02-22: Ajout des tests v7.1 (`tests/test_v7_1_features.py`) + adaptation `tests/test_merge_duplicates.py` au dossier `_Collection`.
- 2026-02-22: Documentation v7.1 ajoutee (`CHANGELOG.md`, `VERSION`) + checklist de validation mise a jour.
- 2026-02-22: Validation complete executee (tests unitaires + build PyInstaller) sans regression detectee.
- 2026-02-22: Phase 7.1.3-dev demarree sur branche `v7_1_score` avec tag `pre_v7_1_score` et backup `_BACKUP_patch_before_v7_1_3.txt`.
- 2026-02-22: Ajout moteur CinemaLux (`cinesort/domain/quality_score.py`), migration DB `003_quality_score_tables.sql`, persistence profils/rapports dans `SQLiteStore`.
- 2026-02-22: Ajout endpoints Qualite dans `CineSortApi` (`get/save/reset/export/import profile`, `get_quality_report`) + integration UI onglet Qualite (`web/index.html`, `web/app.js`, `web/styles.css`).
- 2026-02-22: Tests 7.1.3 executes: `tests.test_quality_score`, `tests.test_v7_foundations`, `tests.test_api_bridge_lot3` -> OK.
- 2026-02-22: Phase 7.1.4-dev demarree sur branche `v7_1_4_dashboard` avec tag `pre_v7_1_4_dashboard` et backup `_BACKUP_patch_before_v7_1_4.txt`.
- 2026-02-22: Ajout endpoint agrege `get_dashboard` + migration DB `004_anomalies_table.sql` et helpers SQLite d'agregation.
- 2026-02-22: Ajout onglet UI Synthese (cartes KPI, distributions, anomalies, outliers, historique runs) avec un seul appel API principal.
- 2026-02-22: Ajout tests `tests.test_dashboard` + mise a jour `check_project.bat`, `CHANGELOG.md`, `VERSION=7.1.4-dev`.
- 2026-02-22: Packaging/hygiene: migrations SQL versionnees (ajustement `.gitignore`) et incluses explicitement dans `CineSortApp.spec`.
- 2026-02-22: Validation 7.1.4 executee:
  - `python -m unittest discover -s tests -p "test_*.py" -v` OK (64 tests),
  - `.\check_project.bat` OK,
  - `pyinstaller --clean --noconfirm CineSortApp.spec` OK.

## Style Guide CineSort (UI premium)
1. Une seule vue visible a la fois:
   - navigation = 1 onglet -> 1 panneau (`.view` + `hidden`),
   - aucun empilement visuel lors du changement d'onglet.
2. Hierarchie typographique stable:
   - titre vue: 20-24px gras,
   - sous-titres: 14-16px semi-gras,
   - texte normal: 13-14px,
   - micro-texte aide: 12px avec opacite reduite.
3. Grille d'espacement 8px:
   - padding sections 16px ou 24px,
   - marges inter-blocs 16px,
   - hauteur inputs/boutons stable (36-40px).
4. Cards pour infos principales:
   - fond legerement different,
   - bordure fine,
   - coins arrondis coherents,
   - lisibilite conservee en contraste faible.
5. Tables premium:
   - header sticky sur zone scrollable,
   - zebra rows legeres,
   - hover discret,
   - alignement: nombres a droite, texte a gauche,
   - badges severite INFO/WARN/ERROR uniformes.
6. Feedback utilisateur visible:
   - etat vide: message + action concrete,
   - loading: indicateur + texte court,
   - erreur: message FR court + copie details en mode avance.
7. Accessibilite minimale:
   - focus visible (outline 2px contraste),
   - navigation clavier onglets (fleches, Enter, Espace),
   - roles ARIA `tablist`, `tab`, `tabpanel`.
8. Contexte global en haut:
   - run actif (copier + ouvrir dossier run),
   - film selectionne (titre/annee),
   - row_id visible en mode avance,
   - bouton "Selectionner..." pour run+film.
9. Ton FR pro:
   - eviter vocabulaire dev expose au user,
   - preferer formulations simples et actionnables.
10. Stabilite visuelle:
   - styles de boutons coherents entre vues,
   - structure de section constante (titre -> aide -> contenu),
   - placement des actions stable dans toute l'app.

## Checklist smoke UI (7.1.5)
1. Changer d'onglet masque bien toutes les autres vues (une seule section visible).
2. Navigation clavier des onglets OK (fleches + Enter/Espace) avec focus visible.
3. Bandeau "Contexte courant" affiche run actif et film selectionne.
4. Bouton "Copier run_id" copie bien la valeur du contexte.
5. Bouton "Ouvrir dossier run" ouvre le dossier attendu via `open_path`.
6. Bouton "Selectionner..." ouvre le modal, liste des runs visible et selectionnable.
7. Selection d'un film dans le modal met a jour `selectedRunId` et `selectedRowId`.
8. Qualite fonctionne sans saisie manuelle d'ID (fallback dernier run + selection guidee).
9. Synthese se charge par defaut sur `latest` sans demander d'ID.
10. Bouton "Aide" explique clairement `run_id` et `row_id` en FR non technique.

## Checklist smoke UI (7.1.7)
1. Parametres: assistant premier lancement visible avec statut global (`Pret`, `Pret (partiel)`, `Incomplet`).
2. Assistant: bouton "Configurer" place le focus sur `ROOT`.
3. Assistant: bouton "Tester TMDb" met a jour le statut TMDb (OK/KO/A tester).
4. Assistant: bouton "Reessayer detection" met a jour le statut probe (hybride/partiel/manquant).
5. Dialogues: plus aucun popup natif navigateur; confirmations/info passent par la modale UI.
6. Validation->Apply: en cas de doublons, la confirmation d'application s'ouvre bien en modale.
7. Logs: exports run JSON/CSV disponibles et feedback de succes/erreur visible.
8. Navigation guidee: bouton "Aller a ..." suit l'etape attendue et respecte les preconditions.
9. Changement d'onglet: toujours une seule vue visible (`.view`).
10. Accessibilite de base: focus visible, fermeture modale via `Escape`, retour focus au declencheur.

CineSort - README FR
====================

Version actuelle
----------------
- `7.2.0-dev`
- Application Windows (Python + pywebview)

Variantes UI
------------
- UI stable = production : `python app.py`
- Le binaire `CineSort.exe` et `python app.py` sans mode dev ouvrent toujours l'UI stable.
- UI Preview = dev only :
  - `set DEV_MODE=1`
  - puis `python app.py --ui preview`
- Alternative Windows :
  - `set DEV_MODE=1`
  - `set CINESORT_UI=preview`
  - puis `python app.py`

Important :
- sans `--dev` ni `DEV_MODE=1`, CineSort charge toujours l'UI stable,
- une demande `--ui preview` ou `CINESORT_UI=preview` sans mode dev retombe proprement sur l'UI stable,
- l'ancien prototype UI Next est archive et n'est plus maintenu comme runtime actif.

Preview web local (audit UI)
----------------------------
- Preview web = dev only :
  - `set DEV_MODE=1`
  - puis `python scripts/run_ui_preview.py --dev`
- Scenario/vues : `python scripts/run_ui_preview.py --dev --scenario quality_anomalies --view quality`
- Captures : `python scripts/capture_ui_preview.py --dev --recommended`
- Doc detaillee : `web/preview/README.md`

Important :
- l'UI stable reste la reference de production,
- le preview web reste le seul chemin UI dev supporte,
- l'ancien prototype UI Next est archive hors du chemin produit actif,
- le preview web sert uniquement au travail UI local et aux captures,
- aucun endpoint backend n'est different entre l'UI stable et le preview.

A quoi sert CineSort ?
----------------------
CineSort sert a organiser une bibliotheque de films de facon propre et sure:
- il analyse tes dossiers sans rien modifier au debut,
- il propose des corrections (titre, annee, structure),
- il te laisse valider avant action,
- il applique uniquement ce que tu as valide.

Objectif principal: gagner du temps sans prendre de risque sur les medias.

Ce qui est deja en place
------------------------
1) Workflow guide reel:
- Reglages
- Analyse
- Vue du run
- Qualite
- Cas a revoir
- Decisions
- Conflits
- Execution (dry-run puis reel)
- Historique

Vue du run:
- vue de recapitulatif du run utile,
- repartition technique, signaux prioritaires et suite logique,
- accessible apres Analyse pour orienter la lecture avant Qualite.

2) Detection et correction:
- candidats depuis noms de dossiers/fichiers,
- support NFO,
- support TMDb (si cle API configuree),
- score de confiance + notes explicatives.

3) Qualite media:
- analyse technique video/audio/sous-titres via ffprobe + MediaInfo (mode hybride),
- scoring qualite explicable,
- batch qualite (film selectionne / selection / filtres).

4) Securite operationnelle:
- verification doublons avant apply,
- anti double apply,
- quarantaine/review pour les cas sensibles,
- pas de suppression destructive par defaut.

5) Outils probe assistes:
- diagnostic ffprobe / MediaInfo dans l'UI,
- installation / mise a jour assistee (winget),
- fallback chemin manuel si winget indisponible.

6) Observabilite:
- logs de run,
- resumes explicites,
- artefacts de run persistants.

7) Scan incremental (nouveau):
- mode optionnel "scan des changements",
- index fichier `path/size/mtime/hash quick`,
- cache par dossier avec invalidation automatique.

TMDb (important)
----------------
Tu peux configurer une cle API TMDb dans les parametres.
- Optionnelle, mais recommandee pour mieux identifier les films.
- Si elle est memorisee, CineSort la stocke protegee par Windows DPAPI pour le compte utilisateur courant.
- Le fichier `settings.json` ne garde plus la cle en clair.
- Si cette protection Windows n'est pas disponible, CineSort ne memorise pas la cle.
- Ne partage jamais ta cle.
- Si elle fuit, regenere-la sur TMDb.

Prerequis
---------
- Windows 10/11
- WebView2 Runtime (souvent deja present)

Utilisation rapide (EXE)
------------------------
1. Lance `CineSort.exe`.
2. Ouvre Reglages:
   - ROOT (ex: `D:\Films`)
   - STATE_DIR (ex: `%LOCALAPPDATA%\CineSort`)
   - (optionnel) cle TMDb
3. Clique Enregistrer.
4. Lance l'analyse.
5. Ouvre Decisions et confirme les lignes.
6. Ouvre Execution et lance d'abord un dry-run.
7. Si le resultat te convient, relance en reel.

Ou se trouvent les donnees de run ?
-----------------------------------
Chaque analyse cree un dossier run, par exemple:
- `STATE_DIR\runs\tri_films_<run_id>\`

Fichiers utiles:
- `plan.jsonl`
- `validation.json`
- `summary.txt`
- `ui_log.txt`

Demande de retours (tres utile)
-------------------------------
Avant de tester, lis ce fichier `README_FR.txt`.

Si tu trouves un bug, une mauvaise detection, ou meme si tu fais juste un test rapide:
- compresse en ZIP le dossier run concerne:
  `STATE_DIR\runs\tri_films_<run_id>\`
- envoie-moi ce ZIP.

Meme les micro-bugs m'aident:
- faux positif/faux negatif,
- annee mal detectee,
- confusion collection/single,
- score qualite incoherent,
- comportement UI ambigu.

Plus j'ai de runs reels, plus la logique devient fiable sur des bibliotheques variees.

Idees pour les prochaines versions
----------------------------------
Voici les pistes prioritaires envisagees:
1. Undo applique (retour arriere controle du dernier apply).
2. Profils qualite predefinis (Remux strict, Equilibre, Light).
3. Integrations optionnelles (Plex/Jellyfin/Emby) apres apply.
4. Comparatif multi-runs dans Vue du run.

Si tu as des idees
------------------
Je prends tous les retours, meme courts. Format conseille:
- Type: Bug / Amelioration / Idee
- Contexte
- Resultat attendu

Documentation complementaire
----------------------------
- Notes de version detaillees : `docs/releases/V7_1_NOTES_FR.md`
- Vision produit : `docs/product/VISION_V7_FR.md`
- Documents de design stables :
  - `docs/design/UNDO_7_2_0_A_DESIGN_FR.md`
  - `docs/design/APPLY_ROWS_7E_DESIGN_FR.md`
- Documentation dev / preview / chantier : `docs/README_DEV.md`

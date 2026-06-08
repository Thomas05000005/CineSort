# test_library/

Bibliotheque fictive multi-root generee par `scripts/make_test_library.py`.
Sert aux tests E2E, demos et captures du scan / classement / dedup CineSort.

## Regenerer

```
python scripts/make_test_library.py
```

Le script est **idempotent** : il ne retelecharge pas les clips deja
en cache (`.cache/`) et ne reecrit pas les stubs / NFO deja presents
avec la bonne taille. Vous pouvez le relancer sans risque.

## Pre-requis optionnels

- `ffmpeg` dans le PATH : permet de produire de vrais clips video
  (trim, upscale faux 4K, re-encode degrade). Si absent, le script
  retombe sur des stubs binaires de taille equivalente.
- Acces reseau HTTPS vers `download.blender.org` : permet de
  recuperer les clips CC. Si indisponible, fallback stubs.

## Sources Creative Commons utilisees

- **big_buck_bunny** -- CC BY 3.0 -- (c) Blender Foundation | peach.blender.org
  - URL : <https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4>
- **sintel** -- CC BY 3.0 -- (c) Blender Foundation | durian.blender.org
  - URL : <https://download.blender.org/durian/trailer/sintel_trailer-480p.mp4>
- **tears_of_steel** -- CC BY 3.0 -- (c) Blender Foundation | mango.blender.org
  - URL : <https://download.blender.org/mango/download.blender.org/demo/movies/ToS/tears_of_steel_720p.mov>

## RootA -- cas nominaux + accents FR + saga

### Clips CC reels (ffmpeg trim)

- `Movies/Big Buck Bunny (2008)/Big Buck Bunny (2008).mp4`
  - Source CC : **big_buck_bunny** (CC BY 3.0, (c) Blender Foundation | peach.blender.org)
  - Transform : `trim 30s`
  - Note : Clip CC reel (Blender Foundation), nom propre tres TMDb-friendly
- `Movies/Sintel (2010)/Sintel (2010).mp4`
  - Source CC : **sintel** (CC BY 3.0, (c) Blender Foundation | durian.blender.org)
  - Transform : `trim 30s`
  - Note : Clip CC reel (Blender Foundation)

### Stubs (fichiers tronques)

- `Movies/Inception (2010)/Inception (2010).mkv` (~1.7 MB)
  - Note : Nom propre canonique, gros titre TMDb attendu
- `Movies/the.matrix.1999.brrip/the matrix.avi` (~878.9 KB)
  - Note : Mal nomme : dossier en lowercase point, fichier sans annee
- `Movies/Parasite/Parasite.mkv` (~1.1 MB)
  - Note : Annee MANQUANTE dans nom et dossier
- `Movies/Le Fabuleux Destin d Amelie Poulain (2001)/Le Fabuleux Destin d Amelie Poulain (2001).mkv` (~1.4 MB)
  - Note : Accents FR + apostrophe remplacee par espace (shell-safe)
- `Movies/Sen to Chihiro no Kamikakushi (2001)/Sen to Chihiro no Kamikakushi (2001).mkv` (~1.3 MB)
  - Note : Titre etranger japonais (translitteration romaji)
- `Movies/Dune (2021)/Dune (2021).mkv` (~1.6 MB)
  - Note : Saga Dune - episode 1
- `Movies/Dune Part Two (2024)/Dune Part Two (2024).mkv` (~1.6 MB)
  - Note : Saga Dune - episode 2

## RootB -- doublons, faux 4K, NFO, series TV

### Clips CC reels

- `Movies/Tears of Steel (2012)/Tears of Steel (2012) 1080p.mkv`
  - Source CC : **tears_of_steel** (CC BY 3.0, (c) Blender Foundation | mango.blender.org)
  - Transform : `trim 30s`
  - Note : Clip CC reel utilise comme base 1080p
- `Movies/Tears of Steel (2012)/Tears of Steel (2012) 720p.mkv`
  - Source CC : **tears_of_steel** (CC BY 3.0, (c) Blender Foundation | mango.blender.org)
  - Transform : `downscale_720p`
  - Note : DOUBLON volontaire du meme clip CC, encode 720p
- `Movies/FakeUpscale (2020)/FakeUpscale (2020) 2160p.mp4`
  - Source CC : **big_buck_bunny** (CC BY 3.0, (c) Blender Foundation | peach.blender.org)
  - Transform : `upscale_4k`
  - Note : FAUX 4K : 720p upscale en 2160p, AUCUN match TMDb attendu
- `Movies/BadReencode (2019)/BadReencode (2019).mp4`
  - Source CC : **sintel** (CC BY 3.0, (c) Blender Foundation | durian.blender.org)
  - Transform : `bad_reencode`
  - Note : Re-encode tres degrade (bitrate bas, CRF eleve)

### Stubs

- `Movies/The Matrix (1999)/The Matrix (1999) 1080p.mkv` (~1.8 MB)
  - Note : Doublon 1080p de The Matrix (stub, pas clip CC)
- `Movies/The Matrix (1999)/The Matrix (1999) 720p.mkv` (~1.0 MB)
  - Note : Doublon 720p de The Matrix (stub, pas clip CC)
- `Shows/Breaking Bad/Season 01/Breaking Bad S01E01.mkv` (~781.2 KB)
  - Note : Serie TV nommage standard SxxExx
- `Shows/Breaking Bad/Season 01/Breaking Bad S01x02.mkv` (~781.2 KB)
  - Note : Serie TV nommage SxxExx variante (x au lieu de E)
- `Shows/Breaking Bad/Saison 1/Breaking Bad Saison 1 Episode 3.mkv` (~781.2 KB)
  - Note : Serie TV nommage FR verbeux (Saison N Episode N)
- `Movies/Night of the Living Dead (1968)/Night of the Living Dead (1968).mkv` (~976.6 KB) + movie.nfo (tt0063350)
  - Note : Domaine public, avec movie.nfo contenant l'ID IMDb
- `Movies/Nosferatu (1922)/Nosferatu (1922).mkv` (~976.6 KB)
  - Note : Domaine public, SANS movie.nfo (a resoudre par TMDb)

## Statistiques de la derniere generation

- Fichiers crees ou re-ecrits : 0
- Avertissements : 0

---
_Aucun fichier sous droits n'est jamais produit ou telecharge par ce script : seuls des clips Creative Commons sont utilises._

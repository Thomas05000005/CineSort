"""Fixture : mini-bibliotheque de 20 films factices pour les tests E2E.

Cree des dossiers avec fichiers .mkv (header valide, 4 Ko min) et .nfo XML.
"""

from __future__ import annotations

from pathlib import Path

# Header MKV valide (EBML) + padding pour passer les checks d'integrite
# Taille totale ~60 Mo pour passer MIN_VIDEO_BYTES (50 Mo par defaut)
_MKV_HEADER = b"\x1a\x45\xdf\xa3" + b"\x93\x42\x86\x81\x01" + b"\x42\xf7\x81\x01"
_MKV_PADDING = b"\xec" * 128  # Void element
_MKV_TAIL = b"\x18\x53\x80\x67" + b"\xff" * 256  # Fin non-nulle
_MKV_BODY_SMALL = _MKV_HEADER + _MKV_PADDING + _MKV_TAIL
# Le fichier final sera padde a ~60 Mo dans create_test_library()

_NFO_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <title>{title}</title>
  <year>{year}</year>
  <runtime>{runtime}</runtime>
  <uniqueid type="imdb">{imdb}</uniqueid>
</movie>"""

# ---- Definition des 20 films -----------------------------------------------

FILMS = [
    # 10 films normaux
    {"title": "Inception", "year": 2010, "imdb": "tt1375666", "category": "normal"},
    {"title": "The Matrix", "year": 1999, "imdb": "tt0133093", "category": "normal"},
    {"title": "Interstellar", "year": 2014, "imdb": "tt0816692", "category": "normal"},
    {"title": "Pulp Fiction", "year": 1994, "imdb": "tt0110912", "category": "normal"},
    {"title": "Avatar", "year": 2009, "imdb": "tt0499549", "category": "normal"},
    {"title": "Gladiator", "year": 2000, "imdb": "tt0172495", "category": "normal"},
    {"title": "The Dark Knight", "year": 2008, "imdb": "tt0468569", "category": "normal"},
    {"title": "Forrest Gump", "year": 1994, "imdb": "tt0109830", "category": "normal"},
    {"title": "Fight Club", "year": 1999, "imdb": "tt0137523", "category": "normal"},
    {"title": "Parasite", "year": 2019, "imdb": "tt6751668", "category": "normal"},
    # 3 cas ambigus
    {
        "title": "BAC Nord",
        "year": 2020,
        "nfo_title": "Bac Nord 2021",
        "nfo_year": 2021,
        "category": "ambiguous",
    },
    {
        "title": "Le Comte de Monte-Cristo",
        "year": 2024,
        "nfo_title": "Monte Cristo",
        "nfo_year": 1975,
        "category": "ambiguous",
    },
    {
        "title": "Beetlejuice Beetlejuice",
        "year": 2024,
        "nfo_title": "Beetlejuice",
        "nfo_year": 1988,
        "category": "ambiguous",
    },
    # 2 doublons (meme film, qualites differentes)
    {"title": "Inception", "year": 2010, "suffix": "720p", "imdb": "tt1375666", "category": "duplicate"},
    {"title": "Inception", "year": 2010, "suffix": "1080p", "imdb": "tt1375666", "category": "duplicate"},
    # 1 non-film
    {"title": "Bloopers Reel 2024", "year": 2024, "runtime": 3, "category": "non_film"},
    # 1 serie TV
    {"title": "Breaking Bad S01E01", "year": 2008, "category": "tv_series"},
    # 3 caracteres speciaux
    {"title": "WALL-E", "year": 2008, "category": "special_chars"},
    {"title": "Asterix et Obelix", "year": 2023, "category": "special_chars"},
    {"title": "L'Ete dernier", "year": 2023, "category": "special_chars"},
]


def create_test_library(base_dir: Path) -> dict:
    """Cree 20 dossiers de films factices sous *base_dir*.

    Retourne ``{"root": str, "films": [{"title", "year", "folder", "category"}]}``.
    """
    root = base_dir / "films"
    root.mkdir(exist_ok=True)
    result_films = []

    for film in FILMS:
        folder_name = f"{film['title']} ({film['year']})"
        if film.get("suffix"):
            folder_name += f" [{film['suffix']}]"

        folder = root / folder_name
        folder.mkdir(exist_ok=True)

        # Fichier video factice avec taille apparente de 60 Mo
        # Header MKV valide + sparse file pour eviter d'ecrire 1.2 Go
        video = folder / f"{folder_name}.mkv"
        target_size = 60 * 1024 * 1024  # 60 Mo (> MIN_VIDEO_BYTES defaut 50 Mo)
        with open(video, "wb") as f:
            f.write(_MKV_BODY_SMALL)
            # seek a target_size - 2, ecrire 2 octets non-nuls pour le tail check
            f.seek(target_size - 2)
            f.write(b"\xff\xff")

        # Fichier NFO
        nfo_title = film.get("nfo_title", film["title"])
        nfo_year = film.get("nfo_year", film["year"])
        runtime = film.get("runtime", 120)
        imdb = film.get("imdb", "")
        nfo = folder / "movie.nfo"
        nfo.write_text(
            _NFO_TEMPLATE.format(title=nfo_title, year=nfo_year, runtime=runtime, imdb=imdb),
            encoding="utf-8",
        )

        result_films.append(
            {
                "title": film["title"],
                "year": film["year"],
                "folder": str(folder),
                "folder_name": folder_name,
                "category": film["category"],
            }
        )

    return {"root": str(root), "films": result_films}

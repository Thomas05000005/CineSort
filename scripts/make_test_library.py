#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_test_library.py
====================

Construit une bibliotheque fictive multi-root pour CineSort (tests E2E,
demos, captures, benchmarks). Le script est IDEMPOTENT : on peut le
relancer sans tout retelecharger / regenerer.

Arborescence de sortie (relative au repo CineSort) :

    test_library/
        .cache/                 -> clips CC bruts telecharges (mutualises)
        RootA/                  -> 1er root multi-bibliotheque
            <fichiers...>
        RootB/                  -> 2nd root multi-bibliotheque
            <fichiers...>
        README.md               -> documentation auto-generee

Conventions de marqueurs (stdout) :
    [skip]         deja present, rien a faire
    [dl]   X.Y MB  telechargement reseau
    [ffmpeg]       transformation ffmpeg (trim, scale, reencode)
    [create stub]  fichier tronque genere de toutes pieces
    [nfo]          fichier movie.nfo cree
    [readme]       README.md de la bibliotheque genere
    [warn]         operation ignoree car prerequis manquant (reseau, ffmpeg)
    [ok]           etape terminee avec succes

Le script est volontairement TOLERANT : si ffmpeg ou le reseau sont
indisponibles, on log un [warn] et on poursuit avec des stubs equivalents
(taille plausible, contenu opaque). Le but est qu'un developpeur sans
connectivite puisse quand meme avoir une bibliotheque de test complete
pour scanner / classer / dedupliquer.

ATTENTION : aucun fichier reel d'oeuvre sous droits n'est jamais produit
ou telecharge. Seuls des clips Creative Commons (Blender Foundation /
peach, durian, mango) sont eventuellement recuperes pour servir
d'echantillons video reels.
"""

from __future__ import annotations

import hashlib
import os
import random
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib import request as urlrequest
from urllib.error import URLError


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_ROOT = REPO_ROOT / "test_library"
CACHE_DIR = LIBRARY_ROOT / ".cache"
ROOT_A = LIBRARY_ROOT / "RootA"
ROOT_B = LIBRARY_ROOT / "RootB"

# Graine deterministe pour que les stubs aient toujours la meme taille
# d'une execution a l'autre (utile pour les snapshots de tests).
RANDOM_SEED = 0xC1E5057E  # "CineSort" lookalike


@dataclass(frozen=True)
class CreativeCommonsClip:
    """Source CC bien identifiee, telechargeable via HTTPS public."""

    key: str
    url: str
    license: str
    credit: str


# Sources Blender Foundation officielles (mirroirs Blender Cloud / download).
# On choisit les versions courtes / basse resolution pour limiter le volume.
CC_CLIPS: dict[str, CreativeCommonsClip] = {
    "big_buck_bunny": CreativeCommonsClip(
        key="big_buck_bunny",
        url="https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4",
        license="CC BY 3.0",
        credit="(c) Blender Foundation | peach.blender.org",
    ),
    "sintel": CreativeCommonsClip(
        key="sintel",
        url="https://download.blender.org/durian/trailer/sintel_trailer-480p.mp4",
        license="CC BY 3.0",
        credit="(c) Blender Foundation | durian.blender.org",
    ),
    "tears_of_steel": CreativeCommonsClip(
        key="tears_of_steel",
        url="https://download.blender.org/mango/download.blender.org/demo/movies/ToS/tears_of_steel_720p.mov",
        license="CC BY 3.0",
        credit="(c) Blender Foundation | mango.blender.org",
    ),
}


@dataclass
class StubSpec:
    """Specification d'un fichier stub (tronque, taille plausible)."""

    relpath: str            # chemin RELATIF au root (RootA ou RootB)
    size_bytes: int         # taille cible, entre 100 KB et 2 MB
    note: str = ""          # commentaire affiche dans README
    # Si renseigne, on cree aussi un movie.nfo a cote du fichier
    nfo_imdb_id: str | None = None
    nfo_title: str | None = None
    nfo_year: int | None = None


@dataclass
class ClipSpec:
    """Specification d'un fichier qui DOIT etre un clip video reel (CC)."""

    relpath: str
    source_key: str         # cle dans CC_CLIPS
    trim_seconds: int = 30
    # Operation supplementaire optionnelle :
    #   "upscale_4k"    -> ffmpeg scale=3840:2160 (faux 4K)
    #   "bad_reencode"  -> ffmpeg bitrate tres bas + crf eleve
    transform: str | None = None
    note: str = ""


@dataclass
class BuildReport:
    """Compte-rendu de l'execution, sert au README et a StructuredOutput."""

    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def log(self, kind: str, msg: str) -> None:
        line = f"[{kind}] {msg}"
        print(line)
        if kind == "warn":
            self.warnings.append(msg)


# ---------------------------------------------------------------------------
# Catalogue : decrit la bibliotheque cible (RootA + RootB)
# ---------------------------------------------------------------------------


def build_catalog() -> tuple[list[ClipSpec], list[StubSpec], list[ClipSpec], list[StubSpec]]:
    """
    Retourne (clips_A, stubs_A, clips_B, stubs_B).

    Le contenu est figure (pas de randomisation des noms) pour rester
    reproductible entre executions.
    """

    # --- RootA : varietes de cas "nominaux" + accents/FR + japonais + saga
    clips_a: list[ClipSpec] = [
        ClipSpec(
            relpath="Movies/Big Buck Bunny (2008)/Big Buck Bunny (2008).mp4",
            source_key="big_buck_bunny",
            trim_seconds=30,
            note="Clip CC reel (Blender Foundation), nom propre tres TMDb-friendly",
        ),
        ClipSpec(
            relpath="Movies/Sintel (2010)/Sintel (2010).mp4",
            source_key="sintel",
            trim_seconds=30,
            note="Clip CC reel (Blender Foundation)",
        ),
    ]

    stubs_a: list[StubSpec] = [
        StubSpec(
            relpath="Movies/Inception (2010)/Inception (2010).mkv",
            size_bytes=1_800_000,
            note="Nom propre canonique, gros titre TMDb attendu",
        ),
        StubSpec(
            relpath="Movies/the.matrix.1999.brrip/the matrix.avi",
            size_bytes=900_000,
            note="Mal nomme : dossier en lowercase point, fichier sans annee",
        ),
        StubSpec(
            relpath="Movies/Parasite/Parasite.mkv",
            size_bytes=1_200_000,
            note="Annee MANQUANTE dans nom et dossier",
        ),
        StubSpec(
            relpath="Movies/Le Fabuleux Destin d Amelie Poulain (2001)/"
                    "Le Fabuleux Destin d Amelie Poulain (2001).mkv",
            size_bytes=1_500_000,
            note="Accents FR + apostrophe remplacee par espace (shell-safe)",
        ),
        StubSpec(
            relpath="Movies/Sen to Chihiro no Kamikakushi (2001)/"
                    "Sen to Chihiro no Kamikakushi (2001).mkv",
            size_bytes=1_400_000,
            note="Titre etranger japonais (translitteration romaji)",
        ),
        # Saga Dune
        StubSpec(
            relpath="Movies/Dune (2021)/Dune (2021).mkv",
            size_bytes=1_700_000,
            note="Saga Dune - episode 1",
        ),
        StubSpec(
            relpath="Movies/Dune Part Two (2024)/Dune Part Two (2024).mkv",
            size_bytes=1_700_000,
            note="Saga Dune - episode 2",
        ),
    ]

    # --- RootB : doublons, faux 4K, mauvais re-encode, NFO, series TV
    clips_b: list[ClipSpec] = [
        ClipSpec(
            relpath="Movies/Tears of Steel (2012)/Tears of Steel (2012) 1080p.mkv",
            source_key="tears_of_steel",
            trim_seconds=30,
            note="Clip CC reel utilise comme base 1080p",
        ),
        ClipSpec(
            relpath="Movies/Tears of Steel (2012)/Tears of Steel (2012) 720p.mkv",
            source_key="tears_of_steel",
            trim_seconds=30,
            transform="downscale_720p",
            note="DOUBLON volontaire du meme clip CC, encode 720p",
        ),
        ClipSpec(
            relpath="Movies/FakeUpscale (2020)/FakeUpscale (2020) 2160p.mp4",
            source_key="big_buck_bunny",
            trim_seconds=20,
            transform="upscale_4k",
            note="FAUX 4K : 720p upscale en 2160p, AUCUN match TMDb attendu",
        ),
        ClipSpec(
            relpath="Movies/BadReencode (2019)/BadReencode (2019).mp4",
            source_key="sintel",
            trim_seconds=20,
            transform="bad_reencode",
            note="Re-encode tres degrade (bitrate bas, CRF eleve)",
        ),
    ]

    stubs_b: list[StubSpec] = [
        # Doublons The Matrix encore non resolvables (clips CC pas dispo
        # pour ce titre) : on garde des stubs differencies par taille.
        StubSpec(
            relpath="Movies/The Matrix (1999)/The Matrix (1999) 1080p.mkv",
            size_bytes=1_900_000,
            note="Doublon 1080p de The Matrix (stub, pas clip CC)",
        ),
        StubSpec(
            relpath="Movies/The Matrix (1999)/The Matrix (1999) 720p.mkv",
            size_bytes=1_100_000,
            note="Doublon 720p de The Matrix (stub, pas clip CC)",
        ),
        # Series TV : trois conventions de nommage SxxExx
        StubSpec(
            relpath="Shows/Breaking Bad/Season 01/Breaking Bad S01E01.mkv",
            size_bytes=800_000,
            note="Serie TV nommage standard SxxExx",
        ),
        StubSpec(
            relpath="Shows/Breaking Bad/Season 01/Breaking Bad S01x02.mkv",
            size_bytes=800_000,
            note="Serie TV nommage SxxExx variante (x au lieu de E)",
        ),
        StubSpec(
            relpath="Shows/Breaking Bad/Saison 1/"
                    "Breaking Bad Saison 1 Episode 3.mkv",
            size_bytes=800_000,
            note="Serie TV nommage FR verbeux (Saison N Episode N)",
        ),
        # NFO Jellyfin/Kodi : Night of the Living Dead, avec ID IMDb
        StubSpec(
            relpath="Movies/Night of the Living Dead (1968)/"
                    "Night of the Living Dead (1968).mkv",
            size_bytes=1_000_000,
            note="Domaine public, avec movie.nfo contenant l'ID IMDb",
            nfo_imdb_id="tt0063350",
            nfo_title="Night of the Living Dead",
            nfo_year=1968,
        ),
        StubSpec(
            relpath="Movies/Nosferatu (1922)/Nosferatu (1922).mkv",
            size_bytes=1_000_000,
            note="Domaine public, SANS movie.nfo (a resoudre par TMDb)",
        ),
    ]

    return clips_a, stubs_a, clips_b, stubs_b


# ---------------------------------------------------------------------------
# Utilitaires bas niveau
# ---------------------------------------------------------------------------


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def deterministic_bytes(size: int, seed_key: str) -> bytes:
    """
    Genere `size` octets pseudo-aleatoires mais reproductibles pour une
    cle donnee. Utilise pour les stubs : on veut le meme contenu d'une
    execution a l'autre afin que les hash de deduplication soient stables.
    """
    rnd = random.Random()
    digest = hashlib.sha256(seed_key.encode("utf-8")).digest()
    rnd.seed(int.from_bytes(digest[:8], "big") ^ RANDOM_SEED)
    return bytes(rnd.getrandbits(8) for _ in range(size))


def download_to_cache(
    clip: CreativeCommonsClip,
    report: BuildReport,
    timeout: int = 30,
) -> Path | None:
    """
    Telecharge `clip` dans le cache si absent. Retourne le chemin local
    ou None si le telechargement a echoue (le caller fera un fallback
    stub).
    """
    ensure_dir(CACHE_DIR)
    suffix = clip.url.rsplit(".", 1)[-1].lower()
    cache_path = CACHE_DIR / f"{clip.key}.{suffix}"

    if cache_path.exists() and cache_path.stat().st_size > 0:
        report.log("skip", f"cache hit {cache_path.name}")
        return cache_path

    try:
        report.log("dl", f"{clip.url} -> {cache_path.name}")
        # Beaucoup de CDN (dont download.blender.org) refusent les
        # requetes sans User-Agent. On en fournit un explicite.
        req = urlrequest.Request(
            clip.url,
            headers={
                "User-Agent": "CineSort-test-library/1.0 (+make_test_library.py)"
            },
        )
        with urlrequest.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = resp.read()
        cache_path.write_bytes(data)
        report.log("ok", f"telecharge {human_size(len(data))} {cache_path.name}")
        return cache_path
    except (URLError, TimeoutError, OSError) as exc:
        report.log("warn", f"telechargement KO {clip.key}: {exc}")
        # On nettoie un fichier partiel
        if cache_path.exists():
            try:
                cache_path.unlink()
            except OSError:
                pass
        return None


def run_ffmpeg(args: list[str], report: BuildReport) -> bool:
    """Execute ffmpeg en silencieux. Retourne True si exit code == 0."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *args]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        report.log("warn", "ffmpeg introuvable au moment de l'execution")
        return False
    if proc.returncode != 0:
        report.log("warn", f"ffmpeg KO ({proc.returncode}): {proc.stderr.strip()[:200]}")
        return False
    return True


# ---------------------------------------------------------------------------
# Generation : stubs, clips, NFO
# ---------------------------------------------------------------------------


def create_stub(root: Path, spec: StubSpec, report: BuildReport) -> None:
    target = root / spec.relpath
    ensure_dir(target.parent)

    if target.exists() and target.stat().st_size == spec.size_bytes:
        report.log("skip", f"stub deja present {target.relative_to(LIBRARY_ROOT)}")
    else:
        # Borne la taille dans [100 KB, 2 MB] meme si la spec deborde
        size = max(100 * 1024, min(spec.size_bytes, 2 * 1024 * 1024))
        payload = deterministic_bytes(size, seed_key=spec.relpath)
        target.write_bytes(payload)
        report.log(
            "create stub",
            f"{target.relative_to(LIBRARY_ROOT)} ({human_size(size)})",
        )
        report.created.append(str(target.relative_to(LIBRARY_ROOT)))

    if spec.nfo_imdb_id:
        write_movie_nfo(
            target.parent,
            title=spec.nfo_title or target.parent.name,
            year=spec.nfo_year,
            imdb_id=spec.nfo_imdb_id,
            report=report,
        )


def write_movie_nfo(
    folder: Path,
    *,
    title: str,
    year: int | None,
    imdb_id: str,
    report: BuildReport,
) -> None:
    nfo_path = folder / "movie.nfo"
    if nfo_path.exists():
        report.log("skip", f"nfo deja present {nfo_path.relative_to(LIBRARY_ROOT)}")
        return
    year_xml = f"  <year>{year}</year>\n" if year else ""
    content = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        "<movie>\n"
        f"  <title>{title}</title>\n"
        f"{year_xml}"
        f"  <imdbid>{imdb_id}</imdbid>\n"
        f"  <uniqueid type=\"imdb\" default=\"true\">{imdb_id}</uniqueid>\n"
        "</movie>\n"
    )
    nfo_path.write_text(content, encoding="utf-8")
    report.log("nfo", f"{nfo_path.relative_to(LIBRARY_ROOT)} -> {imdb_id}")
    report.created.append(str(nfo_path.relative_to(LIBRARY_ROOT)))


def create_clip(
    root: Path,
    spec: ClipSpec,
    report: BuildReport,
    ffmpeg_ok: bool,
) -> None:
    target = root / spec.relpath
    ensure_dir(target.parent)

    if target.exists() and target.stat().st_size > 50 * 1024:
        report.log("skip", f"clip deja present {target.relative_to(LIBRARY_ROOT)}")
        return

    clip = CC_CLIPS[spec.source_key]
    source = download_to_cache(clip, report)

    if source is None or not ffmpeg_ok:
        # Fallback : on cree un stub equivalent pour ne pas bloquer le scan
        fallback_size = 1_500_000
        payload = deterministic_bytes(fallback_size, seed_key=spec.relpath)
        target.write_bytes(payload)
        report.log(
            "create stub",
            f"FALLBACK {target.relative_to(LIBRARY_ROOT)} ({human_size(fallback_size)})",
        )
        report.created.append(str(target.relative_to(LIBRARY_ROOT)))
        return

    # ffmpeg : trim + transform optionnel
    args: list[str] = ["-ss", "0", "-t", str(spec.trim_seconds), "-i", str(source)]

    if spec.transform == "upscale_4k":
        args += [
            "-vf", "scale=3840:2160:flags=neighbor",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
            "-c:a", "aac", "-b:a", "96k",
        ]
    elif spec.transform == "bad_reencode":
        args += [
            "-c:v", "libx264", "-preset", "ultrafast",
            "-b:v", "200k", "-crf", "40",
            "-c:a", "aac", "-b:a", "64k",
        ]
    elif spec.transform == "downscale_720p":
        args += [
            "-vf", "scale=1280:720",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
            "-c:a", "aac", "-b:a", "128k",
        ]
    else:
        # Trim simple (re-encode rapide pour garantir un fichier autonome)
        args += [
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
            "-c:a", "aac", "-b:a", "128k",
        ]

    args.append(str(target))

    report.log(
        "ffmpeg",
        f"{spec.transform or 'trim'} -> {target.relative_to(LIBRARY_ROOT)}",
    )
    ok = run_ffmpeg(args, report)
    if not ok:
        # Si ffmpeg echoue, on retombe sur un stub
        fallback_size = 1_500_000
        payload = deterministic_bytes(fallback_size, seed_key=spec.relpath)
        target.write_bytes(payload)
        report.log(
            "create stub",
            f"FALLBACK ffmpeg-KO {target.relative_to(LIBRARY_ROOT)}",
        )
        report.created.append(str(target.relative_to(LIBRARY_ROOT)))
    else:
        report.created.append(str(target.relative_to(LIBRARY_ROOT)))


# ---------------------------------------------------------------------------
# Listing (post-build) : sert au README et au compteur
# ---------------------------------------------------------------------------


def iter_library_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and not p.name.startswith(".")
    )


def count_files_in_library() -> int:
    total = 0
    for r in (ROOT_A, ROOT_B):
        for _ in iter_library_files(r):
            total += 1
    return total


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------


def render_readme(
    clips_a: list[ClipSpec],
    stubs_a: list[StubSpec],
    clips_b: list[ClipSpec],
    stubs_b: list[StubSpec],
    report: BuildReport,
) -> str:
    def fmt_clip(c: ClipSpec) -> str:
        return (
            f"- `{c.relpath}`\n"
            f"  - Source CC : **{c.source_key}** "
            f"({CC_CLIPS[c.source_key].license}, {CC_CLIPS[c.source_key].credit})\n"
            f"  - Transform : `{c.transform or 'trim ' + str(c.trim_seconds) + 's'}`\n"
            f"  - Note : {c.note}\n"
        )

    def fmt_stub(s: StubSpec) -> str:
        nfo = f" + movie.nfo ({s.nfo_imdb_id})" if s.nfo_imdb_id else ""
        return (
            f"- `{s.relpath}` (~{human_size(s.size_bytes)}){nfo}\n"
            f"  - Note : {s.note}\n"
        )

    body = textwrap.dedent(
        """
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

        """
    ).strip() + "\n\n"
    for clip in CC_CLIPS.values():
        body += f"- **{clip.key}** -- {clip.license} -- {clip.credit}\n"
        body += f"  - URL : <{clip.url}>\n"
    body += "\n## RootA -- cas nominaux + accents FR + saga\n\n"
    body += "### Clips CC reels (ffmpeg trim)\n\n"
    body += "".join(fmt_clip(c) for c in clips_a) or "_aucun_\n"
    body += "\n### Stubs (fichiers tronques)\n\n"
    body += "".join(fmt_stub(s) for s in stubs_a)
    body += "\n## RootB -- doublons, faux 4K, NFO, series TV\n\n"
    body += "### Clips CC reels\n\n"
    body += "".join(fmt_clip(c) for c in clips_b) or "_aucun_\n"
    body += "\n### Stubs\n\n"
    body += "".join(fmt_stub(s) for s in stubs_b)

    body += "\n## Statistiques de la derniere generation\n\n"
    body += f"- Fichiers crees ou re-ecrits : {len(report.created)}\n"
    body += f"- Avertissements : {len(report.warnings)}\n"
    if report.warnings:
        body += "\n<details><summary>Liste des warnings</summary>\n\n"
        for w in report.warnings:
            body += f"- {w}\n"
        body += "\n</details>\n"
    body += (
        "\n---\n"
        "_Aucun fichier sous droits n'est jamais produit ou telecharge par "
        "ce script : seuls des clips Creative Commons sont utilises._\n"
    )
    return body


def write_readme(
    clips_a: list[ClipSpec],
    stubs_a: list[StubSpec],
    clips_b: list[ClipSpec],
    stubs_b: list[StubSpec],
    report: BuildReport,
) -> None:
    ensure_dir(LIBRARY_ROOT)
    readme_path = LIBRARY_ROOT / "README.md"
    content = render_readme(clips_a, stubs_a, clips_b, stubs_b, report)
    if readme_path.exists() and readme_path.read_text(encoding="utf-8") == content:
        report.log("skip", "README.md inchange")
        return
    readme_path.write_text(content, encoding="utf-8")
    report.log("readme", f"{readme_path.relative_to(LIBRARY_ROOT)} ({len(content)} chars)")


# ---------------------------------------------------------------------------
# Orchestrateur
# ---------------------------------------------------------------------------


def main() -> int:
    report = BuildReport()
    ensure_dir(LIBRARY_ROOT)
    ensure_dir(ROOT_A)
    ensure_dir(ROOT_B)

    ffmpeg_ok = has_ffmpeg()
    if not ffmpeg_ok:
        report.log("warn", "ffmpeg introuvable, fallback stubs pour tous les clips")

    clips_a, stubs_a, clips_b, stubs_b = build_catalog()

    print("\n=== RootA ===")
    for spec in stubs_a:
        create_stub(ROOT_A, spec, report)
    for spec in clips_a:
        create_clip(ROOT_A, spec, report, ffmpeg_ok)

    print("\n=== RootB ===")
    for spec in stubs_b:
        create_stub(ROOT_B, spec, report)
    for spec in clips_b:
        create_clip(ROOT_B, spec, report, ffmpeg_ok)

    print("\n=== README ===")
    write_readme(clips_a, stubs_a, clips_b, stubs_b, report)

    total = count_files_in_library()
    print(
        f"\n[ok] terminee : {total} fichier(s) dans {LIBRARY_ROOT.relative_to(REPO_ROOT)}, "
        f"{len(report.warnings)} warning(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""#792 — enrichissement des rows TV : ce que `_plan_tv_episode` doit poser,
et ce qu'il doit DELIBEREMENT ne pas poser.

`_plan_item` (films) applique quatre enrichissements. L'issue demandait de les
transposer tous a `_plan_tv_episode`. L'arbitrage retenu est partiel :

* `year_missing` + `integrity_header_invalid` sont AGNOSTIQUES du kind -> poses.
* `subtitle_*` est refuse : le comptage d'orphelins de `build_subtitle_report`
  qualifie d'orphelin tout sous-titre du dossier ne matchant pas le stem de la
  video courante, or un dossier de saison contient N episodes. Le test
  `test_subtitle_report_would_flag_every_episode_as_orphan` MESURE ce faux
  positif : c'est la justification du refus, pas une opinion.
* `not_a_movie` est refuse : flag de CONFLIT calibre pour des films, alors qu'un
  episode est par construction « pas un film » (l'info est deja dans `kind`).

Les deux tests d'absence verrouillent l'arbitrage : une « completion » future
les fera rougir au lieu de passer en silence.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

import cinesort.domain.core as core
from cinesort.app.plan_support_replan import _plan_tv_episode
from cinesort.domain.subtitle_helpers import build_subtitle_report

# EBML : premiers octets d'un vrai conteneur Matroska.
_MKV_MAGIC = bytes([0x1A, 0x45, 0xDF, 0xA3])
_PADDING = b"\x00" * 2048


def _log(_level: str, _msg: str) -> None:
    return None


def _cfg(root: Path) -> core.Config:
    return core.Config(root=root, enable_tv_detection=True, enable_tmdb=False)


def _write_episode(folder: Path, name: str, *, valid_header: bool = True) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes((_MKV_MAGIC if valid_header else b"\x00\x00\x00\x00") + _PADDING)
    return path


def _plan_one(root: Path, folder: Path, video: Path) -> core.PlanRow:
    rows: List[core.PlanRow] = _plan_tv_episode(_cfg(root), folder, video, None, _log)
    assert len(rows) == 1, f"attendu 1 row TV pour {video.name}, obtenu {rows}"
    return rows[0]


# ── integrity_header_invalid ─────────────────────────────────────────


def test_corrupt_episode_header_is_flagged(tmp_path: Path) -> None:
    """Un en-tete video invalide bloque l'auto-approbation d'un FILM
    (`_AUTO_INTEGRITY_WARNINGS`) ; il doit le faire aussi pour un episode."""
    folder = tmp_path / "Breaking Bad" / "Saison 1"
    video = _write_episode(folder, "Breaking.Bad.S01E01.mkv", valid_header=False)

    row = _plan_one(tmp_path, folder, video)

    assert "integrity_header_invalid" in row.warning_flags, (
        f"episode a l'en-tete corrompu non signale : flags={row.warning_flags}"
    )


def test_valid_episode_header_is_not_flagged(tmp_path: Path) -> None:
    folder = tmp_path / "Breaking Bad" / "Saison 1"
    video = _write_episode(folder, "Breaking.Bad.S01E02.mkv", valid_header=True)

    row = _plan_one(tmp_path, folder, video)

    assert "integrity_header_invalid" not in row.warning_flags, (
        f"faux positif d'integrite sur un MKV valide : flags={row.warning_flags}"
    )


# ── year_missing ─────────────────────────────────────────────────────


def test_episode_without_year_is_flagged_year_missing(tmp_path: Path) -> None:
    """`naming_tv_template` vaut `{series} ({year})` : sans annee, le dossier de
    serie perd sa desambiguisation. La row n'etait deja pas auto-approuvable
    (has_year >= 1900) mais aucune chip n'expliquait pourquoi."""
    folder = tmp_path / "Lost" / "Saison 1"
    video = _write_episode(folder, "Lost.S01E01.mkv")

    row = _plan_one(tmp_path, folder, video)

    assert row.proposed_year == 0, f"premisse cassee : annee resolue ({row.proposed_year})"
    assert "year_missing" in row.warning_flags, f"annee absente non signalee : flags={row.warning_flags}"


def test_episode_with_year_is_not_flagged_year_missing(tmp_path: Path) -> None:
    folder = tmp_path / "Fargo (2014)" / "Saison 1"
    video = _write_episode(folder, "Fargo.2014.S01E01.mkv")

    row = _plan_one(tmp_path, folder, video)

    assert row.proposed_year >= 1900, f"premisse cassee : annee non extraite ({row.proposed_year})"
    assert "year_missing" not in row.warning_flags, f"faux positif year_missing : flags={row.warning_flags}"


def test_year_missing_flag_is_never_duplicated(tmp_path: Path) -> None:
    folder = tmp_path / "Lost" / "Saison 1"
    video = _write_episode(folder, "Lost.S01E03.mkv", valid_header=False)

    row = _plan_one(tmp_path, folder, video)

    assert row.warning_flags.count("year_missing") == 1, f"flag double : {row.warning_flags}"


# ── arbitrage : sous-titres NON transposes ───────────────────────────


def test_subtitle_report_would_flag_every_episode_as_orphan(tmp_path: Path) -> None:
    """MESURE du faux positif qui justifie le refus.

    Trois episodes, chacun avec SON `.fr.srt` correctement nomme : aucun
    orphelin reel. `build_subtitle_report` en compte pourtant 2 par episode
    (les sous-titres des deux autres), soit `subtitle_orphan` sur 100 % des rows
    si `_apply_subtitle_detection` etait branche ici.
    """
    folder = tmp_path / "Serie" / "Saison 1"
    folder.mkdir(parents=True)
    videos = []
    for num in (1, 2, 3):
        videos.append(_write_episode(folder, f"Serie.S01E0{num}.mkv"))
        (folder / f"Serie.S01E0{num}.fr.srt").write_text("1", encoding="utf-8")

    orphan_counts = [build_subtitle_report(folder, video, ["fr"]).orphans for video in videos]

    assert orphan_counts == [2, 2, 2], (
        "premisse de l'arbitrage #792 cassee : build_subtitle_report ne "
        f"sur-compte plus les orphelins d'un dossier de saison ({orphan_counts}). "
        "Si le comptage est devenu per-video, _apply_subtitle_detection peut et "
        "doit etre branche dans _plan_tv_episode."
    )


def test_tv_rows_carry_no_subtitle_flag_nor_counters(tmp_path: Path) -> None:
    """Verrou de l'arbitrage : tant que le sur-comptage ci-dessus existe, aucune
    row TV ne doit porter de signal sous-titres."""
    folder = tmp_path / "Serie" / "Saison 1"
    folder.mkdir(parents=True)
    videos = []
    for num in (1, 2, 3):
        videos.append(_write_episode(folder, f"Serie.S01E0{num}.mkv"))
        (folder / f"Serie.S01E0{num}.fr.srt").write_text("1", encoding="utf-8")

    for video in videos:
        row = _plan_one(tmp_path, folder, video)
        assert "subtitle_orphan" not in row.warning_flags, (
            f"faux positif subtitle_orphan sur {video.name} : flags={row.warning_flags}"
        )
        assert not [f for f in row.warning_flags if f.startswith("subtitle_missing_")], (
            f"flag subtitle_missing_* sur une row TV : flags={row.warning_flags}"
        )
        assert row.subtitle_orphans == 0
        assert row.subtitle_count == 0


# ── arbitrage : not_a_movie NON transpose ────────────────────────────


@pytest.mark.parametrize(
    "filename",
    [
        # Petit fichier + titre de serie court : score film eleve, mais ce n'est
        # qu'un episode ordinaire.
        "Lost.S01E04.mkv",
        # Mot-cle « recap » du vocabulaire not_a_movie, courant en titre d'episode.
        "Lost.S01E05.The.Recap.mkv",
    ],
)
def test_tv_rows_never_carry_not_a_movie(tmp_path: Path, filename: str) -> None:
    """`not_a_movie` est un flag de CONFLIT calibre pour des films. Un episode
    est deja identifie comme tel par `kind`, le poser en plus transformerait un
    fait de structure en incoherence a arbitrer."""
    folder = tmp_path / "Lost" / "Saison 1"
    video = _write_episode(folder, filename)

    row = _plan_one(tmp_path, folder, video)

    assert row.kind == "tv_episode"
    assert "not_a_movie" not in row.warning_flags, f"flag film pose sur un episode : flags={row.warning_flags}"

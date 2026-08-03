"""BASELINE R8 — captures DETERMINISTES de resultats silencieusement FAUX.

Pure-function / pure-construction : importe les VRAIES fonctions du code prod et
imprime les valeurs reelles + un bloc RESUME json. Aucun ffmpeg/ffprobe/reseau
n'est lance. Les rares effets de bord (cache TMDb, settings) restent confines
dans des tempfile jetables ; le code de la lib n'est JAMAIS modifie.

Usage (depuis la racine repo) :
  PYTHONPATH=. .venv313/Scripts/python.exe \
    docs/internal/baseline_r8/captures/cap_false_results.py \
    > docs/internal/baseline_r8/captures/cap_false_results.out.txt 2>&1

Findings couverts :
  F-H4-01  quality_score._normalize_audio_bitrate_kbps : seuil bps strict > 10000,
           donc un flux 8000 bps (8 kbps misere) est lu comme 8000 kbps -> bonus.
  F-H5-01  title_helpers.clean_title_guess (delegue scene_parser.parse_scene_title) :
           'DD5.1' devient 'DD5 1' apres le replace '.'->' ' et survit au NOISE_RE.
  F-CONF-01 settings_support._save_section_probe persiste ffprobe_path=calc.exe sans
           validation, alors que infra/probe/tooling._binary_name_allowed le refuse.
  F-H7-01  tmdb_client.search_movie : un 200 {results:[]} ecrit [] en cache (TTL 7j) ;
           la re-recherche rend [] sans re-fetch meme si un vrai resultat est dispo.
  F-PERC-01 audio_perceptual.analyze_loudnorm force '-v quiet' alors qu'il lit le JSON
           loudnorm dans stderr (emis au niveau info) -> stderr vide -> None.
  F-PERC-02 video_analysis.run_filter_graph (l.90) construit le filtre signalstats SANS
           'metadata=mode=print' -> aucun 'YAVG=' en stderr -> 0 frame parsee.
  F-PERC-03 audio_perceptual : Crest factor / Dynamic range de ffmpeg astats reel
           apparaissent par-canal, pas dans le bloc Overall -> _extract_overall_block
           les coupe -> crest/dynamic_range = None.

NOTE GENERALE : une valeur "fausse" peut etre un choix de design legitime selon le
contexte. Ce harnais CAPTURE l'etat reel ; le jugement bug/non-bug reste a faire.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

SEP = "=" * 78


def section(title: str) -> None:
    print(f"\n{SEP}\n{title}\n{SEP}")


# ---------------------------------------------------------------------------
# F-H4-01 — normalisation bitrate AUDIO : seuil bps strict > 10000
# ---------------------------------------------------------------------------
def cap_h4_01() -> Dict[str, Any]:
    section("F-H4-01  quality_score._normalize_audio_bitrate_kbps (seuil bps > 10000 STRICT)")
    from cinesort.domain.quality_score import _normalize_audio_bitrate_kbps

    cases = [8000, 10000, 10001, 48000, 192000, 640000]
    out: Dict[str, Any] = {}
    print("  source : cinesort/domain/quality_score.py:538 (seuil 'n > 10000.0' l.563)")
    for raw in cases:
        kbps = _normalize_audio_bitrate_kbps(raw)
        # reproduction du calcul per_channel utilise par le scorer (l.973), 6 canaux
        per_channel = (float(kbps) / 6.0) if kbps else None
        bonus = None
        if per_channel is not None:
            if per_channel >= 650:
                bonus = "+4 'Debit audio eleve'"
            elif per_channel >= 320:
                bonus = "+2 'Debit audio correct'"
            elif per_channel < 120:
                bonus = "-3 'Debit audio faible'"
            else:
                bonus = "0"
        out[str(raw)] = kbps
        tag = ""
        if raw == 8000:
            tag = "  <-- 8000 bps (=8 kbps, AAC mono pourri) lu comme 8000 kbps"
        elif raw == 10000:
            tag = "  <-- 10000 bps NON divise (seuil strict) -> 10000 kbps"
        elif raw == 10001:
            tag = "  <-- juste au-dessus du seuil -> divise -> 10 kbps (cliff)"
        print(f"  in={raw:>7} bps -> normalize={kbps!r:>7} kbps | per_channel(6ch)={per_channel} -> bonus={bonus}{tag}")

    bug_8000 = out["8000"] == 8000
    cliff = out["10000"] == 10000 and out["10001"] == 10
    print(f"\n  8000 bps note comme 8000 kbps (bonus +4) : {bug_8000}")
    print(f"  cliff 10000->10000 kbps mais 10001->10 kbps : {cliff}")
    return {
        "out": out,
        "bug_8kbps_scored_as_bonus": bug_8000,
        "threshold_strict_cliff": cliff,
    }


# ---------------------------------------------------------------------------
# F-H5-01 — clean_title_guess laisse 'DD5 1' residuel
# ---------------------------------------------------------------------------
def cap_h5_01() -> Dict[str, Any]:
    section("F-H5-01  clean_title_guess : residu 'DD5 1' (DD5.1 casse par le replace '.')")
    # Le symbole demande 'scene_parser.clean_title_guess' n'existe PAS : la vraie
    # fonction publique est title_helpers.clean_title_guess (re-exportee par
    # domain.core), qui delegue a scene_parser.parse_scene_title.
    from cinesort.domain.scene_parser import parse_scene_title
    from cinesort.domain.title_helpers import clean_title_guess

    print("  NOTE drift symbole : 'scene_parser.clean_title_guess' inexistant.")
    print("  Vraie fonction = title_helpers.clean_title_guess (l.254) -> delegue")
    print("  scene_parser.parse_scene_title (l.327). Mecanisme : replace '.'->' '")
    print("  (l.378) transforme 'DD5.1' en 'DD5 1' AVANT _NOISE_RE (l.398) dont le")
    print("  motif 'dd5\\.?1' n'admet pas d'espace ; _AUDIO_RESIDUE_RE exige \\b")
    print("  avant le chiffre, absent dans 'DD5' -> residu conserve.\n")

    samples = {
        "F-H5-01 sujet": "Joker.2019.DD5.1.1080p.BluRay.x264-GROUP.mkv",
        "controle propre": "Inception.2010.1080p.BluRay.x264",
    }
    out: Dict[str, Any] = {}
    for label, name in samples.items():
        cleaned = clean_title_guess(name)
        parsed = parse_scene_title(name)
        out[label] = cleaned
        print(f"  [{label}]")
        print(f"    in     = {name!r}")
        print(f"    cleaned= {cleaned!r}   (parse_scene_title={parsed!r})")

    joker = out["F-H5-01 sujet"]
    has_dd = bool(re.search(r"\bDD5\b", joker, re.IGNORECASE)) or "DD5 1" in joker
    ctrl = out["controle propre"]
    ctrl_clean = ctrl == "Inception 2010"
    print(f"\n  Joker conserve un residu 'DD5'/'DD5 1' : {has_dd}  (cleaned={joker!r})")
    print(f"  Controle Inception propre ('Inception 2010') : {ctrl_clean}")
    return {
        "joker_cleaned": joker,
        "joker_keeps_dd5_residue": has_dd,
        "control_inception": ctrl,
        "control_clean": ctrl_clean,
    }


# ---------------------------------------------------------------------------
# F-CONF-01 — asymetrie persist (aucune validation) vs resolver (whitelist)
# ---------------------------------------------------------------------------
def cap_conf_01() -> Dict[str, Any]:
    section("F-CONF-01  _save_section_probe persiste calc.exe ; _binary_name_allowed le refuse")
    from cinesort.infra.probe.tooling import EXPECTED_BINARY_NAMES, _binary_name_allowed
    from cinesort.ui.api.settings_support import _save_section_probe

    bogus = "C:/Windows/System32/calc.exe"
    payload = {
        "probe_backend": "ffprobe",
        "ffprobe_path": bogus,
        "mediainfo_path": "",
        "probe_timeout_s": 30.0,
        "probe_workers": 0,
        "probe_parallelism_enabled": True,
    }
    saved = _save_section_probe(payload, default_probe_backend="auto")
    persisted = saved.get("ffprobe_path")
    allowed = _binary_name_allowed("ffprobe", bogus)

    print("  source persist  : cinesort/ui/api/settings_support.py:1366 (_save_section_probe)")
    print("  source resolver : cinesort/infra/probe/tooling.py:30 (_binary_name_allowed)")
    print(f"  EXPECTED_BINARY_NAMES['ffprobe'] = {sorted(EXPECTED_BINARY_NAMES['ffprobe'])}\n")
    print(f"  payload ffprobe_path                     = {bogus!r}")
    print(f"  _save_section_probe -> persiste tel quel : {persisted!r}")
    print(f"  _binary_name_allowed('ffprobe', calc)    = {allowed}")
    asymmetry = (persisted == bogus) and (allowed is False)
    print(f"\n  ASYMETRIE (persiste sans valider, mais resolver refuse) : {asymmetry}")
    return {
        "persisted": persisted,
        "binary_name_allowed": allowed,
        "asymmetry": asymmetry,
    }


# ---------------------------------------------------------------------------
# F-H7-01 — cache TMDb empoisonne par un 200 {results:[]}
# ---------------------------------------------------------------------------
class _FakeResp:
    """Stub minimal de requests.Response pour search_movie."""

    def __init__(self, payload: Dict[str, Any], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.content = json.dumps(payload).encode("utf-8")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Dict[str, Any]:
        return self._payload


def cap_h7_01() -> Dict[str, Any]:
    section("F-H7-01  tmdb_client.search_movie : 200 {results:[]} empoisonne le cache 7j")
    from cinesort.infra.tmdb_client import TmdbClient

    tmp = Path(tempfile.mkdtemp(prefix="cs_tmdb_cache_"))
    cache_path = tmp / "tmdb_cache.json"
    client = TmdbClient(api_key="DUMMY", cache_path=cache_path)

    # Sequence de reponses injectees a la place du reseau : d'abord vide (TMDb
    # transitoirement sans resultat), puis un vrai film. On patche l'instance
    # uniquement (aucune modif du module / code prod).
    state = {"phase": "empty"}

    def fake_http_get(url: str, *, params: Optional[Dict[str, Any]] = None) -> _FakeResp:
        if state["phase"] == "empty":
            return _FakeResp({"results": []})
        return _FakeResp(
            {
                "results": [
                    {
                        "id": 475557,
                        "title": "Joker",
                        "release_date": "2019-10-02",
                        "original_title": "Joker",
                        "popularity": 9.9,
                        "vote_count": 1000,
                        "vote_average": 8.2,
                        "poster_path": "/x.jpg",
                    },
                ]
            }
        )

    client._http_get = fake_http_get  # type: ignore[assignment]

    print("  source : cinesort/infra/tmdb_client.py:431 (search_movie), cache l.515")
    print("  cle search => TTL court _SEARCH_CACHE_TTL_S = 7j (l.45)\n")

    r1 = client.search_movie("Joker", year=2019)
    print(f"  appel #1 (TMDb renvoie 200 results:[]) -> {len(r1)} resultat(s)")

    cache_after_empty = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    poisoned_keys = {k: v.get("value") if isinstance(v, dict) else v for k, v in cache_after_empty.items()}
    print(f"  cache disque apres #1 : {json.dumps(poisoned_keys, ensure_ascii=False)}")

    # Le vrai resultat est maintenant disponible cote 'API'...
    state["phase"] = "real"
    r2 = client.search_movie("Joker", year=2019)
    print(
        f"  appel #2 (TMDb renverrait Joker) -> {len(r2)} resultat(s) "
        f"(re-fetch ? {'NON, sert le cache []' if len(r2) == 0 else 'oui'})"
    )

    # Preuve falsifiable : une cle differente (non empoisonnee) renvoie bien le film.
    r3 = client.search_movie("Inception", year=2010)
    print(
        f"  appel #3 (cle differente, non empoisonnee) -> {len(r3)} resultat(s) "
        f"(prouve que le stub PEUT rendre un vrai resultat)"
    )

    poisoned = (len(r1) == 0) and (len(r2) == 0) and (len(r3) >= 1)
    print(f"\n  CACHE EMPOISONNE (re-search reste 0 alors qu'un vrai resultat existe) : {poisoned}")
    return {
        "first_empty": len(r1),
        "second_after_real_available": len(r2),
        "control_other_key": len(r3),
        "cache_poisoned": poisoned,
    }


# ---------------------------------------------------------------------------
# F-PERC-01 — argv loudnorm force '-v quiet' (incompatible lecture stderr)
# ---------------------------------------------------------------------------
def cap_perc_01() -> Dict[str, Any]:
    section("F-PERC-01  analyze_loudnorm : argv force '-v quiet' mais lit le JSON dans stderr")
    import cinesort.domain.perceptual.audio_perceptual as ap

    captured: Dict[str, Any] = {}

    def fake_run(cmd, timeout_s):
        captured["cmd"] = list(cmd)
        # Au niveau '-v quiet', ffmpeg n'emet PAS le bloc loudnorm : stderr vide.
        # On simule fidelement ce comportement (stderr = "").
        return (0, "", "")

    orig = ap.run_ffmpeg_text
    ap.run_ffmpeg_text = fake_run  # type: ignore[assignment]
    try:
        result = ap.analyze_loudnorm("ffmpeg", "movie.mkv", 0)
    finally:
        ap.run_ffmpeg_text = orig

    cmd = captured.get("cmd", [])
    cmd_str = " ".join(cmd)
    has_quiet = ("-v" in cmd) and (cmd[cmd.index("-v") + 1] == "quiet" if "-v" in cmd else False)
    reads_stderr = True  # confirme par lecture du code (l.145-148 : if not stderr -> None)
    print("  source : cinesort/domain/perceptual/audio_perceptual.py:124 (analyze_loudnorm)")
    print(f"  argv construit : {cmd_str}")
    print(f"  contient '-v quiet'              : {has_quiet}")
    print(f"  utilise loudnorm=print_format=json: {'loudnorm=print_format=json' in cmd_str}")
    print(f"  lit le resultat dans stderr      : {reads_stderr} (l.145-148)")
    print(f"  resultat sous '-v quiet' (stderr='') -> {result!r}")
    contradiction = has_quiet and reads_stderr and (result is None)
    print(f"\n  CONTRADICTION (quiet supprime stderr que le code lit) : {contradiction}")
    return {
        "argv": cmd,
        "has_v_quiet": has_quiet,
        "result_is_none": result is None,
        "contradiction": contradiction,
    }


# ---------------------------------------------------------------------------
# F-PERC-02 — signalstats SANS metadata=mode=print -> aucun YAVG= en stderr
# ---------------------------------------------------------------------------
def cap_perc_02() -> Dict[str, Any]:
    section("F-PERC-02  run_filter_graph (l.90) : signalstats SANS metadata=mode=print")
    import cinesort.domain.perceptual.video_analysis as va

    captured: Dict[str, Any] = {}

    def fake_run(cmd, timeout_s):
        captured["cmd"] = list(cmd)
        # signalstats sans 'metadata=print' n'imprime AUCUN 'YAVG=' en stderr :
        # les stats restent des metadonnees de frame jamais serialisees. On
        # simule un stderr realiste (logs ffmpeg standards, zero ligne YAVG=).
        stderr = (
            "ffmpeg version 6.1\n"
            "  Stream #0:0: Video: h264, yuv420p, 1920x1080, 24 fps\n"
            "Output #0, null, to 'pipe:':\n"
            "frame=  200 fps=120 q=-0.0 size=N/A time=00:00:08.33 bitrate=N/A speed=5x\n"
        )
        return (0, "", stderr)

    orig = va.run_ffmpeg_text
    va.run_ffmpeg_text = fake_run  # type: ignore[assignment]
    try:
        frames = va.run_filter_graph("ffmpeg", "movie.mkv", duration_s=60.0)
    finally:
        va.run_ffmpeg_text = orig

    cmd = captured.get("cmd", [])
    vf = ""
    if "-vf" in cmd:
        vf = cmd[cmd.index("-vf") + 1]
    has_signalstats = "signalstats" in vf
    has_metadata_print = "metadata=mode=print" in vf or "metadata=print" in vf
    print("  source : cinesort/domain/perceptual/video_analysis.py:90 (filtre vf)")
    print("           parser cherche 'YAVG=' (l.52, l.122)")
    print(f"  -vf construit : {vf}")
    print(f"  contient 'signalstats'        : {has_signalstats}")
    print(f"  contient 'metadata=mode=print': {has_metadata_print}")
    print(f"  frames parsees (stderr realiste sans YAVG=) : {len(frames)}")
    silent_empty = has_signalstats and (not has_metadata_print) and (len(frames) == 0)
    print(f"\n  RESULTAT VIDE SILENCIEUX (signalstats sans metadata=print) : {silent_empty}")
    return {
        "vf": vf,
        "has_signalstats": has_signalstats,
        "has_metadata_print": has_metadata_print,
        "frames_parsed": len(frames),
        "silent_empty": silent_empty,
    }


# ---------------------------------------------------------------------------
# F-PERC-03 — Crest/Dynamic seulement par-canal, absents du bloc Overall
# ---------------------------------------------------------------------------
def cap_perc_03() -> Dict[str, Any]:
    section("F-PERC-03  astats : Crest factor / Dynamic range par-canal, hors bloc Overall")
    from cinesort.domain.perceptual.audio_perceptual import (
        _RE_CREST,
        _RE_DYNRANGE,
        _RE_NOISE,
        _RE_PEAK,
        _RE_RMS,
        _extract_overall_block,
    )

    # Sortie astats au FORMAT FFMPEG REEL : Crest factor et Dynamic range sont
    # imprimes dans les blocs PAR CANAL ; le bloc 'Overall' agrege RMS/Peak/Noise
    # mais PAS Crest/Dynamic. (Les tests unitaires utilisent un fixture synthetique
    # 'Overall Crest factor: ...' qui n'existe pas dans ffmpeg standard.)
    real_astats_stderr = (
        "[Parsed_astats_0 @ 0x1] Channel: 1\n"
        "[Parsed_astats_0 @ 0x1] DC offset: 0.000012\n"
        "[Parsed_astats_0 @ 0x1] RMS level dB: -27.1\n"
        "[Parsed_astats_0 @ 0x1] Peak level dB: -1.4\n"
        "[Parsed_astats_0 @ 0x1] Crest factor: 17.5\n"
        "[Parsed_astats_0 @ 0x1] Noise floor dB: -66.0\n"
        "[Parsed_astats_0 @ 0x1] Dynamic range: 51.2\n"
        "[Parsed_astats_0 @ 0x1] Channel: 2\n"
        "[Parsed_astats_0 @ 0x1] DC offset: 0.000010\n"
        "[Parsed_astats_0 @ 0x1] RMS level dB: -29.3\n"
        "[Parsed_astats_0 @ 0x1] Peak level dB: -1.2\n"
        "[Parsed_astats_0 @ 0x1] Crest factor: 19.1\n"
        "[Parsed_astats_0 @ 0x1] Noise floor dB: -68.5\n"
        "[Parsed_astats_0 @ 0x1] Dynamic range: 55.3\n"
        "[Parsed_astats_0 @ 0x1] Overall\n"
        "[Parsed_astats_0 @ 0x1] DC offset: 0.000011\n"
        "[Parsed_astats_0 @ 0x1] RMS level dB: -28.4\n"
        "[Parsed_astats_0 @ 0x1] Peak level dB: -1.2\n"
        "[Parsed_astats_0 @ 0x1] Noise floor dB: -68.5\n"
    )

    overall = _extract_overall_block(real_astats_stderr)

    def grab(rx, txt):
        m = rx.search(txt)
        return m.group(1) if m else None

    # Ce que le parser fait reellement (sur le bloc Overall uniquement) :
    rms_o = grab(_RE_RMS, overall)
    peak_o = grab(_RE_PEAK, overall)
    noise_o = grab(_RE_NOISE, overall)
    crest_o = grab(_RE_CREST, overall)
    dyn_o = grab(_RE_DYNRANGE, overall)

    # Ce qui existe pourtant dans le texte complet (par-canal) :
    crest_full = grab(_RE_CREST, real_astats_stderr)
    dyn_full = grab(_RE_DYNRANGE, real_astats_stderr)

    print("  source : cinesort/domain/perceptual/audio_perceptual.py:234-240 + _extract_overall_block (l.744)")
    print("  bloc Overall extrait :\n      " + overall.replace("\n", "\n      ").rstrip())
    print()
    print("  Sur le bloc Overall (ce que le code lit) :")
    print(f"    RMS={rms_o}  Peak={peak_o}  Noise={noise_o}  Crest={crest_o}  Dynamic={dyn_o}")
    print("  Dans le texte complet (blocs par-canal) :")
    print(f"    Crest={crest_full}  Dynamic={dyn_full}  (presents, mais ignores)")

    lost = (crest_o is None) and (dyn_o is None) and (crest_full is not None) and (dyn_full is not None)
    print(f"\n  Crest/Dynamic PERDUS (presents par-canal, None apres Overall) : {lost}")
    return {
        "overall_crest": crest_o,
        "overall_dynamic": dyn_o,
        "perchannel_crest": crest_full,
        "perchannel_dynamic": dyn_full,
        "crest_dynamic_lost_in_overall": lost,
    }


# ---------------------------------------------------------------------------
def main() -> None:
    print("BASELINE R8 — cap_false_results : resultats silencieusement faux (read-only)")
    resume: Dict[str, Any] = {}
    resume["F-H4-01"] = cap_h4_01()
    resume["F-H5-01"] = cap_h5_01()
    resume["F-CONF-01"] = cap_conf_01()
    resume["F-H7-01"] = cap_h7_01()
    resume["F-PERC-01"] = cap_perc_01()
    resume["F-PERC-02"] = cap_perc_02()
    resume["F-PERC-03"] = cap_perc_03()

    section("RESUME (json)")
    verdicts = {
        "F-H4-01": resume["F-H4-01"]["bug_8kbps_scored_as_bonus"],
        "F-H5-01": resume["F-H5-01"]["joker_keeps_dd5_residue"],
        "F-CONF-01": resume["F-CONF-01"]["asymmetry"],
        "F-H7-01": resume["F-H7-01"]["cache_poisoned"],
        "F-PERC-01": resume["F-PERC-01"]["contradiction"],
        "F-PERC-02": resume["F-PERC-02"]["silent_empty"],
        "F-PERC-03": resume["F-PERC-03"]["crest_dynamic_lost_in_overall"],
    }
    print("RESUME:", json.dumps({"verdicts": verdicts, "detail": resume}, ensure_ascii=False, default=str))
    print(f"\nfindings confirmes (broken-state observe) : {sum(1 for v in verdicts.values() if v)}/{len(verdicts)}")


if __name__ == "__main__":
    main()

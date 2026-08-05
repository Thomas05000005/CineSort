"""Lot « lectures fragiles » — issues #519, #492, #508.

Le fil commun des trois : une entree exterieure abimee (une ligne de JSONL
tronquee, un reseau qui coupe, un ffmpeg qui n'en finit pas) ne doit ni faire
tomber tout un flux, ni — et c'est l'inverse du meme piege — se transformer en
succes silencieux.

#519 `load_rows_from_plan_jsonl` : le sens de l'erreur compte plus que sa
     presence. `plan.jsonl` est le fichier que l'APPLY relit pour renommer et
     DEPLACER des dossiers. Le correctif « ignorer la ligne fautive et
     continuer » propose par l'audit aurait fait travailler l'apply sur un plan
     AMPUTE, avec `errors=0` et des films restes en place sans que personne ne
     l'apprenne. Le comportement retenu NOMME la perte (combien de lignes, et
     lesquelles) et refuse.

#492 `testConnection()` : deux `fetch` sans garde. Le second est le plus couteux
     — l'authentification a DEJA reussi, et une coupure reseau sur le GET
     `/api/health` (un simple enrichissement d'affichage) refusait un token
     valide. Un succes transforme en echec.

#508 3 appelants ffmpeg de l'analyse audio : un timeout sur loudnorm emportait
     astats, clipping, empreinte et Mel avec lui. Les valeurs de repli choisies
     sont NEUTRES (50 / verdict "unknown"), jamais flatteuses — une mesure ratee
     ne devient pas une bonne mesure.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest import mock

import cinesort.domain.core as core
from cinesort.domain.perceptual import audio_perceptual
from cinesort.infra import state
from cinesort.ui.api import apply_support
from cinesort.ui.api.run_data_support import (
    PlanCorruptedError,
    count_plan_rows,
    load_rows_from_plan_jsonl,
)
from tests._jsexec import ROOT, node_check, require_node, run_module_test

RUN_ID = "r519"


# ---------------------------------------------------------------------------
# Fixtures communes #519
# ---------------------------------------------------------------------------


def _run_paths(state_dir: Path, run_id: str = RUN_ID, *, ensure_exists: bool = True) -> state.RunPaths:
    run_dir = state_dir / "runs" / f"tri_films_{run_id}"
    if ensure_exists:
        run_dir.mkdir(parents=True, exist_ok=True)
    return state.RunPaths(
        run_id=run_id,
        run_dir=run_dir,
        plan_jsonl=run_dir / "plan.jsonl",
        ui_log_txt=run_dir / "ui_log.txt",
        summary_txt=run_dir / "summary.txt",
        validation_json=run_dir / "validation.json",
    )


def _plan_line(row_id: str, title: str) -> str:
    return json.dumps(
        {
            "row_id": row_id,
            "kind": "single",
            "folder": f"D:/films/{title} (2010)",
            "video": "movie.mkv",
            "proposed_title": title,
            "proposed_year": 2010,
            "proposed_source": "nfo",
            "confidence": 90,
            "confidence_label": "high",
            "candidates": [],
        },
        ensure_ascii=False,
    )


class _StubRunState:
    def __init__(self, paths: state.RunPaths) -> None:
        self.paths = paths
        self.rows: List[core.PlanRow] = []
        self.lock = threading.Lock()
        self.cfg = SimpleNamespace(root=Path("."))
        self.store = SimpleNamespace()
        self.done = True
        self.log = lambda _lvl, _msg: None


class _StubApi:
    """Surface reellement touchee par `run_context_for_apply` + `_validate_apply`.

    `_load_rows_from_plan_jsonl` delegue a la VRAIE fonction : c'est bien le
    chargeur de production qui leve, pas un mock qui fabrique la condition.
    """

    def __init__(self, state_dir: Path, run_state: Optional[_StubRunState]) -> None:
        self._state_dir = state_dir
        self._run_state = run_state
        self.logged: List[Dict[str, Any]] = []

    def _is_valid_run_id(self, run_id: Any) -> bool:
        return bool(str(run_id or "").strip())

    def _run_paths_for(self, state_dir: Path, run_id: str, *, ensure_exists: bool) -> state.RunPaths:
        return _run_paths(Path(state_dir), run_id, ensure_exists=ensure_exists)

    def _get_run(self, run_id: str) -> Optional[_StubRunState]:
        return self._run_state if str(run_id) == RUN_ID else None

    def _find_run_row(self, _run_id: str) -> None:
        return None

    def _load_rows_from_plan_jsonl(self, run_paths: state.RunPaths) -> List[core.PlanRow]:
        return load_rows_from_plan_jsonl(run_paths)

    def _run_context_for_apply(self, run_id: str) -> Any:
        return apply_support.run_context_for_apply(self, run_id)

    def log_api_exception(self, endpoint: str, exc: BaseException, **kw: Any) -> None:
        self.logged.append({"endpoint": endpoint, "exc": exc, **kw})


# ---------------------------------------------------------------------------
# #519 — le plan ampute doit se voir, pas se subir
# ---------------------------------------------------------------------------


class PlanJsonlCorruptedLineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_519_")
        self.state_dir = Path(self._tmp.name)
        self.paths = _run_paths(self.state_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, lines: List[str]) -> None:
        self.paths.plan_jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_plan_sain_charge_toutes_les_lignes(self) -> None:
        self._write([_plan_line("f1", "Alpha"), _plan_line("f2", "Beta"), _plan_line("f3", "Gamma")])
        rows = load_rows_from_plan_jsonl(self.paths)
        self.assertEqual([r.row_id for r in rows], ["f1", "f2", "f3"])

    def test_ligne_tronquee_refuse_le_plan_et_nomme_la_ligne(self) -> None:
        """Le refus est le point : rendre 2 rows sur 3 serait un plan ampute."""
        self._write([_plan_line("f1", "Alpha"), '{"row_id": "f2", "proposed_ti', _plan_line("f3", "Gamma")])
        with self.assertRaises(PlanCorruptedError) as ctx:
            load_rows_from_plan_jsonl(self.paths)
        self.assertEqual(ctx.exception.invalid_lines, [2])
        self.assertEqual(ctx.exception.invalid_count, 1)
        self.assertEqual(ctx.exception.readable_rows, 2)
        self.assertIn("ligne(s) 2", str(ctx.exception))

    def test_le_fichier_entier_est_parcouru_avant_de_lever(self) -> None:
        """S'arreter a la premiere ligne fautive sous-declarerait l'ampleur.

        Trois lignes cassees sur cinq : le message doit dire trois, pas une.
        """
        self._write(
            [
                _plan_line("f1", "Alpha"),
                "{ pas du json",
                _plan_line("f3", "Gamma"),
                "\\x00\\x00 octets binaires",
                "]]]",
            ]
        )
        with self.assertRaises(PlanCorruptedError) as ctx:
            load_rows_from_plan_jsonl(self.paths)
        self.assertEqual(ctx.exception.invalid_lines, [2, 4, 5])
        self.assertEqual(ctx.exception.readable_rows, 2)

    def test_octet_non_utf8_compte_comme_ligne_illisible(self) -> None:
        """Un octet indecodable ne doit pas emporter TOUTE la lecture.

        En mode texte, le decodage se fait quand l'iterateur AVANCE : le
        `UnicodeDecodeError` etait donc leve dans le `for`, HORS du `try` qui
        entoure `json.loads`. L'appelant recevait une erreur generique au lieu
        d'un `PlanCorruptedError` nommant les lignes fautives.

        Le refus du plan est INCHANGE — c'est le diagnostic qui manquait.
        """
        self.paths.plan_jsonl.write_bytes(
            _plan_line("f1", "Alpha").encode("utf-8")
            + b"\n"
            + b'{"row_id": "f2", "t": "\xff\xfe"}'
            + b"\n"
            + _plan_line("f3", "Gamma").encode("utf-8")
            + b"\n"
        )
        with self.assertRaises(PlanCorruptedError) as ctx:
            load_rows_from_plan_jsonl(self.paths)
        self.assertEqual(ctx.exception.invalid_lines, [2])
        self.assertEqual(ctx.exception.readable_rows, 2, "les lignes SAINES doivent rester comptees")

    def test_octet_non_utf8_et_json_casse_comptes_ENSEMBLE(self) -> None:
        """Les deux familles d'illisible alimentent le MEME compteur.

        Sinon le message sous-declare l'ampleur de la corruption.
        """
        self.paths.plan_jsonl.write_bytes(
            _plan_line("f1", "Alpha").encode("utf-8")
            + b"\n"
            + b"\xff\xff octets bruts"
            + b"\n"
            + b"{ pas du json"
            + b"\n"
            + _plan_line("f4", "Delta").encode("utf-8")
            + b"\n"
        )
        with self.assertRaises(PlanCorruptedError) as ctx:
            load_rows_from_plan_jsonl(self.paths)
        self.assertEqual(ctx.exception.invalid_lines, [2, 3])
        self.assertEqual(ctx.exception.readable_rows, 2)

    def test_ligne_json_valide_mais_non_dict_compte_comme_perdue(self) -> None:
        """`null` parse sans erreur : c'etait la perte VRAIMENT silencieuse.

        `isinstance(data, dict)` la jetait sans un mot — un film disparaissait
        du plan que l'apply execute, sans exception ni compteur.
        """
        self._write([_plan_line("f1", "Alpha"), "null", _plan_line("f3", "Gamma")])
        with self.assertRaises(PlanCorruptedError) as ctx:
            load_rows_from_plan_jsonl(self.paths)
        self.assertEqual(ctx.exception.invalid_lines, [2])

    def test_lignes_vides_restent_tolerees(self) -> None:
        """Une ligne vide n'est pas une perte : `write_plan_jsonl` finit par \\n."""
        self.paths.plan_jsonl.write_text(
            _plan_line("f1", "Alpha") + "\n\n   \n" + _plan_line("f2", "Beta") + "\n",
            encoding="utf-8",
        )
        rows = load_rows_from_plan_jsonl(self.paths)
        self.assertEqual([r.row_id for r in rows], ["f1", "f2"])

    def test_reste_un_valueerror_pour_les_appelants_existants(self) -> None:
        """Contrat de compatibilite : tous les `except ValueError` deja en place
        (apply, get_plan, load_validation, resync) doivent continuer d'attraper."""
        self._write(["{ casse"])
        self.assertTrue(issubclass(PlanCorruptedError, ValueError))
        with self.assertRaises(ValueError):
            load_rows_from_plan_jsonl(self.paths)

    def test_plan_absent_leve_toujours_filenotfound(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_rows_from_plan_jsonl(self.paths)


class CountPlanRowsVisibleLossTests(unittest.TestCase):
    """Le compteur ne peut pas refuser (il alimente l'affichage) — alors il parle."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_519c_")
        self.paths = _run_paths(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_octet_non_utf8_ne_fait_PAS_planter_le_compteur(self) -> None:
        """Ce compteur doit TOUJOURS rendre un entier, degrade au besoin.

        C'est la source unique du « nombre de films » du tableau de bord, de
        l'historique et de la bibliotheque. En mode texte, `UnicodeDecodeError`
        etait leve par l'iterateur, donc HORS de l'`except (OSError,
        PermissionError)` : un seul octet fautif faisait remonter l'exception
        hors du compteur et cassait ces trois ecrans, au lieu de signaler un
        plan ampute.
        """
        self.paths.plan_jsonl.write_bytes(
            _plan_line("f1", "Alpha").encode("utf-8")
            + b"\n"
            + b"\xff\xff octets bruts"
            + b"\n"
            + _plan_line("f3", "Gamma").encode("utf-8")
            + b"\n"
        )
        with self.assertLogs("cinesort.ui.api.run_data_support", level="WARNING") as journal:
            n = count_plan_rows(self.paths, fallback=999)

        self.assertEqual(n, 2, "les lignes SAINES doivent etre comptees")
        self.assertNotEqual(n, 999, "le repli serait un nombre INVENTE, pas une mesure")
        self.assertTrue(
            any("illisible" in ligne for ligne in journal.output),
            f"l'amputation doit etre DITE, pas subie en silence : {journal.output}",
        )

    def test_plan_sain_ne_logge_aucun_avertissement(self) -> None:
        self.paths.plan_jsonl.write_text(
            _plan_line("f1", "Alpha") + "\n" + _plan_line("f2", "Beta") + "\n", encoding="utf-8"
        )
        logger = logging.getLogger("cinesort.ui.api.run_data_support")
        with self.assertNoLogs(logger, level=logging.WARNING):
            self.assertEqual(count_plan_rows(self.paths), 2)

    def test_lignes_illisibles_signalees_avec_leur_nombre(self) -> None:
        self.paths.plan_jsonl.write_text(
            _plan_line("f1", "Alpha") + "\n{ casse\n" + _plan_line("f2", "Beta") + "\nnull\n",
            encoding="utf-8",
        )
        with self.assertLogs("cinesort.ui.api.run_data_support", level=logging.WARNING) as logs:
            total = count_plan_rows(self.paths)
        # Le compte reste HONNETE (2 lignes exploitables) : on ne remplace pas
        # une mesure ratee par une estimation plausible.
        self.assertEqual(total, 2)
        joined = "\n".join(logs.output)
        self.assertIn("2 ligne(s) illisible(s)", joined)


class ApplyRefusesCorruptedPlanTests(unittest.TestCase):
    """Le chemin destructif : l'apply doit refuser ET dire pourquoi."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_519a_")
        self.state_dir = Path(self._tmp.name)
        self.paths = _run_paths(self.state_dir)
        self.api = _StubApi(self.state_dir, _StubRunState(self.paths))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_plan_sain_traverse_le_chargement_du_contexte(self) -> None:
        """Garde-fou anti-faux-vert n°1 : le chargeur de production rend bien un
        contexte sur un plan bien forme — la branche « corrompu » est donc
        conditionnee par le fichier, pas systematique."""
        self.paths.plan_jsonl.write_text(
            _plan_line("f1", "Alpha") + "\n" + _plan_line("f2", "Beta") + "\n", encoding="utf-8"
        )
        ctx = apply_support.run_context_for_apply(self.api, RUN_ID)
        self.assertIsNotNone(ctx)
        self.assertEqual([r.row_id for r in ctx[2]], ["f1", "f2"])

    def test_plan_vide_mais_lisible_refuse_pour_une_autre_raison(self) -> None:
        """Garde-fou anti-faux-vert n°2 : un plan LISIBLE traverse la garde de
        corruption et se fait refuser plus loin, avec un message DIFFERENT."""
        self.paths.plan_jsonl.write_text("", encoding="utf-8")
        out = apply_support._validate_apply(self.api, RUN_ID, {}, True, False)
        self.assertFalse(out.get("ok"))
        self.assertNotIn("corrompu", str(out.get("message", "")).lower())

    def test_apply_refuse_un_plan_corrompu_avec_un_message_explicite(self) -> None:
        self.paths.plan_jsonl.write_text(
            _plan_line("f1", "Alpha") + "\n{ tronque\n" + _plan_line("f3", "Gamma") + "\n",
            encoding="utf-8",
        )
        out = apply_support._validate_apply(self.api, RUN_ID, {}, True, False)
        self.assertFalse(out.get("ok"))
        message = str(out.get("message", ""))
        self.assertIn("corrompu", message.lower())
        # La perte est chiffree, pas juste evoquee.
        self.assertIn("1 ligne(s) illisible(s)", message)
        self.assertEqual(self.api.logged[-1]["extra"]["invalid_plan_lines"], 1)


# ---------------------------------------------------------------------------
# #492 — testConnection : la VRAIE source api.js executee sous Node
# ---------------------------------------------------------------------------

_API_JS = ROOT / "web" / "dashboard" / "core" / "api.js"

_JS_STUBS = r"""
// Imports de api.js (state.js / cache.js), neutralises par le harnais.
const getToken = () => "";
const clearToken = () => {};
const awaitToken = async () => "";
const isCacheable = () => false;
const saveSnapshot = () => {};
const loadSnapshot = () => null;
const formatStaleness = () => "";

globalThis.window = { location: { origin: "http://127.0.0.1:8642" }, addEventListener() {} };
globalThis.document = {
  getElementById: () => null,
  addEventListener() {},
  removeEventListener() {},
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };

// `fetch` pilote par le driver : chaque test decrit ce que le reseau fait.
globalThis.__calls = [];
globalThis.__fetchPlan = {};
globalThis.fetch = async (url) => {
  globalThis.__calls.push(String(url));
  const behaviour = String(url).includes("/api/health")
    ? globalThis.__fetchPlan.health
    : globalThis.__fetchPlan.post;
  if (behaviour === "throw") throw new TypeError("Failed to fetch");
  return behaviour;
};
"""

_JS_EXTRA = r"""
export const __h = { testConnection };
"""


class TestConnectionNetworkTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(_API_JS, stubs=_JS_STUBS, extra=_JS_EXTRA, driver=driver)

    def test_syntaxe_api_js(self) -> None:
        node_check(self, _API_JS)

    def test_reseau_coupe_avant_le_post_donne_un_refus_type(self) -> None:
        """ROUGE avant fix : le `fetch` rejetait et l'exception traversait
        testConnection au lieu d'un `{ok:false, message}` exploitable."""
        res = self._run(
            r"""
globalThis.__fetchPlan = { post: "throw" };
let thrown = null;
let out = null;
try { out = await M.__h.testConnection("abc"); } catch (e) { thrown = String(e); }
__emit({ thrown, out });
"""
        )
        self.assertIsNone(res["thrown"], "l'exception reseau ne doit plus remonter au caller")
        self.assertFalse(res["out"]["ok"])
        self.assertTrue(res["out"]["message"])

    def test_token_valide_reste_valide_si_health_casse(self) -> None:
        """Le cas qui coute : l'auth a REUSSI, seul l'enrichissement version
        echoue. ROUGE avant fix : exception -> login.js affichait une erreur
        reseau pour un token parfaitement bon."""
        res = self._run(
            r"""
globalThis.__fetchPlan = {
  post: { status: 200, ok: true, json: async () => ({ ok: true }) },
  health: "throw",
};
let thrown = null;
let out = null;
try { out = await M.__h.testConnection("abc"); } catch (e) { thrown = String(e); }
__emit({ thrown, out, calls: globalThis.__calls });
"""
        )
        self.assertIsNone(res["thrown"])
        self.assertTrue(res["out"]["ok"], "un token valide ne doit pas etre refuse pour un /api/health muet")
        self.assertEqual(res["out"]["version"], "?")

    def test_health_en_erreur_http_ne_pollue_pas_la_version(self) -> None:
        """Une page d'erreur HTML renvoyee en 502 ne doit pas etre lue comme
        une reponse health."""
        res = self._run(
            r"""
globalThis.__fetchPlan = {
  post: { status: 200, ok: true, json: async () => ({ ok: true }) },
  health: { status: 502, ok: false, json: async () => ({ version: "page-erreur" }) },
};
const out = await M.__h.testConnection("abc");
__emit({ out });
"""
        )
        self.assertTrue(res["out"]["ok"])
        self.assertEqual(res["out"]["version"], "?")

    def test_nominal_remonte_toujours_la_version_backend(self) -> None:
        """Non-regression : le chemin heureux doit rester intact."""
        res = self._run(
            r"""
globalThis.__fetchPlan = {
  post: { status: 200, ok: true, json: async () => ({ ok: true }) },
  health: { status: 200, ok: true, json: async () => ({ version: "7.7.0", active_run_id: "run-9" }) },
};
const out = await M.__h.testConnection("abc");
__emit({ out });
"""
        )
        self.assertEqual(res["out"], {"ok": True, "version": "7.7.0", "active_run_id": "run-9"})

    def test_401_reste_un_refus_de_token(self) -> None:
        """Non-regression : la garde reseau ne doit pas avaler les codes HTTP."""
        res = self._run(
            r"""
globalThis.__fetchPlan = { post: { status: 401, ok: false, json: async () => ({}) } };
const out = await M.__h.testConnection("abc");
__emit({ out, calls: globalThis.__calls });
"""
        )
        self.assertFalse(res["out"]["ok"])
        self.assertEqual(len(res["calls"]), 1, "un 401 ne doit pas declencher le GET health")


# ---------------------------------------------------------------------------
# #508 — un ffmpeg qui n'en finit pas ne doit pas emporter ses voisins
# ---------------------------------------------------------------------------

_ASTATS_STDERR = """
[Parsed_astats_0 @ 0x1] Channel: 1
[Parsed_astats_0 @ 0x1] RMS level dB: -18.500000
[Parsed_astats_0 @ 0x1] Peak level dB: -1.200000
[Parsed_astats_0 @ 0x1] Noise floor dB: -72.000000
[Parsed_astats_0 @ 0x1] Crest factor: 12.500000
[Parsed_astats_0 @ 0x1] Dynamic range: 14.000000
[Parsed_astats_0 @ 0x1] Overall
[Parsed_astats_0 @ 0x1] RMS level dB: -18.000000
[Parsed_astats_0 @ 0x1] Peak level dB: -1.000000
[Parsed_astats_0 @ 0x1] Noise floor dB: -70.000000
"""

_TRACKS = [{"index": 1, "codec": "dts", "channels": 6, "language": "fre"}]


def _timeout(cmd: List[str]) -> subprocess.TimeoutExpired:
    return subprocess.TimeoutExpired(cmd=cmd, timeout=1.0)


class FfmpegTimeoutIsolationTests(unittest.TestCase):
    """Le fake remplace ffmpeg (la panne exterieure), jamais la logique testee."""

    @staticmethod
    def _filter_of(cmd: List[str]) -> str:
        return cmd[cmd.index("-af") + 1] if "-af" in cmd else ""

    def test_loudnorm_en_timeout_rend_none_et_non_une_exception(self) -> None:
        def fake(cmd: List[str], _timeout_s: float):
            raise _timeout(cmd)

        with mock.patch.object(audio_perceptual, "run_ffmpeg_text", fake):
            self.assertIsNone(audio_perceptual.analyze_loudnorm("ffmpeg", "f.mkv", 0))

    def test_astats_en_timeout_rend_none_et_non_une_exception(self) -> None:
        def fake(cmd: List[str], _timeout_s: float):
            raise OSError("ffmpeg introuvable")

        with mock.patch.object(audio_perceptual, "run_ffmpeg_text", fake):
            self.assertIsNone(audio_perceptual.analyze_astats("ffmpeg", "f.mkv", 0))

    def test_clipping_en_timeout_rend_le_verdict_inconnu_pas_zero_clipping(self) -> None:
        """`total_segments == 0` est ce que `_compute_audio_score` exige pour NE
        PAS scorer le clipping (garde R8-098). Sans lui, 0 % de clipping serait
        lu comme "propre" (90) alors que rien n'a ete mesure."""

        def fake(cmd: List[str], _timeout_s: float):
            raise _timeout(cmd)

        with mock.patch.object(audio_perceptual, "run_ffmpeg_text", fake):
            out = audio_perceptual.analyze_clipping_segments("ffmpeg", "f.mkv", 0)
        self.assertEqual(out["verdict"], "unknown")
        self.assertEqual(out["total_segments"], 0)

    def test_un_timeout_loudnorm_n_emporte_plus_astats_ni_clipping(self) -> None:
        """Le coeur de #508 : `_audio_task` entier tombait, donc astats,
        clipping, empreinte et Mel etaient perdus alors qu'ils n'avaient meme
        pas encore tourne."""
        seen: List[str] = []

        def fake(cmd: List[str], _timeout_s: float):
            af = self._filter_of(cmd)
            seen.append(af)
            if "loudnorm" in af:
                raise _timeout(cmd)
            return 0, "", _ASTATS_STDERR

        with mock.patch.object(audio_perceptual, "run_ffmpeg_text", fake):
            result = audio_perceptual.analyze_audio_perceptual(
                "ffmpeg",
                "f.mkv",
                _TRACKS,
                audio_deep=True,
                enable_fingerprint=False,
                enable_spectral=False,
                enable_mel=False,
            )

        self.assertTrue(any("loudnorm" in af for af in seen))
        self.assertTrue(any("astats" in af for af in seen), "astats doit avoir ete tente malgre le timeout loudnorm")
        # Loudnorm non mesure -> reste None, PAS une valeur inventee.
        self.assertIsNone(result.integrated_loudness)
        # Astats mesure -> la moitie exploitable de l'analyse est preservee.
        self.assertEqual(result.noise_floor, -70.0)

    def test_score_audio_reste_neutre_quand_loudnorm_manque(self) -> None:
        """Anti-« mesure ratee devenue mesure plausible » : l'absence de mesure
        vaut 50 (neutre), pas 95."""
        neutre = audio_perceptual._compute_audio_score(None, None, None)
        bon = audio_perceptual._compute_audio_score(
            {"loudness_range": 20.0, "true_peak": -3.0},
            {"noise_floor": -80.0, "dynamic_range": 20.0, "crest_factor": 20.0},
            {"total_segments": 100, "clipping_pct": 0.0},
        )
        self.assertLess(neutre, bon)


if __name__ == "__main__":
    unittest.main()

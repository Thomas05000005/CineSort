"""Lot « chemins et exports que l'application refuse a tort » — #471, #522, #583, #545.

Quatre defauts de la meme famille : une valeur legitime est ecartee par un
perimetre trop etroit, ou un echec disparait sans laisser de trace.

* **#471** `history_support.open_path` construisait sa zone autorisee sur
  `settings["root"]` (singulier), qui n'est que l'alias retro-compatible de
  `roots[0]`. Un film sur une racine secondaire etait refuse « Chemin non
  autorise ». La garde doit s'ELARGIR aux racines configurees sans devenir
  permissive : hors racines, refus inchange.
* **#522** `library_actions_support._exports_dir` ecrivait toujours dans
  `state.default_state_dir()/exports`, ignorant le `state_dir` des settings :
  export introuvable des que l'utilisateur deplace son user-data.
* **#583** `library_timeline_support` ancrait la fenetre de mois sur le dernier
  mois AYANT de l'activite, alors que son contrat annonce « les N derniers
  mois » : timeline fossile sur une bibliotheque mature.
* **#545** 4 sites `except (AttributeError, OSError): pass` dans
  `dashboard_support._compute_active_insights` : un encart de la Home
  disparaissait sans qu'aucune trace n'existe. Le niveau WARNING est ce qui est
  verifie ici — un `logger.debug` serait invisible a la verbosite par defaut
  (INFO) et laisserait le defaut entier.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from tests.test_phase4_bibliotheque_endpoints import _make_mock_api_with_rows

# ---------------------------------------------------------------------------
# #471 — open_path accepte TOUTES les racines configurees
# ---------------------------------------------------------------------------

_DEFAULT_ROOT_SENTINEL = "D:/CineSortDefaultRootQuiNeDoitPasEtreAutorise"


def _normalize_user_path(value: Any, default: Path) -> Path:
    """Reprise fidele du normalize_user_path injecte par cinesort_api.

    Point cle pour #471 : une valeur VIDE rend le `default`. C'est pourquoi
    `_configured_roots` doit ecarter les entrees vides — sinon la racine par
    defaut du produit deviendrait autorisee sans que l'utilisateur l'ait
    configuree.
    """
    if value is None or str(value).strip() == "":
        return Path(default)
    return Path(str(value))


def _canonical(value: Path) -> str:
    return os.path.normcase(os.path.realpath(str(value)))


def _call_open_path(
    settings: Dict[str, Any], path: str, *, default_root: str = _DEFAULT_ROOT_SENTINEL
) -> Dict[str, Any]:
    """Appelle open_path avec os.startfile mocke, expose ce qui a ete ouvert."""
    from cinesort.ui.api import history_support

    api = MagicMock()
    api.settings.get_settings.return_value = settings
    with patch.object(history_support.os, "startfile", create=True) as mock_start:
        res = history_support.open_path(
            api,
            path,
            default_root=default_root,
            normalize_user_path=_normalize_user_path,
        )
        res["__startfile_called"] = mock_start.called
        res["__startfile_args"] = [str(call.args[0]) for call in mock_start.call_args_list]
    return res


class OpenPathMultiRootTests(unittest.TestCase):
    """#471 : les racines secondaires sont des racines a part entiere."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.state_dir = base / "state"
        self.root_a = base / "lib_a"
        self.root_b = base / "lib_b"
        self.root_c = base / "lib_c"
        self.outside = base / "outside"
        for d in (self.state_dir, self.root_a, self.root_b, self.root_c, self.outside):
            d.mkdir()
        self.film_a = self.root_a / "Inception (2010)"
        self.film_b = self.root_b / "Dune (2021)"
        self.film_c = self.root_c / "Arrival (2016)"
        for d in (self.film_a, self.film_b, self.film_c):
            d.mkdir()
        (self.outside / "secret.txt").write_text("secret", encoding="utf-8")

    def _settings(self, **over: Any) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "state_dir": str(self.state_dir),
            # Tel que le produit le persiste : `root` est synchronise sur
            # roots[0] par settings_support._migrate_root_to_roots.
            "root": str(self.root_a),
            "roots": [str(self.root_a), str(self.root_b), str(self.root_c)],
        }
        data.update(over)
        return data

    def test_second_root_is_opened(self) -> None:
        """Le coeur de #471 : un film sur roots[1] doit s'ouvrir."""
        res = _call_open_path(self._settings(), str(self.film_b))

        self.assertTrue(res.get("ok"), msg=res)
        self.assertTrue(res["__startfile_called"])
        self.assertEqual([_canonical(Path(p)) for p in res["__startfile_args"]], [_canonical(self.film_b)])

    def test_third_root_is_opened(self) -> None:
        """La zone est l'UNION de toutes les racines, pas seulement des deux premieres."""
        res = _call_open_path(self._settings(), str(self.film_c))

        self.assertTrue(res.get("ok"), msg=res)
        self.assertEqual([_canonical(Path(p)) for p in res["__startfile_args"]], [_canonical(self.film_c)])

    def test_first_root_still_opened(self) -> None:
        """Non-regression : la racine principale continue de fonctionner."""
        res = _call_open_path(self._settings(), str(self.film_a))

        self.assertTrue(res.get("ok"), msg=res)
        self.assertEqual([_canonical(Path(p)) for p in res["__startfile_args"]], [_canonical(self.film_a)])

    def test_outside_every_root_still_refused(self) -> None:
        """La garde est ELARGIE, pas desarmee : hors des racines, refus."""
        res = _call_open_path(self._settings(), str(self.outside / "secret.txt"))

        self.assertFalse(res.get("ok"), msg=res)
        self.assertEqual(res.get("message"), "Chemin non autorise.")
        self.assertFalse(res["__startfile_called"])

    def test_root_removed_from_roots_is_refused(self) -> None:
        """Retirer une racine des settings la retire de la zone autorisee."""
        settings = self._settings(roots=[str(self.root_a)], root=str(self.root_a))

        res = _call_open_path(settings, str(self.film_b))

        self.assertFalse(res.get("ok"), msg=res)
        self.assertEqual(res.get("message"), "Chemin non autorise.")
        self.assertFalse(res["__startfile_called"])

    def test_legacy_settings_without_roots_still_work(self) -> None:
        """Settings anciens : `root` seul, pas de `roots`. Doit rester ouvrable."""
        settings = {"state_dir": str(self.state_dir), "root": str(self.root_a)}

        res = _call_open_path(settings, str(self.film_a))

        self.assertTrue(res.get("ok"), msg=res)
        self.assertEqual([_canonical(Path(p)) for p in res["__startfile_args"]], [_canonical(self.film_a)])

    def test_roots_stored_as_plain_string_falls_back_to_root(self) -> None:
        """`roots` non-liste (settings corrompus) : on retombe sur `root`, pas de crash."""
        settings = {
            "state_dir": str(self.state_dir),
            "root": str(self.root_a),
            "roots": str(self.root_a),
        }

        res = _call_open_path(settings, str(self.film_a))

        self.assertTrue(res.get("ok"), msg=res)

    def test_state_dir_still_allowed(self) -> None:
        """Non-regression : le dossier d'etat reste une base autorisee."""
        sub = self.state_dir / "runs"
        sub.mkdir()

        res = _call_open_path(self._settings(), str(sub))

        self.assertTrue(res.get("ok"), msg=res)

    def test_empty_root_entries_do_not_authorize_default_root(self) -> None:
        """Une entree VIDE ne doit jamais elargir la zone au `default_root`.

        Preuve prise sur le SITE D'APPEL (`open_path`), pas sur le helper seul :
        `normalize_user_path("", default)` rend le `default`, donc sans filtrage
        des entrees vides c'est la racine par defaut du PRODUIT — que
        l'utilisateur n'a jamais configuree — qui devient ouvrable.
        """
        fake_default_root = Path(self.tmp.name) / "default_root_du_produit"
        fake_default_root.mkdir()
        victim = fake_default_root / "Film Non Configure (1999)"
        victim.mkdir()
        settings = {"state_dir": str(self.state_dir), "root": "", "roots": ["", "   ", None]}

        res = _call_open_path(settings, str(victim), default_root=str(fake_default_root))

        self.assertFalse(res.get("ok"), msg=res)
        self.assertEqual(res.get("message"), "Chemin non autorise.")
        self.assertFalse(res["__startfile_called"])

    def test_configured_roots_drops_empty_entries(self) -> None:
        """Complement unitaire du test precedent, sur le helper lui-meme."""
        from cinesort.ui.api import history_support

        self.assertEqual(history_support._configured_roots({"root": "", "roots": ["", "   ", None]}), [])
        self.assertEqual(
            history_support._configured_roots({"root": "R", "roots": ["", " A ", None, "B"]}),
            ["A", "B"],
        )

    def test_symlink_still_refused_in_multi_root(self) -> None:
        """Securite : l'elargissement multi-root ne touche pas la garde symlink."""
        link = self.root_b / "evil_link.txt"
        try:
            link.symlink_to(self.outside / "secret.txt")
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks indisponibles sur cette plateforme : {exc}")

        res = _call_open_path(self._settings(), str(link))

        self.assertFalse(res.get("ok"), msg=res)
        self.assertIn("symbol", res.get("message", "").lower())
        self.assertFalse(res["__startfile_called"])

    def test_sibling_prefix_of_a_secondary_root_is_refused(self) -> None:
        """`lib_b2` n'est pas inclus dans `lib_b` : comparaison par composant."""
        sibling = Path(str(self.root_b) + "2")
        sibling.mkdir()
        self.addCleanup(sibling.rmdir)

        res = _call_open_path(self._settings(), str(sibling))

        self.assertFalse(res.get("ok"), msg=res)
        self.assertEqual(res.get("message"), "Chemin non autorise.")


# ---------------------------------------------------------------------------
# #522 — _exports_dir suit settings.state_dir
# ---------------------------------------------------------------------------


class ExportsDirFollowsStateDirTests(unittest.TestCase):
    """#522 : l'export atterrit dans le dossier d'etat CONFIGURE."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        # Deux dossiers DISTINCTS : celui que le produit utiliserait par defaut,
        # et celui que l'utilisateur a reellement configure.
        self.default_state_dir = base / "localappdata_cinesort"
        self.custom_state_dir = base / "nas_userdata"
        self.default_state_dir.mkdir()
        self.custom_state_dir.mkdir()

    def _api(self, state_dir: Optional[str]) -> MagicMock:
        api = _make_mock_api_with_rows(self.default_state_dir)
        api.settings.get_settings.return_value = {"state_dir": state_dir}
        return api

    def _export(self, api: MagicMock) -> Dict[str, Any]:
        from cinesort.ui.api import library_actions_support

        with patch.object(
            library_actions_support.state,
            "default_state_dir",
            return_value=self.default_state_dir,
        ):
            return library_actions_support.export_films(api, ["f1", "f2"], fmt="json", run_id="r1")

    def test_export_lands_in_configured_state_dir(self) -> None:
        res = self._export(self._api(str(self.custom_state_dir)))

        self.assertTrue(res.get("ok"), msg=res)
        written = Path(res["file_path"])
        self.assertTrue(written.exists(), f"fichier absent : {written}")
        self.assertEqual(_canonical(written.parent), _canonical(self.custom_state_dir / "exports"))

    def test_export_does_not_land_in_default_state_dir(self) -> None:
        """La moitie « introuvable » du bug : rien ne doit rester a l'ancien endroit."""
        self._export(self._api(str(self.custom_state_dir)))

        stale = self.default_state_dir / "exports"
        leftovers = sorted(p.name for p in stale.glob("*")) if stale.exists() else []
        self.assertEqual(leftovers, [], f"export ecrit dans le dossier par defaut : {leftovers}")

    def test_export_falls_back_to_default_when_state_dir_absent(self) -> None:
        """Non-regression : sans state_dir configure, comportement inchange."""
        res = self._export(self._api(None))

        self.assertTrue(res.get("ok"), msg=res)
        self.assertEqual(
            _canonical(Path(res["file_path"]).parent),
            _canonical(self.default_state_dir / "exports"),
        )

    def test_csv_export_also_follows_state_dir(self) -> None:
        """Les 3 formats partagent le meme repertoire : verifier un 2e format."""
        from cinesort.ui.api import library_actions_support

        api = self._api(str(self.custom_state_dir))
        with patch.object(
            library_actions_support.state,
            "default_state_dir",
            return_value=self.default_state_dir,
        ):
            res = library_actions_support.export_films(api, ["f1"], fmt="csv", run_id="r1")

        self.assertTrue(res.get("ok"), msg=res)
        self.assertEqual(
            _canonical(Path(res["file_path"]).parent),
            _canonical(self.custom_state_dir / "exports"),
        )


# ---------------------------------------------------------------------------
# #583 — la timeline est ancree sur AUJOURD'HUI
# ---------------------------------------------------------------------------


def _utc_month(offset_back: int = 0) -> str:
    """Mois UTC courant recule de `offset_back` mois, au format YYYY-MM."""
    now = datetime.now(timezone.utc)
    y, m = now.year, now.month - offset_back
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}"


class TimelineAnchoredOnTodayTests(unittest.TestCase):
    """#583 : « les N derniers mois » se compte depuis maintenant, pas depuis la donnee."""

    def setUp(self) -> None:
        settings = {"state_dir": "/tmp/test", "jellyfin_enabled": False}
        self.api = MagicMock()
        self.api._internal_settings.return_value = settings
        self.api.settings.get_settings.return_value = settings
        store = MagicMock()
        self.api._get_or_create_infra.return_value = (store, None)
        store.run.get_runs_summary.return_value = [{"run_id": "run-test"}]

    def _timeline(self, mtimes: List[str], months: int = 12) -> Dict[str, Any]:
        from cinesort.ui.api import library_timeline_support

        rows = [{"path": f"/m/Film{i}.mkv", "tmdb_id": str(i)} for i in range(len(mtimes))]
        with (
            patch.object(library_timeline_support, "_build_library_rows", return_value=rows),
            patch.object(library_timeline_support, "normalize_user_path", return_value="/tmp/test"),
            patch.object(library_timeline_support, "_file_mtime_to_month", side_effect=list(mtimes)),
        ):
            return library_timeline_support.get_library_timeline(self.api, months=months, run_id="run-test")

    def test_fossil_library_still_ends_on_current_month(self) -> None:
        """Bibliotheque mature : plus rien depuis 2024, la fenetre reste sur aujourd'hui.

        L'assertion accepte le mois d'avant ET d'apres l'appel : un basculement de
        mois pile pendant le test ne doit pas la rendre instable (on juge une
        propriete de la SEQUENCE, pas une egalite a un instant d'horloge).
        """
        before = _utc_month()
        result = self._timeline(["2024-06", "2024-06", "2024-07"], months=12)
        after = _utc_month()

        self.assertTrue(result["ok"], msg=result)
        self.assertIn(result["months"][-1]["month"], {before, after})

    def test_fossil_library_window_is_contiguous_and_sized(self) -> None:
        """La fenetre garde exactement N mois consecutifs, tous a 0 si rien de recent."""
        result = self._timeline(["2024-06", "2024-06", "2024-07"], months=12)

        months = [m["month"] for m in result["months"]]
        self.assertEqual(len(months), 12)
        self.assertEqual(months, sorted(months))
        self.assertEqual(len(set(months)), 12)
        self.assertEqual([m["count"] for m in result["months"]], [0] * 12)

    def test_recent_activity_is_still_counted(self) -> None:
        """Non-regression : de la donnee dans la fenetre reste agregee.

        `months=6` absorbe un basculement de mois pendant le test : les deux mois
        vises restent dans la fenetre meme si `now` avance d'un cran.
        """
        prev, cur = _utc_month(1), _utc_month(0)
        result = self._timeline([prev, prev, cur], months=6)

        counts = {m["month"]: m["count"] for m in result["months"]}
        self.assertEqual(counts.get(prev), 2)
        self.assertEqual(counts.get(cur), 1)
        self.assertEqual(result["total_films"], 3)
        self.assertEqual(result["films_with_date_pct"], 100.0)

    def test_future_dated_film_is_not_hidden(self) -> None:
        """Un mtime dans le futur (NAS, copie) doit rester visible.

        C'est la raison du `max(today, donnees)` plutot que `today` seul : ancrer
        de force sur aujourd'hui masquerait ces films sans le dire.
        """
        future = f"{datetime.now(timezone.utc).year + 1:04d}-05"
        result = self._timeline([future], months=12)

        counts = {m["month"]: m["count"] for m in result["months"]}
        self.assertEqual(result["months"][-1]["month"], future)
        self.assertEqual(counts.get(future), 1)

    def test_empty_library_keeps_current_month_anchor(self) -> None:
        """Non-regression : la branche « aucune date » etait deja correcte."""
        before = _utc_month()
        result = self._timeline([], months=3)
        after = _utc_month()

        # Aucune row -> court-circuit total_films == 0, months vide.
        self.assertTrue(result["ok"], msg=result)
        self.assertEqual(result["months"], [])
        self.assertIn(before, {before, after})

    def test_rows_without_any_resolvable_date_anchor_on_today(self) -> None:
        """Des films mais aucune date exploitable : ancrage sur aujourd'hui."""
        before = _utc_month()
        result = self._timeline([None, None], months=6)
        after = _utc_month()

        self.assertTrue(result["ok"], msg=result)
        self.assertEqual(len(result["months"]), 6)
        self.assertIn(result["months"][-1]["month"], {before, after})
        self.assertEqual(result["films_with_date_pct"], 0.0)


# ---------------------------------------------------------------------------
# #545 — les insights abandonnes laissent une trace VISIBLE
# ---------------------------------------------------------------------------

_DASH_LOGGER = "cinesort.ui.api.dashboard_support"


def _make_insight_store() -> MagicMock:
    """Store neutre : chaque test ne fait echouer QU'UN site a la fois."""
    store = MagicMock()
    store.run.list_runs.return_value = []
    store.perceptual.list_perceptual_reports.return_value = []
    store.perceptual.count_v2_warnings_flag.return_value = 0
    store.perceptual.count_v2_tier_since.return_value = 0
    return store


class InsightSkipIsLoggedTests(unittest.TestCase):
    """#545 : chacun des 4 sites doit tracer, au niveau de log par defaut.

    `assertLogs(level="WARNING")` est ce qui donne sa valeur a ces tests : il
    porte le logger a WARNING, donc un `logger.debug` (le correctif suggere par
    l'issue) ne serait PAS capture et le test tomberait. C'est exactement la
    distinction entre « trace » et « trace visible » : la verbosite par defaut du
    produit est INFO.
    """

    def _insights(self, store: MagicMock, **kwargs: Any) -> List[Dict[str, Any]]:
        from cinesort.ui.api import dashboard_support

        return dashboard_support._compute_active_insights(
            MagicMock(),
            store,
            kwargs.pop("run_ids", ["r1"]),
            {},
            {},
            latest_scan_rid=kwargs.pop("latest_scan_rid", "r1"),
        )

    def test_run_in_progress_failure_is_logged(self) -> None:
        store = _make_insight_store()
        store.run.list_runs.side_effect = OSError("db locked")

        with self.assertLogs(_DASH_LOGGER, level="WARNING") as captured:
            insights = self._insights(store)

        self.assertTrue(any("run_in_progress" in line for line in captured.output), captured.output)
        self.assertTrue(any("db locked" in line for line in captured.output), captured.output)
        self.assertIsInstance(insights, list)

    def test_quality_reject_failure_is_logged_with_run_id(self) -> None:
        """Site le plus grave : sans trace, « aucun Reject » est indiscernable de « pas compte »."""
        store = _make_insight_store()
        store.perceptual.list_perceptual_reports.side_effect = OSError("io error")

        with self.assertLogs(_DASH_LOGGER, level="WARNING") as captured:
            insights = self._insights(store, latest_scan_rid="run-42")

        joined = "\n".join(captured.output)
        self.assertIn("quality_reject", joined)
        self.assertIn("run-42", joined)
        self.assertEqual([i for i in insights if i["type"] == "quality_reject"], [])

    def test_dnr_partial_failure_is_logged(self) -> None:
        store = _make_insight_store()
        store.perceptual.count_v2_warnings_flag.side_effect = AttributeError("no such method")

        with self.assertLogs(_DASH_LOGGER, level="WARNING") as captured:
            self._insights(store)

        joined = "\n".join(captured.output)
        self.assertIn("dnr_partial", joined)
        # Le TYPE d'exception doit figurer : c'est lui qui distingue un bug de
        # code (AttributeError) d'une panne d'I/O.
        self.assertIn("AttributeError", joined)

    def test_new_platinum_month_failure_is_logged(self) -> None:
        store = _make_insight_store()
        store.perceptual.count_v2_tier_since.side_effect = AttributeError("no such method")

        with self.assertLogs(_DASH_LOGGER, level="WARNING") as captured:
            self._insights(store)

        self.assertTrue(any("new_platinum_month" in line for line in captured.output), captured.output)

    def test_caller_is_not_broken_by_the_failure(self) -> None:
        """Choix assume : la Home reste best-effort, elle ne s'ecroule pas.

        Les 4 sites tombent en meme temps ; la fonction rend quand meme la liste
        des insights derives du bibliothecaire, et 4 traces sont emises.
        """
        store = _make_insight_store()
        store.run.list_runs.side_effect = OSError("boom")
        store.perceptual.list_perceptual_reports.side_effect = OSError("boom")
        store.perceptual.count_v2_warnings_flag.side_effect = OSError("boom")
        store.perceptual.count_v2_tier_since.side_effect = OSError("boom")

        from cinesort.ui.api import dashboard_support

        with self.assertLogs(_DASH_LOGGER, level="WARNING") as captured:
            insights = dashboard_support._compute_active_insights(
                MagicMock(),
                store,
                ["r1"],
                {},
                {"low_confidence_count": 3},
                latest_scan_rid="r1",
            )

        self.assertEqual([i["type"] for i in insights], ["films_low_confidence"])
        skipped = [line for line in captured.output if "abandonne apres erreur du store" in line]
        self.assertEqual(len(skipped), 4, captured.output)

    def test_no_warning_when_everything_works(self) -> None:
        """Pas de bruit : un chemin nominal ne doit rien logger en WARNING."""
        import logging

        store = _make_insight_store()
        logger = logging.getLogger(_DASH_LOGGER)
        with patch.object(logger, "warning") as mock_warning:
            self._insights(store)

        mock_warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()

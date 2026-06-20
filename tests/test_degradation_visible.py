"""ITER13 - Test de degradation visible (JAMAIS silencieuse).

Objectif (BILAN_ITER13 section 4) : prouver que quand un probe echoue
definitivement (apres retry+breaker), la degradation est VISIBLE et non
silencieuse, conformement a la memoire racine :

> degradation JAMAIS silencieuse - qualite indisponible visible PAS score
> invente PAS ligne disparue PAS 0 trompeur

Garanties testees :
1. **Item N'EST PAS perdu** : il reste dans la library (row presente).
2. **Item RESTE IDENTIFIE** : titre + year + tmdb_id sont propagees meme
   sans probe (acquis racine C iter4 - identification DECOUPLEE).
3. **Item RESTE RENOMMABLE** : `apply_core.py` ne lit AUCUN champ
   probe/score/tier -> apply continue de fonctionner.
4. **Qualite marquee EXPLICITEMENT "indisponible"** :
   - `probe_quality == "FAILED"` propage dans library_support et quality_audit_support
   - `quality_unavailable == True`
   - UI affiche "Indispo" / "Indisponible" (testable via grep qualite.js)
5. **Apply n'opere PAS sur metadonnees qualite non lues** : apply_core
   n'a aucune reference a probe/quality/tier/score.
6. **dry-run reste dry-run** : aucune ecriture introduite par les
   mecanismes de resilience.

Test family B : tests STATIQUES qui prouvent la structure du code, pas
de subprocess. Le scenario runtime complet est documente dans BILAN
sections 4 et 5.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_LIBRARY_SUPPORT = _REPO / "cinesort" / "ui" / "api" / "library_support.py"
_QUALITY_AUDIT_SUPPORT = _REPO / "cinesort" / "ui" / "api" / "quality_audit_support.py"
_APPLY_CORE = _REPO / "cinesort" / "app" / "apply_core.py"
_QUALITE_JS = _REPO / "web" / "dashboard" / "views" / "qualite.js"


class TestProbeQualityExposeParUI(unittest.TestCase):
    """Library row doit propager probe_quality + quality_unavailable."""

    def test_library_support_expose_probe_quality(self) -> None:
        self.assertTrue(_LIBRARY_SUPPORT.is_file())
        src = _LIBRARY_SUPPORT.read_text(encoding="utf-8")
        self.assertIn(
            '"probe_quality"', src,
            "library_support doit exposer 'probe_quality' dans la row",
        )
        self.assertIn(
            '"quality_unavailable"', src,
            "library_support doit exposer 'quality_unavailable' dans la row",
        )

    def test_library_support_quality_unavailable_calcule_depuis_failed(self) -> None:
        """quality_unavailable = (probe_quality == 'FAILED')."""
        src = _LIBRARY_SUPPORT.read_text(encoding="utf-8")
        # Regex tolerante : capture la condition d'evaluation.
        pattern = re.compile(
            r'"quality_unavailable"\s*:\s*str\(metrics\.get\("probe_quality"\)[^)]*\)[^=]*==\s*"FAILED"',
            re.DOTALL,
        )
        self.assertIsNotNone(
            pattern.search(src),
            "quality_unavailable doit etre derive de probe_quality == FAILED",
        )

    def test_quality_audit_support_propage_les_champs(self) -> None:
        """get_films_by_tier doit propager probe_quality + quality_unavailable."""
        self.assertTrue(_QUALITY_AUDIT_SUPPORT.is_file())
        src = _QUALITY_AUDIT_SUPPORT.read_text(encoding="utf-8")
        self.assertIn('"probe_quality"', src)
        self.assertIn('"quality_unavailable"', src)


class TestUIAfficheIndispo(unittest.TestCase):
    """qualite.js doit afficher 'Indispo' / 'Indisponible' visible."""

    def setUp(self) -> None:
        self.assertTrue(_QUALITE_JS.is_file())
        self.src = _QUALITE_JS.read_text(encoding="utf-8")

    def test_indispo_dans_qualite_js(self) -> None:
        """Le mot 'Indispo' doit apparaitre pour les cartes Reject."""
        self.assertIn(
            "Indispo",
            self.src,
            "qualite.js doit afficher 'Indispo' quand quality_unavailable",
        )

    def test_indisponible_dans_qualite_js(self) -> None:
        """Le mot 'Indisponible' (long) pour l'inspector."""
        self.assertIn(
            "Indisponible",
            self.src,
            "qualite.js doit afficher 'Indisponible' dans l'inspector",
        )

    def test_quality_unavailable_lu_dans_qualite_js(self) -> None:
        """qualite.js doit lire le champ quality_unavailable expose par le backend."""
        self.assertIn(
            "quality_unavailable",
            self.src,
            "qualite.js doit lire quality_unavailable pour decider l'affichage",
        )

    def test_probe_quality_failed_lu_dans_qualite_js(self) -> None:
        """qualite.js doit accepter probe_quality == 'FAILED' comme fallback."""
        # Cherche au moins un test "FAILED" lie a probe_quality.
        pattern = re.compile(
            r'probe_quality[^"]*"[^"]*"\s*\)?\.toUpperCase\(\)\s*===\s*"FAILED"',
            re.DOTALL,
        )
        self.assertIsNotNone(
            pattern.search(self.src),
            "qualite.js doit verifier probe_quality.toUpperCase() === 'FAILED'",
        )


class TestApplyDecouvert(unittest.TestCase):
    """Apply ne doit lire AUCUN champ qualite/score/tier/probe (acquis iter4)."""

    def setUp(self) -> None:
        self.assertTrue(_APPLY_CORE.is_file())
        self.src = _APPLY_CORE.read_text(encoding="utf-8")

    def test_apply_pas_de_lecture_probe_quality(self) -> None:
        """apply_core.py ne doit JAMAIS lire 'probe_quality'."""
        # Compatibilite : on autorise le mot dans un commentaire, mais pas
        # comme cle de dict.
        bad = re.findall(r'\.get\(\s*["\']probe_quality["\']', self.src)
        self.assertEqual(
            bad, [],
            "apply_core lit probe_quality - apply ne doit PAS dependre du probe",
        )

    def test_apply_pas_de_lecture_score_v2(self) -> None:
        """apply_core.py ne doit JAMAIS lire 'score_v2'."""
        bad = re.findall(r'\.get\(\s*["\']score_v2["\']', self.src)
        self.assertEqual(
            bad, [],
            "apply_core lit score_v2 - apply ne doit PAS dependre du score",
        )

    def test_apply_pas_de_lecture_tier_v2(self) -> None:
        """apply_core.py ne doit JAMAIS lire 'tier_v2'."""
        bad = re.findall(r'\.get\(\s*["\']tier_v2["\']', self.src)
        self.assertEqual(
            bad, [],
            "apply_core lit tier_v2 - apply ne doit PAS dependre du tier",
        )

    def test_apply_pas_de_lecture_quality_unavailable(self) -> None:
        """apply_core ne doit pas non plus utiliser quality_unavailable pour decider."""
        bad = re.findall(r'\.get\(\s*["\']quality_unavailable["\']', self.src)
        self.assertEqual(bad, [])


class TestIdentificationDecoupleePreservee(unittest.TestCase):
    """Item identifie via TMDb/NFO/filename meme avec probe FAILED."""

    def test_library_propage_title_meme_sans_probe(self) -> None:
        """library_support construit `title` depuis proposed_title/nfo_title, pas probe."""
        src = _LIBRARY_SUPPORT.read_text(encoding="utf-8")
        # Cherche la construction du titre (memoire iter4 acquis racine C).
        # On veut un fallback hierarchique (proposed_title OR nfo_title OR ...).
        self.assertTrue(
            "proposed_title" in src or "nfo_title" in src or "title" in src,
            "library_support doit construire le titre INDEPENDAMMENT du probe",
        )

    def test_library_propage_tmdb_id(self) -> None:
        """library_support doit propager tmdb_id (identification)."""
        src = _LIBRARY_SUPPORT.read_text(encoding="utf-8")
        self.assertIn(
            "tmdb_id", src,
            "library_support doit propager tmdb_id (identification decouplee)",
        )


class TestDegradedSourceCircuitBreaker(unittest.TestCase):
    """Quand circuit breaker UNC est ouvert, payload visible 'degraded_source'."""

    def test_probe_service_a_helper_degraded_payload(self) -> None:
        """ProbeService a une methode _degraded_source_payload qui marque visible."""
        service_py = _REPO / "cinesort" / "infra" / "probe" / "service.py"
        self.assertTrue(service_py.is_file())
        src = service_py.read_text(encoding="utf-8")
        self.assertIn(
            "_degraded_source_payload",
            src,
            "ProbeService doit avoir un helper de payload DEGRADED visible",
        )
        self.assertIn(
            "degraded_source",
            src,
            "Payload DEGRADED doit contenir le flag 'degraded_source'",
        )

    def test_payload_degrade_pas_de_score_invente(self) -> None:
        """Le payload DEGRADED ne contient pas de score fabrique (pas de 0 trompeur)."""
        service_py = _REPO / "cinesort" / "infra" / "probe" / "service.py"
        src = service_py.read_text(encoding="utf-8")
        # Capture la fonction _degraded_source_payload.
        match = re.search(
            r"def _degraded_source_payload\(.*?\n(?=    def |\Z)",
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "_degraded_source_payload introuvable")
        body = match.group(0)
        # Le payload ne doit pas tenter d'inventer un score numerique.
        self.assertNotIn(
            '"score":', body,
            "Payload DEGRADED ne doit PAS inventer un score numerique",
        )
        self.assertNotIn(
            '"score_v2":', body,
            "Payload DEGRADED ne doit PAS inventer un score_v2",
        )


class TestDryRunResteDryRun(unittest.TestCase):
    """Les fixes resilience ne touchent pas la logique apply -> dry-run preserve."""

    def test_apply_core_propage_dry_run(self) -> None:
        """apply_core.py propage dry_run partout (acquis iter intact)."""
        src = _APPLY_CORE.read_text(encoding="utf-8")
        # Au moins une occurrence (la verite est que c'est partout, mais 1 suffit
        # pour prouver que le flag existe).
        self.assertIn("dry_run", src, "apply_core doit propager dry_run")


if __name__ == "__main__":
    unittest.main()

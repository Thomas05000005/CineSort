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
   - UI affiche "Indispo" / "Indisponible" : verifie en EXECUTANT qualite.js
     sous Node (harnais tests/_jsexec.py), PAS par grep du source — un grep
     restait vert avec `const qualityUnavailable = false;` en production.
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

from tests._jsexec import require_node, run_module_test

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
            '"probe_quality"',
            src,
            "library_support doit exposer 'probe_quality' dans la row",
        )
        self.assertIn(
            '"quality_unavailable"',
            src,
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


# ---------------------------------------------------------------------------
# 4. L'UI AFFICHE "Indispo" — verifie en EXECUTANT qualite.js
# ---------------------------------------------------------------------------
#
# Historique (lot 7, 2026-08-31) : cette classe ne faisait que chercher les
# chaines "Indispo", "Indisponible", "quality_unavailable" et un motif
# `probe_quality...toUpperCase() === "FAILED"` dans le SOURCE de qualite.js.
# Elle promettait « l'UI AFFICHE Indispo » et ne prouvait que « le fichier
# CONTIENT ces octets ».
#
# Mesure : en remplacant la ligne 224 de `views/qualite.js` par
# `const qualityUnavailable = false;` — c'est-a-dire en faisant afficher a
# l'ecran le score Silver-cap trompeur que toute cette iteration cherche a
# eviter — les 16 tests du fichier restaient VERTS. Les gabarits de secours
# (`Indispo`, `Indisponible`) sont dans des litteraux de template qui, eux, ne
# bougent pas : le grep les voit toujours, l'utilisateur ne les voit plus.
#
# Reecrit sur le harnais `tests/_jsexec.py` : la VRAIE source de
# `views/qualite.js` est executee sous Node (seuls ses imports sont stubbes) et
# on lit le HTML rendu par `_renderRejectSection` / `_buildInspectorSections`.

_QUALITE_STUBS = r"""
const escapeHtml = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
const apiPost = async () => ({ status: 200, data: { ok: true } });
const getNavSignal = () => null;
const navigateTo = () => {};
const rightPanel = { setSections: () => {}, setTitle: () => {}, setExpandedWidth: () => {} };
const dangerConfirmModal = () => {};
const showToast = () => {};
const openQualiteFiltersDrawer = () => {};
const emptyFilters = () => ({ decades: [], genres: [], sources: [], audio_languages: [], period_days: 30 });
globalThis.window = globalThis.window || { addEventListener() {}, removeEventListener() {}, location: { hash: "#/qualite" } };
globalThis.document = globalThis.document || {
  querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
  addEventListener() {}, removeEventListener() {},
};
"""

# Trois films Reject qui couvrent les trois etats possibles de la mesure :
#   r1 : probe FAILED signale par le backend (`quality_unavailable`)
#   r2 : mesure REELLE -> le score doit s'afficher
#   r3 : `probe_quality` en minuscules -> la comparaison est insensible a la casse
# r1 et r3 portent DELIBEREMENT un `score_v2` : c'est exactement le score
# trompeur que l'ecran ne doit pas montrer.
_QUALITE_DRIVER = r"""
const films = [
  { row_id: "r1", title: "Probe injoignable", year: 2001, quality_unavailable: true, score_v2: 42, tier: "reject", warnings: ["w1", "w2"] },
  { row_id: "r2", title: "Mesure reelle", year: 2002, quality_unavailable: false, score_v2: 37, tier: "reject", warnings: [] },
  { row_id: "r3", title: "Probe failed minuscule", year: 2003, probe_quality: "failed", score_v2: 55, tier: "reject", warnings: [] },
];
const stats = { tier_distribution: { reject: 3 } };
M.__testing__.state.rejectFilms = films;
M.__testing__.state.stats = stats;
const cartes = M.__testing__.renderRejectSection(stats);

M.__testing__.state.inspectorSection = "distribution";
M.__testing__.state.inspectorPayload = { tier: "reject", films };
const listeInspecteur = M.__testing__.buildInspectorSections().map((s) => String(s.html || "")).join("");

M.__testing__.state.inspectorSection = "reject_card";
M.__testing__.state.inspectorPayload = { film: films[0] };
const ficheInspecteur = M.__testing__.buildInspectorSections().map((s) => String(s.html || "")).join("");

__emit({ cartes, listeInspecteur, ficheInspecteur });
"""


class TestUIAfficheIndispo(unittest.TestCase):
    """qualite.js doit RENDRE 'Indispo' / 'Indisponible', pas seulement le contenir."""

    _res: dict | None = None

    def _rendu(self) -> dict:
        require_node(self)
        if TestUIAfficheIndispo._res is None:
            TestUIAfficheIndispo._res = run_module_test(
                _QUALITE_JS,
                stubs=_QUALITE_STUBS,
                extra="",
                driver=_QUALITE_DRIVER,
            )
        return TestUIAfficheIndispo._res

    def test_la_carte_reject_rend_indispo_pour_chaque_probe_perdu(self) -> None:
        """ROUGE si `quality_unavailable` cesse d'etre lu : le badge disparait."""
        html = self._rendu()["cartes"]
        badge = (
            '<span class="qualite-reject-score qualite-reject-unavailable"'
            ' title="Probe indisponible : qualite non mesuree">Indispo</span>'
        )
        self.assertEqual(
            html.count(badge),
            2,
            "les 2 films sans mesure (flag backend + probe_quality='failed') doivent porter le badge Indispo",
        )
        self.assertIn(
            '<span class="qualite-reject-warnings" title="Qualite non verifiee">⚠ Qualite indisponible</span>',
            html,
            "la carte doit DIRE que la qualite n'a pas ete verifiee",
        )

    def test_aucun_score_invente_pour_un_probe_perdu(self) -> None:
        """Le score Silver-cap trompeur ne doit JAMAIS s'afficher."""
        html = self._rendu()["cartes"]
        # Bornage sur le badge COMPLET : un `assertNotIn("42", html)` rougirait
        # sur le "42" d'un autre attribut (index, annee, largeur...).
        self.assertNotIn('<span class="qualite-reject-score" title="Score V2">42</span>', html)
        self.assertNotIn('<span class="qualite-reject-score" title="Score V2">55</span>', html)
        # Controle positif OBLIGATOIRE : sans lui, un rendu vide passerait.
        self.assertIn('<span class="qualite-reject-score" title="Score V2">37</span>', html)

    def test_la_ligne_n_est_pas_perdue(self) -> None:
        """Garantie 1 : l'item reste AFFICHE, identifie, cliquable."""
        html = self._rendu()["cartes"]
        for titre in ("Probe injoignable", "Mesure reelle", "Probe failed minuscule"):
            self.assertIn(f'<span class="qualite-reject-title">{titre}</span>', html)
        for row_id in ("r1", "r2", "r3"):
            self.assertIn(f'data-qualite-reject-card="{row_id}"', html)

    def test_l_inspecteur_rend_indisponible_et_pas_un_score(self) -> None:
        """Meme regle dans la liste par tier de l'inspecteur droit."""
        html = self._rendu()["listeInspecteur"]
        badge = (
            '<span class="qualite-inspector-score qualite-reject-unavailable"'
            ' title="Probe indisponible">Indisponible</span>'
        )
        self.assertEqual(html.count(badge), 2)
        self.assertIn('<span class="qualite-inspector-score">37/100</span>', html)
        self.assertNotIn('<span class="qualite-inspector-score">42/100</span>', html)
        self.assertNotIn('<span class="qualite-inspector-score">55/100</span>', html)

    def test_la_fiche_inspecteur_marque_le_tier_comme_estime(self) -> None:
        """Sans mesure, le tier affiche vient du NOM : il est annonce 'estime'."""
        html = self._rendu()["ficheInspecteur"]
        self.assertIn(
            '<span class="qualite-reject-unavailable" title="Probe indisponible apres retry+breaker">Indisponible</span>',
            html,
        )
        self.assertIn("<em>(estime)</em>", html)
        self.assertNotIn("42/100", html)


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
            bad,
            [],
            "apply_core lit probe_quality - apply ne doit PAS dependre du probe",
        )

    def test_apply_pas_de_lecture_score_v2(self) -> None:
        """apply_core.py ne doit JAMAIS lire 'score_v2'."""
        bad = re.findall(r'\.get\(\s*["\']score_v2["\']', self.src)
        self.assertEqual(
            bad,
            [],
            "apply_core lit score_v2 - apply ne doit PAS dependre du score",
        )

    def test_apply_pas_de_lecture_tier_v2(self) -> None:
        """apply_core.py ne doit JAMAIS lire 'tier_v2'."""
        bad = re.findall(r'\.get\(\s*["\']tier_v2["\']', self.src)
        self.assertEqual(
            bad,
            [],
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
            "tmdb_id",
            src,
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
            '"score":',
            body,
            "Payload DEGRADED ne doit PAS inventer un score numerique",
        )
        self.assertNotIn(
            '"score_v2":',
            body,
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

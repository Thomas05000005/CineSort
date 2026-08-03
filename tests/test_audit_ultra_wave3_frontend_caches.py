"""Audit ultra 2026-07-13 — Vague 3 : tri Validation FR + caches frontend jamais invalides.

Findings couverts (assertions sur la SOURCE JS + node --check) :

  - M14 : traitement.js `_sortValidationRows` triait les titres via
    `toLocaleLowerCase().localeCompare()` SANS options (ni numeric, ni
    ignorePunctuation) et sur `proposed_title` seul. Fix : reutiliser le meme
    Intl.Collator FR que la Bibliotheque / l'etape Verification (_FR_COLLATOR)
    et aligner la cle de tri sur la cle AFFICHEE (display_title || proposed_title).

  - M19 : historique.js `_historyStatsCache` / `_filmsCacheByRun` (Maps
    module-level) n'etaient purges que par delete_run/undo/Recharger. Les deux
    unmount (unmountHistorique ET unmountRunDetailPage) doivent les vider pour
    qu'un remontage refetch (sinon stats/films perimes d'un autre run).

  - M21 : accueil.js `_pingCache` (TTL 5 min, clef par NOM d'integration) n'etait
    jamais purge apres un changement de settings -> pastille perimee. Fix : purger
    le cache a chaque (re)lecture des settings dans initAccueil (pas de fingerprint
    des valeurs car get_settings masque les secrets).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TRAITEMENT_JS = _ROOT / "web" / "dashboard" / "views" / "traitement.js"
_HISTORIQUE_JS = _ROOT / "web" / "dashboard" / "views" / "historique.js"
_ACCUEIL_JS = _ROOT / "web" / "dashboard" / "views" / "accueil.js"


def _fn_block(src: str, signature_substr: str) -> str:
    """Retourne le corps { ... } de la fonction dont la signature contient
    `signature_substr`, par comptage d'accolades (robuste aux blocs imbriques)."""
    i = src.index(signature_substr)
    b = src.index("{", i)
    depth = 0
    for j in range(b, len(src)):
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[i : j + 1]
    return src[i:]


class M14SortValidationFrCollatorTests(unittest.TestCase):
    """M14 : tri Validation avec collation FR + cle affichee."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")
        cls.sort_fn = _fn_block(cls.js, "function _sortValidationRows(")

    def test_shared_fr_collator_declared_with_options(self) -> None:
        # Meme instance/options que la Bibliotheque : sensitivity base + numeric + ignorePunctuation.
        self.assertRegex(
            self.js,
            r'const\s+_FR_COLLATOR\s*=\s*new\s+Intl\.Collator\(\s*"fr"\s*,\s*\{[^}]*'
            r'sensitivity:\s*"base"[^}]*numeric:\s*true[^}]*ignorePunctuation:\s*true[^}]*\}\s*\)',
        )

    def test_sort_title_branch_uses_fr_collator(self) -> None:
        self.assertIn("_FR_COLLATOR.compare", self.sort_fn)

    def test_sort_title_branch_no_naive_localecompare(self) -> None:
        # L'ancien tri naif (toLocaleLowerCase sans options) ne doit plus exister
        # dans le CODE de la fonction de tri (on ignore les commentaires, qui
        # citent volontairement l'ancienne approche).
        code_only = re.sub(r"//[^\n]*", "", self.sort_fn)
        self.assertNotIn("toLocaleLowerCase", code_only)
        self.assertNotIn(".localeCompare(", code_only)

    def test_sort_key_aligned_on_displayed_title(self) -> None:
        # La cle de tri doit etre la cle AFFICHEE (display_title || proposed_title),
        # pas proposed_title seul.
        self.assertIn("a.display_title || a.proposed_title", self.sort_fn)
        self.assertIn("b.display_title || b.proposed_title", self.sort_fn)


class M19HistoriqueCacheUnmountTests(unittest.TestCase):
    """M19 : les deux unmount vident _historyStatsCache ET _filmsCacheByRun."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HISTORIQUE_JS.read_text(encoding="utf-8")
        cls.unmount_hist = _fn_block(cls.js, "export function unmountHistorique(")
        cls.unmount_detail = _fn_block(cls.js, "export function unmountRunDetailPage(")

    def test_unmount_historique_clears_history_stats_cache(self) -> None:
        self.assertIn("_historyStatsCache.clear()", self.unmount_hist)

    def test_unmount_historique_clears_films_cache(self) -> None:
        self.assertIn("_filmsCacheByRun.clear()", self.unmount_hist)

    def test_unmount_run_detail_clears_history_stats_cache(self) -> None:
        self.assertIn("_historyStatsCache.clear()", self.unmount_detail)

    def test_unmount_run_detail_clears_films_cache(self) -> None:
        self.assertIn("_filmsCacheByRun.clear()", self.unmount_detail)


class M21PingCachePurgeTests(unittest.TestCase):
    """M21 (+ revue R2) : purge _pingCache UNIQUEMENT quand l'epoque des settings
    change (apres un save_settings), pas a chaque montage (sinon flicker + re-ping)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")
        cls.init_fn = _fn_block(cls.js, "export async function initAccueil(")

    def test_purge_helper_defined(self) -> None:
        self.assertIn("function _purgePingCacheAll(", self.js)
        # La purge doit vraiment vider le dict _pingCache.
        purge_fn = _fn_block(self.js, "function _purgePingCacheAll(")
        self.assertIn("_pingCache", purge_fn)
        self.assertIn("delete", purge_fn)

    def test_purge_called_in_init_accueil(self) -> None:
        self.assertIn("_purgePingCacheAll()", self.init_fn)

    def test_purge_is_after_settings_resolution(self) -> None:
        # La purge doit suivre la resolution des settings (evenement de relecture),
        # donc apparaitre apres l'affectation _currentSettings = settings.
        idx_settings = self.init_fn.index("_currentSettings = settings")
        idx_purge = self.init_fn.index("_purgePingCacheAll()")
        self.assertLess(idx_settings, idx_purge)

    def test_purge_is_gated_on_settings_epoch(self) -> None:
        # Revue R2 : la purge NE DOIT PAS etre inconditionnelle. Elle est gardee
        # par une comparaison d'epoque (getSettingsEpoch) pour ne se declencher
        # qu'apres un vrai save_settings, pas a chaque navigation vers Accueil.
        self.assertIn("getSettingsEpoch()", self.init_fn)
        self.assertIn("_lastPingPurgeEpoch", self.init_fn)
        # L'appel de purge est a l'interieur d'un if (garde par l'epoque).
        idx_guard = self.init_fn.index("_lastPingPurgeEpoch")
        idx_purge = self.init_fn.index("_purgePingCacheAll()")
        self.assertLess(idx_guard, idx_purge)

    def test_api_exports_settings_epoch(self) -> None:
        # L'epoque doit etre bumpee a chaque invalidateSettingsCache (= save_settings).
        api_js = (_ACCUEIL_JS.parent.parent / "core" / "api.js").read_text(encoding="utf-8")
        self.assertIn("export function getSettingsEpoch(", api_js)
        inval_fn = _fn_block(api_js, "export function invalidateSettingsCache(")
        self.assertIn("_settingsEpoch", inval_fn)


class NodeCheckTests(unittest.TestCase):
    """node --check des 3 fichiers modifies (syntaxe ESM valide)."""

    def _node_check(self, path: Path) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node introuvable sur le PATH")
        res = subprocess.run(
            [node, "--check", str(path)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, msg=f"node --check {path.name} a echoue:\n{res.stderr}")

    def test_traitement_js_syntax(self) -> None:
        self._node_check(_TRAITEMENT_JS)

    def test_historique_js_syntax(self) -> None:
        self._node_check(_HISTORIQUE_JS)

    def test_accueil_js_syntax(self) -> None:
        self._node_check(_ACCUEIL_JS)


if __name__ == "__main__":
    unittest.main()

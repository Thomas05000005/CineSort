"""Issue #1022 — la whitelist du cache hors ligne portait 8 cles mortes.

`isCacheable(method)` est interroge avec la methode TELLE QU'ELLE EST APPELEE.
Or l'API n'expose que `POST /api/<facade>/<methode>` : les chemins historiques
`/api/<methode>` rendent 404 (cf. `CLAUDE.md`). Les 8 entrees non prefixees ne
pouvaient donc plus jamais correspondre — le cache hors ligne les portait sans
que rien ne les atteigne.

Mesure faite avant de retirer, cle par cle : 7 des 8 avaient deja leur jumelle
prefixee dans le meme ensemble, qui est le chemin reellement appele. La
huitieme, `get_runs_summary`, n'avait NI site d'appel dans `web/` NI methode de
facade — elle designait une methode inexistante.

Ces tests executent la VRAIE source du module sous Node : ils lisent ce que
`isCacheable` repond, pas le contenu du fichier.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, require_node, run_module_test

JS = ROOT / "web" / "dashboard" / "core" / "cache.js"

STUBS = r"""
globalThis.localStorage = {
  _d: {},
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._d, k) ? this._d[k] : null; },
  setItem(k, v) { this._d[k] = String(v); },
  removeItem(k) { delete this._d[k]; },
};
"""

EXTRA = r"""
export const __h = { isCacheable };
"""


class LeCacheNeRepondQuAuxCheminsPrefixesTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _demande(self, methodes: list[str]) -> dict:
        appels = ", ".join(f'"{m}": M.__h.isCacheable("{m}")' for m in methodes)
        return run_module_test(
            JS, stubs=STUBS, extra=EXTRA, driver=f"__emit({{ {appels} }});", autorise_zero_import=True
        )

    def test_les_chemins_reellement_appeles_restent_cachables(self):
        """Contre-test EN PREMIER : retirer les cles mortes ne doit rien casser.

        Ce sont les seules formes que le client emet — si l'une tombait, le mode
        hors ligne perdrait un ecran, ce qui serait pire que la dette retiree.
        """
        vus = self._demande(
            [
                "run/get_dashboard",
                "run/get_global_stats",
                "settings/get_settings",
                "runtime/get_probe_tools_status",
                "integrations/get_jellyfin_libraries",
                "integrations/get_plex_libraries",
                "integrations/get_radarr_status",
            ]
        )
        for methode, cachable in vus.items():
            self.assertTrue(cachable, f"{methode} doit rester cachable : c'est le chemin REEL")

    def test_les_formes_non_prefixees_ne_sont_plus_declarees(self):
        """ROUGE avant le correctif : les 8 repondaient `true` pour rien.

        Une whitelist qui declare des cles inatteignables se lit comme un
        inventaire de ce qui est cache. Elle ment sur son propre perimetre.
        """
        vus = self._demande(
            [
                "get_dashboard",
                "get_global_stats",
                "get_settings",
                "get_probe_tools_status",
                "get_jellyfin_libraries",
                "get_plex_libraries",
                "get_radarr_status",
            ]
        )
        for methode, cachable in vus.items():
            self.assertFalse(
                cachable,
                f"`{methode}` sans prefixe de facade rend 404 cote API : la declarer cachable est une entree morte",
            )

    def test_get_runs_summary_a_disparu_des_deux_formes(self):
        """Le cas a part : ni site d'appel, ni methode de facade. Aucune des
        deux formes ne doit subsister, sinon on garde une cle qui designe une
        methode qui n'existe pas."""
        vus = self._demande(["get_runs_summary", "run/get_runs_summary"])
        self.assertFalse(vus["get_runs_summary"])
        self.assertFalse(vus["run/get_runs_summary"])


if __name__ == "__main__":
    unittest.main()

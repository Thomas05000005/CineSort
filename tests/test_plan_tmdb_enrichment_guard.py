"""Guard test ITER4 etape 2b RE-ANCRAGE (vraie entree publique start_plan).

Sujet : "plan sur titre matchable Inception peuple tmdb_id ET poster_url
non-null", verifie en TRAVERSANT la VRAIE entree publique `RunFacade.start_plan`
(comme le handler REST) plutot qu'en mockant `_start_plan_impl`.

Pourquoi cette refonte (iter3 -> iter4) :
- Le guard test iter3 mockait `_start_plan_impl` -> il ne validait que le
  wrapper pydantic + la propagation kwargs, JAMAIS la chaine reelle qui
  appelle `_init_tmdb_client` + `plan_multi_roots` + `build_candidates_from_tmdb`.
- Iter4 a decouvert un fix racine plus profond (`_hydrate_settings_from_store`
  dans `run_flow_support.py`) : le caller REST envoie un body minimal
  `{settings:{library_path:...}}` SANS `tmdb_api_key` ; sans hydration depuis
  le settings.json on-disk, TMDb etait silencieusement desactive.
- Le guard test doit donc traverser TOUT le pipeline et asserter sur
  l'artefact final `plan.jsonl` (tmdb_id != None ET poster_url != None sur
  un titre matchable comme "Inception (2010)").

Strategie :
- On monte une bibliotheque tmpdir minimale avec `Inception.2010.1080p.mkv`.
- On persiste un `settings.json` on-disk avec `tmdb_enabled=True` +
  `tmdb_api_key="legacy_plaintext_xyz"` (chemin legacy plaintext autorise par
  `extract_tmdb_key_from_settings_payload`).
- On patche `cinesort.ui.api.run_flow_support.TmdbClient` pour retourner un
  fake deterministe : `search_movie("Inception", 2010)` -> 1 `TmdbResult`
  Inception id=27205 poster_path="/9gk7adH...". Aucun appel reseau.
- On invoque `api.run.start_plan({"library_path": ..., "state_dir": ...,
  "root": ...})` SANS passer `tmdb_api_key` dans le payload : cas du body
  REST minimal.
- On attend le run done puis on lit `plan.jsonl` directement (source de
  verite). Assertions :
    1. `fake_tmdb.search_movie` a ete appele >= 1 fois (preuve que TMDb a
       ete active dans la chaine reelle).
    2. La 1re candidate du plan a `tmdb_id == 27205`.
    3. Son `poster_url` contient `image.tmdb.org` (CSP whitelisted).

Sequence d'echec/passage attendue (cf consigne iter4 etape 2b) :
- Pre-7df3af3e (avant fix ii.b iter3) : pas d'hydration -> tmdb_api_key
  absent du settings transmis a `_init_tmdb_client` -> TmdbClient pas
  instancie -> `search_movie` jamais appele -> ECHEC.
- Post-7df3af3e mais pre-iter4 (commit 9d8b8e9 checkpoint) : meme situation,
  le fix ii.b ne touchait QUE le wrap pydantic, pas l'hydration -> ECHEC.
- Post-iter4 (working tree avec `_hydrate_settings_from_store`) : hydration
  fusionne le settings.json on-disk -> tmdb_api_key present -> TmdbClient
  cree -> search_movie appele -> tmdb_id + poster_url remplis -> PASSE.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, List, Optional
from unittest import mock

import cinesort.domain.core as core
import cinesort.ui.api.run_flow_support as run_flow_support
from cinesort.infra.tmdb_client import TmdbResult
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import cleanup_test_tree
from tests._helpers import create_file as _create_file
from tests._helpers import wait_run_done as _wait_done


class _FakeTmdbClient:
    """Fake TmdbClient deterministe offline.

    Instancie par le production code via `TmdbClient(api_key=..., cache_path=...,
    timeout_s=..., cache_ttl_days=...)`. On accepte les memes kwargs sans
    rien faire (pas d'I/O reseau, pas de cache disque).

    `search_movie` retourne 1 `TmdbResult` Inception si la query contient
    "inception", sinon liste vide. On compte les appels pour pouvoir asserter
    que la chaine a bien appele TMDb. Toutes les autres methodes TMDb appelees
    par le pipeline (get_movie_collection, find_by_tmdb_id, etc.) renvoient
    des valeurs neutres pour ne pas planter le run.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.api_key = kwargs.get("api_key") or (args[0] if args else "")
        self.search_calls: List[dict] = []

    def search_movie(
        self,
        query: str,
        year: Optional[int] = None,
        *,
        language: str = "fr-FR",
        max_results: int = 8,
    ) -> List[TmdbResult]:
        self.search_calls.append({"query": query, "year": year, "language": language})
        q = (query or "").strip().lower()
        if "inception" in q:
            return [
                TmdbResult(
                    id=27205,
                    title="Inception",
                    year=2010,
                    original_title="Inception",
                    popularity=100.0,
                    vote_count=30000,
                    vote_average=8.4,
                    poster_path="/9gk7adHYeDvHkCSEqAvQNLV5Uge.jpg",
                )
            ]
        return []

    # API surface minimale utilisee par le pipeline plan/replan. Les valeurs
    # neutres (None, "", tuple vides) suffisent : on veut juste que la chaine
    # ne plante pas et que `tmdb_id` + `poster_url` arrivent jusqu'au plan.jsonl.
    def get_movie_collection(self, movie_id: int):
        return (None, None)

    def get_alternative_titles(self, movie_id: int):
        return []

    def get_movie_runtime(self, movie_id: int):
        return None

    def get_movie_poster_thumb_url(self, poster_path):
        if not poster_path:
            return None
        p = str(poster_path)
        if not p.startswith("/"):
            p = "/" + p
        return f"https://image.tmdb.org/t/p/w92{p}"

    def get_movie_metadata_for_perceptual(self, movie_id: int):
        return None

    def find_by_tmdb_id(self, tmdb_id: int):
        return None

    def find_by_imdb_id(self, imdb_id: str):
        return None

    def _get_movie_detail_cached(self, movie_id: int):
        return None

    def search_tv(self, *args: Any, **kwargs: Any):
        return []

    def get_tv_episode_title(self, *args: Any, **kwargs: Any):
        return None

    def validate_key(self):
        return (True, "OK")

    def get(self, *args: Any, **kwargs: Any):
        return None

    def flush(self) -> None:
        return None


class PlanTitreMatchablePeupleTmdbIdEtPosterUrlGuardTests(unittest.TestCase):
    """Guard ITER4 2b : valide l'enrichissement TMDb via le pipeline reel."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_guard_tmdb_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # MIN_VIDEO_BYTES=1 pour autoriser un fichier minimal de 2 KB.
        p_min = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        p_min.start()
        self.addCleanup(p_min.stop)

        # Bibliotheque tmpdir : 1 film Inception (2010) reconnaissable par le
        # parseur de noms (folder + video avec annee).
        _create_file(self.root / "Inception.2010.1080p" / "Inception.2010.1080p.mkv")

        # settings.json on-disk : tmdb_enabled + tmdb_api_key plaintext legacy.
        # C'est la persistance que l'iter4 fix racine C lit via
        # `_hydrate_settings_from_store` pour combler le caller minimal.
        settings_path = self.state_dir / "settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "root": str(self.root),
                    "state_dir": str(self.state_dir),
                    "tmdb_enabled": True,
                    "tmdb_api_key": "legacy_plaintext_xyz",
                    "tmdb_cache_ttl_days": 14,
                    "remember_key": True,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        # Holder partage entre _FakeTmdbClient instances et les assertions.
        # On capture la derniere instance creee par le code de prod (chaque
        # _init_tmdb_client en cree une).
        self._fake_instances: List[_FakeTmdbClient] = []

        def _factory(*args: Any, **kwargs: Any) -> _FakeTmdbClient:
            inst = _FakeTmdbClient(*args, **kwargs)
            self._fake_instances.append(inst)
            return inst

        # Patch CIBLE : la classe `TmdbClient` importee par `run_flow_support`.
        # C'est elle qui est instanciee dans `_init_tmdb_client` (line 207),
        # donc patcher ici intercepte la chaine reelle sans toucher au domain.
        p_tmdb = mock.patch.object(run_flow_support, "TmdbClient", side_effect=_factory)
        p_tmdb.start()
        self.addCleanup(p_tmdb.stop)

    def tearDown(self) -> None:
        cleanup_test_tree(self._tmp)

    def _run_dir(self, run_id: str) -> Path:
        return self.state_dir / "runs" / f"tri_films_{run_id}"

    def test_plan_titre_matchable_peuple_tmdb_id_et_poster_url(self) -> None:
        """Guard test ITER4 2b : traverse la VRAIE entree publique start_plan.

        Body REST minimal `{settings:{library_path:...}}` sans tmdb_api_key.
        Avec iter4 fix racine C, l'hydration depuis settings.json on-disk
        permet a TmdbClient de s'initialiser ; sans iter4, TMDb est mute.
        """
        api = CineSortApi()

        # IMPORTANT : on N'envoie PAS tmdb_api_key dans le payload caller.
        # C'est exactement la situation prod (handler REST avec body minimal)
        # qui a motive le fix racine C iter4 (hydration on-disk).
        payload = {
            "library_path": str(self.root),  # cle documentee dans PlanSettings
            "root": str(self.root),  # cle reellement consommee par resolve_roots
            "state_dir": str(self.state_dir),
            # PAS de tmdb_enabled ni tmdb_api_key : ils doivent venir de
            # l'hydration on-disk (settings.json persiste en setUp).
            "collection_folder_enabled": True,
        }

        start = api.run.start_plan(payload)
        self.assertTrue(start.get("ok"), f"start_plan a echoue : {start}")
        run_id = str(start["run_id"])

        # Attendre que le job background termine. Inception sur 1 film
        # tmpdir + tmdb mocke offline = rapide (< 5s en pratique).
        status = _wait_done(api, run_id, timeout_s=20.0)
        self.assertIsNone(status.get("error"), f"Run en erreur : {status}")

        # --- Assertion 1 : TMDb a effectivement ete sollicite ---
        # Si search_movie n'a jamais ete appele, c'est que `_init_tmdb_client`
        # a retourne None (cle vide), preuve que l'hydration a echoue.
        total_calls = sum(len(inst.search_calls) for inst in self._fake_instances)
        self.assertGreater(
            total_calls,
            0,
            "REGRESSION racine C : TmdbClient.search_movie n'a JAMAIS ete appele "
            "sur le pipeline reel. Cela signifie que `_init_tmdb_client` a vu "
            "`api_key=''` (settings sans tmdb_api_key) -> branche `elif "
            "tmdb_enabled` a desactive TMDb. Verifier que "
            "`_hydrate_settings_from_store` dans run_flow_support.py merge bien "
            "le settings.json on-disk avant `_validate_and_init_plan_context`.",
        )

        # --- Assertion 2 : plan.jsonl produit, tmdb_id non-null sur Inception ---
        plan_jsonl = self._run_dir(run_id) / "plan.jsonl"
        self.assertTrue(plan_jsonl.exists(), f"plan.jsonl absent : {plan_jsonl}")

        lines = [line for line in plan_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, f"Attendu 1 row dans plan.jsonl, vu {len(lines)}")
        row = json.loads(lines[0])

        # On verifie la 1re candidate (celle qui a le score max apres tri du
        # domain.core build_candidates_from_tmdb).
        candidates = row.get("candidates") or []
        self.assertGreaterEqual(len(candidates), 1, "Aucune candidate dans plan.jsonl - TMDb n'a rien enrichi.")

        # Extrait toutes les candidates TMDb (source == "tmdb") et verifie
        # qu'au moins une porte tmdb_id + poster_url non-null sur Inception.
        tmdb_candidates = [c for c in candidates if str(c.get("source") or "") == "tmdb"]
        self.assertGreaterEqual(
            len(tmdb_candidates),
            1,
            "REGRESSION : aucune candidate source='tmdb' dans plan.jsonl alors "
            f"que TMDb a ete appele {total_calls} fois. Verifier build_candidates_from_tmdb.",
        )

        chosen = tmdb_candidates[0]
        self.assertEqual(
            int(chosen.get("tmdb_id") or 0),
            27205,
            f"Sujet guard test : candidate.tmdb_id DOIT etre 27205 (Inception). Vu : {chosen}",
        )
        poster_url = str(chosen.get("poster_url") or "")
        self.assertTrue(
            poster_url,
            "Sujet guard test : candidate.poster_url DOIT etre non-null pour "
            "un titre matchable. Si null -> TMDb desactive en amont.",
        )
        self.assertIn(
            "image.tmdb.org",
            poster_url,
            f"poster_url doit pointer sur image.tmdb.org (CSP whitelist). Vu : {poster_url}",
        )


if __name__ == "__main__":
    unittest.main()

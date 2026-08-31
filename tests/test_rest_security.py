"""LOT D — Tests de securite pour l'API REST.

Couvre : auth (401), rate limiter (429, par-IP, fenetre), pas de reflexion 404,
pas de leak 500, path traversal, CORS non-wildcard.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import cinesort.ui.api.cinesort_api as backend
from cinesort.infra.rest_server import RestApiServer, _RateLimiter
from tests._helpers import find_free_port as _find_free_port

# Endpoint VIVANT (format facade) utilise par les tests d'auth.
# Ne PAS revenir a "/api/get_settings" : depuis la desactivation par defaut de
# Pass 1 (P0 #233), cette route legacy repond 410 Gone. Un test d'auth qui vise
# une route morte peut devenir vert/rouge pour une raison etrangere a l'auth.
_AUTH_ENDPOINT = "/api/settings/get_settings"


@contextlib.contextmanager
def _auth_really_enforced():
    """Desactive le bypass « localhost desktop trusted » le temps du bloc.

    Depuis le 2026-06-08, `RestRequestHandler._check_auth` accorde un bypass
    TOTAL de l'auth quand les 3 conditions sont reunies : client loopback,
    serveur bind sur 127.0.0.1, et kill-switch `CINESORT_DISABLE_LOCAL_AUTH`
    inactif (mode bureau pywebview : un attaquant local a deja le shell).

    Consequence : un test d'auth qui tape 127.0.0.1 SANS ce kill-switch ne
    teste plus rien — la requete sans token traverse le handler et repond 200.
    Les assertions 401 ci-dessous epinglaient donc un comportement
    VOLONTAIREMENT change ; on les rebranche sur la configuration ou l'auth
    Bearer est reellement exigee (kill-switch documente = mode expose/LAN),
    pour qu'elles restent capables de rougir si l'auth casse.
    """
    with mock.patch.dict(os.environ, {"CINESORT_DISABLE_LOCAL_AUTH": "1"}):
        yield


# ---------------------------------------------------------------------------
# Tests unitaires du rate limiter (pas besoin de serveur)
# ---------------------------------------------------------------------------


class RateLimiterUnitTests(unittest.TestCase):
    # 29
    def test_rate_limiter_blocks_after_5_failures(self) -> None:
        limiter = _RateLimiter(max_failures=5, window_s=60.0)
        ip = "10.0.0.1"
        for _ in range(4):
            limiter.record_failure(ip)
        self.assertFalse(limiter.is_blocked(ip))
        limiter.record_failure(ip)
        self.assertTrue(limiter.is_blocked(ip))

    # 30
    def test_rate_limiter_resets_after_window(self) -> None:
        """Fenetre tres courte : apres expiration, l'IP n'est plus bloquee."""
        limiter = _RateLimiter(max_failures=3, window_s=0.1)
        ip = "10.0.0.2"
        for _ in range(3):
            limiter.record_failure(ip)
        self.assertTrue(limiter.is_blocked(ip))
        time.sleep(0.15)  # attendre expiration
        self.assertFalse(limiter.is_blocked(ip))

    # 31
    def test_rate_limiter_per_ip(self) -> None:
        limiter = _RateLimiter(max_failures=5, window_s=60.0)
        for _ in range(5):
            limiter.record_failure("10.0.0.1")
        self.assertTrue(limiter.is_blocked("10.0.0.1"))
        self.assertFalse(limiter.is_blocked("10.0.0.2"))


# ---------------------------------------------------------------------------
# Tests HTTP end-to-end
# ---------------------------------------------------------------------------


#: Pannes de transport que les helpers REESSAIENT.
#:
#: `TimeoutError` Y MANQUAIT, ET C'EST ELLE QUI SURVIENT. Le retry a ete ecrit
#: pour les « aborts transitoires sous charge socket » (WinError 10053/10054,
#: AUDIT 2026-06-11) — mais sous cette meme charge, une reponse peut aussi ne
#: PAS ARRIVER dans le delai, et `HTTPConnection(..., timeout=5)` leve alors
#: `TimeoutError`, qui n'etait pas rattrapee.
#:
#: MESURE : `test_path_traversal_post_harmless` a echoue sur `TimeoutError: timed
#: out` dans TROIS executions de CI le meme jour (runs 31683660488, 31685141294
#: et 31688072603), sur trois PR aux diffs sans rapport — et la meme tete etait
#: verte en local. Le garde nommait donc une partie de sa famille de pannes, et
#: laissait passer celle qui frappait.
#:
#: Ce correctif ne pretend PAS connaitre la cause racine (cf. #924, ou la piste
#: de l'epuisement de sockets est coherente et non demontree) : il rend le retry
#: fidele a ce qu'il annonce couvrir. Un premier appel a `run/get_dashboard` sur
#: une base neuve coute 88 ms au repos sur un poste de developpement — la piste
#: « le cout des migrations depasse les 5 s » ne suffit pas a expliquer l'echec.
_PANNES_DE_TRANSPORT_REESSAYABLES = (
    ConnectionAbortedError,
    ConnectionResetError,
    TimeoutError,  # `socket.timeout` en est un alias depuis Python 3.10
)


class RestSecurityHttpTests(unittest.TestCase):
    """Serveur REST reel pour tester auth, rate limit HTTP, CORS, 404, 500."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix="cinesort_rest_sec_")
        cls.root = Path(cls._tmp) / "root"
        cls.state_dir = Path(cls._tmp) / "state"
        cls.root.mkdir()
        cls.state_dir.mkdir()
        cls.api = backend.CineSortApi()
        cls.api.settings.save_settings(
            {
                "root": str(cls.root),
                "state_dir": str(cls.state_dir),
                "tmdb_enabled": False,
            }
        )
        cls.port = _find_free_port()
        cls.token = "secret-token-xyz"
        cls.server = RestApiServer(cls.api, port=cls.port, token=cls.token)
        cls.server.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self) -> None:
        # Reset du rate limiter entre chaque test pour eviter le leakage
        self.server._rate_limiter.reset()

    def _request(self, method: str, path: str, body: Any = None, token: str | None = None) -> tuple:
        # Retry sur ConnectionAborted/Reset Windows (WinError 10053/10054) —
        # ces aborts transitoires apparaissent en suite full sous charge socket.
        last_exc: Exception | None = None
        for attempt in range(3):
            conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
            try:
                headers: Dict[str, str] = {"Content-Type": "application/json"}
                if token is not None:
                    headers["Authorization"] = f"Bearer {token}"
                payload = json.dumps(body or {}) if body is not None else ""
                conn.request(method, path, body=payload.encode("utf-8"), headers=headers)
                resp = conn.getresponse()
                status = resp.status
                data_raw = resp.read()
                headers_out = {k: v for k, v in resp.getheaders()}
            except _PANNES_DE_TRANSPORT_REESSAYABLES as exc:
                last_exc = exc
                conn.close()
                time.sleep(0.05 * (attempt + 1))
                continue
            finally:
                with contextlib.suppress(OSError):
                    conn.close()
            try:
                data = json.loads(data_raw.decode("utf-8")) if data_raw else {}
            except json.JSONDecodeError:
                data = {"_raw": data_raw.decode("utf-8", errors="replace")}
            return status, data, headers_out
        raise RuntimeError(f"3 tentatives epuisees ({type(last_exc).__name__}): {last_exc}")

    def _request_with_origin(
        self,
        method: str,
        path: str,
        body: Any = None,
        token: str | None = None,
        origin: str | None = None,
    ) -> tuple:
        """Variante de _request qui ajoute un en-tete Origin (test CSRF/CORS).

        Meme retry que _request sur ConnectionAborted/Reset Windows (WinError
        10053/10054) : ces aborts transitoires apparaissent en suite full sous
        charge socket. Sans ce retry, le helper etait flaky (cf AUDIT 2026-06-11).
        """
        last_exc: Exception | None = None
        for attempt in range(3):
            conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
            try:
                headers: Dict[str, str] = {"Content-Type": "application/json"}
                if token is not None:
                    headers["Authorization"] = f"Bearer {token}"
                if origin is not None:
                    headers["Origin"] = origin
                payload = json.dumps(body or {}) if body is not None else ""
                conn.request(method, path, body=payload.encode("utf-8"), headers=headers)
                resp = conn.getresponse()
                status = resp.status
                data_raw = resp.read()
                headers_out = {k: v for k, v in resp.getheaders()}
            except _PANNES_DE_TRANSPORT_REESSAYABLES as exc:
                last_exc = exc
                conn.close()
                time.sleep(0.05 * (attempt + 1))
                continue
            finally:
                with contextlib.suppress(OSError):
                    conn.close()
            try:
                data = json.loads(data_raw.decode("utf-8")) if data_raw else {}
            except json.JSONDecodeError:
                data = {"_raw": data_raw.decode("utf-8", errors="replace")}
            return status, data, headers_out
        raise RuntimeError(f"3 tentatives epuisees ({type(last_exc).__name__}): {last_exc}")

    def _assert_401_when_auth_enforced(self, token: str | None) -> None:
        """Verifie qu'un *token* invalide donne 401 sur un endpoint VIVANT.

        Le controle positif (meme requete + bon token -> 200) est obligatoire :
        sans lui, un endpoint mort ou un serveur casse produirait un 4xx et le
        test serait vert sans rien prouver sur l'authentification.
        """
        with _auth_really_enforced():
            status, _, _ = self._request("POST", _AUTH_ENDPOINT, body={}, token=token)
            control, _, _ = self._request("POST", _AUTH_ENDPOINT, body={}, token=self.token)
        self.assertEqual(control, 200, f"controle positif KO ({control}) : le 401 ne prouverait rien")
        self.assertEqual(status, 401)

    # 26
    def test_request_without_auth_returns_401(self) -> None:
        self._assert_401_when_auth_enforced(None)

    # 27
    def test_request_invalid_token_returns_401(self) -> None:
        self._assert_401_when_auth_enforced("wrong-token")

    # 28
    def test_request_empty_token_returns_401(self) -> None:
        self._assert_401_when_auth_enforced("")

    # 32
    def test_404_no_path_reflection(self) -> None:
        """M9 : la reponse 404/410 ne contient pas le path brut.

        Post-2026-05 : avec le kill switch Pass 1 actif par defaut, un appel
        direct legacy (sans prefixe facade) renvoie 410 Gone au lieu de 404.
        On accepte les deux statuts ; l'invariant clef reste : pas de
        reflexion du path dans le message d'erreur.
        """
        status, data, _ = self._request("POST", "/api/nonexistent_xyz_foo", body={}, token=self.token)
        self.assertIn(status, (404, 410))
        msg = str(data.get("message", ""))
        self.assertNotIn("nonexistent_xyz_foo", msg)
        self.assertNotIn("xyz", msg.lower())

    # 33
    def test_500_no_exception_leak(self) -> None:
        """M8 : la reponse 500 ne contient pas de detail interne.

        CE TEST N'AVAIT AUCUNE ASSERTION EFFECTIVE (lot 7, 2026-08-31). Ses
        trois assertions vivaient sous `if status == 500:` et il visait
        `/api/get_dashboard` — une route LEGACY qui, depuis la desactivation
        par defaut de Pass 1 (P0 #233), repond 410 Gone et JAMAIS 500. Le
        corps du `if` n'a donc jamais ete execute. Mesure : en remplacant
        `{"message": "Erreur interne"}` par `{"message": f"...{exc!r}"}` dans
        la frontiere de `rest_server._handle_post`, les 20 tests du fichier
        restaient VERTS.

        Le 500 est desormais PROVOQUE pour de vrai : on injecte une panne dans
        la table de dispatch du handler, et c'est bien la frontiere
        `except Exception` de production qui redige la reponse. `assertEqual(
        status, 500)` sert de controle positif — si la route redevenait morte,
        le test rougirait au lieu de se taire.
        """
        # Detail interne SANS antislash : `json.dumps` echapperait les
        # antislash d'un chemin Windows et le detecteur ne verrait plus la
        # fuite qu'il cherche (cf. l'auto-controle plus bas).
        detail_interne = "sqlite:////home/victime/.cinesort/state.db"
        message_panne = f"no such column: users.password_hash [{detail_interne}]"

        # AUTO-CONTROLE DU DETECTEUR : un `assertNotIn` sur un corps serialise
        # est un controle qui ne peut rendre qu'UNE valeur s'il est incapable
        # de voir un vrai leak. On le prouve capable AVANT de s'en servir.
        self.assertIn(detail_interne, json.dumps({"message": message_panne}, ensure_ascii=False))

        methods = self.server._handler_cls.api_methods
        route = "run/get_dashboard"
        originale = methods[route]

        def _explose(**_kwargs):
            raise RuntimeError(message_panne)

        methods[route] = _explose
        try:
            with self.assertLogs("cinesort.infra.rest_server", level=logging.ERROR) as journal:
                status, data, _ = self._request("POST", f"/api/{route}", body={}, token=self.token)
        finally:
            methods[route] = originale

        self.assertEqual(status, 500, f"la panne injectee doit atteindre la frontiere 500 (recu {status}: {data})")
        msg = str(data.get("message", ""))
        self.assertEqual(msg, "Erreur interne")
        self.assertNotIn("Traceback", msg)
        self.assertNotIn('File "', msg)

        # Le corps ENTIER, pas seulement `message` : un futur champ `detail`
        # ou `error` fuirait sans que l'assertion ci-dessus bronche.
        corps = json.dumps(data, ensure_ascii=False)
        self.assertNotIn(detail_interne, corps, "le chemin interne ne doit pas partir au client")
        self.assertNotIn("password_hash", corps, "le fragment SQL ne doit pas partir au client")
        self.assertNotIn("RuntimeError", corps, "le type d'exception ne doit pas partir au client")

        # L'information n'est pas PERDUE, elle est deplacee : le serveur la
        # journalise. Taire le client sans rien tracer rendrait le prochain
        # diagnostic impossible.
        self.assertTrue(
            any(detail_interne in ligne for ligne in journal.output),
            f"la panne doit rester tracee cote serveur : {journal.output}",
        )

    # 34
    def test_le_retry_couvre_un_TIMEOUT_pas_seulement_un_abort(self) -> None:
        """LA PANNE QUI SURVIENT DOIT ETRE CELLE QUE LE GARDE NOMME.

        Le retry existait pour les aborts transitoires ; sous la meme charge, une
        reponse peut aussi ne pas arriver dans le delai, et `TimeoutError`
        s'echappait. Trois executions de CI le meme jour ont echoue ainsi, sur
        trois PR aux diffs sans rapport.

        On injecte la panne au NIVEAU DU TRANSPORT — la couche ou elle se
        produit — et non en remplacant le helper : c'est le helper qu'on
        eprouve.
        """
        # LE MODULE REELLEMENT EN COURS, pas un homonyme. Selon la racine que
        # pytest insere, ce fichier est importe sous `test_rest_security` OU
        # `tests.test_rest_security` : un `import tests.test_rest_security`
        # fabriquerait un SECOND objet module, et le patch ne toucherait pas
        # celui qui s'execute — le test etait alors vert sans rien eprouver.
        module = sys.modules[type(self).__module__]

        vraie_classe = module.HTTPConnection
        tentatives = {"n": 0}

        class _ConnexionQuiExpireUneFois:
            def __init__(self, *args, **kwargs):
                tentatives["n"] += 1
                self._premiere = tentatives["n"] == 1
                self._delegue = None if self._premiere else vraie_classe(*args, **kwargs)

            def request(self, *args, **kwargs):
                if self._premiere:
                    raise TimeoutError("timed out")
                return self._delegue.request(*args, **kwargs)

            def getresponse(self):
                return self._delegue.getresponse()

            def close(self):
                if self._delegue is not None:
                    self._delegue.close()

        module.HTTPConnection = _ConnexionQuiExpireUneFois
        try:
            status, _data, _h = self._request("POST", "/api/run/get_dashboard", body={}, token=self.token)
        finally:
            module.HTTPConnection = vraie_classe

        # BORNER, PAS EPINGLER. `== 2` n'epinglait pas ce que ce test mesure
        # (« le helper a-t-il reessaye ? ») mais la FIABILITE DU TRANSPORT LOCAL,
        # que le test ne controle pas : seule la PREMIERE construction expire par
        # injection, la seconde delegue au vrai socket. Sous charge, cette
        # seconde tentative peut echouer pour de bon, et le helper consomme alors
        # la troisieme que `range(3)` lui accorde — comportement CORRECT, que
        # `test_trois_expirations_de_suite_LEVENT` affirme d'ailleurs juste en
        # dessous. Les deux tests se contredisaient sur le meme contrat.
        #
        # Mesure : echec observe en CI le 2026-08-29 (run 32449781016) sur une
        # PR de DOCUMENTATION, `3 != 2`, seul rouge de 9254 tests.
        #
        # L'encadrement reste mordant aux deux bouts : sans retry le compteur
        # vaut 1, et un retry sans plafond le fait depasser 3.
        self.assertGreaterEqual(tentatives["n"], 2, "le helper n'a pas REESSAYE apres l'expiration")
        self.assertLessEqual(tentatives["n"], 3, "le plafond de 3 tentatives de `_request` est franchi")
        self.assertIn(status, (200, 400, 404, 410, 500), "aucune tentative n'a abouti")

    def test_trois_expirations_de_suite_LEVENT_en_nommant_la_panne(self) -> None:
        """Reessayer indefiniment masquerait un serveur reellement mort. Au bout
        de trois tentatives on leve — et le message NOMME le type de panne,
        faute de quoi le prochain diagnostic repartirait de zero."""
        module = sys.modules[type(self).__module__]

        vraie_classe = module.HTTPConnection

        class _ConnexionMorte:
            def __init__(self, *args, **kwargs):
                pass

            def request(self, *args, **kwargs):
                raise TimeoutError("timed out")

            def close(self):
                pass

        module.HTTPConnection = _ConnexionMorte
        try:
            with self.assertRaises(RuntimeError) as ctx:
                self._request("POST", "/api/run/get_dashboard", body={}, token=self.token)
        finally:
            module.HTTPConnection = vraie_classe

        self.assertIn("TimeoutError", str(ctx.exception), "le message ne nomme pas la panne rencontree")

    def test_path_traversal_post_harmless(self) -> None:
        """Path traversal dans le body : pas de crash et RIEN n'est reflechi.

        CE TEST ACCEPTAIT TOUT (lot 7, 2026-08-31). `assertIn(status, (200,
        400, 404, 410, 500))` couvrait le succes ET tous les echecs — un
        ensemble dont le statut reel (200) ne pouvait pas sortir. Et sa seule
        verification de CONTENU vivait sous `if status == 500:`, branche jamais
        prise. Mesure : en ajoutant `"run_id": target_run` au payload vide de
        `dashboard_support.get_dashboard` — c'est-a-dire en renvoyant la charge
        d'attaque telle quelle au client — le test restait VERT.

        L'invariant epingle ici est celui que le nom promet : une charge de
        traversee est traitee EXACTEMENT comme un identifiant de run inconnu,
        et aucun de ses octets ne revient dans la reponse.
        """
        charge = "../../etc/passwd"

        # AUTO-CONTROLE DU DETECTEUR avant de s'en servir : `assertNotIn` sur un
        # corps serialise ne prouve rien s'il est incapable de voir une vraie
        # reflexion.
        self.assertIn(charge, json.dumps({"run_id": charge}, ensure_ascii=False))

        status, data, _ = self._request("POST", "/api/run/get_dashboard", body={"run_id": charge}, token=self.token)
        # Controle positif : la route doit etre VIVANTE. Sans lui, une route
        # retiree (410) rendrait toutes les assertions suivantes vraies pour
        # rien — c'est exactement ce qui est arrive au voisin M8.
        temoin, temoin_data, _ = self._request(
            "POST", "/api/run/get_dashboard", body={"run_id": "run-inconnu-inoffensif"}, token=self.token
        )
        self.assertEqual(temoin, 200, f"route morte ({temoin}: {temoin_data}) : le test ne prouverait rien")
        self.assertEqual(
            status,
            temoin,
            "la charge de traversee doit se comporter comme un run_id inconnu ordinaire",
        )

        corps = json.dumps(data, ensure_ascii=False)
        self.assertNotIn(charge, corps, "la charge d'attaque ne doit pas revenir au client")
        self.assertNotIn("etc/passwd", corps)
        # Bornage sur `../` et non sur `..` : une phrase francaise du payload
        # (« Aucun run disponible… ») pourrait porter des points de suspension
        # et rendre ce garde faussement rouge, donc inutilisable.
        self.assertNotIn("../", corps, "aucun segment de remontee ne doit revenir au client")
        self.assertIsNone(
            data.get("run_id"),
            "la charge ne doit pas etre adoptee comme identifiant de run",
        )

    # 35
    def test_cors_default_no_wildcard(self) -> None:
        """AUDIT 2026-06-10 : par defaut, plus de ACAO:* (lecture cross-site /
        CSRF). Une requete sans Origin (non-navigateur) ne recoit aucune ACAO."""
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("OPTIONS", "/api/get_settings")
        resp = conn.getresponse()
        cors = resp.getheader("Access-Control-Allow-Origin", "")
        conn.close()
        self.assertEqual(cors, "", "Plus de ACAO:* par defaut")

    def test_cors_echoes_localhost_origin(self) -> None:
        """Une Origin localhost sur le PORT D'ECOUTE (dashboard same-origin desktop)
        est reflechie. R8-031 (F3) : seul le port effectif du serveur est autorise."""
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("OPTIONS", "/api/get_settings", headers={"Origin": f"http://127.0.0.1:{self.port}"})
        resp = conn.getresponse()
        cors = resp.getheader("Access-Control-Allow-Origin", "")
        conn.close()
        self.assertEqual(cors, f"http://127.0.0.1:{self.port}")

    def test_cors_rejects_localhost_other_port(self) -> None:
        """R8-031 (F3) : une Origin loopback sur un AUTRE port (2e app locale
        hostile, http://127.0.0.1:9999) n'est PLUS reflechie — fermait la CSRF
        que le bypass auth loopback permettait depuis une autre app locale."""
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("OPTIONS", "/api/get_settings", headers={"Origin": "http://127.0.0.1:9999"})
        resp = conn.getresponse()
        cors = resp.getheader("Access-Control-Allow-Origin", "")
        conn.close()
        self.assertEqual(cors, "", "origine loopback sur autre port non reflechie (R8-031)")

    def test_cors_rejects_external_origin(self) -> None:
        """Une Origin externe (site malveillant) ne recoit aucune ACAO."""
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("OPTIONS", "/api/get_settings", headers={"Origin": "https://evil.example.com"})
        resp = conn.getresponse()
        cors = resp.getheader("Access-Control-Allow-Origin", "")
        conn.close()
        self.assertEqual(cors, "", "origine externe non reflechie")

    def test_csrf_post_from_external_origin_403(self) -> None:
        """GATE AUDIT 2026-06-10 (REAL 2/2) : un POST cross-site depuis un site
        externe est rejete 403 AVANT toute action, meme avec un token valide —
        ferme la CSRF possible via le bypass auth loopback."""
        status, data, _ = self._request_with_origin(
            "POST",
            "/api/run/start_plan",
            body={"settings": {"library_path": str(self.root)}},
            token=self.token,
            origin="https://evil.example.com",
        )
        self.assertEqual(status, 403)
        self.assertNotIn("run_id", data)

    def test_csrf_post_from_localhost_origin_allowed(self) -> None:
        """Un POST same-origin (Origin localhost, le dashboard) n'est PAS bloque
        par le garde CSRF (il passe au flux normal auth/dispatch)."""
        status, _, _ = self._request_with_origin(
            "POST",
            "/api/get_settings",
            body={},
            token=self.token,
            origin=f"http://127.0.0.1:{self.port}",
        )
        self.assertNotEqual(status, 403, "le dashboard same-origin ne doit pas etre bloque")

    # R8-087/F6-a : test_cors_configurable_explicit_still_emitted RETIRÉ — c'était un no-op
    # menteur (assertTrue(True), 0 assertion réelle). Son intention (« cors_origin explicite
    # émise même sans Origin ») est DÉJÀ couverte par test_cors_can_be_restricted_explicitly
    # ci-dessous, qui envoie un OPTIONS SANS header Origin et asserte que la valeur configurée
    # est bien émise dans Access-Control-Allow-Origin. Redondant -> retiré.

    def test_cors_can_be_restricted_explicitly(self) -> None:
        """Si rest_api_cors_origin est configure, la valeur est respectee."""
        import shutil as _sh
        import tempfile as _tmp

        port = _find_free_port()
        tmpdir = _tmp.mkdtemp(prefix="cinesort_cors_")
        try:
            api = backend.CineSortApi()
            api.settings.save_settings({"root": tmpdir, "state_dir": tmpdir, "tmdb_enabled": False})
            server = RestApiServer(api, port=port, token="t", cors_origin="http://192.168.1.50:8642")
            server.start()
            time.sleep(0.2)
            try:
                conn = HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("OPTIONS", "/api/get_settings")
                resp = conn.getresponse()
                cors = resp.getheader("Access-Control-Allow-Origin", "")
                conn.close()
                self.assertEqual(cors, "http://192.168.1.50:8642")
            finally:
                server.stop()
        finally:
            _sh.rmtree(tmpdir, ignore_errors=True)

    def test_token_comparison_uses_hmac_compare_digest(self) -> None:
        """H3 : le code source utilise hmac.compare_digest (timing-safe)."""
        from cinesort.infra import rest_server

        source = Path(rest_server.__file__).read_text(encoding="utf-8")
        self.assertIn("hmac.compare_digest", source)


# ---------------------------------------------------------------------------
# Test rate limiter HTTP end-to-end (serveur dedie pour ne pas polluer)
# ---------------------------------------------------------------------------


class RateLimiterHttpIntegrationTests(unittest.TestCase):
    """Serveur dedie pour tester le 429 apres 5 echecs."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_rate_limit_")
        self.api = backend.CineSortApi()
        self.api.settings.save_settings(
            {
                "root": self._tmp,
                "state_dir": self._tmp,
                "tmdb_enabled": False,
            }
        )
        self.port = _find_free_port()
        self.server = RestApiServer(self.api, port=self.port, token="good-token")
        self.server.start()
        time.sleep(0.2)

    def tearDown(self) -> None:
        self.server.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _post_status(self, bearer: str) -> int:
        """POST sur l'endpoint d'auth vivant, retourne le code HTTP."""
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(
                "POST",
                _AUTH_ENDPOINT,
                body=b"{}",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {bearer}"},
            )
            resp = conn.getresponse()
            status = resp.status
            resp.read()
        except (ConnectionAbortedError, ConnectionResetError):
            self.fail("Le serveur a coupe la connexion : localhost ne doit pas etre rate-limite")
        finally:
            conn.close()
        return status

    def test_rate_limiter_returns_429_after_5_failures(self) -> None:
        """FIX DEFINITIF 2026-06-07 : 127.0.0.1 est desormais exempte du
        rate-limiter (saturation par 401 silents du _safeBearer cote front
        quand le token contient un codepoint non-ASCII). Le scenario fonctionnel
        ("apres N echecs -> bloque") reste couvert par les tests unitaires
        `RateLimiterUnitTests` (qui utilisent une IP non-locale "10.0.0.1").
        Ici on verifie le NOUVEAU contrat : meme avec le compteur sature,
        127.0.0.1 (loopback desktop pywebview) recoit 401 et JAMAIS 429.

        2026-08-03 : le test visait "/api/get_settings" (route legacy morte ->
        410) et ne desactivait pas le bypass auth loopback ; il ne pouvait donc
        plus observer le 401 qu'il asserte. On vise l'endpoint facade vivant et
        on force le kill-switch d'auth (cf _auth_really_enforced) : l'exemption
        rate-limit testee ici, elle, reste inconditionnelle cote serveur
        (_is_rate_limited exempte les IP locales quel que soit l'etat du
        kill-switch), donc l'invariant "jamais 429 en loopback" est bien celui
        qui est mis a l'epreuve.
        """
        # 1. Pre-remplit le rate limiter pour 127.0.0.1 (defensif : le filtre
        # cote handler doit court-circuiter is_blocked avant meme de regarder).
        for _ in range(6):
            self.server._rate_limiter.record_failure("127.0.0.1")
        self.assertTrue(self.server._rate_limiter.is_blocked("127.0.0.1"))

        # 2. Une requete HTTP depuis 127.0.0.1 -> doit retourner 401, pas 429
        with _auth_really_enforced():
            status = self._post_status("wrong")
            # Controle : avec le BON token, le compteur sature ne doit pas non
            # plus bloquer le loopback (sinon on lirait 429 ici).
            control = self._post_status("good-token")
        self.assertEqual(control, 200, f"loopback avec bon token bloque ({control}) malgre l'exemption")
        self.assertEqual(
            status,
            401,
            f"Attendu 401 (localhost exempte du rate-limit), recu {status}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

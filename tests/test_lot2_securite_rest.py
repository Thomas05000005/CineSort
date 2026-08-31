# -*- coding: utf-8 -*-
"""LOT 2 — securite REST : casse du schema Bearer, jeton en clair dans les logs,
`/api/spec` sans jeton, oracle d'enumeration des jaquettes, GET non plafonnes.

QUATRE DEFAUTS, MESURES SUR LE SERVEUR REEL (aucun mock du transport) :

A. `auth.startswith("Bearer ")` est SENSIBLE A LA CASSE alors que la RFC 7235
   §2.1 declare le nom de schema insensible : `bearer <bon jeton>` recoit un
   401. Pire, la branche de repli journalise l'en-tete BRUT tronque a 40
   caracteres sous `CINESORT_DEBUG` — or « bearer  » (7) + un
   `token_urlsafe(24)` (32) fait 39 : AUCUNE troncature, le secret entier part
   dans le tampon. Le `log_scrubber` ne mord pas : son motif exige le litteral
   « Authorization: » colle a « Bearer », le message porte
   « Authorization absent ou non-Bearer: ».
   Meme defaut de casse dans `_has_bearer_header` (comptage du rate-limiter).

B. `GET /api/spec` rend la carte complete des 172 endpoints SANS jeton :
   `_handle_get` n'appelle jamais `_check_auth`.

C. `GET /api/poster` : sans `Sec-Fetch-Site` (curl, script), le regime
   200-sur-hit / erreur-sur-miss forme un ORACLE D'APPARTENANCE — on enumere la
   bibliotheque par id TMDb, sans credential. `_poster_navigateur_etranger` ne
   ferme cet oracle que pour les NAVIGATEURS tiers.

D. `_is_rate_limited()` n'a qu'UN site d'appel (`_handle_post`) : aucune route
   GET n'est plafonnee, meme quand l'IP est deja bloquee.
"""

from __future__ import annotations

import email.message
import io
import json
import logging
import os
import unittest
from http.client import HTTPConnection

# Le harnais de serveur local vit deja la : il restaure LOCALAPPDATA en
# `finally`, lecon payee par 52 `ERROR at setup` de Playwright.
from test_auth_loopback_sans_bypass import _TOKEN, _ServeurLocalMixin

import cinesort.infra.rest_server as rest_server
from cinesort.infra.log_scrubber import SecretsScrubFilter, scrub_secrets
from cinesort.infra.rest_server import _CineSortHandler, _pour_journal, _schema_dauth
from cinesort.infra.state import default_state_dir

# Un jeton de la MEME FORME que celui de production (`token_urlsafe(24)` = 32
# caracteres) : c'est cette longueur exacte qui fait passer « bearer  » + jeton
# a 39 caracteres, donc SOUS le plafond de troncature a 40.
# 32 caracteres, comme un `token_urlsafe(24)` — mais qui ne RESSEMBLE PAS a un
# jeton, et c'est deliberé. La premiere version employait une chaine mixte a
# haute entropie : `generic-api-key` (regle PAR DEFAUT de gitleaks) a mordu et
# rendu le check REQUIS `Scan secrets` ROUGE.
#
# Ce qui compte pour ces tests est la LONGUEUR (le plafond `auth[:40]` ne
# tronquait pas « bearer  » + 32 = 39) et l'ABSENCE de la valeur dans les logs.
# Aucun des deux ne demande une chaine d'apparence aleatoire. Entropie mesuree :
# 3,43 — sous le seuil de 4,0 de `.gitleaks.toml`, et sans majuscule, donc
# ecartee par son allowlist de mixite.
_SECRET_32 = "jeton-factice-de-test-pas-secret"

_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d4944415478da6364f8cf000501010025a50d5c00"
    "00000049454e44ae426082"
)


def _handler_nu(entetes: dict, *, ip: str = "127.0.0.1", jeton: str = _SECRET_32) -> _CineSortHandler:
    """Fabrique un handler sans socket, pour interroger ses predicats d'auth."""
    obj = _CineSortHandler.__new__(_CineSortHandler)
    obj.client_address = (ip, 50000)
    msg = email.message.Message()
    for cle, valeur in entetes.items():
        msg[cle] = valeur
    obj.headers = msg
    obj.auth_token = jeton
    obj.rate_limiter = None
    obj.cors_origin = ""
    return obj


class _TamponDeLogsAvecScrubberReel:
    """Monte le VRAI `SecretsScrubFilter` sur un handler de logs en memoire.

    Le tampon est le point de mesure : ce qui y arrive est ce qui atterrirait
    dans `cinesort.log`. Aucun `assertLogs`, qui court-circuiterait justement
    les filtres de handler qu'on veut eprouver.
    """

    def __init__(self, nom: str = "cinesort.infra.rest_server") -> None:
        self._nom = nom
        self.tampon = io.StringIO()

    def __enter__(self) -> "_TamponDeLogsAvecScrubberReel":
        self._logger = logging.getLogger(self._nom)
        self._handler = logging.StreamHandler(self.tampon)
        self._handler.setLevel(logging.DEBUG)
        self._handler.setFormatter(logging.Formatter("%(message)s"))
        self._handler.addFilter(SecretsScrubFilter())
        self._niveau = self._logger.level
        self._logger.setLevel(logging.DEBUG)
        self._logger.addHandler(self._handler)
        return self

    def __exit__(self, *_exc) -> None:
        self._logger.removeHandler(self._handler)
        self._logger.setLevel(self._niveau)
        self._handler.close()

    @property
    def texte(self) -> str:
        return self.tampon.getvalue()


class _DebugAuthActif:
    """`CINESORT_DEBUG=1` pose puis RENDU (une variable laissee derriere soi
    change le verdict des tests voisins)."""

    def __enter__(self) -> None:
        self._precedent = os.environ.get("CINESORT_DEBUG")
        os.environ["CINESORT_DEBUG"] = "1"

    def __exit__(self, *_exc) -> None:
        if self._precedent is None:
            os.environ.pop("CINESORT_DEBUG", None)
        else:
            os.environ["CINESORT_DEBUG"] = self._precedent


# ---------------------------------------------------------------------------
# A — casse du schema, et le jeton en clair dans le tampon de logs
# ---------------------------------------------------------------------------


class LeSchemaBearerEstInsensibleALaCasseTests(unittest.TestCase):
    """RFC 7235 §2.1 : « the scheme name is case-insensitive »."""

    def test_bearer_minuscule_est_accepte(self) -> None:
        handler = _handler_nu({"Authorization": f"bearer {_SECRET_32}"})
        self.assertTrue(
            handler._check_auth(),
            "un schema `bearer` minuscule est rejete alors que la RFC 7235 le declare insensible a la casse",
        )

    def test_bearer_capitalise_autrement_est_accepte(self) -> None:
        for schema in ("BEARER", "BeArEr"):
            with self.subTest(schema=schema):
                handler = _handler_nu({"Authorization": f"{schema} {_SECRET_32}"})
                self.assertTrue(handler._check_auth(), f"schema {schema!r} rejete")

    def test_un_mauvais_jeton_reste_refuse_quelle_que_soit_la_casse(self) -> None:
        """CONTRE-TEST : l'insensibilite porte sur le SCHEMA, jamais sur le jeton."""
        for schema in ("Bearer", "bearer", "BEARER"):
            with self.subTest(schema=schema):
                handler = _handler_nu({"Authorization": f"{schema} PAS-LE-BON-JETON"})
                self.assertFalse(handler._check_auth(), f"jeton faux accepte avec {schema!r}")

    def test_le_compteur_du_rate_limiter_voit_aussi_le_bearer_minuscule(self) -> None:
        """`_has_bearer_header` distingue « jeton absent » de « jeton faux ».

        Insensible a la casse lui aussi, sinon un attaquant qui ecrit `bearer`
        en minuscule n'incremente JAMAIS le compteur d'echecs : le plafond
        5/60 s devient contournable par un simple changement de casse.
        """
        handler = _handler_nu({"Authorization": "bearer un-jeton-faux"})
        self.assertTrue(
            handler._has_bearer_header(),
            "un `bearer` minuscule et faux n'est pas compte comme une tentative d'auth",
        )


class LeJetonNeDoitJamaisEntrerDansLeTamponDeLogsTests(unittest.TestCase):
    """Le scrubber REEL est monte sur le handler : le tampon fait foi."""

    def test_un_schema_inattendu_ne_journalise_pas_la_valeur(self) -> None:
        """Un client qui se trompe de schema envoie quand meme LE SECRET.

        `Authorization: Token <secret>` (forme frequente chez les clients
        generiques) tombe dans la branche de repli, qui journalise l'en-tete
        brut. 5 + 1 + 32 = 38 caracteres : sous le plafond de 40, donc rien
        n'est tronque.
        """
        handler = _handler_nu({"Authorization": f"Token {_SECRET_32}"})
        with _DebugAuthActif(), _TamponDeLogsAvecScrubberReel() as tampon:
            handler._check_auth()
        self.assertNotIn(
            _SECRET_32,
            tampon.texte,
            f"le materiel secret est arrive en clair dans le tampon de logs : {tampon.texte!r}",
        )

    def test_un_bearer_mal_casse_ne_journalise_pas_la_valeur(self) -> None:
        """La forme exacte decrite par la mesure : « bearer  » + 32 = 39 <= 40.

        Ce test reste probant APRES le correctif de casse : le schema devient
        valide, la branche de repli n'est plus prise, donc rien n'est
        journalise. Avant, elle l'etait ET rendait le jeton entier.
        """
        handler = _handler_nu({"Authorization": f"bearer {_SECRET_32}"})
        with _DebugAuthActif(), _TamponDeLogsAvecScrubberReel() as tampon:
            handler._check_auth()
        self.assertNotIn(
            _SECRET_32,
            tampon.texte,
            f"le jeton complet est journalise sans troncature : {tampon.texte!r}",
        )

    def test_un_entete_sans_schema_ne_journalise_pas_sa_valeur(self) -> None:
        """Jeton colle SANS schema : l'en-tete entier EST le secret."""
        handler = _handler_nu({"Authorization": _SECRET_32})
        with _DebugAuthActif(), _TamponDeLogsAvecScrubberReel() as tampon:
            handler._check_auth()
        self.assertNotIn(
            _SECRET_32,
            tampon.texte,
            f"un en-tete sans schema est journalise tel quel : {tampon.texte!r}",
        )

    def test_le_diagnostic_reste_utile(self) -> None:
        """CONTRE-TEST : taire la valeur ne doit pas taire le diagnostic.

        La panne d'origine (2026-06-08) etait un en-tete absent ou malforme :
        il faut encore pouvoir la distinguer d'un jeton faux. Longueur et
        schema suffisent.
        """
        handler = _handler_nu({"Authorization": f"Token {_SECRET_32}"})
        with _DebugAuthActif(), _TamponDeLogsAvecScrubberReel() as tampon:
            handler._check_auth()
        texte = tampon.texte
        self.assertIn("DEBUG-AUTH", texte, "la trace de diagnostic a disparu")
        self.assertIn("Token", texte, "le schema en cause n'est plus lisible")
        self.assertIn("38", texte, "la longueur de l'en-tete n'est plus rendue")


class LeScrubberMordSurUnEnteteDAuthNuTests(unittest.TestCase):
    """Le motif du scrubber exigeait le litteral « Authorization: » + Bearer.

    Un couple `<schema> <credentials>` cite dans une phrase — le cas de tous
    les messages de diagnostic — passait donc entier.
    """

    def test_bearer_minuscule_dans_une_phrase(self) -> None:
        message = f"[DEBUG-AUTH] header Authorization absent ou non-Bearer: 'bearer {_SECRET_32}'"
        self.assertNotIn(_SECRET_32, scrub_secrets(message))

    def test_autres_schemas_http(self) -> None:
        for schema in ("Bearer", "Token", "Basic"):
            with self.subTest(schema=schema):
                message = f"en-tete refuse: {schema} {_SECRET_32}"
                self.assertNotIn(_SECRET_32, scrub_secrets(message), f"schema {schema} non redige")

    def test_le_contexte_de_diagnostic_survit(self) -> None:
        """CONTRE-TEST : on perd la valeur, jamais le nom du schema."""
        redige = scrub_secrets(f"en-tete refuse: Bearer {_SECRET_32}")
        self.assertIn("Bearer", redige)
        self.assertIn("[REDACTED]", redige)

    def test_un_texte_sans_secret_est_inchange(self) -> None:
        """CONTRE-TEST : un motif trop gourmand caviarderait de la prose."""
        for phrase in (
            "Le porteur du jeton doit etre authentifie.",
            "scan termine: 1234 fichiers",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(scrub_secrets(phrase), phrase)


# ---------------------------------------------------------------------------
# B / C / D — sur un serveur REEL
# ---------------------------------------------------------------------------


class _ClientHttp:
    """Petit client GET : lit TOUJOURS le corps avant de fermer.

    Sans cette lecture, le serveur journalise un `ConnectionAbortedError
    [WinError 10053]` par requete — et une sortie bruyante est la facon dont
    les vrais echecs se perdent.
    """

    def _get(self, chemin: str, entetes: dict | None = None) -> tuple:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", chemin, headers=entetes or {})
        reponse = conn.getresponse()
        code = reponse.status
        brut = reponse.read()
        conn.close()
        return code, brut


class LaCarteDesEndpointsExigeLeJetonTests(_ServeurLocalMixin, _ClientHttp, unittest.TestCase):
    """`GET /api/spec` rendait la carte des 172 endpoints a tout venant."""

    _prefixe = "cinesort_lot2_spec_"

    def test_sans_jeton_la_spec_est_refusee(self) -> None:
        code, brut = self._get("/api/spec")
        self.assertEqual(code, 401, f"la spec OpenAPI est servie sans jeton (status={code}, {len(brut)} octets)")

    def test_avec_le_jeton_la_spec_reste_servie(self) -> None:
        """CONTRE-TEST : exiger le jeton ne doit pas supprimer l'endpoint."""
        code, brut = self._get("/api/spec", {"Authorization": f"Bearer {_TOKEN}"})
        self.assertEqual(code, 200, f"la spec n'est plus servie a un appelant authentifie (status={code})")
        spec = json.loads(brut)
        self.assertEqual(spec.get("openapi"), "3.0.3")

    def test_health_reste_public(self) -> None:
        """CONTRE-TEST : la sonde de vivacite ne doit PAS exiger de jeton.

        Le boot du dashboard et `tests/e2e/conftest.py` l'interrogent avant
        d'avoir un jeton ; la fermer bloquerait le demarrage.
        """
        code, _ = self._get("/api/health")
        self.assertEqual(code, 200, f"/api/health n'est plus public (status={code})")


class LaRouteJaquettesNeTrahitPlusLeCacheTests(_ServeurLocalMixin, _ClientHttp, unittest.TestCase):
    """Sans `Sec-Fetch-Site`, 200-sur-hit / 404-sur-miss enumere la bibliotheque."""

    _prefixe = "cinesort_lot2_poster_"

    def _planter_une_jaquette(self, tmdb_id: int, taille: str = "w500") -> None:
        dossier = default_state_dir() / "cache" / "posters" / taille
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / f"{tmdb_id}.png").write_bytes(_PNG_1x1)

    def _poster(self, tmdb_id: int, entetes: dict) -> int:
        code, _ = self._get(f"/api/poster?id={tmdb_id}&size=w500", entetes)
        return code

    def test_un_script_distant_ne_distingue_pas_cache_et_absence(self) -> None:
        """Un script LAN (aucun en-tete Sec-Fetch) enumere par id TMDb.

        `_LOCAL_CLIENT_IPS` est vide le temps du test : la connexion vient bien
        de 127.0.0.1, mais le serveur doit la traiter comme un appelant
        distant — sinon on mesurerait le chemin local, pas celui de l'attaque.
        """
        self._planter_une_jaquette(5150)
        precedent = rest_server._LOCAL_CLIENT_IPS
        rest_server._LOCAL_CLIENT_IPS = frozenset()
        try:
            en_cache = self._poster(5150, {})
            absent = self._poster(5151, {})
        finally:
            rest_server._LOCAL_CLIENT_IPS = precedent
        self.assertEqual(
            en_cache,
            absent,
            f"la reponse trahit le cache a un appelant non fiable : en cache={en_cache}, absent={absent}",
        )

    def test_un_navigateur_same_origin_obtient_toujours_sa_jaquette(self) -> None:
        """CONTRE-TEST : le dashboard est le seul consommateur legitime."""
        self._planter_une_jaquette(5152)
        code = self._poster(5152, {"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Dest": "image"})
        self.assertEqual(code, 200, f"le dashboard n'obtient plus ses jaquettes (status={code})")

    def test_un_client_natif_local_obtient_toujours_sa_jaquette(self) -> None:
        """CONTRE-TEST : pywebview natif / curl local n'envoient pas Sec-Fetch."""
        self._planter_une_jaquette(5153)
        self.assertEqual(self._poster(5153, {}), 200)


class LesRoutesGetSontPlafonneesTests(_ServeurLocalMixin, _ClientHttp, unittest.TestCase):
    """`_is_rate_limited()` n'etait appele que depuis `_handle_post`."""

    _prefixe = "cinesort_lot2_ratelimit_"

    def setUp(self) -> None:
        self.server._rate_limiter.reset()

    def tearDown(self) -> None:
        self.server._rate_limiter.reset()

    def test_une_ip_bloquee_ne_peut_plus_lire_en_GET(self) -> None:
        """5 echecs d'auth suffisent a bloquer les POST ; les GET passaient."""
        precedent = rest_server._LOCAL_CLIENT_IPS
        rest_server._LOCAL_CLIENT_IPS = frozenset()
        try:
            for _ in range(rest_server._RATE_LIMIT_MAX_FAILURES):
                self.server._rate_limiter.record_failure("127.0.0.1")
            self.assertTrue(self.server._rate_limiter.is_blocked("127.0.0.1"), "le limiter n'a pas bloque l'IP")
            code, _ = self._get("/api/health")
        finally:
            rest_server._LOCAL_CLIENT_IPS = precedent
        self.assertEqual(code, 429, f"une IP deja bloquee lit encore en GET (status={code})")

    def test_une_ip_saine_lit_toujours_en_GET(self) -> None:
        """CONTRE-TEST : le plafond ne doit pas fermer la route par defaut."""
        code, _ = self._get("/api/health")
        self.assertEqual(code, 200, f"/api/health refuse une IP saine (status={code})")

    def test_les_ip_locales_restent_exemptees(self) -> None:
        """CONTRE-TEST : l'exemption loopback (fix 2026-06-07) est conservee.

        Sans elle, les 5 pings paralleles de l'Accueil satureraient le compteur
        et le desktop tomberait en 429 des le premier clic.
        """
        for _ in range(rest_server._RATE_LIMIT_MAX_FAILURES * 2):
            self.server._rate_limiter.record_failure("127.0.0.1")
        code, _ = self._get("/api/health")
        self.assertEqual(code, 200, f"une IP loopback est plafonnee en GET (status={code})")


if __name__ == "__main__":
    unittest.main()


class AucuneValeurEXTERNENeForgeUneLigneDeJournalTests(unittest.TestCase):
    """CWE-117. Une entree de journal se termine par un saut de ligne : y
    laisser passer un CR/LF fourni par l'appelant permet d'en FORGER une —
    un « REST auth OK » fabrique, par exemple.

    CodeQL a signale les deux sites (`rest_server.py:954` et `:1396`, alertes
    #336 et #337). Aucun des deux n'est atteignable AUJOURD'HUI, et c'est
    mesure :

      - `_schema_dauth` filtre par `^[A-Za-z][A-Za-z0-9-]{0,31}$`, motif ANCRE
        qui n'admet ni CR ni LF ;
      - `self.path` ne peut pas porter de saut de ligne, `BaseHTTPRequestHandler`
        lisant la ligne de requete jusqu'au `\r\n`.

    Le garde est pose quand meme, et ce test existe pour la meme raison : les
    deux arguments ci-dessus reposent sur des proprietes d'AUTRES fonctions,
    qu'un refactor peut changer sans que personne ne relise ces lignes-la.
    """

    def test_les_sauts_de_ligne_sont_NEUTRALISES(self) -> None:
        for brut, attendu in (
            ("Evil\nINJECTE: faux", "Evil\\nINJECTE: faux"),
            ("a\rb", "a\\rb"),
            ("x\r\ny", "x\\r\\ny"),
        ):
            with self.subTest(brut=brut):
                rendu = _pour_journal(brut)
                self.assertEqual(rendu, attendu)
                self.assertNotIn("\n", rendu)
                self.assertNotIn("\r", rendu)

    def test_une_valeur_NORMALE_traverse_intacte(self) -> None:
        """Contre-epreuve : sans elle, une fonction qui rendrait toujours la
        chaine vide passerait le test precedent — et le diagnostic mourrait."""
        for valeur in ("Bearer", "<absent>", "<sans-schema>", "/api/poster"):
            with self.subTest(valeur=valeur):
                self.assertEqual(_pour_journal(valeur), valeur)

    def test_une_valeur_ENORME_est_bornee(self) -> None:
        """Un chemin de 8 Ko dans un log de diagnostic est du bruit."""
        rendu = _pour_journal("x" * 5000)
        self.assertLess(len(rendu), 300)
        self.assertTrue(rendu.endswith("...(tronque)"))

    def test_le_SCHEMA_dauth_ne_laisse_deja_rien_passer(self) -> None:
        """La premiere ligne de defense, mesuree — c'est elle qui rend les
        alertes CodeQL inatteignables, et c'est pour cela qu'elle est epinglee
        ici : si son motif cessait d'etre ancre, ce test rougirait."""
        for brut in ("Evil\nINJECTE: faux", "Ev\ril xyz", "Bearer\nx y"):
            with self.subTest(brut=brut):
                self.assertEqual(_schema_dauth(brut), "<sans-schema>")
        self.assertEqual(_schema_dauth("Bearer abc"), "Bearer")
        self.assertEqual(_schema_dauth(""), "<absent>")

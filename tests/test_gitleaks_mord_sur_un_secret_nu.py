# -*- coding: utf-8 -*-
"""La regle gitleaks doit mordre sur un secret NU, sans indice lexical.

Le defaut
---------
Un jeton REST du projet est reste publie 67 jours dans deux documents, entre
BACKTICKS, en prose, sans `=` ni nom de variable a cote. Aucune des ~150 regles
par defaut ne mord sur cette forme : `generic-api-key` exige un indice lexical
(`token = ...`, `key: ...`) que la prose ne fournit pas.

Ce n'etait donc PAS une exemption assumee — la valeur n'a jamais figure dans
`.gitleaksignore`. C'etait une NON-DETECTION.

Ce que ce test mesure, et pourquoi il ne recopie rien
----------------------------------------------------
Il ne contient AUCUN secret : il en GENERE avec `secrets.token_urlsafe`, la
fonction meme qui produit le jeton REST du projet. Recopier la valeur reelle la
reintroduirait dans la plage scannee — `git log -p` inclut les messages de
commit et les fichiers ajoutes.

Il lit la regle depuis `.gitleaks.toml` plutot que d'en dupliquer les valeurs :
un test qui reecrit le seuil qu'il verifie ne verifie plus rien.

Le calibrage qui a failli etre faux
-----------------------------------
Le premier seuil essaye etait 4.5. Sur le corpus reel il rendait exactement les
deux vraies detections et zero faux positif — parfait en apparence. Mesure
contre la DISTRIBUTION plutot que contre l'unique exemplaire connu : un seuil a
4.5 RATE 29,73 % des `token_urlsafe(24)`. Celui du depot n'etait attrape que
parce qu'il se trouve a 4.54.

D'ou `test_la_regle_attrape_la_QUASI_TOTALITE_des_jetons`, qui est le seul de ce
fichier a pouvoir detecter cette erreur-la.
"""

from __future__ import annotations

import collections
import io
import math
import re
import secrets
import tomllib
import unittest
from pathlib import Path

import yaml

_RACINE = Path(__file__).resolve().parents[1]
_CONFIG = _RACINE / ".gitleaks.toml"
_WORKFLOW = _RACINE / ".github" / "workflows" / "gitleaks.yml"
_ID = "cinesort-secret-nu-entre-backticks"

#: Taille de l'echantillon. 2000 suffit a distinguer 0,4 % de 30 %.
_N = 2000


def _entropie_shannon(chaine: str) -> float:
    """L'entropie que gitleaks calcule sur le groupe capture."""
    if not chaine:
        return 0.0
    compte = collections.Counter(chaine)
    n = len(chaine)
    return -sum((v / n) * math.log2(v / n) for v in compte.values())


class _Moteur:
    """Rejoue la regle du TOML : regex, entropie, allowlist."""

    def __init__(self, regle: dict) -> None:
        self.motif = re.compile(regle["regex"])
        self.seuil = float(regle["entropy"])
        self.exclus = [re.compile(p) for p in (regle.get("allowlist") or {}).get("regexes", [])]

    def mord(self, texte: str) -> bool:
        for m in self.motif.finditer(texte):
            secret = m.group(1)
            if _entropie_shannon(secret) < self.seuil:
                continue
            if any(e.search(secret) for e in self.exclus):
                continue
            return True
        return False


def _regle() -> dict:
    conf = tomllib.load(io.open(_CONFIG, "rb"))
    for r in conf.get("rules") or []:
        if r.get("id") == _ID:
            return r
    raise AssertionError(f"regle `{_ID}` absente de .gitleaks.toml")


class LaRegleMordSurUnSecretNuTests(unittest.TestCase):
    def setUp(self) -> None:
        self.moteur = _Moteur(_regle())

    def test_les_regles_PAR_DEFAUT_restent_actives(self) -> None:
        """`useDefault = false` remplacerait les ~150 regles built-in par cette
        seule regle. La detection s'effondrerait en silence, et ce fichier
        passerait quand meme au vert : il ne teste que la regle ajoutee."""
        conf = tomllib.load(io.open(_CONFIG, "rb"))
        self.assertIs(conf.get("extend", {}).get("useDefault"), True)

    def test_le_workflow_CHARGE_bien_ce_fichier(self) -> None:
        """Une config que le scan ne lit pas est une regle qui n'existe pas.

        ON PARSE LE YAML, on ne cherche pas la chaine. Une premiere version
        faisait `assertIn("GITLEAKS_CONFIG", texte)` — elle passait au vert sur
        une ligne COMMENTEE, puisque les caracteres y sont toujours. Elle
        mesurait la presence de caracteres, pas celle d'un reglage actif.
        Mutation qui l'a revele : `GITLEAKS_CONFIG:` prefixe d'un `#`."""
        conf = yaml.safe_load(io.open(_WORKFLOW, encoding="utf-8").read())
        etapes = conf["jobs"]["scan"]["steps"]
        env = {}
        for etape in etapes:
            if "gitleaks" in str(etape.get("uses") or ""):
                env = etape.get("env") or {}
        self.assertEqual(
            str(env.get("GITLEAKS_CONFIG") or ""),
            _CONFIG.name,
            "l'etape gitleaks ne designe pas explicitement .gitleaks.toml",
        )

    def test_la_forme_QUI_A_ECHAPPE_est_desormais_prise(self) -> None:
        """Le cas exact : un jeton entre backticks, en prose, sans `=`."""
        jeton = secrets.token_urlsafe(24)
        self.assertTrue(
            self.moteur.mord(f"Le jeton REST actuel est `{jeton}` (a ne pas diffuser)."),
            "la forme qui est restee publiee 67 jours n'est toujours pas prise",
        )

    def test_la_regle_attrape_la_QUASI_TOTALITE_des_jetons(self) -> None:
        """LE test qui distingue un seuil calibre d'un seuil devine.

        Un seuil trop haut passe tous les autres tests de ce fichier — il suffit
        qu'il attrape LE jeton qu'on lui montre. Seule une mesure contre la
        distribution revele qu'il en rate un tiers."""
        for taille in (24, 32):
            with self.subTest(token_urlsafe=taille):
                rates = sum(1 for _ in range(_N) if not self.moteur.mord(f"`{secrets.token_urlsafe(taille)}`"))
                self.assertLess(
                    rates / _N,
                    0.02,
                    f"la regle rate {100 * rates / _N:.2f} % des token_urlsafe({taille}) : "
                    "seuil d'entropie trop haut, ou allowlist trop large",
                )

    def test_elle_ne_mord_PAS_sur_ce_qui_n_est_pas_un_secret(self) -> None:
        """Contre-epreuve. Sans elle, une regle qui mord sur TOUT passerait les
        tests precedents — et 58 detections par scan rendraient l'alerte
        inaudible, ce qui revient a ne pas detecter."""
        # CHAQUE cas n'est ecarte QUE PAR UN SEUL motif de l'allowlist.
        # Une premiere version prenait des exemples couverts par plusieurs
        # motifs a la fois : retirer l'un d'eux laissait le test VERT, puisqu'un
        # autre rattrapait le cas. Le jeu ne distinguait donc pas les trois.
        benins = {
            # majuscules ET minuscules, AUCUN chiffre -> seul `^[^0-9]+$` mord
            "titre en CamelCase sans chiffre": "TitreDeSectionEnCamelCaseAssezLongPourPasser",
            # minuscules ET chiffres, AUCUNE majuscule -> seul `^[^A-Z]+$` mord
            "hash git complet": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
            # majuscules ET chiffres, AUCUNE minuscule -> seul `^[^a-z]+$` mord
            "constante majuscule": "CINESORT_PROBE_DISK_CACHE_V2_OVERRIDE_9",
        }
        for quoi, valeur in benins.items():
            with self.subTest(cas=quoi):
                self.assertFalse(
                    self.moteur.mord(f"voir `{valeur}` dans le rapport"),
                    f"faux positif sur {quoi} : l'alerte deviendrait inaudible",
                )

    def test_une_chaine_TROP_COURTE_est_ignoree(self) -> None:
        """Contre-epreuve de la borne basse : `abc123XY` est mixte et de haute
        entropie par caractere, mais ce n'est pas un secret."""
        self.assertFalse(self.moteur.mord("la variable `abc123XY` du test"))


if __name__ == "__main__":
    unittest.main()

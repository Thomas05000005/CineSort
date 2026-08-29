# -*- coding: utf-8 -*-
"""La cascade d'encodage des NFO ne pouvait pas atteindre son troisieme repli.

LE DEFAUT
---------
`domain.core.parse_movie_nfo` essayait les encodages dans l'ordre
``("utf-8", "latin-1", "cp1252")``. Or le codec `latin-1` mappe les **256**
valeurs d'octet : il ne leve JAMAIS `UnicodeDecodeError`. Place en deuxieme, il
rendait le troisieme element INATTEIGNABLE — `cp1252` etait du code mort, et le
repli reel etait latin-1 pour **tous** les NFO non-UTF-8.

POURQUOI CE N'EST PAS COSMETIQUE
--------------------------------
Les deux jeux ne different que sur la plage `0x80-0x9F`, et c'est exactement la
que Windows range la ponctuation typographique :

    octet 0x92 -> U+2019 en cp1252   vs  U+0092 en latin-1 (controle C1)
    octet 0x93 -> U+201C             vs  U+0093
    octet 0x96 -> U+2013             vs  U+0096
    octet 0x80 -> U+20AC             vs  U+0080

Un NFO ecrit sous Windows — le cas courant — produisait donc un caractere de
CONTROLE la ou il fallait une apostrophe. Et ce titre ne reste pas en memoire :
`build_candidates_from_nfo` en fait un `Candidate(source="nfo", score=0.90)`,
donc un candidat de haute confiance qui peut devenir le `proposed_title`, donc
le NOM DE DOSSIER. `path_utils.windows_safe` ne retire que `[\\x00-\\x1f\\x7f]`
— pas la plage C1 — donc le caractere de controle survit jusque sur le disque.
C'est la regle 2 du CLAUDE.md (« ne jamais mutiler un titre »).

Effet de bord au passage : un titre mojibake fausse aussi la comparaison avec
TMDb et peut lever un `nfo_title_mismatch` sans raison.

CE QUE CHAQUE TEST PROUVE
-------------------------
- `test_apostrophe_windows_est_lue_comme_une_apostrophe` : le cas du defaut.
  ROUGE avant le correctif (latin-1 rend U+0092). L'assertion porte sur ce que
  SEUL le correctif produit — l'egalite exacte du titre ET l'absence du
  controle C1 —, pas sur une sous-chaine que l'ancien comportement satisfait
  aussi.
- `test_octet_indefini_en_cp1252_retombe_sur_latin1` : le CONTRE-TEST. Il
  interdit le correctif trop court qui aurait simplement REMPLACE latin-1 par
  cp1252 : les cinq octets indefinis de cp1252 (0x81, 0x8D, 0x8F, 0x90, 0x9D)
  feraient alors echouer la lecture entiere et le NFO serait perdu. Ce test est
  vert avant comme apres — il contraint la FORME du correctif, pas le defaut.
- `test_utf8_reste_prioritaire` : non-regression. Un NFO UTF-8 valide doit
  encore etre lu en UTF-8, sinon le correctif aurait deplace le probleme (les
  memes octets `0xC3 0xA9` se lisent « Ã© » en cp1252).

Les points de code sensibles sont construits par `chr(0x...)` a dessein : le
fichier reste ainsi lisible la ou il parle d'octets, un controle C1 ecrit
litteralement etant invisible en revue et fragile aux reformatages.

Aucun test ne compare une chaine de CODE SOURCE : le tuple d'encodages n'est
jamais asserte, seul le comportement l'est.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cinesort.domain.core as core

# Apostrophe typographique (U+2019) : c'est l'octet 0x92 sous Windows-1252.
APOSTROPHE_TYPO = chr(0x2019)
# Ce que latin-1 rend du MEME octet : U+0092, un controle C1 invisible.
CONTROLE_C1 = chr(0x92)
# Octet sans point de code en cp1252 : seul latin-1 sait le lire (U+0090).
CARACTERE_HORS_CP1252 = chr(0x90)


class NfoEncodageCascadeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="cinesort_nfo_enc_")
        self.addCleanup(self._dir.cleanup)
        self.racine = Path(self._dir.name)

    def _ecrire(self, brut: bytes) -> Path:
        chemin = self.racine / "movie.nfo"
        chemin.write_bytes(brut)
        return chemin

    def test_apostrophe_windows_est_lue_comme_une_apostrophe(self) -> None:
        titre = f"L{APOSTROPHE_TYPO}Auberge espagnole"
        # Encode en cp1252 : l'apostrophe typographique devient l'octet 0x92,
        # qui n'est pas de l'UTF-8 valide — la premiere tentative echoue donc
        # et c'est bien le repli qui decide.
        brut = f"<movie><title>{titre}</title><year>2002</year></movie>".encode("cp1252")
        self.assertIn(b"\x92", brut, "le cas de test doit vraiment porter l'octet 0x92")

        info = core.parse_movie_nfo(self._ecrire(brut))

        self.assertIsNotNone(info)
        self.assertEqual(info.title, titre)
        self.assertNotIn(
            CONTROLE_C1,
            info.title,
            "0x92 lu en latin-1 donne un controle C1, qui survit a windows_safe et part dans le nom de dossier",
        )
        self.assertEqual(info.year, 2002)

    def test_octet_indefini_en_cp1252_retombe_sur_latin1(self) -> None:
        """Contre-test : cp1252 ne doit pas REMPLACER latin-1, seulement le preceder."""
        # 0x90 est l'un des cinq octets sans point de code en cp1252. Le NFO
        # doit rester lisible : sans repli latin-1, tout le fichier serait perdu.
        brut = b"<movie><title>A\x90B</title><year>1999</year></movie>"

        info = core.parse_movie_nfo(self._ecrire(brut))

        self.assertIsNotNone(info, "un octet indefini en cp1252 ne doit pas faire perdre le NFO entier")
        self.assertEqual(info.year, 1999)
        self.assertEqual(info.title, f"A{CARACTERE_HORS_CP1252}B")

    def test_utf8_reste_prioritaire(self) -> None:
        """Non-regression : les memes octets se lisent « Ã© » en cp1252."""
        titre = "Amélie"
        brut = f"<movie><title>{titre}</title><year>2001</year></movie>".encode("utf-8")

        info = core.parse_movie_nfo(self._ecrire(brut))

        self.assertIsNotNone(info)
        self.assertEqual(info.title, titre)
        self.assertEqual(info.year, 2001)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

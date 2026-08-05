"""Issue #782 — `check_header` sur la famille MPEG-TS (.ts / .m2ts / .mts).

`_check_ts` supposait un paquet de 188 octets avec le sync 0x47 a l'offset 0.
Or `_EXT_TO_FORMAT` route aussi `.m2ts` et `.mts` vers ce handler, et ces
conteneurs (Blu-ray / AVCHD) utilisent des source packets BDAV de 192 octets :
un `TP_extra_header` de 4 octets PUIS le paquet TS de 188. Le sync y est donc a
l'offset 4 et TOUT M2TS valide etait declare `header_mismatch`, ce qui pose le
flag `integrity_header_invalid` et sort le fichier de l'auto-approbation.

Les tailles couvertes (188 / 192 / 204) sont celles que FFmpeg sonde dans
libavformat/mpegts.c (TS_PACKET_SIZE / TS_DVHS_PACKET_SIZE / TS_FEC_PACKET_SIZE),
et son `analyze()` cherche le decalage initial via `i % packet_size` — d'ou le
balayage des decalages ici aussi (un flux coupe ne commence pas forcement sur
une frontiere de paquet).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cinesort.domain.integrity_check import check_header

_SYNC = 0x47
# Octet de bourrage qui n'est jamais 0x47 : garantit que seule la grille de sync
# reellement construite est detectable (pas de faux positif fortuit).
_FILLER = 0xB7


def _ts_stream(*, packet_size: int, base: int, packets: int = 10, prefix: bytes = b"") -> bytes:
    """Flux TS synthetique : `prefix`/bourrage sur `base` octets, puis un sync
    0x47 en tete de chaque paquet de `packet_size` octets."""
    out = bytearray()
    out += prefix if prefix else bytes([_FILLER]) * base
    if len(out) != base:
        raise AssertionError(f"prefix de {len(out)} octets pour un base de {base}")
    for _ in range(packets):
        out.append(_SYNC)
        out += bytes([_FILLER]) * (packet_size - 1)
    return bytes(out)


def _no_sync_bytes(length: int, *, seed: int = 12345) -> bytes:
    """Octets varies mais garantis sans aucun 0x47 (donc sans grille TS)."""
    out = bytearray()
    state = seed
    for _ in range(length):
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
        value = (state >> 16) & 0xFF
        out.append(0x48 if value == _SYNC else value)
    return bytes(out)


class TsHeaderLayoutTests(unittest.TestCase):
    def _check(self, ext: str, content: bytes) -> tuple[bool, str]:
        with tempfile.TemporaryDirectory(prefix="cinesort_ts_layout_") as tmp:
            path = Path(tmp) / f"video{ext}"
            path.write_bytes(content)
            return check_header(path)

    # --- 188 octets, offset 0 : MPEG-2 TS nu (comportement historique) --------

    def test_ts_188_offset_0_est_valide(self) -> None:
        ok, detail = self._check(".ts", _ts_stream(packet_size=188, base=0))
        self.assertTrue(ok, f"TS 188 standard doit rester valide, detail={detail}")
        self.assertEqual(detail, "ok")

    # --- 192 octets, offset 4 : M2TS / MTS (le defaut #782) ------------------

    def test_m2ts_192_offset_4_est_valide(self) -> None:
        """Un .m2ts BDAV parfaitement valide ne doit plus etre dit corrompu."""
        ok, detail = self._check(".m2ts", _ts_stream(packet_size=192, base=4))
        self.assertTrue(ok, f".m2ts (192 o, sync a l'offset 4) doit etre valide, detail={detail}")
        self.assertEqual(detail, "ok")

    def test_mts_192_offset_4_est_valide(self) -> None:
        """.mts (camescopes AVCHD) partage le layout BDAV du .m2ts."""
        ok, detail = self._check(".mts", _ts_stream(packet_size=192, base=4))
        self.assertTrue(ok, f".mts (192 o, sync a l'offset 4) doit etre valide, detail={detail}")
        self.assertEqual(detail, "ok")

    def test_m2ts_avec_0x47_dans_le_tp_extra_header_est_valide(self) -> None:
        """Le TP_extra_header porte un horodatage 27 MHz : il peut contenir 0x47.

        Ce cas piege les parseurs qui se resynchronisent sur le premier 0x47
        rencontre (cf. FFmpeg trac #11172) ; il doit rester valide ici.
        """
        content = _ts_stream(packet_size=192, base=4, prefix=bytes([0x00, _SYNC, 0x12, 0x34]))
        ok, detail = self._check(".m2ts", content)
        self.assertTrue(ok, f"TP_extra_header contenant 0x47 doit rester valide, detail={detail}")

    # --- 204 octets : TS + parite Reed-Solomon (captures DVB) ----------------

    def test_ts_204_reed_solomon_est_valide(self) -> None:
        ok, detail = self._check(".ts", _ts_stream(packet_size=204, base=0))
        self.assertTrue(ok, f"TS 204 (FEC Reed-Solomon) doit etre valide, detail={detail}")

    # --- decalage initial quelconque : capture coupee en plein paquet --------

    def test_ts_188_commencant_au_milieu_d_un_paquet_est_valide(self) -> None:
        """Une capture tronquee en tete ne commence pas sur une frontiere de paquet."""
        ok, detail = self._check(".ts", _ts_stream(packet_size=188, base=37))
        self.assertTrue(ok, f"TS demarrant a l'offset 37 doit etre valide, detail={detail}")

    # --- non-regression : ce qui doit RESTER invalide ------------------------

    def test_fichier_sans_aucune_grille_de_sync_reste_header_mismatch(self) -> None:
        ok, detail = self._check(".ts", _no_sync_bytes(4096))
        self.assertFalse(ok, "des octets sans aucun 0x47 ne peuvent pas etre un TS")
        self.assertEqual(detail, "header_mismatch")

    def test_mkv_renomme_en_m2ts_reste_header_mismatch(self) -> None:
        """Le but du check reste de detecter un fichier renomme."""
        content = bytes([0x1A, 0x45, 0xDF, 0xA3]) + _no_sync_bytes(4096, seed=999)
        ok, detail = self._check(".m2ts", content)
        self.assertFalse(ok, "un MKV renomme .m2ts doit rester signale")
        self.assertEqual(detail, "header_mismatch")

    def test_fichier_vide_reste_empty_file(self) -> None:
        ok, detail = self._check(".ts", b"")
        self.assertFalse(ok)
        self.assertEqual(detail, "empty_file")

    def test_fichier_trop_court_reste_file_too_small(self) -> None:
        """Trop court pour eliminer un layout : file_too_small, pas une accusation."""
        ok, detail = self._check(".ts", _ts_stream(packet_size=188, base=0, packets=1)[:100])
        self.assertFalse(ok)
        self.assertEqual(detail, "file_too_small")

    def test_grille_partielle_deux_sync_sur_trois_reste_invalide(self) -> None:
        """2 sync alignes ne suffisent pas : le 3e doit tomber juste aussi."""
        data = bytearray(_ts_stream(packet_size=188, base=0))
        data[2 * 188] = _FILLER  # casse le 3e sync de la grille 188
        # ... et toute autre grille candidate : le reste du flux ne doit pas
        # offrir 3 sync alignes sur une autre taille/decalage.
        ok, detail = self._check(".ts", bytes(data[: 3 * 188]) + _no_sync_bytes(2048, seed=7))
        self.assertFalse(ok, f"une grille incomplete ne doit pas passer, detail={detail}")

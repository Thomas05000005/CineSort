# -*- coding: utf-8 -*-
"""Test parite cles i18n : locales/fr.json et locales/en.json doivent avoir
exactement le meme ensemble de cles plates.

Cette parite est critique : le frontend essaye t("foo.bar") en FR, et si la
cle n'existe pas, le fallback EN doit fonctionner — donc EN doit contenir
toutes les cles FR, et vice-versa.

Ce test echoue si :
- Une cle existe en EN mais pas en FR (l'utilisateur FR verra la cle brute)
- Une cle existe en FR mais pas en EN (l'utilisateur EN verra la cle brute)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EN_PATH = ROOT / "locales" / "en.json"
FR_PATH = ROOT / "locales" / "fr.json"


def _flatten(d: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for k, v in d.items():
        if k == "_meta":
            continue
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys |= _flatten(v, full)
        else:
            keys.add(full)
    return keys


@pytest.fixture(scope="module")
def en_keys() -> set[str]:
    return _flatten(json.loads(EN_PATH.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def fr_keys() -> set[str]:
    return _flatten(json.loads(FR_PATH.read_text(encoding="utf-8")))


def test_en_keys_present_in_fr(en_keys: set[str], fr_keys: set[str]) -> None:
    """Toute cle EN doit avoir un equivalent FR."""
    missing = sorted(en_keys - fr_keys)
    assert not missing, f"{len(missing)} cles EN sans equivalent FR (fallback FR echoue) : {missing[:10]}..."


def test_fr_keys_present_in_en(en_keys: set[str], fr_keys: set[str]) -> None:
    """Toute cle FR doit avoir un equivalent EN."""
    missing = sorted(fr_keys - en_keys)
    assert not missing, f"{len(missing)} cles FR sans equivalent EN (fallback EN echoue) : {missing[:10]}..."


def test_parity_count(en_keys: set[str], fr_keys: set[str]) -> None:
    """Symetrie complete : meme nombre de cles dans les deux langues."""
    assert len(en_keys) == len(fr_keys), (
        f"FR={len(fr_keys)} vs EN={len(en_keys)} : ecart de {abs(len(en_keys) - len(fr_keys))} cles."
    )

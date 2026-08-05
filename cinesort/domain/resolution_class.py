"""Classification canonique de la resolution video — LARGEUR-primaire.

Pourquoi ce module existe
=========================
La hauteur retournee par ffprobe est celle du FLUX ENCODE, bandes noires deja
retirees. Un film cinema 2.39:1 masterise en 1080p mesure 1920x800, un 4K scope
mesure 3840x1600. Toute comparaison ecrite `height >= 1080` sur cette valeur
brute declasse d'une bande entiere l'integralite du catalogue cinemascope.

Le depot a tranche cette ambiguite en 2026-05-30 (bug 178) en passant a un
critere LARGEUR-primaire, verifie par ffprobe direct sur 15 echantillons de la
bibliotheque utilisateur : 15/15 des `1920x[784-818]` etaient de vrais 1080p que
l'ancienne logique classait en 720p. La regle retenue est `w >= X or h >= Y` :
la largeur tranche seule, la hauteur ne sert que de filet quand la largeur
manque (probe partiel, rapport persiste tronque).

Ce module porte cette regle UNE fois. Il est volontairement sans dependance
(domaine pur, aucun import interne) pour pouvoir etre importe partout, y compris
depuis les modules les plus bas de `cinesort.domain`.

Note de dette : quatre autres implementations de la meme echelle subsistent
(`naming.py`, `duplicate_compare.py`, `perceptual/composite_score_v2.py`,
`ui/api/library_support.py`). Elles retournent des types et des queues
differents (labels `480p`/`{h}p`, rangs entiers, tiers perceptuels) et ne sont
pas rebranchees ici : voir la reserve de la PR du lot #641/#682/#745/#806.
"""

from __future__ import annotations

from typing import Any

RES_2160P = "2160p"
RES_1080P = "1080p"
RES_720P = "720p"
RES_SD = "SD"
RES_UNKNOWN = ""

# Ordre decroissant, du plus haut au plus bas. Sert aux comparaisons de bande.
_ORDER = (RES_2160P, RES_1080P, RES_720P, RES_SD)


def _positive_int(value: Any) -> int:
    """Entier >= 0, tolerant : None, "", texte non numerique -> 0.

    `analyze_encode_quality` recoit des `metrics.detected` PERSISTES (JSON
    SQLite) : un `int()` nu y leverait ValueError sur une valeur corrompue et
    ferait echouer tout le rapport qualite. On degrade vers 0, ce qui remonte
    `RES_UNKNOWN` donc « pas de verdict » — jamais un faux verdict.

    `OverflowError` est INDISPENSABLE dans le tuple, et c'est le meme piege que
    la regle 4 du CLAUDE.md (`sqlite3.Error` n'herite pas d'`OSError`) :
    `OverflowError` derive d'`ArithmeticError`, PAS de `ValueError`. Or le cas
    est ATTEIGNABLE — `json.loads` accepte `Infinity` et `NaN` par defaut
    (extension non standard), donc une valeur persistee peut les contenir :

        int(float("nan"))  -> ValueError      (attrape)
        int(float("inf"))  -> OverflowError   (NON attrape sans cette entree)

    Sans elle, un seul `Infinity` dans `metrics.detected` faisait echouer le
    rapport qualite entier — exactement ce que cette fonction existe pour
    empecher. Releve par CodeRabbit sur la PR#908.
    """
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return n if n > 0 else 0


def classify_resolution(width: Any, height: Any) -> str:
    """Classe de resolution canonique depuis les dimensions MESUREES.

    Retourne l'une des constantes `RES_*`. `RES_UNKNOWN` ("") quand aucune des
    deux dimensions n'est exploitable : l'appelant doit alors s'abstenir de
    juger, pas retomber sur une bande par defaut.

    Seuils identiques a `quality_score._resolution_label` (qui delegue ici).
    """
    w = _positive_int(width)
    h = _positive_int(height)
    if w <= 0 and h <= 0:
        return RES_UNKNOWN
    if w >= 3800 or h >= 2100:
        return RES_2160P
    if w >= 1900 or h >= 1000:
        return RES_1080P
    if w >= 1280 or h >= 680:
        return RES_720P
    return RES_SD


def is_below(res: str, floor: str) -> bool:
    """`res` est-il STRICTEMENT sous la bande `floor` ?

    `RES_UNKNOWN` n'est jamais « sous » quoi que ce soit : sans mesure, on ne
    penalise pas (une classe inconnue traitee comme basse infligerait un malus
    a tout fichier dont le probe a echoue).
    """
    if res not in _ORDER or floor not in _ORDER:
        return False
    return _ORDER.index(res) > _ORDER.index(floor)


__all__ = [
    "RES_2160P",
    "RES_1080P",
    "RES_720P",
    "RES_SD",
    "RES_UNKNOWN",
    "classify_resolution",
    "is_below",
]

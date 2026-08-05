"""Producteur UNIQUE des `run_id` CineSort + validateur associe.

Historique du defaut corrige ici : la generation etait dupliquee a l'identique
dans `app/job_runner.py` et `ui/api/runtime_support.py`, et valait

    time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"

soit une resolution d'exactement 1 milliseconde SANS aucune garde d'unicite :
deux appels dans la meme milliseconde renvoyaient le MEME identifiant (mesure :
1997 collisions sur 2000 appels en rafale). Or `run_id` est la cle primaire de
`runs`, une composante de PRIMARY KEY de TROIS autres tables (quality_reports,
perceptual_reports, duplicate_decisions — mesure : `PRAGMA table_info`, verrouille
par `RunsSchemaDocumentationTests`), une colonne de rattachement de huit autres
(film_marked_for_deletion, film_tmdb_overrides, film_decisions_v2, apply_batches,
errors, anomalies, film_field_locks, user_quality_feedback), le nom du dossier de
run `runs/tri_films_<run_id>` et la cle du brouillon de validation en
localStorage : son unicite est une garantie d'ISOLATION METIER, pas un detail de
journalisation.

Format canonique : ``<YYYYMMDD>_<HHMMSS>_<mmm>_<ccc>``

- ``<YYYYMMDD>_<HHMMSS>_<mmm>`` : horodatage LOCAL a la milliseconde, inchange.
- ``<ccc>`` : compteur intra-milliseconde, monotone et propre au processus.

Pourquoi un compteur a LARGEUR FIXE et zero-padde plutot qu'un suffixe aleatoire
de longueur variable :

1. `infra/state.py:clean_old_runs` trie les dossiers de run par
   ``key=lambda x: x.name`` puis `shutil.rmtree` tout ce qui depasse `keep_last`.
   Ce tri LEXICOGRAPHIQUE n'equivaut a un tri chronologique que parce que le
   format est a largeur fixe et zero-padde. Un suffixe variable (``_1`` puis
   ``_10``) ferait supprimer les MAUVAIS runs — perte de donnees.
2. `ui/api/cinesort_api.py:RUN_ID_RE` impose l'alphabet ``[A-Za-z0-9_-]`` et
   une longueur maximale de 80 : le format reste a 23 caracteres.
3. Le run_id est injecte tel quel dans un nom de dossier NTFS : l'alphabet
   ci-dessus exclut deja tous les caracteres interdits par Windows.

`RUN_ID_PATTERN` est ELARGI EN UNION (ancien format 3 groupes OU nouveau format
4 groupes), jamais substitue : `normalize_or_generate_run_id` est appele avec le
run_id EXISTANT lors d'une reprise, et un ancien `20260612_234833_444` juge
invalide repartirait sous une nouvelle identite, orphelinant sa ligne `runs`,
son dossier `tri_films_...` et ses quality_reports.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Callable, Optional, Tuple

RUN_ID_PATTERN = re.compile(r"^\d{8}_\d{6}_\d{3}(?:_\d{3})?$")

# Largeur du compteur intra-milliseconde. 3 chiffres = 1000 run_id par
# milliseconde, soit un million par seconde : tres au-dela de ce qu'un scan
# CineSort peut demarrer. La saturation reste neanmoins geree (cf `_MonotonicSlots`)
# pour que l'unicite soit une GARANTIE et non une probabilite.
_COUNTER_WIDTH = 3
_COUNTER_MODULO = 10**_COUNTER_WIDTH


def _now_ms() -> int:
    """Horloge par defaut : epoch en millisecondes."""
    return time.time_ns() // 1_000_000


class _MonotonicSlots:
    """Source de couples (epoch_ms, compteur) STRICTEMENT croissants.

    Trois cas, tous sous verrou :

    - horloge avancee : nouvelle milliseconde, compteur remis a 0 ;
    - meme milliseconde : compteur incremente ;
    - horloge RECULEE (ajustement NTP, changement d'heure) : on reste sur la
      derniere milliseconde emise et on incremente le compteur. Sans ce cas,
      un recul d'horloge pourrait re-emettre un identifiant deja utilise.

    Si le compteur sature dans une milliseconde donnee, on avance d'une
    milliseconde VIRTUELLE plutot que d'attendre : la monotonie (donc
    l'unicite et l'ordre lexicographique) est preservee, au prix d'un
    horodatage en avance d'au plus 1 ms par tranche de 1000 identifiants.

    `clock` est INJECTABLE, et ce n'est pas de la complaisance de conception :
    une rafale reelle ne peut ni faire reculer l'horloge du systeme ni garantir
    1001 appels dans la meme milliseconde. Sans injection, ces deux gardes ne
    sont couvertes par aucun test — mesure : les neutraliser toutes les deux
    laissait la batterie entierement verte alors que chacune produit de VRAIS
    doublons (cf `MonotonicSlotsClockTests`).
    """

    def __init__(self, clock: Callable[[], int] = _now_ms) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._epoch_ms = -1
        self._counter = -1

    def next_slot(self) -> Tuple[int, int]:
        with self._lock:
            now_ms = self._clock()
            if now_ms > self._epoch_ms:
                self._epoch_ms = now_ms
                self._counter = 0
            else:
                self._counter += 1
                if self._counter >= _COUNTER_MODULO:
                    self._epoch_ms += 1
                    self._counter = 0
            return self._epoch_ms, self._counter


_SLOTS = _MonotonicSlots()


def _format_run_id(epoch_ms: int, counter: int) -> str:
    # localtime(entier de secondes) : pas de division flottante, donc pas de
    # desynchronisation possible entre la partie <HHMMSS> et la partie <mmm>.
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(epoch_ms // 1000))
    return f"{stamp}_{epoch_ms % 1000:03d}_{counter % _COUNTER_MODULO:0{_COUNTER_WIDTH}d}"


def generate_run_id() -> str:
    """Genere un `run_id` unique, triable et conforme aux deux validateurs.

    Unicite garantie pour tout le processus (verrou + compteur monotone). Les
    collisions inter-processus (deux CineSort sur un meme volume physique
    atteint par deux chemins differents) restent couvertes en defense en
    profondeur par la PRIMARY KEY de `runs` et par la reservation atomique du
    dossier de run (`infra/state.py:create_run_dir(exclusive=True)`).

    Une reserve, mesuree et assumee : `_MonotonicSlots` rend des `epoch_ms`
    strictement croissants, mais `_format_run_id` les projette en heure LOCALE.
    Au retour a l'heure d'hiver, deux `epoch_ms` distants d'une heure rendent
    donc la MEME chaine (mesure en Europe/Paris :
    `_format_run_id(1792889940500, 0) == _format_run_id(1792893540500, 0) ==
    '20261025_025900_500_000'`). C'est pre-existant a l'identique (l'ancienne
    formule utilisait deja `strftime` local), non corrige ici pour ne pas
    changer la lisibilite des identifiants, et couvert par les memes deux
    gardes de defense en profondeur que le cas inter-processus.
    """
    epoch_ms, counter = _SLOTS.next_slot()
    return _format_run_id(epoch_ms, counter)


def normalize_or_generate_run_id(existing: Optional[str]) -> str:
    """Conserve un `run_id` deja valide, sinon en genere un neuf.

    Le repli produit desormais un identifiant au FORMAT CANONIQUE et non plus
    un `uuid4().hex`. Deux raisons :

    1. Un uuid hexadecimal ne matche pas `RUN_ID_PATTERN`, donc il etait detruit
       au passage suivant dans cette meme fonction (le repli se re-generait a
       chaque reprise) ;
    2. il commence par une lettre dans ~62 % des cas et trie donc APRES tout
       identifiant horodate : `clean_old_runs` le classait eternellement comme
       « le plus recent » et supprimait de vrais runs dates a sa place.
    """
    candidate = str(existing or "").strip()
    if candidate and RUN_ID_PATTERN.match(candidate):
        return candidate
    return generate_run_id()

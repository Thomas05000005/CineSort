"""Garde-fou anti-fuite de dossiers temporaires (issue #960).

Constat MESURE sur `origin/main` : la suite laissait des centaines de dossiers
dans `%TEMP%` par execution (`mkdtemp` sans `rmtree`). Au-dela de quelques
milliers d'entrees, la creation et le renommage de dossiers temporaires partent
en `PermissionError [WinError 5]` — un echec attribue a tort au « verrou de
fichiers Windows », qui disparait quand on rejoue le test en isolation (la
verification de reference habituelle devient donc TROMPEUSE : le test passe
seul parce qu'il ne subit plus la charge de ses voisins, pas parce qu'il est
sain). La CI ne le voit jamais : runner neuf a chaque execution. Le defaut ne
frappe que la machine de developpement, precisement la ou on tente de
reproduire un echec de CI.

Ce garde-fou ne LIT PAS le source (un `grep rmtree` declare propre un fichier
qui ne nettoie qu'une classe sur trois). Il COMPTE : il redirige `%TEMP%` et
`tempfile.tempdir` vers un bac a sable vide pour la duree de la session, puis
compte ce qui reste dedans a la fin.

Compter dans un bac a sable plutot que dans le vrai `%TEMP%` donne trois choses :
  - aucune flakiness due aux autres processus de la machine ou du runner de CI ;
  - aucune liste blanche de prefixes a maintenir — un prefixe qui fuit est
    attrape le jour ou il apparait, meme s'il n'existait pas quand ce fichier
    a ete ecrit ;
  - la suite devient auto-nettoyante (le bac a sable est supprime a la fin),
    donc la machine de developpement ne derive plus vers le seuil.

Deux bornes, parce qu'elles n'attrapent pas la meme chose : le TOTAL attrape
une derive diffuse, la borne PAR FAMILLE de prefixe attrape le cas reel — un
fichier de tests qui oublie son nettoyage et produit N dossiers du meme prefixe.

Reglages :
  CINESORT_TEMP_LEAK_GUARD=0        desactive completement (aucune redirection).
  CINESORT_TEMP_LEAK_MAX=<n>        borne du total.
  CINESORT_TEMP_LEAK_MAX_FAMILY=<n> borne par famille de prefixe.

Limites connues, toutes MESUREES — a lire avant de croire un vert :

1. **La redirection a lieu au demarrage de la session**, donc APRES l'import des
   modules de test. Un `mkdtemp` execute au niveau module (a l'import) atterrit
   dans le vrai `%TEMP%` et echappe au comptage. Aucun cas de ce genre
   n'existe aujourd'hui dans `tests/` (verifie par un `--collect-only` complet,
   qui ne laisse aucune entree).
2. **Une borne de SESSION n'attrape que les gros fuyards.** Elle mord sur 15 ou
   22 dossiers ; elle ne voit pas revenir une fuite de 1 a 3 dossiers, qui est
   pourtant le profil de la majorite des fichiers corriges pour #960. Controle :
   restaurer la version fuyante de `tests/test_lotd_chain_doublons.py` laisse la
   session VERTE (2 entrees de 2 familles distinctes). Ce garde-fou borne la
   derive, il ne verrouille pas chaque fichier.
3. **Le nettoyage en `tearDown` n'est pas equivalent a `addCleanup`.** ~40 sites
   utilisent encore `tearDown`, qui ne s'execute pas si `setUp` echoue a
   mi-parcours — et `skipTest()` dans un `setUp` suffit (69 occurrences dans 26
   fichiers). MESURE : une exception inseree dans un `setUp` apres le `mkdtemp`
   laisse 45 dossiers. Le bac a sable masque la consequence, il ne ferme pas la
   boucle.
4. **Le residu se remesure, il ne se recopie pas** : 5 entrees sur une session,
   6 sur une autre (`cinesort_report_` et `cinesort_lotd_rest_` apparaissent
   sous charge). `tests/test_lotd_chain_rest.py` en laisse 1 de facon
   reproductible, meme en isolation.
"""

from __future__ import annotations

import collections
import gc
import os
import shutil
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

GUARD_ENV = "CINESORT_TEMP_LEAK_GUARD"
MAX_ENV = "CINESORT_TEMP_LEAK_MAX"
MAX_FAMILY_ENV = "CINESORT_TEMP_LEAK_MAX_FAMILY"
# Mesure du 2026-08-05, perimetre EXACT de la CI, une session : 5 dossiers
# residuels (2 `cinesort_atomic_e2e_`, 1 `cinesort_concurrency_`,
# 1 `cinesort_dupbrowse_`, 1 `cinesort_lot3_`) contre 259 avant les correctifs.
# Le total est borne LARGE (marge pour un runner de CI et pour les dossiers que
# Playwright laisse derriere lui) ; c'est la borne PAR FAMILLE qui mord.
DEFAULT_MAX = 12
# Un fichier de tests qui recommence a fuir produit N dossiers du MEME prefixe
# (15 pour `omdb_test_`, 14 pour `probe_test_`, 42 pour `cinesort_existing_db_`).
# Une borne de 3 par famille attrape cela des la premiere regression, la ou une
# borne globale genereuse le laisserait passer. Le residu connu plafonne a 2.
DEFAULT_MAX_FAMILY = 3
TEMP_VARS = ("TMP", "TEMP", "TMPDIR")
BOX_PREFIX = "cslb"
# Un bac homonyme qui resiste a la suppression fait glisser le nom d'un cran.
# Au-dela, on renonce plutot que de boucler.
_MAX_NOMS_DE_BAC = 4
# Un bac a sable plus vieux que ca appartient forcement a une session morte.
STALE_BOX_AGE_S = 3 * 3600.0
# Suppression finale : les threads de fond de l'app peuvent encore tenir un
# handle quelques dizaines de ms. On re-essaie, sinon le bac a sable reste.
_FINAL_RMTREE_ATTEMPTS = 8
_FINAL_RMTREE_DELAY_S = 0.1
# Longueur du bloc aleatoire de `tempfile.mkdtemp`, retiree pour regrouper
# `probe_test_ab12cd34` et `probe_test_zz99yy88` sous la meme famille.
_RANDOM_SUFFIX_LEN = 8
# Au-dela, l'appariement de familles (quadratique) ne vaut plus son prix : la
# borne du TOTAL a deja tranche bien avant.
_MAX_NOMS_APPARIEMENT = 400

# Bac a sable actif pour la session, ou None si le garde-fou est desactive.
_box: Path | None = None
# Nom d'entree fuitee -> nodeid du test qui l'a fait apparaitre (best effort).
_owners: dict[str, str] = {}


def guard_enabled() -> bool:
    return os.environ.get(GUARD_ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(0, int(raw.strip()))
    except ValueError:
        return default


def leak_max() -> int:
    return _env_int(MAX_ENV, DEFAULT_MAX)


def leak_max_family() -> int:
    return _env_int(MAX_FAMILY_ENV, DEFAULT_MAX_FAMILY)


def _cle_naive(name: str) -> str:
    """Famille supposant que le bloc aleatoire termine le nom (`prefix + rrrrrrrr`)."""
    return name[: max(1, len(name) - _RANDOM_SUFFIX_LEN)]


def _cles_candidates(name: str) -> list[str]:
    """Toutes les familles possibles, la plus vraisemblable D'ABORD.

    Une cle = le nom prive d'un bloc de 8 caracteres pris a une position. On
    balaie les positions de la FIN vers le DEBUT, donc la premiere cle produite
    est celle du cas courant (`prefix + rrrrrrrr`) : elle sert de depart
    d'egalite quand aucune position ne rassemble plus de monde qu'une autre.
    """
    cles: list[str] = []
    vus: set[str] = set()
    for i in range(len(name) - _RANDOM_SUFFIX_LEN, -1, -1):
        cle = name[:i] + name[i + _RANDOM_SUFFIX_LEN :]
        if cle not in vus:
            vus.add(cle)
            cles.append(cle)
    return cles or [_cle_naive(name)]


def count_families(leftovers: list[str]) -> collections.Counter[str]:
    """Regroupe les entrees par famille, bloc aleatoire de `mkdtemp` retire.

    Le bloc aleatoire fait 8 caracteres et se place APRES le prefixe, pas
    forcement a la fin : `mkdtemp(prefix=P, suffix=S)` produit `P + rrrrrrrr + S`
    et `mkstemp(suffix=".json")` fait de meme. Retirer betement les 8 derniers
    caracteres donnait alors une famille DIFFERENTE par dossier, et la borne par
    famille — celle qui mord — ne voyait plus rien passer. MESURE : 10 dossiers
    du meme `mkdtemp(prefix="agentleak_")` declenchaient la borne ; les memes
    avec `suffix="_end"` passaient en silence, et 12 aussi.

    On ne devine donc pas ou est le bloc : on essaie toutes les positions, et on
    retient pour chaque nom la cle qui rassemble le plus de monde. Deux noms ne
    peuvent partager une cle qu'en ayant meme longueur et meme reste — c'est-a-
    dire meme prefixe ET meme suffixe, donc bien la meme famille. Les familles
    distinctes ne fusionnent pas : `cinesort_atomic_e2e_XXXXXXXX` (28) et
    `cinesort_concurrency_XXXXXXXX` (29) n'ont deja pas la meme longueur.

    Au-dela de `_MAX_NOMS_APPARIEMENT` entrees, on retombe sur la regle naive :
    a ce stade la borne du TOTAL a de toute facon deja tranche, et l'appariement
    est quadratique.
    """
    if len(leftovers) > _MAX_NOMS_APPARIEMENT:
        return collections.Counter(_cle_naive(name) for name in leftovers)

    # Combien de noms chaque cle candidate rassemble-t-elle ?
    popularite: collections.Counter[str] = collections.Counter()
    candidates: list[list[str]] = []
    for name in leftovers:
        cles = _cles_candidates(name)
        candidates.append(cles)
        popularite.update(cles)

    families: collections.Counter[str] = collections.Counter()
    for cles in candidates:
        # `max` rend le PREMIER maximum, et `_cles_candidates` commence par la
        # cle naive : a egalite de popularite — le cas d'un dossier isole, ou
        # toutes les cles valent 1 — c'est donc le prefixe qui gagne, et non un
        # fragment arbitraire. Sans ce depart d'egalite, `omdb_test_cccccccc`
        # etait rapporte sous la famille `t_cccccccc*`.
        families[max(cles, key=popularite.__getitem__)] += 1
    return families


def verdict(leftovers: list[str], limit: int, limit_family: int) -> str:
    """Retourne le motif d'echec, ou "" si la session est acceptable.

    Deux bornes, parce qu'elles n'attrapent pas la meme chose :
      - le TOTAL attrape une derive diffuse ;
      - la borne PAR FAMILLE attrape le cas reel — un fichier de tests qui
        oublie son nettoyage et produit N dossiers du meme prefixe — meme si le
        total reste sous une limite globale genereuse.
    """
    if len(leftovers) > limit:
        return f"total {len(leftovers)} > {limit}"
    families = count_families(leftovers)
    worst = families.most_common(1)
    if worst and worst[0][1] > limit_family:
        return f"famille {worst[0][0]}* : {worst[0][1]} > {limit_family}"
    return ""


def build_report(
    leftovers: list[str],
    limit: int,
    owners: dict[str, str] | None = None,
    *,
    reason: str = "",
    limit_family: int | None = None,
) -> str:
    """Message d'echec : combien, quelles familles de prefixes, quels tests."""
    owners = _owners if owners is None else owners
    limit_family = DEFAULT_MAX_FAMILY if limit_family is None else limit_family
    families = count_families(leftovers)
    lines = [
        f"Fuite de dossiers temporaires : {len(leftovers)} entree(s) laissee(s) dans %TEMP% "
        f"par cette session (bornes : total {limit}, par famille {limit_family}).",
        f"Borne franchie : {reason}." if reason else "",
        "",
        "NB : ce verdict porte sur la SESSION ENTIERE. pytest l'agrafe au dernier",
        "test execute, qui n'y est pour rien — les coupables sont ci-dessous.",
        "",
        "Familles (prefixe -> nombre) :",
    ]
    lines += [f"  {count:5d}  {prefix}*" for prefix, count in families.most_common(15)]
    responsible: collections.Counter[str] = collections.Counter()
    for name in leftovers:
        responsible[owners.get(name, "<inconnu>")] += 1
    lines += ["", "Tests responsables (best effort) :"]
    lines += [f"  {count:5d}  {nodeid}" for nodeid, count in responsible.most_common(15)]
    lines += [
        "",
        "Correctif : `tempfile.TemporaryDirectory()`, ou pour `mkdtemp` ajouter",
        "    self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)",
        "juste apres la creation. `addCleanup` et pas `tearDown` : il s'execute meme",
        "si `setUp` echoue a mi-parcours, et il s'empile proprement avec l'heritage.",
        "",
        f"Pour desactiver temporairement ce garde-fou : {GUARD_ENV}=0.",
    ]
    return "\n".join(lines)


def est_un_bac(name: str) -> bool:
    """True si `name` est un bac a sable a NOUS (`cslb<pid>`, ou `cslb<pid>x<n>`).

    Le test porte sur le premier caractere apres le prefixe : il doit etre un
    chiffre, donc le debut d'un PID. Un dossier tiers qui commencerait par
    `cslb` sans PID derriere (`cslbackup`, `cslbabc`...) n'est JAMAIS balaye —
    le balayage supprime, il doit se tromper dans le sens conservateur.
    """
    reste = name[len(BOX_PREFIX) :]
    return name.startswith(BOX_PREFIX) and bool(reste) and reste[0].isdigit()


def sweep_stale_boxes(real_temp: Path, *, now: float | None = None, max_age_s: float = STALE_BOX_AGE_S) -> int:
    """Supprime les bacs a sable abandonnes par des sessions precedentes.

    Une poignee de dossiers resiste a la suppression de fin de session : leur
    handle est tenu par le processus pytest lui-meme et n'est relache qu'a sa
    mort. Ce balayage les recupere au demarrage suivant, ce qui borne la derive
    a UNE session au lieu de la laisser croitre indefiniment.

    Le mtime d'un bac a sable actif est rafraichi en permanence (les tests y
    creent et suppriment des dossiers), donc une session longue mais vivante
    n'est jamais consideree comme perimee. Retourne le nombre de bacs enleves.
    """
    reference = time.time() if now is None else now
    removed = 0
    try:
        entries = list(real_temp.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not est_un_bac(entry.name):
            continue
        try:
            if reference - entry.stat().st_mtime < max_age_s:
                continue
        except OSError:
            continue
        before = entry.exists()
        shutil.rmtree(entry, ignore_errors=True)
        if before and not entry.exists():
            removed += 1
    return removed


def _bac_vide(souhaite: Path) -> Path:
    """Retourne un bac a sable GARANTI vide, quitte a changer son nom.

    Le nom du bac contient le PID, et Windows recycle les PID (mesure : 2 sur
    300 processus). Une session TUEE — Ctrl-C dur, agent interrompu, OOM —
    laisse son bac derriere elle ; `sweep_stale_boxes` ne le ramasse qu'au-dela
    de 3 h. Entre les deux, une session qui herite du meme PID adoptait ce bac
    et se voyait accusee des restes de la precedente : « 20 entree(s) laissee(s)
    par cette session », « Tests responsables : 20 <inconnu> » — un rouge sur
    une session qui n'a rien fuit, et personne a nommer.

    C'est exactement le scenario « je reproduis un echec de CI en local » :
    on interrompt, on relance.

    Un bac homonyme ne peut appartenir qu'a un processus MORT (deux processus
    vivants n'ont pas le meme PID), donc le vider est sans risque. S'il resiste
    — un handle encore tenu ailleurs — on prend un nom voisin plutot que de
    compter les restes d'autrui.
    """
    for tentative in range(_MAX_NOMS_DE_BAC):
        box = souhaite if tentative == 0 else souhaite.with_name(f"{souhaite.name}x{tentative}")
        shutil.rmtree(box, ignore_errors=True)
        box.mkdir(parents=True, exist_ok=True)
        try:
            if not any(box.iterdir()):
                return box
        except OSError:
            return box
    return souhaite


@pytest.fixture(scope="session", autouse=True)
def _temp_leak_guard(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Redirige %TEMP% vers un bac a sable et echoue si la session y laisse des restes."""
    global _box
    if not guard_enabled():
        yield
        return

    # Le basetemp de pytest (`tmp_path`) est cree AVANT la redirection : il reste
    # donc dans le vrai %TEMP%, ou pytest applique deja sa propre retention
    # (3 sessions). Sinon il atterrirait dans le bac a sable, ou il serait
    # compte comme une fuite et ou il rallongerait tous les chemins de
    # `tmp_path` de la longueur du nom du bac (MAX_PATH est etroit sur Windows).
    tmp_path_factory.getbasetemp()

    real_temp = Path(tempfile.gettempdir())
    sweep_stale_boxes(real_temp)

    # Nom court volontairement : chaque caractere ajoute ici se paie sur la
    # longueur de TOUS les chemins temporaires de la suite.
    box = _bac_vide(real_temp / f"{BOX_PREFIX}{os.getpid()}")

    saved_tempdir = tempfile.tempdir
    saved_env = {name: os.environ.get(name) for name in TEMP_VARS}
    tempfile.tempdir = str(box)
    for name in TEMP_VARS:
        os.environ[name] = str(box)
    _box = box
    try:
        yield
    finally:
        _box = None
        tempfile.tempdir = saved_tempdir
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        # Un `TemporaryDirectory` encore reference est nettoye par son
        # finalizer : on force le GC AVANT de compter, sinon on l'accuse a tort.
        gc.collect()
        gc.collect()
        try:
            leftovers = sorted(entry.name for entry in box.iterdir())
        except OSError:
            leftovers = []
        for attempt in range(_FINAL_RMTREE_ATTEMPTS):
            shutil.rmtree(box, ignore_errors=True)
            if not box.exists():
                break
            time.sleep(_FINAL_RMTREE_DELAY_S * (attempt + 1))
        limit, limit_family = leak_max(), leak_max_family()
        reason = verdict(leftovers, limit, limit_family)
        if reason:
            pytest.fail(
                build_report(leftovers, limit, reason=reason, limit_family=limit_family),
                pytrace=False,
            )


@pytest.fixture(autouse=True)
def _temp_leak_attribution(request: pytest.FixtureRequest) -> Iterator[None]:
    """Note quel test a fait apparaitre chaque entree du bac a sable.

    Sans cela, le message d'echec de session dirait « 412 dossiers » sans dire
    ou regarder. Best effort : une entree creee par un thread de fond apres la
    fin du test est attribuee au test suivant.
    """
    box = _box
    if box is None:
        yield
        return
    try:
        before = set(os.listdir(box))
    except OSError:
        before = set()
    try:
        yield
    finally:
        try:
            after = set(os.listdir(box))
        except OSError:
            after = before
        for name in after - before:
            _owners.setdefault(name, request.node.nodeid)

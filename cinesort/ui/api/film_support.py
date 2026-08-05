"""§v7.6.0 Vague 4 — Film detail standalone page backend.

Endpoint unique : get_film_full(run_id, row_id)

Consolide en 1 seul appel :
    - metadata PlanRow (titre, annee, source path, collection, edition, ...)
    - probe technique (codec, resolution, HDR, audio tracks, subs)
    - perceptual result complet (V1 + V2 si dispo)
    - history timeline (via film_history_support)
    - poster TMDb URL
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from typing import Any, Dict, List, Optional

from cinesort.domain.film_history import identity_key_from_dict
from cinesort.infra import state
from cinesort.infra._http_utils import get_bounded
from cinesort.ui.api import film_history_support
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api.settings_support import _SECRET_MASK, normalize_user_path

logger = logging.getLogger(__name__)


def _resolve_run_id(api: Any, run_id: Optional[str]) -> Optional[str]:
    if run_id:
        return str(run_id)
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)
        runs = store.run.list_runs(limit=1)
        if runs:
            return str(runs[0].get("run_id") or "")
    except (OSError, AttributeError, KeyError, TypeError, ValueError):
        pass
    return None


def _find_plan_row(api: Any, run_id: str, row_id: str) -> Optional[Dict[str, Any]]:
    """Retourne LA row de plan demandee, sans materialiser tout le plan.

    PERF (ultra-audit 2026-08, HIGH) : cette fonction appelait
    `api.run.get_plan(run_id)`, qui serialise ET enrichit les N rows du run
    (dont 2 connexions SQLite par row pour l'override TMDb), puis jetait les
    N-1 autres. Mesure : 9,2 s et ~2000 connexions SQLite pour renvoyer UNE
    ligne sur un plan de 1000 films. `history_support.get_plan_row` fait passer
    la seule row voulue dans la MEME chaine d'enrichissement (alertes ignorees,
    override TMDb, reconciliation des sous-titres, display_title,
    auto_approvable) : memes champs en sortie, cout constant.
    """
    from cinesort.ui.api.history_support import get_plan_row  # noqa: PLC0415 — import tardif (cycle)

    try:
        return get_plan_row(api, str(run_id), str(row_id), normalize_user_path=normalize_user_path)
    except (OSError, AttributeError, KeyError, TypeError, ValueError):
        return None


def _fetch_poster_url(api: Any, tmdb_id: int, size: str = "w500") -> Optional[str]:
    """Spec 06 §3.1 : poster TMDb taille w500 par defaut (~200x300 affichage)."""
    if not tmdb_id or int(tmdb_id) <= 0:
        return None
    try:
        result = api.integrations.get_tmdb_posters([int(tmdb_id)], size)
        if result and result.get("ok"):
            return result.get("posters", {}).get(str(int(tmdb_id)))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.debug("poster fetch error: %s", exc)
    return None


def _fetch_tmdb_extras(api: Any, tmdb_id: int) -> Dict[str, Any]:
    """Spec 06 §3.1 : recupere runtime (min) + director + overview via TmdbClient.

    Best-effort : retourne dict vide si TMDb pas configure ou indispo. Utilise
    le cache local TmdbClient.
    """
    out: Dict[str, Any] = {"runtime": None, "director": None, "overview": None}
    if not tmdb_id or int(tmdb_id) <= 0:
        return out
    # Import lazy : TmdbClient n'est pas necessaire si pas de cle TMDb.
    try:
        from cinesort.infra.tmdb_client import TmdbClient
    except ImportError:
        return out
    try:
        # AUDIT F20 : _internal_settings() -> secrets EN CLAIR. get_settings()
        # renvoie tmdb_api_key MASQUEE ("••••••••") depuis SEC-H2, et le masque
        # etant truthy le garde `if not api_key` ne stoppait rien : la cle
        # masquee partait telle quelle vers api.themoviedb.org -> 401 -> runtime
        # /director/overview systematiquement null. Meme correctif qu'a
        # tmdb_support.py:103 et library_actions_support.py:661-664.
        settings = api._internal_settings()
        api_key = str(settings.get("tmdb_api_key") or "").strip()
        if not api_key or api_key == _SECRET_MASK:
            # Masque residuel (settings.json illisible / secret non de-masque) :
            # inutile de bruler des requetes HTTP vouees au 401.
            return out
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        try:
            cache_ttl_days = int(settings.get("tmdb_cache_ttl_days") or 30)
        except (TypeError, ValueError):
            cache_ttl_days = 30
        client = TmdbClient(
            api_key=api_key,
            cache_path=state_dir / "tmdb_cache.json",
            timeout_s=float(settings.get("tmdb_timeout_s") or 10.0),
            cache_ttl_days=cache_ttl_days,
        )
        try:
            out["runtime"] = client.get_movie_runtime(int(tmdb_id))
        except (AttributeError, TypeError, ValueError) as exc:
            logger.debug("tmdb runtime fetch error: %s", exc)
        # AUDIT F20 (revue R1) : director + overview ne sont dans AUCUN champ du
        # cache TmdbClient (_get_movie_detail_cached ne stocke que poster /
        # collection / genres / budget / companies / runtime, et ne demande meme
        # pas append_to_response=credits). Ils partaient donc en GET NON CACHE a
        # chaque appel : 1 par ouverture de fiche film, et surtout N en parallele
        # quand la vue Doublons hydrate N groupes (un library/get_film_full par
        # groupe, Promise.allSettled). On range desormais le resultat dans le
        # cache local du client (meme tmdb_cache.json, meme TTL configure) sous
        # une cle dediee : le 2e appel et les suivants ne touchent plus le reseau.
        extras_key = f"movie_extras|{int(tmdb_id)}"
        cached_extras: Any = None
        with contextlib.suppress(AttributeError, OSError, TypeError, ValueError):
            cached_extras = client._cache_get(extras_key)
        if isinstance(cached_extras, dict):
            out["director"] = cached_extras.get("director") or None
            out["overview"] = cached_extras.get("overview") or None
            if not out.get("runtime"):
                out["runtime"] = cached_extras.get("runtime") or None
        else:
            # Miss (ou cache indisponible) : appel HTTP frais avec
            # append_to_response=credits pour recuperer crew -> Director.
            try:
                import requests as _req

                # Meme famille que #753/#824 : ce GET direct etait la derniere
                # lecture JSON non bornee du depot (il n'est dans aucun client,
                # donc l'inventaire par client le manquait). `requests.get()`
                # ouvre de toute facon une Session ephemere en interne : on la
                # rend explicite pour pouvoir passer par le lecteur borne, sans
                # changer la semantique reseau (pas de retry ajoute).
                with _req.Session() as _session:
                    r = get_bounded(
                        _session,
                        f"https://api.themoviedb.org/3/movie/{int(tmdb_id)}",
                        params={
                            "api_key": api_key,
                            "language": "fr-FR",
                            "append_to_response": "credits",
                        },
                        timeout=float(settings.get("tmdb_timeout_s") or 10.0),
                    )
                if r.status_code == 200:
                    data = r.json() or {}
                    # Director : prend le premier crew member job=Director
                    credits = data.get("credits") or {}
                    crew = credits.get("crew") or []
                    for c in crew:
                        if str(c.get("job") or "").lower() == "director":
                            out["director"] = str(c.get("name") or "").strip() or None
                            break
                    out["overview"] = str(data.get("overview") or "").strip() or None
                    # Runtime aussi en fallback si pas deja recupere
                    fresh_runtime: Optional[int] = None
                    try:
                        rt = int(data.get("runtime") or 0)
                        fresh_runtime = rt if rt > 0 else None
                    except (TypeError, ValueError):
                        fresh_runtime = None
                    if not out.get("runtime"):
                        out["runtime"] = fresh_runtime
                    # On ne memorise QUE les reponses 200 : une erreur reseau ou
                    # un 401 doit etre reessaye au prochain appel, pas fige pour
                    # la duree du TTL.
                    with contextlib.suppress(AttributeError, OSError, TypeError, ValueError):
                        client._cache_set(
                            extras_key,
                            {
                                "director": out.get("director"),
                                "overview": out.get("overview"),
                                "runtime": out.get("runtime") or fresh_runtime,
                            },
                        )
            except (OSError, ImportError, KeyError, TypeError, ValueError) as exc:
                logger.debug("tmdb extras http fetch error: %s", exc)
        with contextlib.suppress(OSError, AttributeError):
            client.flush()
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.debug("_fetch_tmdb_extras error: %s", exc)
    return out


def _resolve_chosen_tmdb_id(row: Dict[str, Any], candidates: List[Dict[str, Any]]) -> int:
    """Fix audit 2026-05-25 (v1.5.4) Vague I : resolution canonique du candidat
    "chosen" pour le modal film.

    Priorite (high -> low) :
      1. row.chosen_tmdb_id (override utilisateur via set_film_tmdb_candidate)
      2. row.tmdb_id (TMDb match auto principal)
      3. candidates[0].tmdb_id (top match par defaut)
    Retourne 0 si aucun candidate exploitable.
    """
    for source_key in ("chosen_tmdb_id", "tmdb_id"):
        try:
            raw = row.get(source_key) if isinstance(row, dict) else None
        except AttributeError:
            raw = None
        if raw is None:
            continue
        try:
            val = int(raw)
        except (TypeError, ValueError):
            continue
        if val > 0:
            return val
    if candidates:
        try:
            return int(candidates[0].get("tmdb_id") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


#: Marqueur pose sur une row UNIQUEMENT quand `film_tmdb_overrides` a ete lue
#: AVEC SUCCES pour cette row (qu'un override existe ou non).
#:
#: Revue adversaire PR #849 : le seul signal qui prouve « l'overlay a tourne »
#: doit etre pose par l'overlay lui-meme, sur son chemin de succes. Inferer ce
#: succes depuis un autre champ (`display_title`, pose de toute facon par
#: `history_support._enrich_plan_payload` APRES un `contextlib.suppress`) fait
#: passer un echec silencieux pour un succes -> le choix TMDb manuel de
#: l'utilisateur disparait de la Bibliotheque (bug R7-3 re-ouvert).
#:
#: Contrat : marqueur ABSENT => la lecture n'a pas abouti (store None, run_id/
#: row_id vide, erreur SQLite/OS...) => tout consommateur en aval DOIT refaire
#: l'overlay lui-meme. Fail-closed : en cas de doute on relit.
TMDB_OVERLAY_DONE_KEY = "_tmdb_overlay_done"


def overlay_tmdb_override(store: Any, run_id: Optional[str], row: Dict[str, Any]) -> bool:
    """AUDIT 2026-06-14 (R7-3) : applique l'override TMDb manuel sur une row dict.

    Le choix manuel d'un candidat (set_film_tmdb_candidate) est persiste dans la
    table film_tmdb_overrides mais AUCUN consommateur de prod ne la lisait :
    biblio, fiche film et apply retombaient sur le match auto -> au reload le
    choix disparaissait et l'apply renommait avec l'ancien match. Ce helper
    overlay tmdb_id/chosen_tmdb_id/proposed_title/proposed_year/confidence depuis
    l'override. Sans override -> no-op (comportement inchange). Reversible : la
    table reste la source, on n'ecrit pas le plan (clear_tmdb_override suffit).

    Effet de bord voulu : pose `TMDB_OVERLAY_DONE_KEY` sur la row des que la
    lecture de la table a abouti (voir la constante). La valeur de retour, elle,
    ne dit que « un override a ete APPLIQUE » : elle vaut False aussi bien quand
    la lecture a echoue que quand il n'y a simplement rien a appliquer, donc
    elle ne peut PAS servir de signal « l'overlay a tourne ».
    """
    if not isinstance(row, dict) or store is None:
        return False
    rid = str(run_id or "")
    row_id = str(row.get("row_id") or "")
    if not rid or not row_id:
        return False
    try:
        ov = store.film_modal.get_tmdb_override(run_id=rid, row_id=row_id)
    # Regle 4 du CLAUDE.md : sqlite3.Error n'herite PAS d'OSError. Sans lui, une
    # base verrouillee remontait ici en exception nue -> chemin divergent selon
    # l'appelant (avalee par le `contextlib.suppress(Exception)` de
    # _enrich_plan_payload, mais fatale a toute la vue Bibliotheque).
    except (AttributeError, OSError, TypeError, ValueError, sqlite3.Error) as exc:
        # PAS de marqueur : la row n'a pas d'etat d'override fiable, l'appelant
        # suivant doit refaire le travail.
        logger.debug("overlay_tmdb_override read failed run_id=%s row_id=%s: %s", rid, row_id, exc)
        return False
    # Lecture aboutie : cette row porte desormais l'etat authoritatif de
    # film_tmdb_overrides. Le marqueur est pose ICI, et sur le chemin GROUPE
    # dans `apply_tmdb_overrides_bulk` — les deux seules fonctions qui savent
    # qu'une lecture a abouti. Jamais chez un appelant (cf. la constante).
    row[TMDB_OVERLAY_DONE_KEY] = True
    return apply_tmdb_override(row, ov)


def apply_tmdb_override(row: Dict[str, Any], override: Optional[Dict[str, Any]]) -> bool:
    """Applique un override DEJA LU sur une row dict. Fonction pure (zero I/O).

    Extraite de `overlay_tmdb_override` (dont elle garde la semantique champ
    pour champ) pour que les appelants qui traitent un LOT de rows puissent
    lire les overrides en une seule requete (`list_tmdb_overrides_bulk`) au
    lieu d'ouvrir 2 connexions SQLite par row.

    Ne pose deliberement PAS `TMDB_OVERLAY_DONE_KEY` : recevant un override
    deja lu, elle ne peut pas distinguer « pas d'override pour cette row » de
    « la lecture a echoue » — `override=None` vaut pour les deux. Le marqueur
    appartient aux fonctions qui font la lecture (`overlay_tmdb_override` et
    `apply_tmdb_overrides_bulk`).
    """
    if not isinstance(row, dict) or not override:
        return False
    tid = int(override.get("tmdb_id") or 0)
    if tid > 0:
        row["tmdb_id"] = tid
        row["chosen_tmdb_id"] = tid
    if override.get("proposed_title"):
        row["proposed_title"] = str(override["proposed_title"])
    if int(override.get("proposed_year") or 0) > 0:
        row["proposed_year"] = int(override["proposed_year"])
    conf = int(override.get("new_confidence") or 0)
    if conf > 0:
        row["confidence"] = conf
    return True


def list_tmdb_overrides_bulk(store: Any, run_id: Optional[str]) -> Optional[Dict[str, Dict[str, Any]]]:
    """Tous les overrides TMDb d'un run, en UNE requete. Cf `apply_tmdb_override`.

    PERF (ultra-audit 2026-08, CRITICAL) : `film_modal.get_tmdb_override`
    enchaine `_ensure_tables()` (1 connexion) puis `_managed_conn()` (2e
    connexion), soit EXACTEMENT 2 ouvertures de connexion SQLite par appel.
    Applique par row sur un plan entier, cela donnait 2N connexions : 40 s et
    2002 connexions mesurees pour 1000 films, meme quand la table est vide.
    Le cout n'est pas le SELECT (~0,003 ms) mais l'ouverture de connexion
    (~14 ms : `apply_pragmas` ecrit dans `pragma_history` a chaque ouverture).

    Retour :
      - `{}`   : run sans aucun override (cas normal, rien a appliquer) ;
      - dict   : {row_id: override} au meme format que `get_tmdb_override` ;
      - `None` : lecture bulk indisponible (store/table/repo hors service) OU
        seulement PARTIELLE (au moins une ligne de la table indecodable).
        Les deux cas sont volontairement distincts pour que l'appelant puisse
        retomber sur le chemin par row plutot que de servir un plan
        silencieusement prive de ses overrides.

    Fail-closed (contrat `TMDB_OVERLAY_DONE_KEY`, PR #849) : un resultat
    PARTIEL rendrait ce contrat menteur. L'appelant marque les rows « override
    a jour » sur la foi d'un dict non-`None` ; une ligne silencieusement omise
    ferait donc disparaitre le choix TMDb manuel de l'utilisateur SANS que la
    Bibliotheque relise (bug R7-3 re-ouvert). Une seule ligne illisible suffit
    donc a rendre `None` — exactement ce que fait deja le chemin par row, ou
    `get_tmdb_override` leve sur les memes conversions et laisse
    `overlay_tmdb_override` repartir sans marqueur.
    """
    rid = str(run_id or "")
    repo = getattr(store, "film_modal", None) if store is not None else None
    if repo is None or not rid:
        return None
    # Acces aux helpers du repository : `film_tmdb_overrides` n'expose pas de
    # lecture par run, et ces helpers sont precisement le contrat documente de
    # `_BaseRepository` (delegation vers le SQLiteStore parent).
    try:
        repo._ensure_tables()  # noqa: SLF001
        with repo._managed_conn() as conn:  # noqa: SLF001
            cur = conn.execute(
                """
                SELECT row_id, tmdb_id, new_confidence, proposed_title, proposed_year, chosen_at
                FROM film_tmdb_overrides
                WHERE run_id=?
                """,
                (rid,),
            )
            fetched = cur.fetchall()
    # sqlite3.Error n'herite PAS d'OSError (regle projet) : sans lui, un
    # 'database is locked' pendant un apply concurrent remonterait au lieu de
    # rendre la main au chemin par row.
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
        logger.debug("list_tmdb_overrides_bulk unavailable: %s", exc)
        return None
    out: Dict[str, Dict[str, Any]] = {}
    for r in fetched:
        try:
            out[str(r["row_id"])] = {
                "tmdb_id": int(r["tmdb_id"]),
                "new_confidence": int(r["new_confidence"]),
                "proposed_title": str(r["proposed_title"] or ""),
                "proposed_year": int(r["proposed_year"] or 0),
                "chosen_at": float(r["chosen_at"]),
            }
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            # Resultat PARTIEL : on rend `None` au lieu de sauter la ligne. Cf.
            # la docstring — un dict ampute ferait poser le marqueur d'overlay
            # sur des rows dont l'override n'a PAS ete applique.
            logger.debug("list_tmdb_overrides_bulk partial read, falling back to per-row: %s", exc)
            return None
    return out


def apply_tmdb_overrides_bulk(
    rows: Any,
    overrides: Optional[Dict[str, Dict[str, Any]]],
) -> int:
    """Applique un LOT d'overrides deja lus et pose le marqueur d'overlay.

    Pendant groupe de `overlay_tmdb_override` : meme contrat, meme endroit ou
    le marqueur est ecrit (dans film_support, sur une lecture ABOUTIE), mais
    une seule requete pour tout le run au lieu de 2 connexions SQLite par row.

    `overrides is None` (lecture bulk indisponible ou partielle) => aucune row
    n'est touchee et AUCUNE n'est marquee : l'appelant doit repasser par le
    chemin par row. Une row sans `row_id`, ou dont l'application echoue, ne
    recoit pas non plus le marqueur — fail-closed jusqu'au grain de la row.

    Retourne le nombre de rows sur lesquelles un override a ete APPLIQUE (les
    autres rows lues restent marquees : marqueur != override applique).
    """
    if overrides is None:
        return 0
    applied = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("row_id") or "")
        if not row_id:
            # Meme regle que `overlay_tmdb_override` : sans row_id il n'y a pas
            # d'etat d'override connu pour cette row.
            continue
        try:
            if apply_tmdb_override(row, overrides.get(row_id)):
                applied += 1
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            # Pas de marqueur pour CETTE row : son etat d'override est douteux.
            logger.debug("apply_tmdb_overrides_bulk failed row_id=%s: %s", row_id, exc)
            continue
        row[TMDB_OVERLAY_DONE_KEY] = True
    return applied


def get_film_full(api: Any, run_id: Optional[str], row_id: str) -> Dict[str, Any]:
    """Retourne la totalite des informations d'un film pour la page standalone.

    Response :
      {
        ok: bool,
        run_id: str,
        row_id: str,
        row: {...},                // PlanRow complet
        probe: {...} | None,       // normalized probe (video+audio+subs)
        perceptual: {...} | None,  // PerceptualResult incl. global_score_v2_payload
        history: [...] | [],       // timeline events
        poster_url: str | None,
        tmdb_id: int,
      }
    """
    # Fix audit 2026-05-25 (v1.5.3) Vague F : wrap global pour eviter HTTP 500
    # quand le run devient obsolete ou la base inaccessible. On retourne un
    # contrat JSON {ok: False, error, user_message} que le frontend peut afficher.
    try:
        return _get_film_full_impl(api, run_id, row_id)
    except Exception as exc:  # noqa: BLE001 - on doit attraper tout pour eviter HTTP 500
        logger.exception("get_film_full failed for run_id=%s row_id=%s", run_id, row_id)
        return {
            "ok": False,
            "error": "film_load_failed",
            "message": str(exc),
            "user_message": (
                "Impossible de charger ce film (run obsolete ou base inaccessible). Relance un scan ou redemarre l'app."
            ),
        }


def _get_film_full_impl(api: Any, run_id: Optional[str], row_id: str) -> Dict[str, Any]:
    """Implementation reelle de get_film_full, sans wrap global.

    Extrait pour faciliter le wrap try/except dans get_film_full (Vague F Fix 3).
    """
    resolved_rid = _resolve_run_id(api, run_id)
    if not resolved_rid:
        return _err_response("Aucun run disponible.", category="state", level="info", log_module=__name__)

    row = _find_plan_row(api, resolved_rid, row_id)
    if not row:
        return _err_response(
            f"Film introuvable (row_id={row_id}).", category="runtime", level="error", log_module=__name__
        )

    # Probe (via quality_reports store)
    probe_dict = None
    perceptual_dict = None
    store: Any = None
    _has_override = False  # R7-12
    _is_marked = False  # R7-12
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)

        # R7-3 : overlay du choix manuel de candidat TMDb (film_tmdb_overrides)
        # AVANT la resolution du chosen tmdb_id / poster, sinon la fiche film
        # re-affiche le match auto et ignore le choix utilisateur.
        overlay_tmdb_override(store, resolved_rid, row)

        # R7-12 : flags d'etat pour exposer les actions d'annulation dans l'UI
        # (revenir au match auto / annuler le marquage pour suppression).
        #
        # Revue adversaire R3 2026-07-13 (defaut 5) : `is_marked_for_deletion` ne
        # lit QUE la table DB, alors que l'apply honore l'UNION DB + legacy
        # (apply_support.py:1584). C'etait le seul chemin de lecture des marques
        # SANS le drain : sur une install portant encore un deletion_marks.json,
        # ouvrir une fiche film affichait "Marquer pour suppression" pour un film
        # qui SERA pourtant bucketise a l'apply. On draine donc ici aussi, et on
        # prend l'UNION avec les row_ids restes en attente (drain DB en echec).
        _legacy_marked = set()
        try:
            from cinesort.ui.api.library_actions_support import (  # noqa: PLC0415
                migrate_legacy_deletion_marks,
            )

            _legacy_marked = set(migrate_legacy_deletion_marks(api, resolved_rid) or [])
        except (
            ImportError,
            AttributeError,
            KeyError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            sqlite3.Error,
        ) as exc:
            logger.warning("drain deletion_marks legacy ignore run_id=%s: %s", resolved_rid, exc)

        _is_marked = str(row_id) in _legacy_marked
        try:
            _has_override = store.film_modal.get_tmdb_override(run_id=resolved_rid, row_id=str(row_id)) is not None
            # Revue adversaire R3 (defaut 5) : sqlite3.Error n'herite PAS d'OSError.
            _is_marked = _is_marked or bool(
                store.film_modal.is_marked_for_deletion(run_id=resolved_rid, row_id=str(row_id))
            )
        except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
            pass

        # Perceptual
        try:
            perc = store.perceptual.get_perceptual_report(run_id=resolved_rid, row_id=str(row_id))
            if perc:
                perceptual_dict = perc
                # Attach global_score_v2 payload pour le frontend
                gv2_payload = perc.get("global_score_v2_payload")
                if gv2_payload:
                    perceptual_dict["global_score_v2"] = gv2_payload
        except (AttributeError, OSError, TypeError, ValueError):
            pass

        # Probe via quality_reports (metrics)
        try:
            quality = store.quality.get_quality_report(run_id=resolved_rid, row_id=str(row_id))
            if quality and quality.get("metrics"):
                probe_dict = quality.get("metrics")
        except (AttributeError, OSError, TypeError, ValueError):
            pass
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("get_film_full infra error: %s", exc)

    # History timeline
    history = []
    try:
        fid = identity_key_from_dict(row)
        h_res = film_history_support.get_film_history(api, fid)
        if h_res and h_res.get("ok"):
            # AUDIT 2026-06-10 (REAL 2/2) : get_film_history retourne la cle
            # "events" (domain/film_history.py:232), pas "history" -> la timeline
            # du Modal Film etait systematiquement vide.
            history = h_res.get("events") or []
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.debug("history fetch error: %s", exc)

    # Spec 06 §3.3 : filtre des warning_flags par alertes ignorees persistees.
    # Persistance via film_modal.ignored_alerts (cf endpoint library/mark_alert_ignored).
    ignored_codes: List[str] = []
    try:
        if store is not None and hasattr(store, "film_modal"):
            ignored_codes = list(store.film_modal.list_ignored_alerts(str(row_id)))
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        logger.debug("ignored_alerts fetch error: %s", exc)
    if ignored_codes and isinstance(row, dict):
        flags = row.get("warning_flags") or []
        if isinstance(flags, list):
            row = dict(row)
            row["warning_flags"] = [f for f in flags if str(f) not in ignored_codes]
            row["_ignored_alerts"] = list(ignored_codes)

    # Fix R5 bug 2 (verify-r5) : resoudre le chosen tmdb_id AVANT de fetch
    # poster + extras, sinon le Modal Film re-render avec les infos du candidat
    # auto (candidates[0]) au lieu de celui choisi par l'utilisateur via
    # set_film_tmdb_candidate. Le helper _resolve_chosen_tmdb_id applique la
    # priorite canonique : row.chosen_tmdb_id (override) > row.tmdb_id (auto)
    # > candidates[0].tmdb_id (fallback top match).
    candidates = row.get("candidates") or []
    chosen_tmdb_id = _resolve_chosen_tmdb_id(row, candidates)
    tmdb_id = int(chosen_tmdb_id or 0)

    # TMDb poster (taille w500 selon spec 06 §3.1) -> utilise le chosen tmdb_id
    poster_url = _fetch_poster_url(api, tmdb_id, size="w500") if tmdb_id > 0 else None

    # Fix audit 2026-05-25 (v1.5.4) Vague I : garantir UN SEUL candidat marque
    # comme "chosen" pour eviter le bug du double "Choisi" dans le modal film.
    # Cause racine : le frontend utilisait `candidates[0].tmdb_id` comme fallback
    # alors que l'override TMDb stocke peut ne pas etre le premier de la liste.
    # Si plusieurs candidats partageaient le meme tmdb_id (cas degrade), les
    # deux etaient highlightes. On expose desormais un seul `chosen_tmdb_id`
    # canonique cote backend, et on annote chaque candidate avec `chosen: bool`
    # (un seul True garanti). Log warning si etat incoherent detecte.
    if isinstance(row, dict) and chosen_tmdb_id:
        row = dict(row)  # copie defensive (deja peut-etre copiee plus haut)
        row["chosen_tmdb_id"] = int(chosen_tmdb_id)
        # Annoter les candidates : marquer le PREMIER candidat dont tmdb_id
        # matche chosen_tmdb_id (et un seul). Les doublons tmdb_id eventuels
        # voient leur chosen=False -> evite le double "Choisi" cote UI.
        new_candidates: List[Dict[str, Any]] = []
        already_marked = False
        multiple_match_count = 0
        for cand in candidates:
            try:
                cand_tid = int(cand.get("tmdb_id") or 0)
            except (TypeError, ValueError):
                cand_tid = 0
            is_chosen = False
            if not already_marked and cand_tid > 0 and cand_tid == int(chosen_tmdb_id):
                is_chosen = True
                already_marked = True
            elif already_marked and cand_tid > 0 and cand_tid == int(chosen_tmdb_id):
                multiple_match_count += 1
            new_cand = dict(cand)
            new_cand["chosen"] = is_chosen
            new_candidates.append(new_cand)
        if multiple_match_count > 0:
            logger.warning(
                "get_film_full: %d candidat(s) duplique(s) avec tmdb_id=%s pour row_id=%s — un seul marque chosen=True",
                multiple_match_count,
                chosen_tmdb_id,
                row_id,
            )
        row["candidates"] = new_candidates

    # Spec 06 §3.1 : enrichissement runtime + director + overview depuis TMDb
    extras = _fetch_tmdb_extras(api, tmdb_id) if tmdb_id > 0 else {}
    runtime = extras.get("runtime")
    director = extras.get("director")
    overview = extras.get("overview")

    return {
        "ok": True,
        "run_id": resolved_rid,
        "row_id": str(row_id),
        "row": row,
        "probe": probe_dict,
        "perceptual": perceptual_dict,
        "history": history,
        "poster_url": poster_url,
        "tmdb_id": tmdb_id,
        # Spec 06 §3.1 : champs top-level pour le hero du Modal Film
        "runtime": runtime,
        "director": director,
        "overview": overview,
        # R7-12 : etat des corrections manuelles -> actions d'annulation UI.
        "has_tmdb_override": _has_override,
        "is_marked_for_deletion": _is_marked,
    }

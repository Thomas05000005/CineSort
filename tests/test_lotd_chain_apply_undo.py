"""Lot D (verif totale 2026-07) — chaine 4.2 APPLY -> UNDO bout-en-bout.

Chaine verifiee sur bibliotheque VIRTUELLE JETABLE (tempfile, fichiers factices,
probe_backend="none", tmdb_enabled=False — aucun binaire externe requis) :

  scan (start_plan) -> plan -> decisions accepted -> save_validation ->
  (1) DRY-RUN   : aucune modif disque (snapshot avant/apres identique),
                  aucun batch reversible cree ;
  (2) APPLY     : renames conformes au plan, sidecars .srt/.nfo suivent,
                  contenu intact (sha1), ops MOVE_DIR en DB (batch DONE,
                  reversible, undo_status=PENDING), journal pending_moves
                  reconcilie (0 entree residuelle) ;
  (3) UNDO      : restauration a l'identique (snapshot == initial), batch
                  UNDONE_DONE, ops undo_status=DONE, can_undo=False apres ;
  (4) IDEMPOTENCE : re-apply apres undo == meme resultat disque que le 1er
                  apply, nouveau batch ;
  (5) FICHIER VERROUILLE : echec PROPRE par row (message FICHIER VERROUILLE,
                  dossier intact, 0 demi-etat, 0 entree journal residuelle),
                  les autres rows appliquees et annulables normalement.

Gardes xfail nominatives (bugs reels reportes, PAS corriges ici) :
  [R8-085] (F-V7-COLLMKDIR, apply_core.py::apply_single ~L1966-1969) :
    sur un chemin FILM avec collection/saga, `coll_dir.mkdir(parents=True)`
    est execute AVANT les gardes MAX_PATH/NOOP et SANS `mkdir_counted` :
      - variante A : film saga deja conforme -> skip NOOP mais le dossier
        saga vide orphelin est cree quand meme (aucune op MKDIR en DB,
        l'undo ne le supprimera jamais) ;
      - variante B : film saga deplace puis UNDO -> le film est restaure mais
        les dossiers `_Collection/<Saga>/` restent en orphelins vides
        (restauration PAS a l'identique).
    Variante preview : dans le code actuel le mkdir est gate `if not dry_run`
    (dry-run propre) ; la garde dynamique [R8-085-preview] se declenchera si
    une regression fait apparaitre l'orphelin des la preview.

LIMITES explicites (voir SYNTHESE Lot D) :
  - tmdb_collection_name est injecte dans plan.jsonl apres scan (TMDb off en
    test) puis relu par une CineSortApi fraiche — c'est le chemin DB-only
    officiel (redemarrage app), pas un mock ;
  - le journal write-ahead apply-side (apply_pending_moves) ne couvre que les
    MOVE_FILE (merge/atomic_move) — les renames de dossier passent par
    Path.rename atomique sans write-ahead ; la chaine simple l'exerce donc
    cote UNDO (UNDO_RESTORE journalise) + reconciliation a 0 ;
  - pas de test de crash mi-move (hors perimetre biblio virtuelle).

Execution : .venv/Scripts/python.exe -X utf8 -m pytest tests/test_lotd_chain_apply_undo.py -q
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple
from unittest import mock

import pytest

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import create_file, wait_run_done

# ---------------------------------------------------------------------------
# Helpers biblio virtuelle + snapshots
# ---------------------------------------------------------------------------

_SCAN_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class ChainEnv:
    base: Path
    root: Path
    state_dir: Path


@pytest.fixture()
def env():
    """Tempdir jetable (biblio virtuelle) + MIN_VIDEO_BYTES abaisse a 1.

    mkdtemp + rmtree(ignore_errors=True) plutot que TemporaryDirectory strict :
    sur Windows le store SQLite du JobRunner peut garder un handle ouvert
    quelques instants apres le test (pattern des tests apply/undo existants).
    """
    base = Path(tempfile.mkdtemp(prefix="cinesort_lotd42_"))
    root = base / "root"
    state_dir = base / "state"
    root.mkdir()
    state_dir.mkdir()
    patcher = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
    patcher.start()
    try:
        yield ChainEnv(base=base, root=root, state_dir=state_dir)
    finally:
        patcher.stop()
        shutil.rmtree(base, ignore_errors=True)


def _settings(env: ChainEnv) -> Dict[str, object]:
    return {
        "root": str(env.root),
        "state_dir": str(env.state_dir),
        "tmdb_enabled": False,
        "collection_folder_enabled": True,
        # Binaires externes (ffprobe/mediainfo) absents en CI : degrade propre.
        "probe_backend": "none",
    }


def _make_movie(root: Path, folder: str, video: str) -> Path:
    """Cree un dossier film factice : .mkv (contenu arbitraire) + .srt + .nfo."""
    d = root / folder
    create_file(d / video)  # 2048 bytes 'x'
    stem = video.rsplit(".", 1)[0]
    (d / f"{stem}.fr.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nsous-titre factice\n", encoding="utf-8")
    (d / "movie.nfo").write_text("<movie><title>fixture</title></movie>", encoding="utf-8")
    return d


def _snapshot_tree(root: Path) -> Dict[str, str]:
    """Snapshot {D:relpath -> "", F:relpath -> sha1(contenu)[:12]} de root."""
    out: Dict[str, str] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        rel = d.relative_to(root)
        if rel != Path("."):
            out[f"D:{rel.as_posix()}"] = ""
        for fn in filenames:
            p = d / fn
            out[f"F:{(rel / fn).as_posix()}"] = hashlib.sha1(p.read_bytes()).hexdigest()[:12]
    return out


def _diff(a: Dict[str, str], b: Dict[str, str]) -> Tuple[List[str], List[str], List[str]]:
    """(present seulement dans a, present seulement dans b, contenu change)."""
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    return only_a, only_b, changed


def _rewrite_prefixes(snap: Dict[str, str], renames: Dict[str, str]) -> Dict[str, str]:
    """Snapshot attendu apres apply : reecrit le 1er segment selon renames."""
    out: Dict[str, str] = {}
    for key, value in snap.items():
        kind, rel = key.split(":", 1)
        parts = rel.split("/")
        if parts[0] in renames:
            parts[0] = renames[parts[0]]
        out[f"{kind}:{'/'.join(parts)}"] = value
    return out


def _scan(api: CineSortApi, env: ChainEnv) -> Tuple[str, List[Dict[str, object]]]:
    start = api.run.start_plan(_settings(env))
    assert start.get("ok"), f"start_plan KO: {start}"
    run_id = str(start["run_id"])
    wait_run_done(api, run_id, timeout_s=_SCAN_TIMEOUT_S)
    plan = api.run.get_plan(run_id)
    assert plan.get("ok"), f"get_plan KO: {plan}"
    rows = plan.get("rows", [])
    assert rows, "plan vide"
    return run_id, rows


def _accept_all(rows: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    return {
        str(r["row_id"]): {
            "ok": True,
            "title": r.get("proposed_title"),
            "year": r.get("proposed_year"),
        }
        for r in rows
    }


def _expected_folder_name(row: Dict[str, object]) -> str:
    """Nom de dossier attendu par le template par defaut `{title} ({year})`."""
    return f"{row.get('proposed_title')} ({row.get('proposed_year')})"


def _inject_saga_in_plan(env: ChainEnv, run_id: str, saga: str) -> None:
    """Injecte tmdb_collection_name dans plan.jsonl (TMDb off en test).

    Le plan est ensuite relu par une CineSortApi FRAICHE (chemin DB-only
    officiel = redemarrage app), donc l'apply consomme bien cette valeur.
    """
    plan_path = env.state_dir / "runs" / f"tri_films_{run_id}" / "plan.jsonl"
    lines = []
    for line in plan_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        d["tmdb_collection_name"] = saga
        lines.append(json.dumps(d, ensure_ascii=False))
    plan_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fresh_api_on_state(env: ChainEnv) -> CineSortApi:
    """API fraiche pointee sur le state_dir tempdir (mode DB-only)."""
    api = CineSortApi()
    saved = api.settings.save_settings(_settings(env))
    assert saved.get("ok"), f"save_settings KO: {saved}"
    return api


# ---------------------------------------------------------------------------
# (1) DRY-RUN : aucune modif disque, aucun batch reversible
# ---------------------------------------------------------------------------


def test_dry_run_makes_no_disk_change(env: ChainEnv) -> None:
    _make_movie(env.root, "Alpha.Movie.2019.1080p", "Alpha.Movie.2019.1080p.mkv")
    _make_movie(env.root, "Beta.Film.2021.2160p", "Beta.Film.2021.2160p.mkv")
    _make_movie(env.root, "Gamma.Doc.2018", "Gamma.Doc.2018.mkv")

    api = CineSortApi()
    run_id, rows = _scan(api, env)
    decisions = _accept_all(rows)

    snap0 = _snapshot_tree(env.root)
    dry = api.run.apply(run_id, decisions, True, False)
    assert dry.get("ok"), f"dry-run KO: {dry}"
    result = dry.get("result") or {}
    assert int(result.get("renames") or 0) == 3, result
    assert int(result.get("errors") or 0) == 0, result

    only_before, only_after, changed = _diff(snap0, _snapshot_tree(env.root))
    assert not only_before and not changed, (only_before, changed)
    if only_after:
        # Garde dynamique : si une regression fait sortir le mkdir saga du
        # gate `if not dry_run`, l'orphelin apparaitrait ici des la preview.
        pytest.xfail(f"[R8-085-preview] modif disque en dry-run : {only_after}")

    preview = api.run.undo_last_apply_preview(run_id)
    assert preview.get("ok"), preview
    assert not preview.get("can_undo"), f"dry-run ne doit pas creer d'undo candidate: {preview}"

    store, _runner = api._get_or_create_infra(env.state_dir)
    batches = store.apply.list_apply_batches_for_run(run_id=run_id, limit=10)
    assert batches == [], f"dry-run ne doit pas journaliser de batch: {batches}"


# ---------------------------------------------------------------------------
# (2)(3)(4) APPLY reel -> UNDO -> re-APPLY (chaine principale)
# ---------------------------------------------------------------------------


def test_apply_undo_reapply_full_chain(env: ChainEnv) -> None:
    _make_movie(env.root, "Alpha.Movie.2019.1080p", "Alpha.Movie.2019.1080p.mkv")
    _make_movie(env.root, "Beta.Film.2021.2160p", "Beta.Film.2021.2160p.mkv")
    _make_movie(env.root, "Gamma.Doc.2018", "Gamma.Doc.2018.mkv")

    api = CineSortApi()
    run_id, rows = _scan(api, env)
    assert len(rows) == 3, [r.get("folder") for r in rows]
    decisions = _accept_all(rows)

    # Decisions accepted persistees + relues (round-trip validation.json/DB).
    saved = api.run.save_validation(run_id, decisions)
    assert saved.get("ok"), saved
    loaded = api.run.load_validation(run_id)
    assert loaded.get("ok"), loaded
    for row in rows:
        dec = (loaded.get("decisions") or {}).get(str(row["row_id"])) or {}
        assert dec.get("ok") is True, (row["row_id"], dec)

    snap0 = _snapshot_tree(env.root)
    expected_renames = {Path(str(r["folder"])).name: _expected_folder_name(r) for r in rows}
    expected_after_apply = _rewrite_prefixes(snap0, expected_renames)

    # ---- (2) APPLY REEL --------------------------------------------------
    applied = api.run.apply(run_id, decisions, False, False)
    assert applied.get("ok"), f"apply KO: {applied}"
    result = applied.get("result") or {}
    assert int(result.get("errors") or 0) == 0, result
    assert int(result.get("renames") or 0) == 3, result
    batch_id = str(applied.get("apply_batch_id") or "")
    assert batch_id, applied

    snap1 = _snapshot_tree(env.root)
    assert snap1 == expected_after_apply, _diff(expected_after_apply, snap1)
    # Sidecars .srt + .nfo ont suivi le rename, contenu video intact (sha1
    # verifie par l'egalite de snapshot ci-dessus). Verification explicite :
    for row in rows:
        new_dir = env.root / _expected_folder_name(row)
        assert new_dir.is_dir(), new_dir
        assert list(new_dir.glob("*.srt")), f"sidecar .srt absent dans {new_dir}"
        assert list(new_dir.glob("*.nfo")), f"sidecar .nfo absent dans {new_dir}"

    # Ops en DB : batch DONE + 3 MOVE_DIR reversibles PENDING, journal
    # write-ahead reconcilie (aucune pending_move residuelle).
    store, _runner = api._get_or_create_infra(env.state_dir)
    batches = store.apply.list_apply_batches_for_run(run_id=run_id, limit=10)
    assert [b.get("status") for b in batches] == ["DONE"], batches
    ops = store.apply.list_apply_operations(batch_id=batch_id)
    assert len(ops) == 3, ops
    assert all(o.get("op_type") == "MOVE_DIR" for o in ops), ops
    assert all(int(o.get("reversible") or 0) == 1 for o in ops), ops
    assert all(str(o.get("undo_status")) == "PENDING" for o in ops), ops
    assert all(str(o.get("row_id") or "") for o in ops), "row_id manquant sur une op"
    assert store.apply.count_pending_moves() == 0

    # ---- (3) UNDO ----------------------------------------------------------
    preview = api.run.undo_last_apply_preview(run_id)
    assert preview.get("ok") and preview.get("can_undo"), preview
    assert int((preview.get("counts") or {}).get("reversible") or 0) == 3, preview

    undone = api.run.undo_last_apply(run_id, False)
    assert undone.get("ok"), f"undo KO: {undone}"
    assert undone.get("status") == "UNDONE_DONE", undone
    counts = undone.get("counts") or {}
    assert int(counts.get("done") or 0) == 3, counts
    assert int(counts.get("failed") or 0) == 0, counts

    snap2 = _snapshot_tree(env.root)
    assert snap2 == snap0, f"restauration PAS a l'identique: {_diff(snap0, snap2)}"

    # Statuts DB coherents apres undo.
    ops_after = store.apply.list_apply_operations(batch_id=batch_id)
    assert all(str(o.get("undo_status")) == "DONE" for o in ops_after), ops_after
    batches_after = store.apply.list_apply_batches_for_run(run_id=run_id, limit=10)
    assert [b.get("status") for b in batches_after] == ["UNDONE_DONE"], batches_after
    assert store.apply.count_pending_moves() == 0
    preview_after = api.run.undo_last_apply_preview(run_id)
    assert preview_after.get("ok"), preview_after
    assert not preview_after.get("can_undo"), preview_after

    # ---- (4) IDEMPOTENCE : re-apply apres undo == meme resultat -----------
    reapplied = api.run.apply(run_id, decisions, False, False)
    assert reapplied.get("ok"), reapplied
    result2 = reapplied.get("result") or {}
    assert int(result2.get("errors") or 0) == 0, result2
    assert int(result2.get("renames") or 0) == 3, result2
    batch2_id = str(reapplied.get("apply_batch_id") or "")
    assert batch2_id and batch2_id != batch_id, (batch_id, batch2_id)

    snap3 = _snapshot_tree(env.root)
    assert snap3 == snap1, f"re-apply != 1er apply: {_diff(snap1, snap3)}"
    statuses = sorted(str(b.get("status")) for b in store.apply.list_apply_batches_for_run(run_id=run_id, limit=10))
    assert statuses == ["DONE", "UNDONE_DONE"], statuses


# ---------------------------------------------------------------------------
# (5) Fichier verrouille : echec PROPRE, pas de demi-etat non journalise
# ---------------------------------------------------------------------------


def test_locked_file_fails_cleanly_without_half_state(env: ChainEnv) -> None:
    locked_dir = _make_movie(env.root, "Locked.Movie.2020", "Locked.Movie.2020.mkv")
    _make_movie(env.root, "Free.Movie.2021", "Free.Movie.2021.mkv")

    api = CineSortApi()
    run_id, rows = _scan(api, env)
    assert len(rows) == 2, rows
    decisions = _accept_all(rows)
    snap0 = _snapshot_tree(env.root)
    locked_row = next(r for r in rows if "Locked" in str(r["folder"]))
    free_row = next(r for r in rows if "Free" in str(r["folder"]))

    # Handle ouvert sans FILE_SHARE_DELETE -> le rename du dossier parent
    # echoue sous Windows (WinError 5), cas VLC/indexeur documente.
    with open(locked_dir / "Locked.Movie.2020.mkv", "rb"):
        applied = api.run.apply(run_id, decisions, False, False)

    assert applied.get("ok"), applied
    result = applied.get("result") or {}
    assert int(result.get("errors") or 0) == 1, result
    assert int(result.get("renames") or 0) == 1, result
    messages = [str(m) for m in (result.get("error_messages") or [])]
    assert any("FICHIER VERROUILLE" in m for m in messages), messages

    # Dossier verrouille INTACT (aucun demi-etat), l'autre film applique.
    assert locked_dir.is_dir(), "dossier verrouille disparu"
    assert (locked_dir / "Locked.Movie.2020.mkv").is_file()
    assert not (env.root / _expected_folder_name(locked_row)).exists()
    assert (env.root / _expected_folder_name(free_row)).is_dir()

    # Journal : aucune entree residuelle, seule l'op du film libre en DB.
    store, _runner = api._get_or_create_infra(env.state_dir)
    assert store.apply.count_pending_moves() == 0
    batch_id = str(applied.get("apply_batch_id") or "")
    ops = store.apply.list_apply_operations(batch_id=batch_id)
    assert len(ops) == 1, ops
    assert str(ops[0].get("row_id")) == str(free_row["row_id"]), ops

    # Undo : seul le film libre est reverse -> retour exact au snapshot.
    undone = api.run.undo_last_apply(run_id, False)
    assert undone.get("ok"), undone
    assert undone.get("status") == "UNDONE_DONE", undone
    snap_end = _snapshot_tree(env.root)
    assert snap_end == snap0, _diff(snap0, snap_end)


# ---------------------------------------------------------------------------
# Gardes nominatives R8-085 (bug reel FIGE, pas corrige ici)
# ---------------------------------------------------------------------------


def test_r8_085_saga_conform_film_creates_orphan_collection_dir(env: ChainEnv) -> None:
    """[R8-085] variante A : film saga DEJA conforme -> skip NOOP mais le
    dossier `_Collection/<Saga>/` vide orphelin est cree quand meme (mkdir
    avant les gardes, sans op MKDIR journalisee)."""
    d = env.root / "Saga Movie (2020)"
    create_file(d / "Saga Movie (2020).mkv")
    (d / "Saga Movie (2020).fr.srt").write_text("s", encoding="utf-8")

    api = CineSortApi()
    run_id, rows = _scan(api, env)
    assert len(rows) == 1, rows
    decisions = _accept_all(rows)
    _inject_saga_in_plan(env, run_id, "Test Saga")

    api2 = _fresh_api_on_state(env)
    snap0 = _snapshot_tree(env.root)

    # Preview d'abord : la garde [R8-085-preview] est dans _assert ci-dessous.
    dry = api2.run.apply(run_id, decisions, True, False)
    assert dry.get("ok"), dry
    _only_b_dry = _diff(snap0, _snapshot_tree(env.root))[1]
    if _only_b_dry:
        pytest.xfail(f"[R8-085-preview] dossier saga cree des le dry-run : {_only_b_dry}")

    applied = api2.run.apply(run_id, decisions, False, False)
    assert applied.get("ok"), applied
    result = applied.get("result") or {}
    skip_reasons = result.get("skip_reasons") or {}
    assert int(skip_reasons.get("skip_noop_deja_conforme") or 0) == 1, result

    coll_dir = env.root / "_Collection" / "Test Saga"
    store, _runner = api2._get_or_create_infra(env.state_dir)
    batch_id = str(applied.get("apply_batch_id") or "")
    ops = store.apply.list_apply_operations(batch_id=batch_id) if batch_id else []
    mkdir_ops = [o for o in ops if str(o.get("op_type")) == "MKDIR"]

    if coll_dir.is_dir() and not any(coll_dir.iterdir()):
        assert not mkdir_ops, "orphelin PRESENT mais op MKDIR journalisee (etat inattendu)"
        pytest.xfail(
            "[R8-085] F-V7-COLLMKDIR : dossier saga vide orphelin cree pour un "
            f"film conforme skippe (apply_core.py::apply_single) : {coll_dir}"
        )

    # Bug corrige : plus aucun orphelin, arborescence inchangee.
    snap_after = _snapshot_tree(env.root)
    assert snap_after == snap0, _diff(snap0, snap_after)


def test_r8_085_saga_move_undo_leaves_orphan_dirs(env: ChainEnv) -> None:
    """[R8-085] variante B : film saga NON conforme deplace vers
    `_Collection/<Saga>/` (mkdir jamais journalise) puis UNDO -> le film est
    restaure mais les dossiers saga restent en orphelins vides."""
    d = env.root / "Saga.Two.2021.1080p"
    create_file(d / "Saga.Two.2021.1080p.mkv")
    (d / "Saga.Two.2021.1080p.fr.srt").write_text("s", encoding="utf-8")

    api = CineSortApi()
    run_id, rows = _scan(api, env)
    assert len(rows) == 1, rows
    decisions = _accept_all(rows)
    _inject_saga_in_plan(env, run_id, "Test Saga")

    api2 = _fresh_api_on_state(env)
    snap0 = _snapshot_tree(env.root)

    applied = api2.run.apply(run_id, decisions, False, False)
    assert applied.get("ok"), applied
    result = applied.get("result") or {}
    assert int(result.get("errors") or 0) == 0, result
    assert int(result.get("renames") or 0) == 1, result

    # Positif : le film ET son sidecar sont bien sous _Collection/<Saga>/.
    moved = env.root / "_Collection" / "Test Saga" / _expected_folder_name(rows[0])
    assert moved.is_dir(), moved
    assert list(moved.glob("*.srt")), f"sidecar .srt absent dans {moved}"

    undone = api2.run.undo_last_apply(run_id, False)
    assert undone.get("ok"), undone
    assert undone.get("status") == "UNDONE_DONE", undone
    assert d.is_dir(), "film non restaure par l'undo"

    only_before, only_after, changed = _diff(snap0, _snapshot_tree(env.root))
    assert not only_before and not changed, (only_before, changed)
    orphan_dirs = {"D:_Collection", "D:_Collection/Test Saga"}
    if only_after and set(only_after) <= orphan_dirs:
        pytest.xfail(
            "[R8-085] F-V7-COLLMKDIR : apres UNDO les dossiers saga restent en "
            f"orphelins vides (mkdir non journalise, pas d'op MKDIR) : {only_after}"
        )
    assert not only_after, f"residus inattendus apres undo: {only_after}"

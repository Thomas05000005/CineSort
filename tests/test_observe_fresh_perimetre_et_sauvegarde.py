"""Gardes du GATE FRAICHEUR d'`scripts/observe.py` (`--fresh`).

Trois constats CRITIQUES de perte de donnees sont couverts ici, plus les
constats MAJEURS/MINEURS de la meme famille :

* `--library` n'etait qu'un INTERRUPTEUR : la garde testait
  `"test_library" in str(lib_abs)`, mais les suppressions employaient le
  litteral `'%test_library%'`. Une bibliotheque `test_library_B` etait donc
  detruite quand on demandait `--library .../test_library_A`. Le perimetre
  etait calcule (`scope_marker`) puis JETE.
* la sauvegarde annoncee (`backup auto` dans l'aide de `--fresh`) copiait le
  seul `cinesort.sqlite` alors que tous les profils imposent
  `journal_mode=WAL` : les sidecars `-wal`/`-shm` restaient au sol, donc la
  copie pouvait ne contenir AUCUNE des ecritures recentes.
* les dossiers de run etaient detruits par `shutil.rmtree(...)` sans aucune
  sauvegarde, alors que la meme ligne d'aide promet `backup auto`.
* `sqlite3.connect()` laissait `PRAGMA foreign_keys` a OFF (defaut SQLite) :
  `apply_operations` (pas de colonne `run_id`) n'etait donc PAS emportee par
  la CASCADE posee expres par `021_fk_cascade.sql`, et restait orpheline.
* le declencheur de destruction d'un dossier de run etait une recherche de
  sous-chaine brute (`b"test_library" in chunk.lower()`) sur `ui_log.txt` :
  un simple JOURNAL mentionnant le mot suffisait a faire detruire le run.
* `--dry-run` DESACTIVAIT l'etape destructrice au lieu de la SIMULER : aucun
  moyen de previsualiser ce que `--fresh` allait supprimer.
* `taskkill /F /IM msedgewebview2.exe` tuait TOUS les hotes WebView2 de la
  machine (Teams, Outlook, ...), pas seulement celui du run observe.

Chaque test ci-dessous a ete vu ROUGE sur l'arbre d'avant correctif.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import observe  # noqa: E402

# ---------------------------------------------------------------------------
# Schema minimal : le sous-ensemble des tables reellement traversees par la
# purge (`runs`, tables porteuses de `run_id`, `probe_cache`), plus le couple
# `apply_batches`/`apply_operations` dont la CASCADE est l'objet du constat FK.
# ---------------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE runs (
  run_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  created_ts REAL NOT NULL,
  root TEXT NOT NULL,
  state_dir TEXT NOT NULL,
  config_json TEXT NOT NULL
);
CREATE TABLE apply_batches (
  batch_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  status TEXT NOT NULL
);
CREATE TABLE apply_operations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL,
  op_index INTEGER NOT NULL,
  src_path TEXT NOT NULL,
  FOREIGN KEY (batch_id) REFERENCES apply_batches(batch_id) ON DELETE CASCADE
);
CREATE TABLE probe_cache (
  path TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime REAL NOT NULL,
  tool TEXT NOT NULL,
  PRIMARY KEY (path, size, mtime, tool)
);
"""


def _db_path(localappdata: Path) -> Path:
    return localappdata / "CineSort" / "db" / "cinesort.sqlite"


def _make_db(localappdata: Path, *, wal: bool = False) -> sqlite3.Connection:
    """Cree la DB de state et retourne une connexion OUVERTE.

    En mode `wal=True` la connexion reste ouverte volontairement : c'est la
    seule facon d'avoir des sidecars `-wal`/`-shm` AU SOL au moment de la
    sauvegarde (SQLite checkpointe et les supprime a la fermeture du dernier
    lecteur). C'est exactement l'etat d'une app en cours d'execution.
    """
    db = _db_path(localappdata)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _insert_run(conn: sqlite3.Connection, run_id: str, root: Path) -> None:
    conn.execute(
        "INSERT INTO runs (run_id, status, created_ts, root, state_dir, config_json) VALUES (?,?,?,?,?,?)",
        (run_id, "DONE", 0.0, str(root), "", "{}"),
    )
    conn.commit()


def _run_ids(localappdata: Path) -> set[str]:
    conn = sqlite3.connect(str(_db_path(localappdata)))
    try:
        return {r[0] for r in conn.execute("SELECT run_id FROM runs")}
    finally:
        conn.close()


def _make_run_dir(localappdata: Path, run_id: str, *, plan_src: Path | None, ui_log: str | None) -> Path:
    run_dir = localappdata / "CineSort" / "runs" / f"tri_films_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    if plan_src is not None:
        run_dir.joinpath("plan.jsonl").write_text(
            json.dumps({"row_id": "r1", "src_path": str(plan_src), "dst_path": str(plan_src)}) + "\n",
            encoding="utf-8",
        )
    if ui_log is not None:
        run_dir.joinpath("ui_log.txt").write_text(ui_log, encoding="utf-8")
    return run_dir


@pytest.fixture()
def deux_biblios(tmp_path: Path) -> tuple[Path, Path, Path]:
    """(localappdata, biblio_ciblee, biblio_voisine) — les deux portent le marqueur."""
    cible = tmp_path / "test_library_A"
    voisine = tmp_path / "test_library_B"
    cible.mkdir()
    voisine.mkdir()
    return tmp_path / "LOCALAPPDATA", cible, voisine


# ---------------------------------------------------------------------------
# Scrub — chemins utilisateur (constats 27 et 43)
# ---------------------------------------------------------------------------


def test_scrub_redige_un_chemin_windows_natif() -> None:
    """Un chemin Windows NATIF (un seul antislash) doit etre redige.

    Le motif exigeait DEUX antislashs litteraux, donc ne mordait que sur du
    texte deja echappe. Le tail de `cinesort.log`, lui, est du texte natif.
    """
    ligne = "ouverture C:\\Users\\blanc\\AppData\\Local\\CineSort\\logs\\cinesort.log"
    sortie = observe.scrub(ligne)
    assert "blanc" not in sortie, sortie
    assert "<USER>" in sortie, sortie


def test_scrub_preserve_l_echappement_json() -> None:
    """Sur du JSON, la redaction ne doit pas casser l'echappement.

    Le remplacement posait UN antislash la ou la source en portait DEUX : la
    ligne JSON devenait indecodable (`\\U` n'est pas une echappement JSON).
    """
    ligne = json.dumps({"path": "C:\\Users\\blanc\\AppData"})
    sortie = observe.scrub(ligne)
    assert "blanc" not in sortie, sortie
    assert json.loads(sortie)["path"] == "C:\\Users\\<USER>\\AppData"


# ---------------------------------------------------------------------------
# Perimetre reel de --library (constats 34 et 49)
# ---------------------------------------------------------------------------


def test_reset_epargne_la_biblio_voisine_hors_perimetre(deux_biblios: tuple[Path, Path, Path]) -> None:
    """`--library A` ne doit PAS supprimer les runs de `B`.

    Les deux chemins portent le marqueur `test_library`, donc le litteral
    `LIKE '%test_library%'` les emportait tous les deux.
    """
    localappdata, cible, voisine = deux_biblios
    conn = _make_db(localappdata)
    _insert_run(conn, "RUN_A", cible)
    _insert_run(conn, "RUN_B", voisine)
    conn.close()

    rapport = observe._reset_test_library_state(localappdata, cible)

    assert rapport["ok"] is True, rapport
    assert _run_ids(localappdata) == {"RUN_B"}, "le run de la biblio voisine a ete detruit"


def test_reset_supprime_bien_le_run_de_la_biblio_ciblee(deux_biblios: tuple[Path, Path, Path]) -> None:
    """Non-regression : le comportement NOMINAL ne change pas."""
    localappdata, cible, _voisine = deux_biblios
    conn = _make_db(localappdata)
    _insert_run(conn, "RUN_A", cible / "Movies")
    conn.close()

    rapport = observe._reset_test_library_state(localappdata, cible)

    assert _run_ids(localappdata) == set()
    assert rapport["backup"], rapport


def test_reset_epargne_le_probe_cache_hors_perimetre(deux_biblios: tuple[Path, Path, Path]) -> None:
    """`probe_cache` est purge par chemin : le perimetre doit s'y appliquer aussi."""
    localappdata, cible, voisine = deux_biblios
    conn = _make_db(localappdata)
    conn.executemany(
        "INSERT INTO probe_cache (path, size, mtime, tool) VALUES (?,?,?,?)",
        [
            (str(cible / "a.mkv"), 1, 1.0, "ffprobe"),
            (str(voisine / "b.mkv"), 1, 1.0, "ffprobe"),
        ],
    )
    conn.commit()
    conn.close()

    observe._reset_test_library_state(localappdata, cible)

    conn2 = sqlite3.connect(str(_db_path(localappdata)))
    try:
        restants = [r[0] for r in conn2.execute("SELECT path FROM probe_cache")]
    finally:
        conn2.close()
    assert restants == [str(voisine / "b.mkv")], restants


# ---------------------------------------------------------------------------
# Sauvegarde DB : sidecars WAL (constat 50)
# ---------------------------------------------------------------------------


def test_backup_db_emporte_les_sidecars_wal_et_shm(deux_biblios: tuple[Path, Path, Path]) -> None:
    """La copie doit emporter `-wal` et `-shm`, sinon elle est vide de l'essentiel."""
    localappdata, cible, _voisine = deux_biblios
    conn = _make_db(localappdata, wal=True)
    _insert_run(conn, "RUN_A", cible)
    db = _db_path(localappdata)
    assert db.with_name(db.name + "-wal").is_file(), "pre-condition : sidecar -wal au sol"

    try:
        rapport = observe._reset_test_library_state(localappdata, cible)
    finally:
        conn.close()

    backup = Path(rapport["backup"])
    wal = backup.with_name(backup.name + "-wal")
    shm = backup.with_name(backup.name + "-shm")
    assert wal.is_file(), f"sidecar -wal non sauvegarde ({sorted(p.name for p in backup.parent.iterdir())})"
    assert wal.stat().st_size > 0, "sidecar -wal sauvegarde VIDE"
    assert shm.is_file(), "sidecar -shm non sauvegarde"


# ---------------------------------------------------------------------------
# Sauvegarde des dossiers de run (constat 51)
# ---------------------------------------------------------------------------


def test_les_dossiers_de_run_sont_sauvegardes_avant_destruction(
    deux_biblios: tuple[Path, Path, Path],
) -> None:
    """L'aide de `--fresh` promet `backup auto` : la branche runs/ n'en faisait aucune."""
    localappdata, cible, _voisine = deux_biblios
    conn = _make_db(localappdata)
    _insert_run(conn, "RUN_A", cible)
    conn.close()
    run_dir = _make_run_dir(localappdata, "RUN_A", plan_src=cible / "film.mkv", ui_log="scan ok\n")
    contenu = run_dir.joinpath("plan.jsonl").read_bytes()

    rapport = observe._reset_test_library_state(localappdata, cible)

    assert not run_dir.exists(), "le dossier de run n'a pas ete detruit (pre-condition du test)"
    sauvegarde = rapport.get("runs_backup")
    assert sauvegarde, f"aucune sauvegarde des dossiers de run: {rapport}"
    copie = Path(sauvegarde) / "tri_films_RUN_A" / "plan.jsonl"
    assert copie.is_file(), f"copie absente: {sauvegarde}"
    assert copie.read_bytes() == contenu


# ---------------------------------------------------------------------------
# CASCADE foreign keys (constat 53)
# ---------------------------------------------------------------------------


def test_la_purge_emporte_les_operations_par_cascade(deux_biblios: tuple[Path, Path, Path]) -> None:
    """`apply_operations` n'a pas de `run_id` : sans `foreign_keys=ON`, elle reste orpheline."""
    localappdata, cible, _voisine = deux_biblios
    conn = _make_db(localappdata)
    _insert_run(conn, "RUN_A", cible)
    conn.execute("INSERT INTO apply_batches (batch_id, run_id, status) VALUES (?,?,?)", ("B1", "RUN_A", "DONE"))
    conn.execute(
        "INSERT INTO apply_operations (batch_id, op_index, src_path) VALUES (?,?,?)",
        ("B1", 0, str(cible / "film.mkv")),
    )
    conn.commit()
    conn.close()

    observe._reset_test_library_state(localappdata, cible)

    conn2 = sqlite3.connect(str(_db_path(localappdata)))
    try:
        restantes = conn2.execute("SELECT COUNT(*) FROM apply_operations").fetchone()[0]
        batches = conn2.execute("SELECT COUNT(*) FROM apply_batches").fetchone()[0]
    finally:
        conn2.close()
    assert batches == 0, "pre-condition : le batch porteur de run_id doit partir"
    assert restantes == 0, "lignes apply_operations orphelines : la CASCADE n'a pas joue"


# ---------------------------------------------------------------------------
# Declencheur de destruction d'un dossier de run (constat 54)
# ---------------------------------------------------------------------------


def test_un_journal_qui_mentionne_le_marqueur_ne_declenche_pas_la_destruction(
    deux_biblios: tuple[Path, Path, Path],
) -> None:
    """`ui_log.txt` est un JOURNAL : y lire le mot ne prouve pas que le run porte sur la biblio."""
    localappdata, cible, voisine = deux_biblios
    conn = _make_db(localappdata)
    conn.close()
    orphelin = _make_run_dir(
        localappdata,
        "RUN_ORPHELIN",
        plan_src=voisine / "film.mkv",
        ui_log=f"INFO scan termine pour {voisine}\nINFO comparaison avec test_library\n",
    )

    observe._reset_test_library_state(localappdata, cible)

    assert orphelin.is_dir(), "run hors perimetre detruit sur une simple sous-chaine"


def test_un_run_orphelin_du_perimetre_reste_detruit(deux_biblios: tuple[Path, Path, Path]) -> None:
    """Non-regression : un run SANS ligne DB mais dont le plan vise la biblio part quand meme."""
    localappdata, cible, _voisine = deux_biblios
    conn = _make_db(localappdata)
    conn.close()
    orphelin = _make_run_dir(localappdata, "RUN_ORPH2", plan_src=cible / "film.mkv", ui_log=None)

    rapport = observe._reset_test_library_state(localappdata, cible)

    assert not orphelin.exists(), rapport
    assert rapport["runs_deleted"] == 1, rapport


# ---------------------------------------------------------------------------
# --dry-run : SIMULER au lieu de DESACTIVER (constat 56)
# ---------------------------------------------------------------------------


def test_dry_run_simule_la_purge_sans_rien_detruire(deux_biblios: tuple[Path, Path, Path]) -> None:
    localappdata, cible, _voisine = deux_biblios
    conn = _make_db(localappdata)
    _insert_run(conn, "RUN_A", cible)
    conn.close()
    run_dir = _make_run_dir(localappdata, "RUN_A", plan_src=cible / "film.mkv", ui_log=None)

    rapport = observe._reset_test_library_state(localappdata, cible, dry_run=True)

    assert rapport["dry_run"] is True, rapport
    assert _run_ids(localappdata) == {"RUN_A"}, "dry-run a supprime des lignes"
    assert run_dir.is_dir(), "dry-run a supprime un dossier de run"
    assert rapport["would_delete_run_dirs"] == ["tri_films_RUN_A"], rapport
    assert rapport["would_delete_run_ids"] == ["RUN_A"], rapport


def test_main_dry_run_ecrit_le_rapport_de_gate_sans_tuer_de_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--fresh --dry-run` doit ANNONCER la purge, et ne toucher a rien."""
    biblio = tmp_path / "test_library_A"
    biblio.mkdir()
    out = tmp_path / "out"
    appels: list[list[str]] = []

    def _fake_run(cmd, *a, **kw):  # type: ignore[no-untyped-def]
        appels.append(list(cmd))
        return subprocess.CompletedProcess(list(cmd), 0, b"", b"")

    monkeypatch.setattr(observe.subprocess, "run", _fake_run)

    code = observe.main(
        ["--fresh", "--dry-run", "--library", str(biblio), "--output", str(out), "--modes", "dashboard"]
    )

    assert code == 0
    gate = json.loads((out / "freshness_gate.json").read_text(encoding="utf-8"))
    assert gate["dry_run"] is True, gate
    assert not [c for c in appels if c and c[0] == "taskkill"], appels


# ---------------------------------------------------------------------------
# taskkill : cibler le run, pas toute la machine (constat 57)
# ---------------------------------------------------------------------------


def test_le_kill_webview2_cible_des_pid_et_jamais_l_image_globale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`/IM msedgewebview2.exe` tue Teams, Outlook et tout hote WebView2 de la machine."""
    localappdata = tmp_path / "LOCALAPPDATA"
    scope = localappdata / "CineSort"
    scope.mkdir(parents=True)
    appels: list[list[str]] = []

    charge = json.dumps(
        [
            {"ProcessId": 4242, "CommandLine": f'msedgewebview2.exe --user-data-dir="{scope}\\webview2_userdata"'},
            {"ProcessId": 777, "CommandLine": 'msedgewebview2.exe --user-data-dir="C:\\Teams\\wv2"'},
        ]
    )

    def _fake_run(cmd, *a, **kw):  # type: ignore[no-untyped-def]
        appels.append(list(cmd))
        if cmd and "powershell" in str(cmd[0]).lower():
            return subprocess.CompletedProcess(list(cmd), 0, charge, "")
        return subprocess.CompletedProcess(list(cmd), 0, b"", b"")

    monkeypatch.setattr(observe.subprocess, "run", _fake_run)

    observe._kill_residual_processes(localappdata)

    taskkills = [c for c in appels if c and c[0] == "taskkill"]
    assert taskkills, appels
    assert not [c for c in taskkills if "msedgewebview2.exe" in c], (
        "kill par NOM D'IMAGE : tout hote WebView2 de la machine est emporte"
    )
    assert ["taskkill", "/F", "/PID", "4242"] in taskkills, taskkills
    assert not [c for c in taskkills if "777" in c], "un hote WebView2 etranger au run a ete tue"


# ---------------------------------------------------------------------------
# Deux modes de panne SILENCIEUX, signales par une revue automatique sur la PR.
#
# Ils partagent une signature : la fonction rend une reponse d'apparence normale
# la ou elle n'a rien pu mesurer.
#
# 1. `_webview2_pids_in_scope` ne lit JAMAIS `cp.returncode`. Un PowerShell qui
#    echoue sans rien ecrire sur stdout rend donc `([], None)` — soit exactement
#    « aucun hote WebView2, aucune erreur ». Plus rien n'est tue, et rien ne le
#    dit. C'est la RESERVE que ce lot portait deja par ecrit ; elle est levee.
#
# 2. `_run_dir_in_scope` decide du perimetre sur les 256 premiers Kio des
#    journaux. Un `plan.jsonl` plus gros dont le chemin cible n'apparait qu'apres
#    est declare HORS perimetre : le run survit a la purge et ses donnees
#    perimees restent en base. Or `plan.jsonl` est du JSONL — il se lit ligne a
#    ligne, sans troncature et sans surcout, puisqu'on s'arrete au premier
#    chemin qui correspond.
# ---------------------------------------------------------------------------


def test_un_powershell_en_echec_ne_passe_pas_pour_zero_processus(tmp_path: Path, monkeypatch) -> None:
    echec = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="acces refuse")
    monkeypatch.setattr(observe.subprocess, "run", lambda *a, **k: echec)
    pids, erreur = observe._webview2_pids_in_scope(tmp_path)
    assert pids == []
    assert erreur is not None, (
        "PowerShell a echoue et la fonction rend « aucun processus, aucune erreur » : "
        "plus aucun hote WebView2 n'est tue et rien ne le signale."
    )


def test_un_plan_volumineux_reste_dans_le_perimetre(tmp_path: Path) -> None:
    run_dir = tmp_path / "tri_films_RUN_X"
    run_dir.mkdir(parents=True)
    cible = (tmp_path / "test_library_A").as_posix().lower()
    bourrage = json.dumps({"src_path": "D:/ailleurs/" + "x" * 200}) + "\n"
    with (run_dir / "plan.jsonl").open("w", encoding="utf-8") as fh:
        for _ in range(400 * 1024 // len(bourrage) + 1):
            fh.write(bourrage)
        fh.write(json.dumps({"src_path": cible + "/Film (2020)/f.mkv"}) + "\n")
    taille = (run_dir / "plan.jsonl").stat().st_size
    assert taille > 256 * 1024, f"le plan doit depasser la troncature ({taille} o)"
    assert observe._run_dir_in_scope(run_dir, cible), (
        "le chemin cible figure dans le plan mais au-dela des 256 premiers Kio : "
        "le run est declare hors perimetre et sa purge n'a jamais lieu."
    )

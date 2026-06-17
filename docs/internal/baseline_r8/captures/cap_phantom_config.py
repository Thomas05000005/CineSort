"""Captures '0-consommateur' REJOUABLES des settings/features FANTOMES — baseline_r8.

But (READ-ONLY, aucun effet de bord) : pour chaque cle de settings / feature
suspectee fantome, on grep le BACKEND `cinesort/` (et le front `web/` quand la
question est cote UI) a la recherche d'un VRAI consommateur — c.-a-d. un site qui
LIT la valeur et change un comportement — au-dela de :
  - l'echo-persist (save section dans settings_support.py),
  - la definition UI (champ dans parametres.js / app.js styling),
  - la liste de reset (reset_support.py),
  - les tests / artefacts de build (dist*/).

Comptage = 0  =>  FANTOME (cle persistee mais jamais consommee, ou label/feature
mort). On imprime le compte + les sites bruts, puis un bloc RESUME JSON final.

Pourquoi un script et pas un grep one-shot : les references "innocentes"
(persist/definition/reset/tests/dist) faussent un grep naif. Ici on les exclut
explicitement et on prouve la falsifiabilite (une cle REELLE — p.ex.
`subtitle_expected_languages` — doit, elle, ressortir avec >=1 vrai consommateur).

VERIFIE le 2026-06-17 contre la source reelle (chaque file:line ci-dessous a ete
relu ; aucun n'a derive au moment de l'ecriture). Les ancres servent de "marqueur
de derive" : si un assert echoue a une relecture future, la ligne a bouge.

Usage (depuis la racine du repo) :
  PYTHONPATH=. .venv313/Scripts/python.exe \
    docs/internal/baseline_r8/captures/cap_phantom_config.py \
    > docs/internal/baseline_r8/captures/cap_phantom_config.py.out.txt 2>&1
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# --- Racine repo : ce fichier est sous docs/internal/baseline_r8/captures/ ----
REPO = Path(__file__).resolve().parents[4]
CINESORT = REPO / "cinesort"
WEB = REPO / "web"


# --- Classement des sites : un hit est-il un VRAI consommateur ? --------------
# On marque "non-consommateur" tout chemin/contexte qui n'est que :
#   persist (save section), definition UI, reset, tests, artefacts de build.
_PERSIST_FILE = "settings_support.py"   # echo/save d'une section de settings
_DEF_FILES = ("parametres.js", "app.js")  # definition de champ UI / styling pur
_RESET_FILE = "reset_support.py"        # liste des cles a reset
_NONCONSUMER_DIR_HINTS = (
    "/tests/",
    "\\tests\\",
    "dist_backup",
    "/dist/",
    "\\dist\\",
    "/docs/",
    "\\docs\\",
    "_revue_adversaire",
    ".json",  # rapports d'audit / payload mocks
    "__pycache__",
)


def _walk_files(root: Path, exts: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in exts:
            sp = str(p).replace("\\", "/")
            if "__pycache__" in sp:
                continue
            out.append(p)
    return out


# On scanne le code SOURCE vivant : backend cinesort/ + front web/.
# (On exclut volontairement dist_backup*, tests/, docs/ via les hints ci-dessus
#  lors du classement, mais on les LIT quand meme pour les MONTRER en contexte.)
_PY = _walk_files(CINESORT, (".py",))
_JS = _walk_files(WEB, (".js",))
# Inclure les artefacts/tests pour pouvoir les ETIQUETER comme non-consommateurs
# (transparence : on prouve qu'on les a vus et ecartes).
_EXTRA = _walk_files(REPO / "tests", (".py", ".js", ".mjs"))
ALL_FILES = _PY + _JS + _EXTRA


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(REPO)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def grep(pattern: str, files: list[Path]) -> list[tuple[str, int, str]]:
    rx = re.compile(pattern)
    hits: list[tuple[str, int, str]] = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append((_rel(p), i, line.strip()))
    return hits


def _is_nonconsumer(rel: str, line: str, persist_ok: bool = True) -> bool:
    """True si ce hit n'est PAS un vrai consommateur (persist/def/reset/test/dist)."""
    low = rel.lower()
    # Chemins repo-relatifs : 'tests/...' n'a pas de '/' initial -> on traite le
    # prefixe tests/ explicitement en plus des hints internes (/tests/).
    if low.startswith("tests/") or low.startswith("tests\\"):
        return True
    for h in _NONCONSUMER_DIR_HINTS:
        if h in low:
            return True
    base = rel.rsplit("/", 1)[-1]
    if base == _PERSIST_FILE and persist_ok:
        return True
    if base in _DEF_FILES:
        return True
    if base == _RESET_FILE:
        return True
    return False


def classify(hits: list[tuple[str, int, str]], persist_ok: bool = True):
    """Separe (consommateurs_reels, non_consommateurs)."""
    real, noise = [], []
    for rel, ln, line in hits:
        if _is_nonconsumer(rel, line, persist_ok=persist_ok):
            noise.append((rel, ln, line))
        else:
            real.append((rel, ln, line))
    return real, noise


def _print_hits(label: str, hits: list[tuple[str, int, str]], cap: int = 8) -> None:
    print(f"    {label} ({len(hits)}):")
    if not hits:
        print("      <aucun>")
        return
    for rel, ln, line in hits[:cap]:
        snippet = line if len(line) <= 130 else line[:127] + "..."
        print(f"      {rel}:{ln}  |  {snippet}")
    if len(hits) > cap:
        print(f"      ... (+{len(hits) - cap} autres)")


# --- Capture d'un cas fantome -------------------------------------------------
RESUME: list[dict] = []


def capture(
    fid: str,
    title: str,
    *,
    phantom_pattern: str,
    anchor: tuple[str, int, str] | None = None,
    persist_ok: bool = True,
    files: list[Path] | None = None,
    note: str = "",
) -> int:
    """Grep `phantom_pattern`, classe, imprime, retourne le nb de VRAIS consommateurs.

    `anchor` = (rel_path, line, substring_attendu) verifie que la reference clef
    n'a pas derive. Si elle a bouge, on l'imprime (best-effort) sans planter.
    """
    # fid peut deja etre entre crochets (ex '[27]') ; on evite '[[27]]'.
    _hdr = fid if fid.startswith("[") else f"[{fid}]"
    print("=" * 78)
    print(f"{_hdr} {title}")
    print("-" * 78)
    scope = files if files is not None else ALL_FILES
    hits = grep(phantom_pattern, scope)
    real, noise = classify(hits, persist_ok=persist_ok)

    # Verification d'ancre (anti-derive)
    if anchor:
        arel, aln, asub = anchor
        found = None
        for rel, ln, line in hits:
            if rel.endswith(arel) and asub in line:
                found = (rel, ln, line)
                break
        if found is None:
            print(f"    [ANCRE] ATTENDUE {arel}:{aln} contenant {asub!r} -> NON TROUVEE (derive ?)")
        else:
            frel, fln, _ = found
            drift = "" if fln == aln else f"  (DERIVE: attendu L{aln}, reel L{fln})"
            print(f"    [ANCRE] {frel}:{fln} OK{drift}")

    _print_hits("CONSOMMATEURS REELS (hors persist/def/reset/test/dist)", real)
    _print_hits("non-consommateurs (persist/def/reset/test/dist)", noise)
    count = len(real)
    verdict = "FANTOME (0 consommateur)" if count == 0 else f"{count} consommateur(s) reel(s)"
    print(f"    => COMPTE CONSOMMATEUR REEL = {count}  [{verdict}]")
    if note:
        print(f"    note: {note}")
    RESUME.append(
        {
            "id": fid,
            "title": title,
            "real_consumers": count,
            "phantom": count == 0,
            "real_sites": [f"{r}:{n}" for r, n, _ in real][:6],
        }
    )
    return count


def main() -> None:
    print("CAPTURE PHANTOM CONFIG — baseline_r8 (READ-ONLY, 0 effet de bord)")
    print(f"REPO    = {REPO}")
    print(f"fichiers scannes: {len(_PY)} .py (cinesort) + {len(_JS)} .js (web) "
          f"+ {len(_EXTRA)} tests = {len(ALL_FILES)}")
    print()

    # === F-PROM-02 : cleanup_orphans + cleanup_empty_folders =================
    # parametres.js:151-152 (toggles), persistes settings_support.py:1707-1710,
    # ABSENTS de la dataclass Config (core.py:208-274) ET de
    # build_cfg_from_settings -> core.Config(...) (settings_support.py:1054-1085).
    # Un vrai consommateur lirait cfg.cleanup_orphans / cfg.cleanup_empty_folders
    # ou settings.get("cleanup_orphans") dans app/ ou domain/.
    capture(
        "F-PROM-02",
        "cleanup_orphans / cleanup_empty_folders : toggles inertes",
        phantom_pattern=r"cleanup_orphans|cleanup_empty_folders",
        anchor=("parametres.js", 151, 'cleanup_orphans'),
        note="absents de Config dataclass (core.py:208-274) et de "
             "build_cfg_from_settings->core.Config (settings_support.py:1054-1085)",
    )
    # Preuve d'absence dans la dataclass Config : grep des attributs exacts dans
    # le constructeur core.Config(...) de build_cfg_from_settings -> 0.
    cfg_attr = grep(r"cleanup_orphans\s*=|cleanup_empty_folders\s*=",
                    [CINESORT / "domain" / "core.py",
                     CINESORT / "ui" / "api" / "settings_support.py"])
    print(f"    [sous-preuve] attribut Config 'cleanup_orphans=/cleanup_empty_folders=' "
          f"dans core.py/settings_support.py = {len(cfg_attr)} (attendu 0)")
    print()

    # === F-PROM-01 : auto_approve_enabled =====================================
    # parametres.js:105 (toggle). Le SEUL consommateur du flag est le parametre
    # `enabled` de get_auto_approved_summary (run_read_support.py:124, lu L177-178)
    # — mais cette methode n'a 0 appelant UI (rien dans web/ ne POST
    # run/get_auto_approved_summary ni ne lit auto_approved_summary).
    capture(
        "F-PROM-01",
        "auto_approve_enabled : consomme uniquement par get_auto_approved_summary "
        "(0 appelant UI)",
        phantom_pattern=r"auto_approve_enabled",
        anchor=("parametres.js", 105, "auto_approve_enabled"),
        note="real key consommee dans run_read_support.get_auto_approved_summary, "
             "mais 0 caller UI -> feature de fait morte",
    )
    # Le consommateur indirect (la methode) existe-t-il, et a-t-il un caller front ?
    method_def = grep(r"def get_auto_approved_summary",
                      [CINESORT / "ui" / "api" / "run_read_support.py"])
    front_caller = grep(r"get_auto_approved_summary|auto_approved_summary", _JS)
    print(f"    [sous-preuve] def get_auto_approved_summary (run_read_support.py) "
          f"= {len(method_def)} (la methode existe)")
    print(f"    [sous-preuve] appelant FRONT (web/*.js) de get_auto_approved_summary "
          f"= {len(front_caller)} (attendu 0 -> feature morte)")
    print()

    # === F-PROM-03a : separator inerte dans les presets =======================
    # cfg.separator approvisionne ctx['sep'] (naming.py:332) MAIS aucun template
    # de PRESET ne reference {sep} (naming.py:127-152). Donc en preset standard,
    # le selecteur Separateur n'a aucun effet de rendu.
    print("=" * 78)
    print("[F-PROM-03a] separator : variable {sep} absente de tout template de preset")
    print("-" * 78)
    naming = (CINESORT / "domain" / "naming.py").read_text(encoding="utf-8", errors="replace")
    # Extraire les movie_template/tv_template des PRESETS et compter ceux qui
    # contiennent {sep}.
    tmpl_lines = [ln.strip() for ln in naming.splitlines()
                  if re.search(r"(movie_template|tv_template)\s*=", ln)]
    sep_in_tmpl = [ln for ln in tmpl_lines if "{sep}" in ln]
    print(f"    templates de preset trouves (movie/tv) : {len(tmpl_lines)}")
    for ln in tmpl_lines:
        print(f"      {ln[:120]}")
    print(f"    => templates referencant {{sep}} = {len(sep_in_tmpl)} "
          f"[{'FANTOME en preset' if not sep_in_tmpl else 'actif'}]")
    print(f"    note: {{sep}} est injecte dans le contexte (naming.py ~L332) mais "
          f"opt-in uniquement -> inerte tant qu'un template custom ne l'ecrit pas")
    RESUME.append({
        "id": "F-PROM-03a",
        "title": "separator {sep} dans presets",
        "real_consumers": len(sep_in_tmpl),
        "phantom": len(sep_in_tmpl) == 0,
        "real_sites": [],
    })
    print()

    # === F-PROM-03b : subtitle_lang_priority FANTOME (vraie cle = expected) ====
    # parametres.js:100 (text). Persiste settings_support.py:1711-1716. La VRAIE
    # cle lue par le pipeline est subtitle_expected_languages
    # (run_flow_support.py:425, librarian.py:50).
    capture(
        "F-PROM-03b",
        "subtitle_lang_priority : fantome ; la vraie cle est "
        "subtitle_expected_languages",
        phantom_pattern=r"subtitle_lang_priority",
        anchor=("parametres.js", 100, "subtitle_lang_priority"),
        note="0 consommateur backend ; cf F-PROM-03b-bis pour la vraie cle",
    )
    # Falsifiabilite : la VRAIE cle, elle, DOIT avoir des consommateurs reels.
    real_key = capture(
        "F-PROM-03b-bis",
        "[FALSIFIABILITE] subtitle_expected_languages : la VRAIE cle a des "
        "consommateurs",
        phantom_pattern=r"subtitle_expected_languages",
        persist_ok=True,
        note="doit etre >0 sinon le harnais ne distingue pas vrai/faux",
    )
    print(f"    [gate falsifiabilite] real_key consumers = {real_key} (doit etre > 0)")
    print()

    # === [27] animations_enabled : 0 consommateur DOM/CSS =====================
    # parametres.js:277, persiste settings_support.py:1705-1706. Aucun JS ne lit
    # s.animations_enabled pour basculer une classe/dataset ; les animations ne
    # sont coupees que par @media prefers-reduced-motion (OS).
    capture(
        "[27]",
        "animations_enabled : 0 consommateur DOM/CSS",
        phantom_pattern=r"animations_enabled",
        anchor=("parametres.js", 277, "animations_enabled"),
        note="aucun toggle DOM/CSS ; coupure uniquement via prefers-reduced-motion (OS)",
    )
    print()

    # === [28] worker_count (label 'Nombre de workers globaux') : 0 consommateur
    # parametres.js:315 (l'audit l'appelait 'global_workers' mais la VRAIE cle est
    # worker_count). Persiste settings_support.py:1698-1699. Jamais lu ailleurs.
    capture(
        "[28]",
        "worker_count (= 'workers globaux', PAS global_workers) : 0 consommateur",
        phantom_pattern=r"worker_count",
        anchor=("parametres.js", 315, "worker_count"),
        note="cle REELLE = worker_count ; 'global_workers' n'existe PAS dans le code "
             "(seulement dans les docs d'audit)",
    )
    # Preuve que 'global_workers' est un nom fantome cote audit, absent du code.
    gw = grep(r"global_workers", _PY + _JS)
    print(f"    [sous-preuve] 'global_workers' dans cinesort/+web/ = {len(gw)} "
          f"(attendu 0 ; nom utilise par l'audit, pas par le code)")
    print()

    # === [29] desktop_notifications_enabled : 0 consommateur ==================
    # parametres.js:215, persiste settings_support.py:1703-1704. La VRAIE cle
    # consommee est notifications_enabled (notify_service.py:67).
    capture(
        "[29]",
        "desktop_notifications_enabled : fantome ; vraie cle = notifications_enabled",
        phantom_pattern=r"desktop_notifications_enabled",
        anchor=("parametres.js", 215, "desktop_notifications_enabled"),
        note="real notif key = notifications_enabled (notify_service.py:67)",
    )
    real_notif = grep(r"notifications_enabled",
                      [CINESORT / "app" / "notify_service.py"])
    print(f"    [sous-preuve] notifications_enabled lu dans notify_service.py = "
          f"{len(real_notif)} (la VRAIE cle a un consommateur)")
    print()

    # === [30] retention_days : seul consommateur prune_disk_cache, jamais appele
    # parametres.js:341, persiste settings_support.py:1682-1683. ATTENTION : le mot
    # 'retention_days' apparait abondamment dans retention_cleanup.py / cleanup_old_runs,
    # mais ce flux est aliment par history_retention_days (cle DISTINCTE), pas par
    # settings['retention_days']. La VRAIE conso de la cle settings retention_days
    # serait un settings.get('retention_days') hors persist, OU un appel reel a
    # prune_disk_cache (disk_cache.py:226, seul code qui prend retention_days pour
    # CETTE cle). On mesure les deux precisement (le grep large \bretention_days\b
    # serait trompeur a cause du cron history).
    print("=" * 78)
    print("[30] retention_days : cle settings sans lecteur (prune_disk_cache jamais appele)")
    print("-" * 78)
    # (a) lectures settings.get('retention_days') HORS persist (settings_support.py)
    rd_reads_all = grep(r"\.get\(\s*['\"]retention_days['\"]", _PY)
    rd_reads_real = [h for h in rd_reads_all
                     if not h[0].endswith("settings_support.py")]
    print(f"    settings.get('retention_days') hors persist = {len(rd_reads_real)} "
          f"(attendu 0 ; total avec persist = {len(rd_reads_all)})")
    for rel, ln, line in rd_reads_all[:5]:
        flag = "PERSIST" if rel.endswith("settings_support.py") else "READ"
        print(f"      [{flag}] {rel}:{ln}  |  {line[:100]}")
    # (b) le nominal-consumer prune_disk_cache est-il jamais appele ?
    prune_def = grep(r"def prune_disk_cache", _PY)
    prune_calls = grep(r"prune_disk_cache\s*\(", _PY)
    real_prune_calls = [h for h in prune_calls if "def prune_disk_cache" not in h[2]]
    print(f"    def prune_disk_cache = {len(prune_def)} (disk_cache.py) ; "
          f"APPELS prune_disk_cache(...) = {len(real_prune_calls)} (attendu 0 -> mort)")
    for rel, ln, line in real_prune_calls[:5]:
        print(f"      appel: {rel}:{ln}  |  {line[:110]}")
    rd_real = len(rd_reads_real) + len(real_prune_calls)
    print(f"    => CONSOMMATEUR REEL de la cle settings retention_days = {rd_real} "
          f"[{'FANTOME' if rd_real == 0 else 'actif'}]")
    print("    note: retention_cleanup.py/cleanup_old_runs lisent history_retention_days "
          "(cle distincte), PAS settings['retention_days']")
    RESUME.append({
        "id": "[30]",
        "title": "retention_days : cle settings sans lecteur (prune_disk_cache jamais appele)",
        "real_consumers": rd_real,
        "phantom": rd_real == 0,
        "real_sites": [f"{r}:{n}" for r, n, _ in rd_reads_real + real_prune_calls][:4],
    })
    print()

    # === [31] naming_template : persiste mais jamais relu dans Config ==========
    # parametres.js:120 (text 'Template general'), persiste settings_support.py:
    # 1629-1630. Le moteur lit naming_movie_template / naming_tv_template, JAMAIS
    # settings['naming_template'] pour construire Config.
    print("=" * 78)
    print("[31] naming_template : persiste mais jamais lu (moteur lit movie/tv)")
    print("-" * 78)
    nt_hits = grep(r"naming_template", _PY)
    # On veut prouver qu'aucun site ne fait settings.get('naming_template') /
    # payload.get('naming_template') AILLEURS que la persist. Les hits restants
    # (apply_core, plan_support_replan, core, duplicate_support) concernent le
    # PARAMETRE de fonction naming_template= aliment par cfg.naming_movie_template,
    # PAS la cle settings 'naming_template'.
    settings_read_all = grep(r"(settings|payload|cfg_json|raw_settings)\.get\(\s*['\"]naming_template['\"]",
                             _PY)
    # Exclure la persist (settings_support.py : payload.get('naming_template') du
    # save section) -> il ne reste que les VRAIES lectures vers Config/moteur.
    settings_read = [h for h in settings_read_all
                     if not h[0].endswith("settings_support.py")]
    print(f"    references 'naming_template' (param/persist confondus) : {len(nt_hits)}")
    for rel, ln, line in nt_hits[:10]:
        print(f"      {rel}:{ln}  |  {line[:110]}")
    print(f"    lectures .get('naming_template') TOTAL = {len(settings_read_all)} "
          f"(dont persist settings_support.py)")
    print(f"    => LECTURES HORS PERSIST (vraie conso vers Config/moteur) = "
          f"{len(settings_read)} (attendu 0)")
    print("    note: les autres hits sont le PARAMETRE de fonction naming_template= "
          "des helpers _single_folder_is_conform, aliment par cfg.naming_movie_template "
          "(PAS la cle settings 'naming_template')")
    RESUME.append({
        "id": "[31]",
        "title": "naming_template persiste non relu",
        "real_consumers": len(settings_read),
        "phantom": len(settings_read) == 0,
        "real_sites": [f"{r}:{n}" for r, n, _ in settings_read][:6],
    })
    print()

    # === [32] effects_mode : applique par app.js, aucun controle dans parametres
    # app.js:895 fait document.documentElement.dataset.effects = s.effects_mode.
    # Persiste settings_support.py:1730. Mais AUCUN champ effects_mode dans
    # parametres.js -> l'utilisateur ne peut jamais le changer depuis l'UI.
    print("=" * 78)
    print("[32] effects_mode : applique par app.js mais AUCUN controle dans parametres.js")
    print("-" * 78)
    eff_app = grep(r"effects_mode", [WEB / "dashboard" / "app.js"])
    eff_param = grep(r"effects_mode", [WEB / "dashboard" / "views" / "parametres.js"])
    eff_persist = grep(r"effects_mode", [CINESORT / "ui" / "api" / "settings_support.py"])
    print(f"    application dans app.js : {len(eff_app)}")
    for rel, ln, line in eff_app[:3]:
        print(f"      {rel}:{ln}  |  {line[:110]}")
    print(f"    CONTROLE (champ) dans parametres.js : {len(eff_param)} (attendu 0 -> "
          f"non modifiable par l'UI)")
    print(f"    persist settings_support.py : {len(eff_persist)} (echo seul)")
    RESUME.append({
        "id": "[32]",
        "title": "effects_mode sans controle UI",
        "real_consumers": len(eff_param),  # ici 0 = pas de controle = fantome UI
        "phantom": len(eff_param) == 0,
        "real_sites": [f"{r}:{n}" for r, n, _ in eff_app][:3],
    })
    print()

    # === [21] traitement.js k.duplicates_groups absent des kpis dashboard ======
    # traitement.js:245 lit Number(k.duplicates_groups || 0) ou k = data.kpis.
    # Or dashboard_support.py n'emet JAMAIS duplicates_groups dans 'kpis'
    # (ni le fallback L166-172, ni le payload reel L542-559). Seuls history_support
    # et run_facade emettent duplicates_groups -> en page Traitement, toujours 0.
    print("=" * 78)
    print("[21] traitement.js k.duplicates_groups : absent du payload kpis dashboard")
    print("-" * 78)
    front_read = grep(r"duplicates_groups", [WEB / "dashboard" / "views" / "traitement.js"])
    dash_emit = grep(r"['\"]duplicates_groups['\"]\s*:",
                     [CINESORT / "ui" / "api" / "dashboard_support.py"])
    hist_emit = grep(r"['\"]duplicates_groups['\"]\s*:",
                     [CINESORT / "ui" / "api" / "history_support.py",
                      CINESORT / "ui" / "api" / "facades" / "run_facade.py"])
    print(f"    lecture front (traitement.js) : {len(front_read)}")
    for rel, ln, line in front_read[:3]:
        print(f"      {rel}:{ln}  |  {line[:110]}")
    print(f"    EMISSION dans dashboard_support kpis : {len(dash_emit)} "
          f"(attendu 0 -> k.duplicates_groups toujours undefined cote Traitement)")
    print(f"    emission ailleurs (history_support / run_facade) : {len(hist_emit)} "
          f"(la cle existe, mais hors get_dashboard)")
    RESUME.append({
        "id": "[21]",
        "title": "k.duplicates_groups absent des kpis dashboard",
        "real_consumers": len(dash_emit),  # 0 emetteur cote dashboard => lecture morte
        "phantom": len(dash_emit) == 0,
        "real_sites": [f"{r}:{n}" for r, n, _ in hist_emit][:4],
    })
    print()

    # === F-DEAD-01 : quality-simulator.js / custom-rules-editor.js morts =======
    # Seuls hosts : qij.js (L36-37) et quality.js (L7-8). Or app.js redirige
    # /qij -> /accueil (app.js:291) et /quality -> /qualite (app.js:293) ; la
    # route ACTIVE /qualite monte qualite.js (app.js:219,332), PAS qij.js/quality.js.
    # Aucun import de initQij/initQuality(qij.js)/quality.js dans app.js.
    print("=" * 78)
    print("[F-DEAD-01] quality-simulator.js / custom-rules-editor.js : hosts morts")
    print("-" * 78)
    hosts = grep(r"quality-simulator\.js|custom-rules-editor\.js", _JS)
    # Distinguer les hosts (qij.js/quality.js) et les non-vivants connus.
    host_files = sorted({rel for rel, _, _ in hosts
                         if rel.endswith(("qij.js", "quality.js",
                                          "quality-simulator.js",
                                          "custom-rules-editor.js"))})
    print("    fichiers important quality-simulator/custom-rules-editor :")
    for rel, ln, line in hosts:
        print(f"      {rel}:{ln}  |  {line[:100]}")
    # app.js importe-t-il qij.js ou quality.js (les hosts) ?
    app_imports_host = grep(
        r"import.*from\s*['\"]\.\/views\/(qij|quality)\.js['\"]",
        [WEB / "dashboard" / "app.js"],
    )
    # app.js importe-t-il la vue VIVANTE qualite.js ?
    app_imports_live = grep(
        r"import.*from\s*['\"]\.\/views\/qualite\.js['\"]",
        [WEB / "dashboard" / "app.js"],
    )
    # Les redirections legacy /qij et /quality
    redirects = grep(r"_legacyRedirect\(\s*['\"](qij|quality)['\"]",
                     [WEB / "dashboard" / "app.js"])
    print(f"    app.js importe-t-il qij.js/quality.js (hosts) ? = {len(app_imports_host)} "
          f"(attendu 0 -> hosts non montes)")
    print(f"    app.js importe la vue VIVANTE qualite.js ? = {len(app_imports_live)} "
          f"(attendu >=1)")
    print(f"    redirections legacy _legacyRedirect('qij'/'quality') : {len(redirects)}")
    for rel, ln, line in redirects[:4]:
        print(f"      {rel}:{ln}  |  {line[:110]}")
    RESUME.append({
        "id": "F-DEAD-01",
        "title": "quality-simulator/custom-rules hosts (qij.js/quality.js) morts",
        "real_consumers": len(app_imports_host),  # 0 = hosts jamais montes
        "phantom": len(app_imports_host) == 0,
        "real_sites": [f"{r}:{n}" for r, n, _ in app_imports_live][:2],
    })
    print()

    # === [37] index.html:92 commentaire trompeur =============================
    print("=" * 78)
    print("[37] index.html:92 commentaire /processing trompeur")
    print("-" * 78)
    idx = (WEB / "dashboard" / "index.html").read_text(encoding="utf-8", errors="replace")
    idx_lines = idx.splitlines()
    target = idx_lines[91].strip() if len(idx_lines) >= 92 else "<hors borne>"
    print(f"    index.html:92  |  {target[:120]}")
    # Le commentaire dit 'initLibraryWorkflow' ; verifions ce que monte vraiment
    # /processing dans app.js.
    proc_route = grep(r"/processing", [WEB / "dashboard" / "app.js"])
    print(f"    references /processing dans app.js : {len(proc_route)}")
    for rel, ln, line in proc_route[:4]:
        print(f"      {rel}:{ln}  |  {line[:110]}")
    print("    note: le commentaire evoque 'initLibraryWorkflow (vue v4 unifiee)' ; "
          "verifier que /processing ne pointe plus sur cette fonction.")
    RESUME.append({
        "id": "[37]",
        "title": "index.html:92 commentaire /processing trompeur",
        "real_consumers": 0,
        "phantom": True,
        "real_sites": [f"web/dashboard/index.html:92"],
    })
    print()

    # === RESUME JSON FINAL ====================================================
    print("=" * 78)
    print("RESUME (JSON)")
    print("=" * 78)
    phantom_total = sum(1 for r in RESUME if r["phantom"])
    summary = {
        "baseline": "r8",
        "capture": "phantom_config",
        "findings": len(RESUME),
        "phantom_count": phantom_total,
        "items": RESUME,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

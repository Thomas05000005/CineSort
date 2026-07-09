# -*- coding: utf-8 -*-
"""Contrat M3 — cablage settings write->read->effet (verif totale 2026-07, Phase 5).

Ce test permanent garantit que CHAQUE cle canonique du GET settings (extraite
de cinesort/ui/api/settings_support.py par AST, meme technique que
docs/internal/verif_totale_2026_07/scripts_matrices/m3_settings.py) a au moins
UN site de lecture backend consommatrice (settings.get('cle'),
settings['cle'], 'cle' in settings) hors couche persistance/echo, OU figure :

- dans KNOWN_UNWIRED : les violations CONNUES figees par la matrice
  docs/internal/verif_totale_2026_07/matrices/m3_settings.json
  (21 FANTOME + 15 WRITE_ONLY), plus 2 cles hors matrice decouvertes le
  2026-07-08 en reparant la branche literal_default (m3_settings.py ne
  gerait pas l'AnnAssign de _LITERAL_DEFAULTS ; ce test le gere).
  Cette liste ne peut que RETRECIR (ref Phase 5 PLAN_VERIF_TOTALE.md) :
  si une entree n'est plus violee, le test echoue pour forcer son retrait.
- dans INDIRECTIONS : cablages reels invisibles au scan mecanique,
  documentes avec preuve fichier:ligne (verdicts CABLEE "special" du JSON).

Toute NOUVELLE cle canonique sans lecteur backend echoue ce test : soit on
cable un consommateur, soit on documente l'indirection, soit on assume la
dette en l'ajoutant a KNOWN_UNWIRED (a eviter).

Statique et rapide : aucune app lancee, aucun reseau, aucune DB.
Modele du pattern borne : tests/test_refactor_84_progress_v77.py.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_SUPPORT = REPO_ROOT / "cinesort" / "ui" / "api" / "settings_support.py"
SETTINGS_SUPPORT_REL = "cinesort/ui/api/settings_support.py"

# ---------------------------------------------------------------------------
# Violations CONNUES, figees depuis matrices/m3_settings.json (2026-07-08).
# Cle -> verdict + justification. LISTE EN RETRECISSEMENT UNIQUEMENT :
# cabler une cle => retirer son entree ici (le test l'exige).
# ---------------------------------------------------------------------------
KNOWN_UNWIRED: Dict[str, str] = {
    # --- FANTOME (21) : ni UI ni lecture backend hors persistance ---
    "_has_email_smtp_password": "FANTOME - meta GET (derivee backend) jamais affichee par l'UI",
    "_has_jellyfin_api_key": "FANTOME - meta GET (derivee backend) jamais affichee par l'UI",
    "_has_omdb_api_key": "FANTOME - meta GET (derivee backend) jamais affichee par l'UI",
    "_has_plex_token": "FANTOME - meta GET (derivee backend) jamais affichee par l'UI",
    "_has_radarr_api_key": "FANTOME - meta GET (derivee backend) jamais affichee par l'UI",
    "_has_rest_api_token": "FANTOME - meta GET (derivee backend) jamais affichee par l'UI",
    "auto_quarantine_corrupted": "FANTOME - default + save + reset list mais aucun consommateur ni champ UI (feature M-2 jamais cablee)",
    "email_smtp_password_protection": "FANTOME - meta GET jamais affichee par l'UI",
    "email_smtp_password_warning": "FANTOME - meta GET jamais affichee par l'UI",
    "jellyfin_key_protection": "FANTOME - meta GET jamais affichee par l'UI",
    "jellyfin_key_warning": "FANTOME - meta GET jamais affichee par l'UI",
    "omdb_key_protection": "FANTOME - meta GET jamais affichee par l'UI",
    "omdb_key_warning": "FANTOME - meta GET jamais affichee par l'UI",
    "plex_token_protection": "FANTOME - meta GET jamais affichee par l'UI",
    "plex_token_warning": "FANTOME - meta GET jamais affichee par l'UI",
    "radarr_key_protection": "FANTOME - meta GET jamais affichee par l'UI",
    "radarr_key_warning": "FANTOME - meta GET jamais affichee par l'UI",
    "root_example": "FANTOME - exemple onboarding, aucun lecteur",
    "state_dir_example": "FANTOME - exemple onboarding, aucun lecteur",
    "tmdb_key_protection": "FANTOME - meta GET jamais affichee par l'UI",
    "tmdb_key_warning": "FANTOME - meta GET jamais affichee par l'UI",
    # --- WRITE_ONLY (15) : UI ecrit/affiche, aucune lecture backend hors persistance ---
    "animation_level": "WRITE_ONLY - effet purement client-side (app.js:900 applique le niveau d'animation)",
    "auto_approve_enabled": "WRITE_ONLY - toggle parametres.js:105, aucune logique d'auto-approbation ne lit la cle dans cinesort/",
    "auto_approve_threshold": "WRITE_ONLY - seuil parametres.js:106 jamais lu (get_auto_approved_summary n'applique rien)",
    "cleanup_empty_folders": "WRITE_ONLY - toggle parametres.js:155, aucun lecteur backend",
    "cleanup_orphans": "WRITE_ONLY - toggle parametres.js:154, aucun lecteur backend",
    "dry_run_apply": "WRITE_ONLY - toggle dry-run cote UI (traitement.js) ; le backend lit le flag dry_run du payload run/apply, pas ce setting",
    "effect_speed": "WRITE_ONLY - effet client-side (variables CSS d'animation)",
    "excluded_patterns": "WRITE_ONLY - multi-path parametres.js:52, aucun lecteur backend",
    "expert_mode": "WRITE_ONLY - effet client-side (parametres.js:3337 classList 'is-expert')",
    "glow_intensity": "WRITE_ONLY - effet client-side (variables CSS)",
    "light_intensity": "WRITE_ONLY - effet client-side (variables CSS)",
    "notifications_enabled": "WRITE_ONLY - R8-069 : le gate desktop lit desktop_notifications_enabled, ce toggle n'a plus aucun lecteur",
    "onboarding_completed": "WRITE_ONLY - toggle parametres.js:328 mais AUCUN lecteur (ni wizard ni backend)",
    "retention_days": "WRITE_ONLY - persiste mais aucun lecteur backend",
    "theme": "WRITE_ONLY - effet client-side (app.js:899 document.body.dataset.theme)",
    # --- HORS matrice JSON (2) : _LITERAL_DEFAULTS est un AnnAssign que
    # m3_settings.py ne parsait pas (branche literal_default morte). Ce test
    # parse aussi AnnAssign et a decouvert 2 defaults sans AUCUN lecteur :
    "update_check_channel": "FANTOME (hors matrice, 2026-07-08) - default 'stable' (settings_support.py:811) + reset list, aucun lecteur ni champ UI",
    "update_last_check_ts": "FANTOME (hors matrice, 2026-07-08) - default 0.0 (settings_support.py:812), ECRIT par cinesort_api.py:1007 mais jamais lu",
}

# ---------------------------------------------------------------------------
# INDIRECTIONS documentees : cablage REEL prouve, invisible au scan mecanique
# (verdicts CABLEE/READ_ONLY "special" de m3_settings.json). Si la cle gagne
# une lecture directe, l'entree devient inutile et doit etre retiree.
# ---------------------------------------------------------------------------
INDIRECTIONS: Dict[str, str] = {
    "file_extensions": "CABLEE special - jamais lu tel quel : miroir vers video_exts au save "
                       "(_save_section_sources settings_support.py) ; video_exts est lu par build_cfg_from_settings",
    "remember_key": "CABLEE special - lu par write_settings (couche persistance settings_support.py:608,614) : "
                    "gate la persistance DPAPI de tmdb_api_key -> effet reel",
    "_has_tmdb_api_key": "CABLEE meta GET - generee backend, consommee par l'UI (accueil.js:821) ; "
                         "aucune lecture backend attendue",
    "notifications_scan_triggered": "READ_ONLY indirect - lu via notify_service._SETTING_KEYS (notify_service.py:25-31) "
                                    "-> self._settings.get(key, True) (notify_service.py:84)",
    "notifications_scan_done": "CABLEE indirect - lu via notify_service._SETTING_KEYS -> .get(key, True)",
    "notifications_apply_done": "CABLEE indirect - lu via notify_service._SETTING_KEYS -> .get(key, True)",
    "notifications_undo_done": "CABLEE indirect - lu via notify_service._SETTING_KEYS -> .get(key, True)",
    "notifications_errors": "CABLEE indirect - lu via notify_service._SETTING_KEYS -> .get(key, True)",
}

# Fonctions de settings_support.py dont les lectures BRANCHENT un comportement
# (meme set que m3_settings.py CONSUMER_FUNCS). Toute autre fonction de ce
# fichier = couche persistance/echo, ses lectures ne comptent pas.
CONSUMER_FUNCS = frozenset({
    "build_cfg_from_settings", "build_cfg_from_run_row",
    "resolve_effective_scan_max_workers", "get_scan_max_workers_payload",
    "get_advanced_pragma_settings_payload",
    "resolve_payload_state_dir", "resolve_root_from_payload", "resolve_roots_from_payload",
    "test_tmdb_key", "test_jellyfin_connection",
})


# ---------------------------------------------------------------------------
# 1. Extraction AST des cles canoniques (technique de m3_settings.py)
# ---------------------------------------------------------------------------

def _const_str(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _extract_canonical_keys() -> Tuple[Dict[str, List[str]], Dict[str, Tuple[int, int]]]:
    """Cles du GET settings + ranges des fonctions top-level du module."""
    src = SETTINGS_SUPPORT.read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    keys: Dict[str, List[str]] = {}
    func_ranges: Dict[str, Tuple[int, int]] = {}
    funcs: Dict[str, ast.FunctionDef] = {}
    secret_fields: List[str] = []

    def add(key: Optional[str], provenance: str, line: int) -> None:
        if not key or key.startswith("_orig_"):
            return
        keys.setdefault(key, []).append(f"{provenance}@settings_support.py:{line}")

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            funcs[node.name] = node
            func_ranges[node.name] = (node.lineno, node.end_lineno or node.lineno)
            continue
        # _LITERAL_DEFAULTS est un AnnAssign (annote Tuple[...]) : couvrir les
        # deux formes (m3_settings.py ne couvrait qu'ast.Assign -> branche morte).
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        for tgt in targets:
            if not isinstance(tgt, ast.Name):
                continue
            if tgt.id == "_LITERAL_DEFAULTS":
                for elt in getattr(node.value, "elts", []):
                    if isinstance(elt, ast.Tuple) and elt.elts:
                        add(_const_str(elt.elts[0]), "literal_default", elt.lineno)
            elif tgt.id == "_SECRET_FIELDS":
                for elt in getattr(node.value, "elts", []):
                    s = _const_str(elt)
                    if s:
                        secret_fields.append(s)

    def scan_func(name: str, receivers: Tuple[str, ...],
                  take_setdefault: bool = False, take_return_dict: bool = False,
                  take_meta_strings: bool = False) -> None:
        fn = funcs.get(name)
        if fn is None:
            return
        for node in ast.walk(fn):
            if take_setdefault and isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Attribute) and f.attr == "setdefault" and node.args:
                    add(_const_str(node.args[0]), name, node.lineno)
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if (isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name)
                            and tgt.value.id in receivers):
                        add(_const_str(tgt.slice), name, node.lineno)
            if take_return_dict and isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                for kn in node.value.keys:
                    k = _const_str(kn) if kn is not None else None
                    if k:
                        add(k, name, kn.lineno)  # type: ignore[union-attr]
            if take_meta_strings and isinstance(node, ast.Constant) and isinstance(node.value, str):
                if re.fullmatch(r"[a-z0-9_]+(_protection|_warning)", node.value):
                    add(node.value, name, node.lineno)

    scan_func("apply_settings_defaults", ("payload",), take_setdefault=True)
    scan_func("read_settings", ("data",), take_meta_strings=True)
    for fname in sorted(funcs):
        if fname.startswith("_save_section_"):
            scan_func(fname, ("out",), take_return_dict=True)
    scan_func("_apply_naming_preset", ("to_save",))
    scan_func("_apply_tmdb_key_persistence", ("to_save",))
    scan_func("_apply_jellyfin_key_persistence", ("to_save",))
    scan_func("_save_settings_payload_locked", ("to_save",))
    scan_func("set_scan_max_workers_payload", ("data",))
    scan_func("set_advanced_pragma_settings_payload", ("data",))

    mask_fn = funcs.get("_mask_secrets")
    mask_line = mask_fn.lineno if mask_fn else 0
    for f in secret_fields:
        add(f, "secret_field", mask_line)
        add(f"_has_{f}", "mask_secrets_meta", mask_line)

    return keys, func_ranges


# ---------------------------------------------------------------------------
# 2. Scan des lectures backend consommatrices (cle QUOTEE, hors commentaires)
# ---------------------------------------------------------------------------

def _strip_line_comment(line: str) -> str:
    quote = None
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        else:
            if c in ("'", '"'):
                quote = c
            elif c == "#":
                return line[:i]
        i += 1
    return line


def _read_context(line: str, m: "re.Match[str]") -> Optional[str]:
    """Contexte de lecture (read_get / read_subscript / read_membership) ou None."""
    before = line[: m.start()]
    after = line[m.end():]
    if re.search(r"\.get\(\s*$", before):
        return "read_get"
    if re.search(r"\.pop\(\s*$", before) or re.search(r"\.setdefault\(\s*$", before):
        return None  # ecriture
    if re.search(r"\[\s*$", before):
        m2 = re.match(r"\s*\]\s*(=[^=])?", after)
        if m2 and m2.group(1):
            return None  # write_subscript
        return "read_subscript"
    if re.match(r"\s*:", after):
        return None  # dict_key
    if re.match(r"\s+in\s", after) or re.search(r"\bin\s+$", before):
        return "read_membership"
    return None


def _scan_consumer_reads(all_keys: List[str],
                         support_ranges: Dict[str, Tuple[int, int]]) -> Dict[str, List[str]]:
    """Sites de lecture backend hors persistance/echo, par cle canonique."""
    quoted_re = re.compile(r"[\"'](" + "|".join(re.escape(k) for k in all_keys) + r")[\"']")
    reads: Dict[str, List[str]] = {k: [] for k in all_keys}

    def support_func_for(line_no: int) -> Optional[str]:
        for name, (a, b) in support_ranges.items():
            if a <= line_no <= b:
                return name
        return None

    files = [p for p in sorted((REPO_ROOT / "cinesort").rglob("*.py"))
             if "__pycache__" not in p.parts]
    files.append(REPO_ROOT / "app.py")
    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        is_support = rel == SETTINGS_SUPPORT_REL
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1")
        if quoted_re.search(text) is None:
            continue
        for ln, raw in enumerate(text.splitlines(), 1):
            if raw.lstrip().startswith("#"):
                continue
            line = _strip_line_comment(raw)
            for m in quoted_re.finditer(line):
                ctx = _read_context(line, m)
                if ctx is None:
                    continue
                if is_support and support_func_for(ln) not in CONSUMER_FUNCS:
                    continue  # couche persistance/echo de settings_support.py
                reads[m.group(1)].append(f"{rel}:{ln} ({ctx})")
    return reads


class SettingsContractTests(unittest.TestCase):
    """Contrat M3 : chaque cle canonique settings a un lecteur backend reel."""

    keys: Dict[str, List[str]] = {}
    reads: Dict[str, List[str]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        cls.keys, func_ranges = _extract_canonical_keys()
        cls.reads = _scan_consumer_reads(sorted(cls.keys), func_ranges)

    def test_extraction_is_sane(self) -> None:
        """Garde anti-silence : si l'extracteur casse, on le voit tout de suite."""
        self.assertGreaterEqual(
            len(self.keys), 140,
            msg=(
                f"Extraction des cles canoniques suspecte : {len(self.keys)} cles "
                f"(attendu >= 140, la matrice M3 2026-07 en listait 160). "
                f"settings_support.py a-t-il ete refactore (_LITERAL_DEFAULTS, "
                f"apply_settings_defaults, _save_section_*) ? Adapter l'extracteur "
                f"de ce test comme scripts_matrices/m3_settings.py."
            ),
        )

    def test_lists_are_disjoint_and_canonical(self) -> None:
        overlap = set(KNOWN_UNWIRED) & set(INDIRECTIONS)
        self.assertEqual(
            overlap, set(),
            msg=f"Cles a la fois KNOWN_UNWIRED et INDIRECTIONS : {sorted(overlap)}",
        )

    def test_every_canonical_key_has_backend_reader(self) -> None:
        """NOUVELLE violation = cle canonique sans lecteur backend ni exemption."""
        violations = []
        for key in sorted(self.keys):
            if key in KNOWN_UNWIRED or key in INDIRECTIONS:
                continue
            if not self.reads.get(key):
                prov = "; ".join(self.keys[key][:3])
                violations.append(f"  - {key!r} (canonique via {prov})")
        self.assertEqual(
            violations, [],
            msg=(
                f"{len(violations)} cle(s) canonique(s) du GET settings SANS lecture "
                f"backend consommatrice (settings.get('cle') & co dans cinesort/, hors "
                f"couche persistance/echo de settings_support.py) :\n"
                + "\n".join(violations)
                + "\n\nComment corriger : cabler un consommateur backend reel de la cle ; "
                  "ou, si le cablage est indirect (table de mapping, endpoint dedie, "
                  "miroir vers une autre cle), le documenter avec preuve fichier:ligne "
                  "dans INDIRECTIONS ; en dernier recours, assumer la dette dans "
                  "KNOWN_UNWIRED (deconseille : la liste doit retrecir, pas grossir). "
                  "Ref : docs/internal/verif_totale_2026_07/matrices/m3_settings.json."
            ),
        )

    def test_known_unwired_entries_are_still_violations(self) -> None:
        """Entree KNOWN perimee = a retirer (la liste ne peut que retrecir)."""
        stale = []
        for key in sorted(KNOWN_UNWIRED):
            if key not in self.keys:
                stale.append(f"  - {key!r} : n'est PLUS une cle canonique du GET settings")
            elif self.reads.get(key):
                stale.append(
                    f"  - {key!r} : a maintenant un lecteur backend "
                    f"({self.reads[key][0]}) -> la cle est cablee"
                )
        self.assertEqual(
            stale, [],
            msg=(
                f"{len(stale)} entree(s) KNOWN_UNWIRED perimee(s) :\n" + "\n".join(stale)
                + "\n\nComment corriger : retirer ces entrees de KNOWN_UNWIRED dans "
                  "tests/test_contract_settings.py (Phase 5 PLAN_VERIF_TOTALE : la "
                  "liste des violations connues ne peut que retrecir)."
            ),
        )

    def test_indirections_entries_are_still_needed(self) -> None:
        """Indirection perimee (cle disparue ou lecture directe apparue) = a retirer."""
        stale = []
        for key in sorted(INDIRECTIONS):
            if key not in self.keys:
                stale.append(f"  - {key!r} : n'est plus une cle canonique du GET settings")
            elif self.reads.get(key):
                stale.append(
                    f"  - {key!r} : a maintenant une lecture directe "
                    f"({self.reads[key][0]}), l'indirection documentee est inutile"
                )
        self.assertEqual(
            stale, [],
            msg=(
                f"{len(stale)} entree(s) INDIRECTIONS perimee(s) :\n" + "\n".join(stale)
                + "\n\nComment corriger : retirer ces entrees d'INDIRECTIONS dans "
                  "tests/test_contract_settings.py."
            ),
        )


if __name__ == "__main__":
    unittest.main()

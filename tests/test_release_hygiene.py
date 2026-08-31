from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

# --- Perimetre du scan PII (cf. test_no_personal_strings_in_repo) ------------

# CE PREFIXE A ETE EXCLU PENDANT DES MOIS, ET LE RAISONNEMENT ETAIT FAUX.
#
# Il disait : `docs/internal/` ne part PAS dans la release — le zip source le
# retire (`SOURCE_EXCLUDE_PATH_PATTERNS`, verifie plus bas) et le bundle
# PyInstaller n'embarque que web/, locales/, presets/ et migrations/. Tout cela
# est VRAI. Et sans rapport : CE DEPOT EST PUBLIC. « Pas dans l'archive » ne
# veut pas dire « pas publie » — chaque fichier de `docs/internal/` est
# consultable sur github.com.
#
# Le test s'appelle « hygiene de RELEASE » et mesurait la frontiere de la
# RELEASE ; la surface d'exposition, elle, est le DEPOT. Un garde peut etre
# correct dans son propre cadre et aveugle a ce qui compte.
#
# Ce que l'exclusion couvrait, mesure le 2026-08-31 avant nettoyage : 103
# marqueurs personnels sur 26 fichiers de `docs/internal/` (67 en separateur
# POSIX, 31 en separateur Windows, 5 chemins UNC du NAS) — plus, dans les deux
# bilans de juin, le JETON REST alors ACTIF de l'utilisateur, publie 72 jours.
# Tout est redige dans le meme lot, et le jeton a ete revoque par rotation.
#
# L'argument « nettoyer detruirait la valeur de preuve du materiau » etait le
# bon reflexe applique a la mauvaise donnee : un nom d'utilisateur n'est pas
# une preuve. La FORME du chemin est conservee, seule l'identite disparait.
RELEASE_EXCLUDED_PREFIXES: tuple[str, ...] = ()

# Dette PII gelee le 2026-08-03, SOLDEE le 2026-08-31. La liste ne pouvait que
# retrecir ; elle est vide. Les douze fichiers portaient un chemin absolu de la
# machine de developpement et ils PARTAIENT dans le zip source : ils etaient
# donc PLUS exposes que ceux de `docs/internal/`, pas moins.
#
# Deux traitements, selon ce que la chaine faisait :
#   - dans une docstring ou un commentaire (la majorite) : le segment de login
#     est remplace, la forme du chemin reste lisible ;
#   - dans une CONSTANTE EXECUTABLE (5 sites : `LIB_ROOT` des deux smoketests,
#     `REPO_ROOT` de m7_db, `_STATE_DB` et `db` de deux scripts de preuve),
#     rediger aurait casse l'outil. Elles derivent desormais de l'environnement
#     (`Path.home()`, `LOCALAPPDATA`, `Path(__file__)`), ce qui vise le MEME
#     emplacement pour l'auteur et fonctionne pour tout le monde.
KNOWN_PII_DEBT_2026_08_03: frozenset[str] = frozenset()


def _git_tracked_files(repo_root: Path) -> list[str] | None:
    """Chemins (relatifs, separes par /) suivis par git, ou None si indisponible."""
    try:
        proc = subprocess.run(  # noqa: S603,S607 - git du PATH, arguments constants
            # `-c safe.directory=*` : sur un runner, le checkout peut appartenir
            # a un autre uid que le process de test ; sans ca git refuse le depot
            # ("dubious ownership") et le test partirait en skip pour rien.
            ["git", "-c", "safe.directory=*", "ls-files", "-z"],
            cwd=repo_root,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]


class ReleaseHygieneTests(unittest.TestCase):
    def test_no_personal_strings_in_repo(self) -> None:
        """Detecte les fuites PII : chemins Windows perso, NAS, base d'etat
        precedente. On evite de chercher le bare "blanc" qui matche aussi
        "bruit blanc" (audio FR), "carte blanche", etc. — on traque les
        vrais marqueurs de leak (chemin Users\\..., adresse mail, NAS path).

        Le scan porte sur les fichiers SUIVIS PAR GIT, pas sur le repertoire de
        travail. C'etait le defaut principal de la version precedente : elle
        lisait aussi les artefacts locaux non versionnes (`.aider.chat.history.md`,
        `_iter8_test/`, `docs/internal/observe/`, `docs/internal/r8/suite_*.txt`
        — tous ignores par .gitignore). Resultat : rouge sur la machine de dev,
        pour des fichiers qui n'existent meme pas sur le runner, sur du contenu
        qui n'a jamais ete publie. Un test d'hygiene de RELEASE doit juger ce
        que le depot publie, pas le bazar local du developpeur.
        """
        repo_root = Path(__file__).resolve().parents[1]
        tracked = _git_tracked_files(repo_root)
        if tracked is None:
            self.skipTest(
                "`git ls-files` indisponible ici : impossible de distinguer le contenu "
                "versionne des artefacts locaux ignores, et scanner le repertoire de "
                "travail produirait des faux positifs. Le test s'execute normalement "
                "en CI (checkout git complet) et sur toute copie de travail git."
            )

        allowed_exts = {".py", ".md", ".txt", ".spec", ".html", ".js", ".css"}
        skip_files = {"_BACKUP_patch_before.txt", "_BACKUP_patch_after.txt", "test_release_hygiene.py"}

        # Le prefixe exempte doit rester exclu du zip source, sinon l'exemption
        # devient un mensonge : on le verifie plutot que de le supposer.
        package_zip = (repo_root / "scripts" / "package_zip.py").read_text(encoding="utf-8")
        self.assertIn(
            '"docs/internal"',
            package_zip,
            "package_zip.py n'exclut plus docs/internal du zip source : "
            "RELEASE_EXCLUDED_PREFIXES n'est plus justifie, il faut nettoyer ces "
            "fichiers ou re-exclure le dossier.",
        )

        # Les fragments sont assembles a runtime pour que le fichier de test
        # lui-meme ne matche pas (sinon ce serait recursif).
        user_login = "".join(["bl", "anc"])
        forbidden_tokens = [
            # Chemin Windows perso: c:\users\<utilisateur>, /users/<utilisateur>/, users\<utilisateur>
            "users\\" + user_login,
            "users/" + user_login,
            "users\\\\" + user_login,
            # Email perso
            user_login + ".thomas@",
            # NAS UNC perso
            "".join(["\\\\", "omv", "\\", "media", "\\", "films"]),
            # Ancien nom du dossier d'etat (leak base v1)
            "".join(["tri_", "films_", "state"]),
        ]

        offenders = []
        for rel in tracked:
            if rel.startswith(RELEASE_EXCLUDED_PREFIXES) or rel in KNOWN_PII_DEBT_2026_08_03:
                continue
            path = repo_root / rel
            if path.suffix.lower() not in allowed_exts:
                continue
            if path.name in skip_files:
                continue
            if not path.is_file():  # entree d'index sans fichier (checkout partiel)
                continue

            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = path.read_text(encoding="latin-1", errors="ignore")

            content_l = content.lower()
            for token in forbidden_tokens:
                if token in content_l:
                    offenders.append(f"{rel}: {token}")
                    break

        if offenders:
            details = "\n".join(offenders[:40])
            self.fail(f"Forbidden strings found:\n{details}")

    def test_docs_use_stable_ui_terminology(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        # CHANGELOG.md retire : c'est de l'historique, la terminologie ancienne
        # ("dashboard") y est legitimement preservee comme trace des versions
        # passees. Le test s'applique aux docs operationnelles courantes.
        critical_docs = [
            repo_root / "README_FR.txt",
            repo_root / "docs" / "releases" / "V7_1_NOTES_FR.md",
        ]
        offenders: list[str] = []
        forbidden_patterns = [
            re.compile(r"\bDashboard\b"),
            re.compile(r"\bdashboard\b"),
            re.compile(r"Workflow clair en 4 etapes"),
        ]

        for path in critical_docs:
            content = path.read_text(encoding="utf-8")
            for pattern in forbidden_patterns:
                for match in pattern.finditer(content):
                    line_no = content.count("\n", 0, match.start()) + 1
                    offenders.append(f"{path.name}:{line_no}: {pattern.pattern}")

        if offenders:
            self.fail("Legacy UI/doc terms found:\n" + "\n".join(offenders))

    def test_readme_contains_official_guided_workflow(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        readme = (repo_root / "README_FR.txt").read_text(encoding="utf-8")
        expected_workflow = (
            "Workflow guide reel:\n"
            "- Reglages\n"
            "- Analyse\n"
            "- Vue du run\n"
            "- Qualite\n"
            "- Cas a revoir\n"
            "- Decisions\n"
            "- Conflits\n"
            "- Execution (dry-run puis reel)\n"
            "- Historique"
        )
        self.assertIn(expected_workflow, readme)
        self.assertIn("Vue du run:", readme)
        self.assertIn("accessible apres Analyse", readme)

    def test_release_docs_keep_official_synthese_wording(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        changelog = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
        release_notes = (repo_root / "docs" / "releases" / "V7_1_NOTES_FR.md").read_text(encoding="utf-8")

        self.assertIn("Synthese qualite", changelog)
        self.assertIn("nouvel onglet **Synthese**", changelog)
        self.assertIn("Ajout onglet UI Synthese", release_notes)

    def test_check_project_covers_preview_scripts_and_new_modules(self) -> None:
        # Audit AUDIT_20260422 T2 : migration vers pytest + ruff sur le projet
        # entier (les excludes sont declares dans pyproject.toml). On garde ici
        # juste les invariants du gate qualite.
        repo_root = Path(__file__).resolve().parents[1]
        check_project = (repo_root / "check_project.bat").read_text(encoding="utf-8")
        compile_helper = repo_root / "scripts" / "check_python_compile.py"
        self.assertTrue(compile_helper.exists())
        self.assertIn("scripts\\check_python_compile.py", check_project)
        self.assertIn("-m ruff check", check_project)
        self.assertIn("-m ruff format --check", check_project)
        self.assertIn("-m pytest", check_project)
        self.assertIn("-m coverage run -m pytest", check_project)
        self.assertIn("-m coverage report", check_project)

    def test_internal_and_design_docs_are_reorganized_out_of_repo_root(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        moved_docs = {
            "VISION_V7_FR.md": "docs/product/VISION_V7_FR.md",
            "V7_1_NOTES_FR.md": "docs/releases/V7_1_NOTES_FR.md",
            "UNDO_7_2_0_A_DESIGN_FR.md": "docs/design/UNDO_7_2_0_A_DESIGN_FR.md",
            "APPLY_ROWS_7E_DESIGN_FR.md": "docs/design/APPLY_ROWS_7E_DESIGN_FR.md",
            "AUDIT_CORRECTIFS_PROJET_FR.txt": "docs/internal/audits/AUDIT_CORRECTIFS_PROJET_FR.txt",
            "CODEX_WORKLOG.md": "docs/internal/worklogs/CODEX_WORKLOG.md",
            "PHASE1_CADRAGE_APP_20260309.txt": "docs/internal/plans/PHASE1_CADRAGE_APP_20260309.txt",
        }

        for old_rel, new_rel in moved_docs.items():
            self.assertFalse((repo_root / old_rel).exists(), old_rel)
            self.assertTrue((repo_root / new_rel).exists(), new_rel)

        self.assertTrue((repo_root / "docs" / "README_DEV.md").exists())

    def test_readme_stays_operator_focused_and_avoids_internal_root_doc_links(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        readme = (repo_root / "README_FR.txt").read_text(encoding="utf-8")
        forbidden_internal_root_refs = [
            "AUDIT_CORRECTIFS_PROJET_FR.txt",
            "CODEX_WORKLOG.md",
            "PHASE1_CADRAGE_APP_20260309.txt",
            "UI_NEXT_REFONTE_WORKLOG.txt",
            "UI_NEXT_ZERO_WORKLOG.txt",
        ]

        for token in forbidden_internal_root_refs:
            self.assertNotIn(token, readme)

        self.assertIn("docs/releases/V7_1_NOTES_FR.md", readme)
        self.assertIn("docs/design/UNDO_7_2_0_A_DESIGN_FR.md", readme)
        self.assertIn("docs/README_DEV.md", readme)

    def test_operator_docs_no_longer_advertise_archived_next_ui(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        readme = (repo_root / "README_FR.txt").read_text(encoding="utf-8")
        dev_readme = (repo_root / "docs" / "README_DEV.md").read_text(encoding="utf-8")

        self.assertNotIn("UI Next = dev only", readme)
        self.assertNotIn("python app.py --ui next", readme)
        self.assertNotIn("CINESORT_UI=next", readme)
        self.assertIn("prototype UI Next est archive", readme)
        self.assertIn("archive dans `docs/internal/archive/ui_next_20260319/`", dev_readme)

    def test_build_docs_scripts_and_spec_agree_on_packaging_strategy(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        dev_readme = (repo_root / "docs" / "README_DEV.md").read_text(encoding="utf-8")
        vision = (repo_root / "docs" / "product" / "VISION_V7_FR.md").read_text(encoding="utf-8")
        build_script = (repo_root / "build_windows.bat").read_text(encoding="utf-8")
        spec = (repo_root / "CineSort.spec").read_text(encoding="utf-8")
        package_zip = (repo_root / "scripts" / "package_zip.py").read_text(encoding="utf-8")

        self.assertIn("dist/CineSort_QA/CineSort.exe", dev_readme)
        self.assertIn("dist/CineSort.exe", dev_readme)
        self.assertIn("QA interne = `onedir`", vision)
        self.assertIn("release utilisateur = `onefile`", vision)
        self.assertIn("dist\\CineSort_QA\\CineSort.exe", build_script)
        self.assertIn("dist\\CineSort.exe", build_script)
        self.assertIn('name="CineSort_QA"', spec)
        self.assertIn('name="CineSort"', spec)
        self.assertIn('parser.add_argument("--qa"', package_zip)
        self.assertIn('build_zip_name("qa"', package_zip)


class SmtplibAvailabilityTests(unittest.TestCase):
    """Verifie que les modules requis par email_report.py ne sont pas exclus du bundle."""

    def test_smtplib_importable(self) -> None:
        import smtplib

        self.assertTrue(hasattr(smtplib, "SMTP"))

    def test_email_mime_importable(self) -> None:
        from email.mime.text import MIMEText

        self.assertTrue(callable(MIMEText))

    def test_ssl_importable(self) -> None:
        import ssl

        self.assertTrue(hasattr(ssl, "create_default_context"))


class RecordApplyOpTests(unittest.TestCase):
    """Tests pour record_apply_op (logging echec + retour boolean)."""

    def test_returns_true_on_success(self) -> None:
        from cinesort.app.apply_core import record_apply_op

        ops = []
        ok = record_apply_op(ops.append, op_type="MOVE", src_path=Path("/a"), dst_path=Path("/b"))
        self.assertTrue(ok)
        self.assertEqual(len(ops), 1)

    def test_returns_true_when_record_op_is_none(self) -> None:
        from cinesort.app.apply_core import record_apply_op

        ok = record_apply_op(None, op_type="MOVE", src_path=Path("/a"), dst_path=Path("/b"))
        self.assertTrue(ok)

    def test_returns_false_on_failure_and_logs(self) -> None:
        import logging

        from cinesort.app.apply_core import record_apply_op

        def _broken_recorder(_data: dict) -> None:
            raise OSError("DB verrouille")

        # Le niveau attendu est WARNING depuis le fix audit 2026-05-25 (v1.5.3, Vague H) :
        # l'echec de journalisation est NON FATAL (le move physique a deja reussi), il ne
        # doit donc pas remonter en ERROR. Le test exigeait encore ERROR et echouait depuis.
        with self.assertLogs("cinesort.app.apply_core", level=logging.WARNING) as cm:
            ok = record_apply_op(_broken_recorder, op_type="MOVE", src_path=Path("/a"), dst_path=Path("/b"))
        self.assertFalse(ok)
        self.assertTrue(any("echec journalisation" in msg for msg in cm.output))


if __name__ == "__main__":
    unittest.main(verbosity=2)

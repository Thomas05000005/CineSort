"""Script de remplacement controle des accents francais manquants dans les
strings UI visibles. NE TOUCHE PAS aux ID, keys, variables, ou commentaires.

Strategie : pour chaque tuple (avant, apres, fichiers), faire le remplacement
exact. Les chaines sont entourees de quotes (simple ou double) pour eviter
les faux positifs sur des noms de variables.

Usage :
    .venv313/Scripts/python.exe tests/manual/fix_french_accents.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


# Liste des remplacements : (chaine_avant, chaine_apres, glob_fichiers).
# Les chaines incluent les quotes pour cibler les strings UI uniquement
# (pas les keys/identifiants).
REPLACEMENTS: List[Tuple[str, str, str]] = [
    # =========================================================
    # settings-v5.js (le plus gros offender)
    # =========================================================
    ('label: "Cle API"', 'label: "Clé API"', "web/views/settings-v5.js"),
    ('hint: "Separes par ; ou par ligne"', 'hint: "Séparés par ; ou par ligne"', "web/views/settings-v5.js"),
    ('hint: "Separees par ;"', 'hint: "Séparées par ;"', "web/views/settings-v5.js"),
    ('label: "Frames analysees"', 'label: "Frames analysées"', "web/views/settings-v5.js"),
    ('label: "Refresh auto apres apply"', 'label: "Refresh auto après apply"', "web/views/settings-v5.js"),
    ('label: "Refresh apres apply"', 'label: "Refresh après apply"', "web/views/settings-v5.js"),
    ('label: "Detection sous-titres"', 'label: "Détection sous-titres"', "web/views/settings-v5.js"),
    ('label: "Detection series TV"', 'label: "Détection séries TV"', "web/views/settings-v5.js"),
    ('label: "Nettoyer fichiers residuels"', 'label: "Nettoyer fichiers résiduels"', "web/views/settings-v5.js"),
    ('label: "Apres scan"', 'label: "Après scan"', "web/views/settings-v5.js"),
    ('label: "Apres apply"', 'label: "Après apply"', "web/views/settings-v5.js"),
    ('label: "Modere"', 'label: "Modéré"', "web/views/settings-v5.js"),
    ('l:"Modere"', 'l:"Modéré"', "web/views/settings-v5.js"),
    ('label: "Densite"', 'label: "Densité"', "web/views/settings-v5.js"),
    ('label: "Densite interface"', 'label: "Densité interface"', "web/views/settings-v5.js"),
    ('label: "Sequentiel"', 'label: "Séquentiel"', "web/views/settings-v5.js"),
    ('l:"Sequentiel"', 'l:"Séquentiel"', "web/views/settings-v5.js"),
    ('label: "Parallelisme"', 'label: "Parallélisme"', "web/views/settings-v5.js"),
    ('label: "Mode parallelisme"', 'label: "Mode parallélisme"', "web/views/settings-v5.js"),
    ('label: "Wizard premier lancement termine"', 'label: "Wizard premier lancement terminé"', "web/views/settings-v5.js"),
    ('label: "Theme"', 'label: "Thème"', "web/views/settings-v5.js"),
    ('label: "Defaut"', 'label: "Défaut"', "web/views/settings-v5.js"),
    ('l:"Defaut"', 'l:"Défaut"', "web/views/settings-v5.js"),
    ('label: "Qualite"', 'label: "Qualité"', "web/views/settings-v5.js"),
    ('l:"Qualite"', 'l:"Qualité"', "web/views/settings-v5.js"),
    ('label: "Scoring qualite"', 'label: "Scoring qualité"', "web/views/settings-v5.js"),
    ('label: "Template serie"', 'label: "Template série"', "web/views/settings-v5.js"),
    ('label: "Templates de renommage"', 'label: "Templates de renommage"', "web/views/settings-v5.js"),  # OK
    ('label: "Avance"', 'label: "Avancé"', "web/views/settings-v5.js"),
    ('label: "Bibliotheque"', 'label: "Bibliothèque"', "web/views/settings-v5.js"),
    ('label: "Integrations"', 'label: "Intégrations"', "web/views/settings-v5.js"),
    ('label: "Chemin cle"', 'label: "Chemin clé"', "web/views/settings-v5.js"),
    ('label: "Niveau log"', 'label: "Niveau log"', "web/views/settings-v5.js"),  # OK
    ('label: "Cinema"', 'label: "Cinéma"', "web/views/settings-v5.js"),
    ('l:"Cinema"', 'l:"Cinéma"', "web/views/settings-v5.js"),
    # =========================================================
    # qij-v5.js (Qualite, Decennie, Ere grain, donnee)
    # =========================================================
    ('"Qualite"', '"Qualité"', "web/views/qij-v5.js"),
    ("'Qualite'", "'Qualité'", "web/views/qij-v5.js"),
    ('>Qualite<', '>Qualité<', "web/views/qij-v5.js"),
    ('"Decennie"', '"Décennie"', "web/views/qij-v5.js"),
    ("'Decennie'", "'Décennie'", "web/views/qij-v5.js"),
    ('>Decennie<', '>Décennie<', "web/views/qij-v5.js"),
    ('"Ere grain"', '"Ère grain"', "web/views/qij-v5.js"),
    ("'Ere grain'", "'Ère grain'", "web/views/qij-v5.js"),
    ('"Aucune donnee pour cette dimension"', '"Aucune donnée pour cette dimension"', "web/views/qij-v5.js"),
    ('>Aucune donnee pour cette dimension<', '>Aucune donnée pour cette dimension<', "web/views/qij-v5.js"),
    # =========================================================
    # film-detail.js (Apercu, Bibliotheque)
    # =========================================================
    ('"Apercu"', '"Aperçu"', "web/views/film-detail.js"),
    ("'Apercu'", "'Aperçu'", "web/views/film-detail.js"),
    ('>Apercu<', '>Aperçu<', "web/views/film-detail.js"),
    ('"Bibliotheque"', '"Bibliothèque"', "web/views/film-detail.js"),
    ("'Bibliotheque'", "'Bibliothèque'", "web/views/film-detail.js"),
    ('>Bibliotheque<', '>Bibliothèque<', "web/views/film-detail.js"),
    # =========================================================
    # processing.js (decisions, Parametres)
    # =========================================================
    ('"Valider les decisions"', '"Valider les décisions"', "web/views/processing.js"),
    ('"Appliquer les changements"', '"Appliquer les changements"', "web/views/processing.js"),  # OK
    # configure dans message
    ('configure dans les Parametres', 'configurés dans les Paramètres', "web/views/processing.js"),
    ('configure dans les parametres', 'configurés dans les paramètres', "web/views/processing.js"),
    # =========================================================
    # web/index.html (UI principale legacy)
    # =========================================================
    (">ANNEE<", ">ANNÉE<", "web/index.html"),
    (">DUREE<", ">DURÉE<", "web/index.html"),
    (">ANALYSE VIDEO<", ">ANALYSE VIDÉO<", "web/index.html"),
    (">Cle API<", ">Clé API<", "web/index.html"),
    ('"Cle API"', '"Clé API"', "web/index.html"),
    (">Memoriser la cle<", ">Mémoriser la clé<", "web/index.html"),
    (">Dossier d'etat (optionnel)<", ">Dossier d'état (optionnel)<", "web/index.html"),
    (">Non classe<", ">Non classé<", "web/index.html"),
    # =========================================================
    # views legacy
    # =========================================================
    ('"Cle API"', '"Clé API"', "web/views/settings.js"),
    ('"Memoriser la cle"', '"Mémoriser la clé"', "web/views/settings.js"),
    ('"Non classe"', '"Non classé"', "web/views/library.js"),
    ('"ANNEE"', '"ANNÉE"', "web/views/library.js"),
    ('"DUREE"', '"DURÉE"', "web/views/library.js"),
    # =========================================================
    # dashboard/views/settings.js (3x Cle API)
    # =========================================================
    ('class="field-label">Cle API<', 'class="field-label">Clé API<', "web/dashboard/views/settings.js"),
    # =========================================================
    # sidebar-v5.js (Bibliotheque/Qualite/Parametres si presents)
    # =========================================================
    ('"Bibliotheque"', '"Bibliothèque"', "web/components/sidebar-v5.js"),
    ('"Qualite"', '"Qualité"', "web/components/sidebar-v5.js"),
    ('"Parametres"', '"Paramètres"', "web/components/sidebar-v5.js"),
    ('"Integrations"', '"Intégrations"', "web/components/sidebar-v5.js"),
    # =========================================================
    # Reinit. dans components
    # =========================================================
    ('>Reinit.<', '>Réinit.<', "web/views/settings-v5.js"),
    ('"Reinit."', '"Réinit."', "web/views/settings-v5.js"),
    ("'Reinit.'", "'Réinit.'", "web/views/settings-v5.js"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    total_changes = 0
    files_changed: dict[Path, int] = {}

    for before, after, glob in REPLACEMENTS:
        if before == after:
            continue
        path = _PROJECT_ROOT / glob
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"  [skip] {glob}: {exc}", flush=True)
            continue

        if before not in content:
            continue

        n = content.count(before)
        new_content = content.replace(before, after)

        if not args.dry_run:
            path.write_text(new_content, encoding="utf-8")
        total_changes += n
        files_changed[path] = files_changed.get(path, 0) + n
        print(f"  [{'DRY' if args.dry_run else 'OK'}] {glob}: '{before[:60]}' -> '{after[:60]}' (x{n})", flush=True)

    print(f"\n=== Total : {total_changes} remplacements dans {len(files_changed)} fichier(s) ===", flush=True)
    for f, n in sorted(files_changed.items(), key=lambda x: x[1], reverse=True):
        print(f"  {n:3d} : {f.relative_to(_PROJECT_ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

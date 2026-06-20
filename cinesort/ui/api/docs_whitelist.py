"""Whitelist des documents publics accessibles via runtime/get_doc.

Cf docs/internal/design/refonte_2026_05_17/screens/12-aide.md — ecran Aide.

Securite : pour empecher tout path traversal, le frontend ne fournit qu'un
identifiant logique (doc_id) ; le backend resout le chemin via ce mapping.
Aucune chaine `..`, aucun chemin absolu, aucun fichier hors du repertoire
`docs/` ne peut etre lu via cet endpoint.

Le mapping pointe vers des chemins RELATIFS a la racine du repo (parents[3]
de ce fichier). La resolution finale verifie que le chemin reel est bien
contenu dans le dossier `docs/`.
"""

from __future__ import annotations

from typing import Dict

# Identifiant logique -> chemin relatif depuis la racine du projet.
# Tous les fichiers doivent etre dans `docs/` (filtre defensif dans le loader).
DOCS_WHITELIST: Dict[str, str] = {
    # Guide utilisateur principal (cf spec 12-aide.md section 2).
    "user-guide": "docs/USER_GUIDE_v2.md",
    # Manuel legacy (reference dev/power user).
    "manual": "docs/MANUAL.md",
    # Troubleshooting public (FAQ ffprobe, etc.).
    "troubleshooting": "docs/TROUBLESHOOTING.md",
    # Format des exports JSON/CSV/HTML.
    "export-format": "docs/EXPORT_FORMAT.md",
    # Documentation API REST publique.
    "api-endpoints": "docs/api/ENDPOINTS.md",
    # i18n public.
    "i18n": "docs/i18n.md",
    # Release notes / changelog public.
    "release": "docs/RELEASE.md",
}


def get_doc_path(doc_id: str) -> str | None:
    """Retourne le chemin relatif d'un doc_id whiteliste, ou None.

    Args:
        doc_id: Identifiant logique du document (ex. "user-guide").

    Returns:
        Chemin relatif depuis la racine du repo, ou None si doc_id inconnu.
    """
    if not isinstance(doc_id, str):
        return None
    return DOCS_WHITELIST.get(doc_id.strip().lower())


def list_doc_ids() -> list[str]:
    """Retourne la liste triee des doc_id disponibles."""
    return sorted(DOCS_WHITELIST.keys())

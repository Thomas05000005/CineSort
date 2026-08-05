"""Issue #556 — un seul validateur `owner/repo` pour l'enregistrement ET l'appel.

La regex SSRF (#240) qui protege l'URL `api.github.com/repos/<owner>/<repo>`
existait en double : compilee dans `app/updater`, recopiee en clair dans
`ui/api/settings_support._save_section_advanced` sous un commentaire disant
qu'elle devait rester identique. Un commentaire ne fait pas respecter une
egalite : la faire evoluer d'un seul cote produit une valeur acceptee a
l'enregistrement puis refusee a l'appel (ou l'inverse), sans un mot pour
l'utilisateur.

Le test ne compare pas deux motifs entre eux : il verifie que ce que la couche
Parametres PERSISTE est exactement ce que le verificateur de mises a jour
ACCEPTE, sur un jeu de valeurs qui couvre les deux verdicts.
"""

from __future__ import annotations

import unittest
from unittest import mock

from cinesort.app import updater
from cinesort.app.updater import _fetch_latest_release, is_valid_github_repo
from cinesort.ui.api.settings_support import _save_section_advanced

# Valeurs choisies pour tomber des deux cotes de la frontiere, dont les formes
# d'attaque que la regle #240 existe pour bloquer.
_ACCEPTEES = (
    "Thomas05000005/CineSort",
    "user/cine-sort",
    "a_b.c/d.e_f",
)
_REFUSEES = (
    "Thomas05000005",  # pas de barre oblique
    "foo/bar/../../search",  # path traversal, la raison d'etre de la regle
    "owner/repo?x=1",
    "owner /repo",
    "https://api.github.com/repos/o/r",
    "o/r\nX-Injected: 1",
)


def _persiste(repo: str) -> bool:
    """Vrai si la couche Parametres retient `repo` tel quel."""
    out = _save_section_advanced({"update_github_repo": repo})
    return out.get("update_github_repo") == repo


class GithubRepoValidationSourceUniqueTests(unittest.TestCase):
    def test_ce_qui_est_persiste_est_exactement_ce_que_l_updater_accepte(self) -> None:
        for repo in _ACCEPTEES + _REFUSEES:
            with self.subTest(repo=repo):
                self.assertEqual(
                    _persiste(repo),
                    is_valid_github_repo(repo),
                    f"divergence enregistrement/appel sur {repo!r}",
                )

    def test_les_valeurs_valides_sont_bien_persistees(self) -> None:
        for repo in _ACCEPTEES:
            with self.subTest(repo=repo):
                self.assertTrue(_persiste(repo))

    def test_les_valeurs_invalides_ne_sont_pas_persistees(self) -> None:
        for repo in _REFUSEES:
            with self.subTest(repo=repo):
                self.assertFalse(_persiste(repo), f"{repo!r} ne doit jamais atteindre l'URL GitHub")

    def test_la_chaine_vide_reste_acceptee(self) -> None:
        """C'est la valeur par defaut, et le seul retour au depot integre."""
        out = _save_section_advanced({"update_github_repo": "   "})
        self.assertEqual(out.get("update_github_repo"), "")

    def test_l_updater_n_atteint_pas_le_reseau_sur_une_valeur_invalide(self) -> None:
        """Le validateur est bien celui qu'emprunte le chemin reseau reel.

        Sans cette assertion, `is_valid_github_repo` pourrait etre un helper
        parallele que `_fetch_latest_release` n'utilise pas : le test de
        coherence ci-dessus resterait vert pendant que l'appel HTTP
        contournerait la regle.

        On observe l'appel a `urlopen`, PAS la valeur de retour : un
        `_fetch_latest_release` qui rend `None` ne prouve rien — il rend deja
        `None` sur une panne reseau, un 404 ou un corps illisible. Seule
        l'absence d'appel prouve que la valeur a ete arretee avant l'URL.
        """
        for repo in _REFUSEES:
            with self.subTest(repo=repo), mock.patch.object(updater, "urlopen") as fake_urlopen:
                self.assertFalse(is_valid_github_repo(repo))
                self.assertIsNone(_fetch_latest_release(repo, 1))
                fake_urlopen.assert_not_called()

    def test_le_temoin_de_ce_test_appelle_bien_le_reseau_sur_une_valeur_valide(self) -> None:
        """Temoin : sans lui, `assert_not_called` passerait meme si `urlopen`
        n'etait jamais atteint pour une raison sans rapport avec la validation."""
        with mock.patch.object(updater, "urlopen", side_effect=OSError("hors ligne")) as fake_urlopen:
            self.assertIsNone(_fetch_latest_release("Thomas05000005/CineSort", 1))
            fake_urlopen.assert_called_once()


if __name__ == "__main__":
    unittest.main()

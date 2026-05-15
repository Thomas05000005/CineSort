"""Helpers partages pour la suite de tests CineSort.

Issue #86 PR 2 : module utilitaire commun, utilisable par unittest et pytest.

Le `conftest.py` racine fournit deja les fixtures pytest (`free_port`,
`create_movie_file`, `tmp_state_dir`, `wait_run_terminal`). Ce module
expose les MEMES helpers sous forme de fonctions importables, pour les
tests `unittest.TestCase` qui ne peuvent pas consommer les fixtures pytest
naturellement.

Usage :

    from tests._helpers import find_free_port

    class MyTests(unittest.TestCase):
        def setUp(self):
            self.port = find_free_port()
"""

from __future__ import annotations

import socket


def find_free_port() -> int:
    """Retourne un port TCP libre sur 127.0.0.1.

    Remplace les 14 definitions duplicatees de `_find_free_port` dans
    les fichiers de test (issue #86).

    NB : il y a une race condition entre l'obtention du port et son
    utilisation. Acceptable pour les serveurs longs-running du test
    (REST server, etc.), risque negligeable.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])

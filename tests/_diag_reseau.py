"""Etat du reseau LOCAL a l'instant d'un echec — instrument de l'issue #924.

POURQUOI CET INSTRUMENT EXISTE. Le shell du dashboard n'apparait parfois JAMAIS
en CI : 30 s de timeout, ce qui est « jamais » et non « lent ». Un
`net::ERR_NO_BUFFER_SPACE` a deja ete observe sur le meme workflow. Trois faits
convergent vers un epuisement de sockets — mais aucun ne le demontre, et le
nombre de sockets n'a JAMAIS ete mesure pendant un echec.

Raisonner par elimination a deja coute : le message d'erreur d'avant #918
accusait l'authentification pour un shell qui, en realite, ne s'affichait pas.
Cet instrument repond a la seule question qui tranche, au moment ou elle se pose :
le port repond-il encore, et combien de connexions TCP locales existent, par etat ?

TROIS CHOIX DE CONCEPTION, tous les trois payes ici meme :

1. **Aucune dependance nouvelle.** `psutil` n'est pas installe dans cet
   environnement ; une branche qui l'utiliserait aurait TOUJOURS rendu
   « indisponible », soit un diagnostic decoratif. On passe par `netstat`,
   present sur le runner Windows de la CI.
2. **L'encodage est IMPOSE.** `text=True` seul decode avec l'encodage de la
   console (cp1252 ici), et la sortie de `netstat` porte des octets qu'il ne sait
   pas lire (0x90). Le thread de lecture de `subprocess` meurt alors sur un
   `UnicodeDecodeError`, `proc.stdout` vaut `None` — et l'instrument cense
   documenter un echec le REMPLACE par le sien. Mesure faite au premier appel
   reel de la premiere version de ce fichier.
3. **Ne leve JAMAIS.** Consequence directe du point 2 : le contrat est verifie
   par un test, pas seulement annonce en docstring.
"""

from __future__ import annotations

import socket
import subprocess
from typing import Dict, Optional, Tuple

#: Au-dela, `netstat` a rencontre autre chose qu'un reseau local.
_TIMEOUT_NETSTAT_S = 10.0

#: Les deux premiers mots d'une ligne TCP, selon l'OS.
_PREFIXES_TCP = {"TCP", "TCP6"}


def joignabilite(port: int) -> Tuple[Optional[int], str]:
    """Le port accepte-t-il encore une connexion ?

    Rend `(code, phrase)`. `code` vaut 0 si la connexion aboutit, l'errno sinon,
    et `None` si la tentative elle-meme a echoue — auquel cas la phrase porte
    l'exception, alors la donnee la plus interessante : un `WSAENOBUFS` ici
    vaudrait verdict.
    """
    try:
        numero = int(port)
    except (TypeError, ValueError):
        return None, f"port illisible ({port!r}) : aucune mesure possible"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            code = s.connect_ex(("127.0.0.1", numero))
    except (OSError, OverflowError, ValueError) as exc:
        return None, f"connect_ex(127.0.0.1:{numero}) a leve {type(exc).__name__}: {exc}"
    etat = "joignable" if code == 0 else "REFUSE"
    return code, f"connect_ex(127.0.0.1:{numero}) = {code} ({etat})"


def comptes_tcp() -> Tuple[Optional[Dict[str, int]], str]:
    """Compte les connexions TCP locales par etat, via `netstat -an`.

    C'est `TIME_WAIT` qui interesse #924 : il s'accumule quand des serveurs a
    courte vie se succedent, et finit par empecher une nouvelle connexion. Rend
    `(comptes, phrase)`, `comptes` valant `None` si la mesure n'a pas pu se faire
    — et la phrase DIT alors pourquoi, plutot que de se taire.
    """
    try:
        proc = subprocess.run(  # noqa: S603,S607 - argv fixe, aucune entree utilisateur
            ["netstat", "-an"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT_NETSTAT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return None, f"connexions TCP : netstat indisponible ({type(exc).__name__}: {exc})"
    if proc.returncode != 0:
        return None, f"connexions TCP : netstat a rendu {proc.returncode}"
    if not proc.stdout:
        return None, "connexions TCP : netstat n'a rien ecrit sur sa sortie"

    comptes: Dict[str, int] = {}
    for ligne in proc.stdout.splitlines():
        morceaux = ligne.split()
        if not morceaux or morceaux[0].upper() not in _PREFIXES_TCP:
            continue
        etat = morceaux[-1].upper()
        # Sans etat lisible (ligne tronquee, ou UDP mal prefixe) on ne compte
        # rien plutot que d'inventer une categorie qui fausserait le total.
        if not etat.replace("_", "").isalpha():
            continue
        comptes[etat] = comptes.get(etat, 0) + 1

    if not comptes:
        return None, "connexions TCP : netstat n'a rendu aucune ligne exploitable"
    total = sum(comptes.values())
    detail = ", ".join(f"{k}={v}" for k, v in sorted(comptes.items()))
    return comptes, f"connexions TCP locales : {total} ({detail})"


def etat_reseau(port: int) -> str:
    """Les deux mesures, assemblees en un texte lisible dans un rapport pytest.

    DERNIER FILET. Les deux mesures se gardent deja elles-memes, mais le contrat
    de cette fonction est « ne leve jamais » : une exception ici effacerait le
    rapport d'echec qu'elle est censee enrichir. Ce filet n'est pas de la
    ceinture-et-bretelles — la premiere version de `comptes_tcp` levait un
    `AttributeError` des son premier appel reel.
    """
    lignes = []
    try:
        lignes.append(joignabilite(port)[1])
    except Exception as exc:  # noqa: BLE001 - un diagnostic ne casse jamais son rapport
        lignes.append(f"joignabilite : mesure impossible ({type(exc).__name__}: {exc})")
    try:
        lignes.append(comptes_tcp()[1])
    except Exception as exc:  # noqa: BLE001 - idem
        lignes.append(f"connexions TCP : mesure impossible ({type(exc).__name__}: {exc})")
    return "\n".join(lignes)

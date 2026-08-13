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

import errno
import re
import socket
import subprocess
from typing import Dict, Optional, Tuple

#: Au-dela, `netstat` a rencontre autre chose qu'un reseau local.
_TIMEOUT_NETSTAT_S = 10.0

#: Borne de la sonde de joignabilite. Elle n'est payee que dans le cas ou le
#: port ne repond pas — c'est-a-dire le seul ou la sonde a quelque chose a dire.
_TIMEOUT_SONDE_S = 1.5

#: Les deux premiers mots d'une ligne TCP, selon l'OS.
_PREFIXES_TCP = {"TCP", "TCP6"}

#: Un etat TCP : une lettre, puis lettres/chiffres/souligne.
#:
#: `FIN_WAIT_1` ET `FIN_WAIT_2` PORTENT UN CHIFFRE. Le filtre precedent
#: (`etat.replace("_", "").isalpha()`) les REJETAIT en silence — eux et leurs
#: variantes Linux `FIN_WAIT1`/`FIN_WAIT2`. Ils disparaissaient du detail ET du
#: total, sans un mot. Or `FIN_WAIT_*` est l'une des familles qui s'accumulent
#: quand une table de sockets deborde : l'instrument pouvait donc rendre un
#: chiffre rassurant a l'instant precis ou il fallait s'alarmer.
_ETAT_TCP = re.compile(r"^[A-Z][A-Z0-9_]*$")


def joignabilite(port: Optional[int]) -> Tuple[Optional[int], str]:
    """Le port accepte-t-il encore une connexion ?

    Rend `(code, phrase)`. `code` vaut 0 si la connexion aboutit, l'errno sinon,
    et `None` si la tentative elle-meme a echoue — auquel cas la phrase porte
    l'exception, alors la donnee la plus interessante : un `WSAENOBUFS` ici
    vaudrait verdict.

    `port=None` EST UN CAS REEL, ET IL A UNE PHRASE A LUI. Mesure sur pytest :
    quand la fixture `e2e_server` echoue ELLE-MEME, `item.funcargs` ne la contient
    pas, donc l'appelant n'a aucun port a fournir. Se taire alors serait perdre le
    diagnostic au moment ou il vaudrait le plus cher — les COMPTES de sockets,
    eux, restent mesurables sans port.
    """
    if port is None:
        return None, "port inconnu : la fixture du serveur a echoue avant de le publier"
    try:
        numero = int(port)
    except (TypeError, ValueError):
        return None, f"port illisible ({port!r}) : aucune mesure possible"
    # UN PORT HORS PLAGE EST UNE ERREUR DE PROGRAMMATION, PAS UNE PANNE RESEAU.
    # Mesure : `create_connection(("127.0.0.1", 999999))` ne leve pas — elle
    # EXPIRE, et l'instrument aurait donc rapporte « aucune reponse » (en payant
    # le delai complet) pour un appelant qui s'est trompe de valeur.
    if not 0 <= numero <= 65535:
        return None, f"port hors plage ({numero}) : 0-65535 attendu, aucune mesure faite"

    # `connect_ex` SUR UN SOCKET A TIMEOUT NE MESURE PAS CE QU'ON CROIT. Poser
    # `settimeout()` rend le socket NON BLOQUANT : `connect_ex` rend alors
    # `WSAEWOULDBLOCK` (10035) — « je ne sais pas encore » — pour tout ce qui
    # n'aboutit pas instantanement. La version precedente etiquetait ce code
    # « REFUSE », c'est-a-dire qu'elle AFFIRMAIT un mecanisme (le serveur a
    # repondu RST, il est mort) la ou elle n'avait aucune reponse. Mesure sur ce
    # poste : un port ferme rendait 10035, exactement comme un port lent.
    #
    # Or « refuse » et « aucune reponse » sont PRECISEMENT les deux hypotheses
    # que #924 doit separer : un port qui refuse dit que le serveur est tombe ;
    # un port muet dit que la pile reseau ne repond plus.
    try:
        with socket.create_connection(("127.0.0.1", numero), timeout=_TIMEOUT_SONDE_S):
            return 0, f"127.0.0.1:{numero} : joignable"
    except ConnectionRefusedError as exc:
        nom = errno.errorcode.get(exc.errno or 0, str(exc.errno))
        return exc.errno, f"127.0.0.1:{numero} : REFUSE ({nom}) — le serveur ne tient plus le port"
    except (TimeoutError, socket.timeout):
        return None, f"127.0.0.1:{numero} : AUCUNE REPONSE en {_TIMEOUT_SONDE_S:g} s (ni refus, ni acceptation)"
    except (OSError, OverflowError, ValueError) as exc:
        # C'est ICI qu'un `WSAENOBUFS` apparaitrait, et il vaudrait verdict.
        nom = errno.errorcode.get(getattr(exc, "errno", 0) or 0, "")
        return None, f"127.0.0.1:{numero} : {type(exc).__name__} {nom} ({exc})"


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
    ignorees = 0
    for ligne in proc.stdout.splitlines():
        morceaux = ligne.split()
        if not morceaux or morceaux[0].upper() not in _PREFIXES_TCP:
            continue
        etat = morceaux[-1].upper()
        # Sans etat lisible (ligne tronquee, ou UDP mal prefixe) on ne compte
        # rien plutot que d'inventer une categorie qui fausserait le total.
        if not _ETAT_TCP.match(etat):
            ignorees += 1
            continue
        comptes[etat] = comptes.get(etat, 0) + 1

    if not comptes:
        return None, "connexions TCP : netstat n'a rendu aucune ligne exploitable"
    total = sum(comptes.values())
    detail = ", ".join(f"{k}={v}" for k, v in sorted(comptes.items()))
    # CE QUI EST IGNORE EST DIT. Un total silencieusement ampute est pire qu'une
    # absence de total : il se lit comme un fait.
    reste = f", {ignorees} ligne(s) TCP non classee(s)" if ignorees else ""
    return comptes, f"connexions TCP de cette machine : {total} ({detail}){reste}"


def etat_reseau(port: Optional[int]) -> str:
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

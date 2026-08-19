"""Le triangle « annonce / journal / disque » — premier cote : annonce vs journal.

POURQUOI CE MODULE EXISTE
-------------------------
Sur la semaine du 2026-08-13 au 2026-08-19, quatre defauts de la MEME forme ont
ete trouves et corriges, tous a la main et tous APRES coup : *ce que
l'application annonce n'est pas ce qu'elle a fait*.

    #1103  l'ecran annonce « 1 fichier »  -> un DOSSIER entier deplace
    #1062  « 0 fichier(s) supprime(s) » en vert -> 300 fichiers ont RESISTE
    #1099  apply `errors: 0`              -> N-1 films, une ligne du plan disparue
    #1097  « Sauvegarde a HH:MM »         -> les reglages effaces

L'invariant qui les attrape existe deja dans ce depot, mais REINVENTE a la main,
endpoint par endpoint, et toujours apres l'incident : `reset_support._a_disparu`,
`test_purge_jonction_premier_niveau`, `test_crit1_granularite_destructive`,
`test_apply_mkdirs_dryrun_parity`. Il n'en existait AUCUNE forme generique.
C'est ce trou que ce module comble.

CE QU'IL FAIT, ET CE QU'IL NE FAIT PAS
--------------------------------------
Il compare deux des trois sommets : le PAYLOAD rendu a l'utilisateur et le
JOURNAL des operations reellement enregistrees. Le troisieme sommet (l'etat du
DISQUE) demande une photo avant/apres et fera l'objet d'une seconde passe.

Consequence a connaitre, et ecrite plutot que tue : ce cote seul attrape #1062
(un succes vert alors que le journal porte des echecs) mais PAS #1103, ou une
seule operation journalisee emportait tout un dossier — la, seul le disque parle.

AUCUNE CONCLUSION SANS SA MATIERE
---------------------------------
Chaque `Incoherence` porte les GRANDEURS qui l'ont produite, pas seulement un
libelle. C'est une exigence de conception : l'application est ce qu'on debogue,
elle n'est pas un temoin fiable. Un verdict qu'on ne peut pas recalculer depuis
ses termes ne vaut rien.

Ce module est PUR : aucune E/S, aucun etat global, aucune dependance a `api`. La
decision est donc testable exhaustivement sans faire bouger un fichier, et le
cablage se mute separement (regle du depot : muter le SITE D'APPEL a part).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Sequence

#: Les `op_type` qui deplacent quelque chose et que l'undo sait rejouer.
#: `apply_rollback.py` refuse tout ce qui n'est pas dans cette liste ; la
#: dupliquer serait une derive, donc `tests/test_verdicts_annonce_journal.py`
#: verifie qu'elle n'a pas diverge de la source.
OPS_DE_DEPLACEMENT: tuple[str, ...] = ("MOVE_FILE", "MOVE_DIR", "QUARANTINE_FILE", "QUARANTINE_DIR")

#: Les `op_type` de mise en quarantaine, sous-ensemble strict du precedent.
OPS_DE_QUARANTAINE: tuple[str, ...] = ("QUARANTINE_FILE", "QUARANTINE_DIR")


@dataclass(frozen=True)
class Incoherence:
    """Un ecart entre ce qui est annonce et ce qui est enregistre.

    `annonce` et `journal` sont les DEUX termes qui ont produit le verdict. Ils
    sont conserves tels quels pour qu'un lecteur refasse le calcul sans faire
    confiance a `message`.
    """

    code: str
    message: str
    annonce: Any
    journal: Any
    #: Ce que le verdict ne prouve PAS. Rempli quand la comparaison a une limite
    #: connue — une reserve ecrite vaut mieux qu'une confiance mal placee.
    reserve: str = ""

    def as_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "annonce": self.annonce,
            "journal": self.journal,
        }
        if self.reserve:
            d["reserve"] = self.reserve
        return d


@dataclass(frozen=True)
class Verdict:
    """Le resultat d'une comparaison, avec ce qui a servi a le produire."""

    incoherences: List[Incoherence] = field(default_factory=list)
    #: Les comptes observes dans le journal, pour que le verdict soit recalculable.
    comptes_journal: Dict[str, int] = field(default_factory=dict)

    @property
    def coherent(self) -> bool:
        return not self.incoherences

    def as_dict(self) -> Dict[str, Any]:
        return {
            "coherent": self.coherent,
            "comptes_journal": dict(self.comptes_journal),
            "incoherences": [i.as_dict() for i in self.incoherences],
        }


def _compter_par_type(operations: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    """Compte les operations par `op_type`, en tolerant les formes degradees.

    Une operation dont l'`op_type` est illisible est comptee sous la cle vide
    plutot que jetee : la jeter ferait mentir le total, et c'est exactement le
    genre de silence que ce module existe pour attraper.
    """
    comptes: Dict[str, int] = {}
    for op in operations or ():
        try:
            t = str(op.get("op_type") or "")
        except AttributeError:
            t = ""
        comptes[t] = comptes.get(t, 0) + 1
    return comptes


def _en_echec(op: Mapping[str, Any]) -> bool:
    """Une operation porte-t-elle la marque d'un echec ?

    LES FORMES SONT MESUREES, PAS SUPPOSEES
    ---------------------------------------
    Une premiere version de cette fonction cherchait une cle `error`. Elle
    passait ses 15 tests et tuait ses mutants — parce que les tests lui
    fournissaient la forme que j'avais IMAGINEE. Confrontee aux deux sources
    reelles, elle etait MUETTE sur les deux. Un detecteur muet est pire
    qu'absent : il fait croire que le controle a eu lieu.

    Les deux sources, relevees dans le code qui les ECRIT :

    1. `apply_operations` (SQLite, `list_apply_operations`). La regle qui fait
       autorite est celle de `apply_batches_reconciliation.py:247`, qui s'en
       sert pour classer un batch `ROLLED_BACK` :
       *`error_message` non vide OU `undo_status='FAILED'`*.
       A noter — et c'est une limite a connaitre : `record_apply_op` n'a aucun
       parametre d'erreur et n'est appelee qu'APRES un move reussi. Cette table
       ne porte donc quasiment que des succes ; c'est `apply_audit.jsonl` qui
       voit les echecs.
    2. `apply_audit.jsonl` (`read_apply_audit`). L'echec n'y est pas une CLE
       mais un TYPE d'evenement : `ApplyAuditLogger.error()` ecrit
       `{"event": "error", "context": ..., "message": ...}`.

    La cle `error` nue reste acceptee : c'est la forme des payloads internes, et
    la retirer ferait de ce troisieme cas un silence de plus.
    """
    try:
        if str(op.get("undo_status") or "") == "FAILED":
            return True
        if str(op.get("error_message") or ""):
            return True
        if str(op.get("event") or "") == "error":
            return True
        return bool(op.get("error"))
    except AttributeError:
        return False


def comparer_annonce_et_journal(
    annonce: Mapping[str, Any],
    operations: Sequence[Mapping[str, Any]],
    *,
    evenements_audit: Sequence[Mapping[str, Any]] = (),
    dry_run: bool = False,
) -> Verdict:
    """Compare le payload rendu a l'utilisateur au journal des operations.

    DEUX SOURCES, ET IL EN FAUT DEUX
    --------------------------------
    Ce depot journalise l'apply a deux endroits qui ne voient PAS la meme chose,
    et n'ont meme pas la meme forme :

    - `operations` — les lignes SQLite `apply_operations`, cle `op_type` en
      MAJUSCULES (`MOVE_FILE`). `record_apply_op` n'est appelee qu'APRES un move
      reussi et n'a aucun parametre d'erreur : cette table dit ce qui a BOUGE,
      presque jamais ce qui a echoue.
    - `evenements_audit` — les lignes de `apply_audit.jsonl` (`read_apply_audit`),
      cle `event` en minuscules (`op_move_file`), et surtout `event="error"`,
      seule trace des echecs, ecrite en trois endroits de `apply_core`.

    N'en brancher qu'une rendrait l'instrument muet sur la moitie du probleme :
    les comptes sans les echecs, ou les echecs sans les comptes. Les echecs sont
    donc cherches dans les DEUX, les comptes seulement dans `operations` — seule
    source a porter un `op_type` exploitable.

    Args:
        annonce: le payload d'apply (`ApplyResult` aplati, ou le dict rendu).
        operations: les lignes `apply_operations` du batch.
        evenements_audit: les evenements `apply_audit.jsonl` du batch.
        dry_run: en apercu, rien n'est journalise. Les comparaisons de compte
            sont alors sans objet, et sans ce garde un dry-run leverait une
            incoherence a chaque fois — le genre de faux positif qui fait
            desapprendre a lire les verdicts.

    Returns:
        Un `Verdict` dont chaque incoherence porte ses deux termes.
    """
    comptes = _compter_par_type(operations)
    trouvees: List[Incoherence] = []

    def _entier(cle: str) -> int:
        try:
            return int(annonce.get(cle) or 0)
        except (TypeError, ValueError):
            return 0

    erreurs_annoncees = _entier("errors")
    ops_en_echec = sum(1 for op in operations or () if _en_echec(op)) + sum(
        1 for ev in evenements_audit or () if _en_echec(ev)
    )

    # --- 1. UN SUCCES FRANC QUI CACHE DES ECHECS -------------------------
    # C'est #1062 mot pour mot : « 0 fichier(s) supprime(s) » affiche en VERT
    # alors que les 300 fichiers avaient resiste. Le payload posait son succes a
    # la CONSTRUCTION et ne le rediscutait jamais ; les echecs vivaient dans une
    # cle que l'ecran ne lisait pas.
    if erreurs_annoncees == 0 and ops_en_echec > 0:
        trouvees.append(
            Incoherence(
                code="succes_annonce_malgre_des_echecs",
                message=f"l'apply annonce errors=0 mais le journal porte {ops_en_echec} operation(s) en echec",
                annonce={"errors": erreurs_annoncees},
                journal={"operations_en_echec": ops_en_echec},
            )
        )

    if dry_run:
        # En apercu rien n'est journalise : comparer des comptes n'aurait aucun
        # sens. On s'arrete ici, APRES la verification ci-dessus qui reste vraie.
        return Verdict(incoherences=trouvees, comptes_journal=comptes)

    # --- 2. LE COMPTE DE QUARANTAINE ------------------------------------
    quarantaine_annoncee = _entier("quarantined")
    quarantaine_journalisee = sum(comptes.get(t, 0) for t in OPS_DE_QUARANTAINE)
    if quarantaine_annoncee != quarantaine_journalisee:
        trouvees.append(
            Incoherence(
                code="compte_de_quarantaine_diverge",
                message=(
                    f"l'apply annonce quarantined={quarantaine_annoncee} mais le journal "
                    f"porte {quarantaine_journalisee} operation(s) de quarantaine"
                ),
                annonce={"quarantined": quarantaine_annoncee},
                journal={t: comptes.get(t, 0) for t in OPS_DE_QUARANTAINE},
                reserve=(
                    "un COMPTE egal ne prouve pas que la bonne CHOSE a bouge : #1103 "
                    "deplacait un dossier entier en une seule operation, donc 1 = 1. "
                    "Seule la photo du disque tranche ce cas."
                ),
            )
        )

    # --- 3. DES DEPLACEMENTS JOURNALISES SANS RIEN D'ANNONCE -------------
    # Le sens inverse compte autant, et il est plus dangereux : un apply qui dit
    # n'avoir rien fait alors que le journal porte des deplacements laisse
    # l'utilisateur sans raison d'annuler.
    deplacements = sum(comptes.get(t, 0) for t in OPS_DE_DEPLACEMENT)
    total_annonce = _entier("renames") + _entier("moves") + _entier("quarantined") + _entier("collection_moves")
    if deplacements > 0 and total_annonce == 0:
        trouvees.append(
            Incoherence(
                code="deplacements_journalises_non_annonces",
                message=f"le journal porte {deplacements} deplacement(s) mais le payload n'en annonce aucun",
                annonce={
                    "renames": _entier("renames"),
                    "moves": _entier("moves"),
                    "quarantined": quarantaine_annoncee,
                    "collection_moves": _entier("collection_moves"),
                },
                journal={t: comptes.get(t, 0) for t in OPS_DE_DEPLACEMENT if comptes.get(t, 0)},
            )
        )

    return Verdict(incoherences=trouvees, comptes_journal=comptes)

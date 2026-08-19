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
`comparer_annonce_et_journal` compare deux des trois sommets : le PAYLOAD rendu
a l'utilisateur et le JOURNAL des operations enregistrees. Cela attrape #1062 —
un succes vert alors que le journal porte des echecs.

Ce cote seul ne voit PAS #1103 : une seule operation journalisee emportait tout
un dossier, donc 1 annonce = 1 inscrit, les comptes concordent.

`verifier_operations_qui_emportent_d_autres_lignes` le voit, et SANS lire le
disque. Le plan prevoyait une photo avant/apres du sous-arbre ; les helpers
existants (`_snapshot_tree`) hachent chaque fichier, ce qui est praticable dans
un test et impensable sur une bibliotheque de films. Or #1103 est une question
GEOMETRIQUE — « ce dossier abrite-t-il plusieurs lignes du plan ? » — a laquelle
une comparaison de chemins repond, et qui reste vraie apres coup, quand la
source n'existe plus.

Reste hors de portee : ce qui n'est ni annonce, ni inscrit, ni deductible du
plan — un fichier qu'un tiers deplacerait pendant l'apply, par exemple. La photo
du disque garderait la son sens ; elle n'est simplement pas necessaire aux
quatre defauts connus.

DEUX JOURNAUX, ET IL EN FAUT DEUX
---------------------------------
Ce depot journalise l'apply a deux endroits qui ne voient PAS la meme chose, et
n'ont meme pas la meme forme :

- `apply_operations` (SQLite) — cle `op_type` en MAJUSCULES (`MOVE_FILE`).
  `record_apply_op` n'est appelee qu'APRES un move reussi et n'a aucun parametre
  d'erreur : cette table dit ce qui a BOUGE, presque jamais ce qui a echoue.
- `apply_audit.jsonl` (`read_apply_audit`) — cle `event` en minuscules
  (`op_move_file`), et surtout `event="error"`, seule trace des echecs, ecrite en
  trois endroits de `apply_core`.

N'en brancher qu'une rendrait l'instrument muet sur la moitie du probleme. Les
echecs sont donc cherches dans les DEUX, les comptes seulement dans
`apply_operations` — seule source a porter un `op_type` exploitable.

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

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

#: Les `op_type` qui deplacent quelque chose et que l'undo sait rejouer.
#: `apply_rollback.py` refuse tout ce qui n'est pas dans cette liste ; la
#: dupliquer serait une derive, donc `tests/test_verdicts_annonce_journal.py`
#: verifie qu'elle n'a pas diverge de la source.
OPS_DE_DEPLACEMENT: tuple[str, ...] = ("MOVE_FILE", "MOVE_DIR", "QUARANTINE_FILE", "QUARANTINE_DIR")

#: Les `op_type` de mise en quarantaine, sous-ensemble strict du precedent.
OPS_DE_QUARANTAINE: tuple[str, ...] = ("QUARANTINE_FILE", "QUARANTINE_DIR")

#: Tous les compteurs d'`ApplyResult` qui signifient « le disque a change ».
#:
#: Une premiere version n'en listait que QUATRE (`renames`, `moves`,
#: `quarantined`, `collection_moves`) — ceux que j'avais devines. Confrontee a un
#: vrai `ApplyResult`, elle produisait un FAUX POSITIF sur l'apply le plus
#: banal : un nettoyage de buckets incremente `applied_count` et
#: `leftovers_moved_count` sans toucher aux quatre. Le verdict criait a
#: l'incoherence sur un apply sain.
#:
#: Un faux positif est le pire defaut possible pour un detecteur : on apprend a
#: l'ignorer, et les vrais avec. La liste est donc RELEVEE sur le dataclass, et
#: `test_verdicts_annonce_journal.py` rougit si un compteur de deplacement y est
#: ajoute sans passer ici — sinon la derive rendrait le faux positif au bout de
#: quelques versions.
COMPTEURS_D_ACTION_DISQUE: tuple[str, ...] = (
    "applied_count",
    "cleanup_residual_folders_moved_count",
    "collection_moves",
    "conflicts_quarantined_count",
    "conflicts_sidecars_quarantined_count",
    "duplicates_identical_deleted_count",
    "duplicates_identical_moved_count",
    "duplicates_user_decided_moved_count",
    "empty_folders_moved_count",
    "leftovers_moved_count",
    "marked_for_deletion_moved_count",
    "merges_count",
    "mkdirs",
    "moves",
    "quarantined",
    "renames",
    "sidecar_conflicts_kept_both_count",
    "source_dirs_deleted_count",
)


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


def _verifier_succes_menteur(erreurs_annoncees: int, ops_en_echec: int) -> Optional[Incoherence]:
    """#1062 mot pour mot : « 0 fichier(s) supprime(s) » affiche en VERT alors
    que les 300 fichiers avaient resiste.

    Le payload posait son succes a la CONSTRUCTION et ne le rediscutait jamais ;
    les echecs vivaient dans une cle que l'ecran ne lisait pas.
    """
    if erreurs_annoncees != 0 or ops_en_echec <= 0:
        return None
    return Incoherence(
        code="succes_annonce_malgre_des_echecs",
        message=f"l'apply annonce errors=0 mais le journal porte {ops_en_echec} operation(s) en echec",
        annonce={"errors": erreurs_annoncees},
        journal={"operations_en_echec": ops_en_echec},
    )


def _verifier_compte_de_quarantaine(annoncee: int, comptes: Mapping[str, int]) -> Optional[Incoherence]:
    """Le nombre de mises en quarantaine annonce contre celui inscrit."""
    journalisee = sum(comptes.get(t, 0) for t in OPS_DE_QUARANTAINE)
    if annoncee == journalisee:
        return None
    return Incoherence(
        code="compte_de_quarantaine_diverge",
        message=(
            f"l'apply annonce quarantined={annoncee} mais le journal porte {journalisee} operation(s) de quarantaine"
        ),
        annonce={"quarantined": annoncee},
        journal={t: comptes.get(t, 0) for t in OPS_DE_QUARANTAINE},
        reserve=(
            "un COMPTE egal ne prouve pas que la bonne CHOSE a bouge : #1103 "
            "deplacait un dossier entier en une seule operation, donc 1 = 1. "
            "C'est `verifier_operations_qui_emportent_d_autres_lignes` qui tranche "
            "ce cas — par la geometrie des chemins, sans lire le disque."
        ),
    )


def _verifier_deplacements_tus(annonce: Mapping[str, int], comptes: Mapping[str, int]) -> Optional[Incoherence]:
    """Le sens inverse, et c'est le plus dangereux.

    Un apply qui dit n'avoir rien fait alors que le journal porte des
    deplacements laisse l'utilisateur sans aucune raison d'annuler.
    """
    deplacements = sum(comptes.get(t, 0) for t in OPS_DE_DEPLACEMENT)
    if deplacements <= 0 or sum(annonce.values()) != 0:
        return None
    return Incoherence(
        code="deplacements_journalises_non_annonces",
        message=(
            f"le journal porte {deplacements} deplacement(s) mais AUCUN des "
            f"{len(annonce)} compteurs du payload n'est non nul"
        ),
        annonce={"tous_les_compteurs_d_action": 0, "compteurs_examines": sorted(annonce)},
        journal={t: comptes.get(t, 0) for t in OPS_DE_DEPLACEMENT if comptes.get(t, 0)},
    )


def _cle_de_chemin(chemin: Any) -> str:
    """Normalise un chemin pour la comparaison, SANS toucher au disque.

    `resolve()` est proscrit ici : au moment ou le verdict se calcule, la source
    a deja bouge — elle n'existe plus. `normcase`/`normpath` sont de pures
    operations sur la chaine (separateurs, casse Windows, `..`).
    """
    brut = str(chemin or "").strip()
    if not brut:
        return ""
    return os.path.normcase(os.path.normpath(brut))


def _est_sous(enfant: str, parent: str) -> bool:
    """`enfant` est-il DANS `parent` (ou lui-meme) ?

    Comparaison par SEGMENTS et non par prefixe de chaine : `C:/films/Rocky2`
    commence par `C:/films/Rocky` sans etre dedans, et confondre les deux ferait
    accuser un apply parfaitement sain.
    """
    if not enfant or not parent:
        return False
    if enfant == parent:
        return True
    return enfant.startswith(parent.rstrip(os.sep) + os.sep)


def verifier_operations_qui_emportent_d_autres_lignes(
    operations: Sequence[Mapping[str, Any]],
    dossiers_par_ligne: Mapping[str, str],
) -> List[Incoherence]:
    """#1103 : une seule operation de quarantaine emportait TOUT un dossier.

    LE COTE DISQUE, SANS LIRE LE DISQUE
    -----------------------------------
    Le plan prevoyait ici une photo avant/apres du sous-arbre. Les helpers
    existants (`_snapshot_tree`, `_diff`) hachent chaque fichier : praticable
    dans un test, impensable sur une bibliotheque de films.

    Or #1103 n'a pas besoin du disque. Son mecanisme exact : `quarantine_row`
    resolvait la video par `folder / row.video`, et `PlanRow.video` « can be
    empty » — `folder / ""` vaut `folder`. Pour tout `kind` autre que `single`,
    le dossier est PARTAGE entre plusieurs lignes du plan. Mettre ce dossier en
    quarantaine emportait donc les films des AUTRES lignes.

    La question devient purement geometrique : *cette operation a-t-elle deplace
    un dossier ou vivent plusieurs lignes du plan ?* Une comparaison de chemins
    y repond, sans une seule E/S — et elle reste vraie apres coup, quand la
    source n'existe plus.

    Une remarque qui compte : l'`op_type` etait HONNETE (`QUARANTINE_DIR`, un
    dossier). Un controle « le type dit FILE mais c'est un DIR » n'aurait rien
    vu. Ce qui mentait, c'etait l'AMPLEUR — 1 operation comptee, 4 films partis.

    Args:
        operations: les lignes `apply_operations` du batch.
        dossiers_par_ligne: `{row_id: folder}` pour TOUTES les lignes du plan,
            pas seulement celles qu'on applique — c'est justement une ligne
            qu'on n'appliquait pas qui se faisait emporter.

    Returns:
        Une incoherence par operation ayant emporte plus d'une ligne.
    """
    # PERIMETRE : la quarantaine seulement.
    #
    # Un `MOVE_DIR` de collection deplace legitimement un dossier racine qui
    # CONTIENT plusieurs films (`move_collection_folder`) : l'y inclure ferait
    # rougir chaque apply de collection. La restriction est volontaire, et c'est
    # la limite connue de cet invariant.
    quarantaines = []
    for op in operations or ():
        try:
            if str(op.get("op_type") or "") in OPS_DE_QUARANTAINE:
                source = _cle_de_chemin(op.get("src_path"))
                if source:
                    quarantaines.append((source, op))
        except AttributeError:
            continue
    if not quarantaines:
        return []

    # PAR LES ANCETRES, ET NON PAIRE A PAIRE.
    #
    # La premiere version comparait chaque ligne du plan a chaque operation.
    # MESURE : 20 000 lignes x 2 000 operations = 4,7 SECONDES — un apply termine
    # qui se fige cinq secondes pour calculer un verdict, c'est un instrument
    # qu'on finit par debrancher.
    #
    # On indexe donc les sources de quarantaine, puis on remonte les ancetres de
    # chaque dossier de ligne : la profondeur d'un chemin est bornee (~10), le
    # nombre d'operations ne l'est pas.
    sources = {src for src, _ in quarantaines}
    emportees_par_source: Dict[str, set] = {src: set() for src in sources}
    for row_id, dossier in (dossiers_par_ligne or {}).items():
        cle = _cle_de_chemin(dossier)
        while cle:
            if cle in emportees_par_source:
                emportees_par_source[cle].add(str(row_id))
            parent = os.path.dirname(cle)
            if parent == cle:  # racine atteinte : `dirname('d:\')` rend `d:\`
                break
            cle = parent

    trouvees: List[Incoherence] = []
    for source, op in quarantaines:
        emportees = sorted(emportees_par_source.get(source) or ())
        if len(emportees) <= 1:
            continue
        op_type = str(op.get("op_type") or "")
        trouvees.append(
            Incoherence(
                code="une_operation_emporte_plusieurs_lignes",
                message=(
                    f"une seule operation {op_type} a emporte {len(emportees)} lignes du plan "
                    f"— l'utilisateur en a vu compter UNE"
                ),
                annonce={"operations_comptees": 1, "op_type": op_type},
                journal={"src_path": str(op.get("src_path") or ""), "lignes_emportees": emportees},
                reserve=(
                    "ne couvre QUE la quarantaine : un MOVE_DIR de collection emporte "
                    "legitimement plusieurs lignes, l'y inclure ferait rougir chaque "
                    "apply de collection."
                ),
            )
        )
    return trouvees


def comparer_annonce_et_journal(
    annonce: Mapping[str, Any],
    operations: Sequence[Mapping[str, Any]],
    *,
    evenements_audit: Sequence[Mapping[str, Any]] = (),
    dry_run: bool = False,
) -> Verdict:
    """Compare le payload rendu a l'utilisateur aux deux journaux du batch.

    Args:
        annonce: le payload d'apply (`ApplyResult` aplati, ou le dict rendu).
        operations: les lignes `apply_operations` du batch (cle `op_type`).
        evenements_audit: les evenements `apply_audit.jsonl` (cle `event`).
        dry_run: en apercu, rien n'est journalise. Les comparaisons de compte
            sont alors sans objet, et sans ce garde un dry-run leverait une
            incoherence a chaque fois — le genre de faux positif qui fait
            desapprendre a lire les verdicts.

    Returns:
        Un `Verdict` dont chaque incoherence porte ses deux termes.
    """
    comptes = _compter_par_type(operations)

    def _entier(cle: str) -> int:
        try:
            return int(annonce.get(cle) or 0)
        except (TypeError, ValueError):
            return 0

    ops_en_echec = sum(1 for op in operations or () if _en_echec(op)) + sum(
        1 for ev in evenements_audit or () if _en_echec(ev)
    )
    trouvees = [i for i in (_verifier_succes_menteur(_entier("errors"), ops_en_echec),) if i is not None]

    if dry_run:
        # En apercu rien n'est journalise : comparer des comptes n'aurait aucun
        # sens. On s'arrete ici, APRES la verification ci-dessus qui reste vraie.
        return Verdict(incoherences=trouvees, comptes_journal=comptes)

    # Tous les compteurs, pas seulement ceux qu'on croit pertinents : n'en
    # oublier qu'un fait rougir un apply sain (cf. COMPTEURS_D_ACTION_DISQUE).
    annonce_des_deplacements = {c: _entier(c) for c in COMPTEURS_D_ACTION_DISQUE}
    for inc in (
        _verifier_compte_de_quarantaine(_entier("quarantined"), comptes),
        _verifier_deplacements_tus(annonce_des_deplacements, comptes),
    ):
        if inc is not None:
            trouvees.append(inc)
    return Verdict(incoherences=trouvees, comptes_journal=comptes)

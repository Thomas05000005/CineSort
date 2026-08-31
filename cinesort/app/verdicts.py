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

CE QU'IL COUVRE REELLEMENT — MESURE, PAS ESPERE
------------------------------------------------
Une premiere redaction de ce module annoncait fermer #1062 ET #1103. C'est faux,
et la difference compte pour qui s'y fiera :

    #1103  COUVERT. `verifier_operations_qui_emportent_d_autres_lignes` (le
           dossier partage entre plusieurs lignes du plan) et
           `verifier_granularite_des_operations` (le type dit FICHIER, la
           destination est un DOSSIER) attrapent chacun sa moitie.
    #1062  NON. Son payload portait `errors: 300` : il etait HONNETE. C'est
           l'ecran qui ne lisait que `deleted`, et le correctif a ete pose cote
           front, deliberement (« mettre ok a faux des qu'errors > 0 ferait
           passer pour un echec une purge ou 299 fichiers sur 300 sont partis »).
    #1099  NON. Le plan etait tronque AVANT l'apply ; en aval tout concorde.
    #1097  NON. Ecran des reglages, route non couverte.

ATTEIGNABILITE DES INVARIANTS, MESUREE
---------------------------------------
    succes_annonce_malgre_des_echecs      INATTEIGNABLE aujourd'hui.
        Les TROIS `audit_logger.error` d'`apply_core` (2388, 2420, 2466) sont
        chacun precede d'un `res.errors += 1`, et `append_apply_operation` n'a
        aucun parametre d'erreur (INSERT 'PENDING', NULL en dur). Il ne peut
        donc pas exister d'echec journalise avec `errors == 0` a l'instant de
        l'apply. Conserve en DEFENSE EN PROFONDEUR — un quatrieme site d'erreur
        qui oublierait le compteur le rendrait vivant — mais il ne faut pas
        compter dessus, et surtout pas le presenter comme le cœur du module.
    deplacements_journalises_non_annonces ATTEIGNABLE, etroit : exige que les
        DIX-HUIT compteurs soient nuls simultanement.
    une_operation_emporte_plusieurs_lignes ATTEIGNABLE — c'est #1103.
    op_type_fichier_sur_un_dossier         ATTEIGNABLE — c'est #1103 aussi.

CE QUI A ETE RETIRE, ET POURQUOI
--------------------------------
Un cinquieme invariant comparait `result.quarantined` aux operations
`QUARANTINE_*`. Il produisait un FAUX POSITIF SYSTEMATIQUE :
`apply_core.move_to_review_bucket` journalise `QUARANTINE_*` pour tout passage
sous `_review` via une dizaine de sites, dont SEPT alimentent d'autres compteurs
(leftovers, doublons, sidecars, marques pour suppression). Un seul fichier de rab
suffisait a faire rougir un apply parfaitement sain. L'appariement 1:1 n'etant
pas demontrable, l'invariant n'a pas ete repare : il a ete retire.

CE QUI RESTE HORS DE PORTEE
---------------------------
Le sens ANNONCE > JOURNAL (le payload annonce plus que le journal ne porte)
n'est verifie nulle part, et c'est la forme de #1099. Le durcissement evident —
egalite des comptes — est refute par la mesure : il n'existe pas de bijection
entre les dix-huit compteurs et les `op_type`, et l'exiger recreerait le faux
positif qu'on vient de retirer.

Et ce qui n'est ni annonce, ni inscrit, ni deductible du plan — un fichier qu'un
tiers deplacerait pendant l'apply — echappe par construction. La photo du disque
garderait la son sens ; elle n'est simplement pas necessaire aux defauts connus.

DEUX JOURNAUX, ET IL EN FAUT DEUX
---------------------------------
Ce depot journalise l'apply a deux endroits qui ne voient PAS la meme chose, et
n'ont meme pas la meme forme :

- `apply_operations` (SQLite) — cle `op_type` en MAJUSCULES (`MOVE_FILE`).
  `record_apply_op` n'est appelee qu'APRES un move reussi et n'a aucun parametre
  d'erreur : cette table dit ce qui a BOUGE, presque jamais ce qui a echoue.
- `apply_audit.jsonl` (`read_apply_audit`) — cle `event` en minuscules
  (`op_move_file`), et surtout `event="error"`, ecrite en trois endroits de
  `apply_core`. C'est la seule trace des echecs DE L'APPLY ; `apply_rollback`,
  lui, ecrit bien `error_message` et `undo_status='FAILED'` dans
  `apply_operations` — mais lors de l'UNDO, donc apres que ce verdict est rendu.

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


def _verifier_journal_absent(annonce: Mapping[str, int], journal_ouvert: bool) -> Optional[Incoherence]:
    """Le sens qui manquait a `_verifier_deplacements_tus`, et il ment plus fort.

    Celui du dessus attrape « le journal porte des deplacements, le payload n'en
    annonce aucun » : l'utilisateur n'a alors aucune raison d'annuler. Celui-ci
    attrape l'inverse — le payload annonce douze rangements et AUCUN journal n'a
    ete ouvert. L'utilisateur voit « 12 films ranges » et un bouton *Annuler*
    qui ne fera rien.

    Cas reel, documente dans `apply_support.py` : quand `insert_apply_batch`
    echoue, `apply_batch_id` reste `None`, `record_apply_op` sort immediatement,
    et l'apply s'execute quand meme. Le mode degrade etait ecrit ; ce qui ne
    l'etait pas, c'est qu'il rendait un verdict VERT.

    Le critere est le journal JAMAIS OUVERT, pas le journal vide. La difference
    porte tout : un batch qui existe et ne contient rien peut avoir une cause
    legitime — un compteur qui n'ecrit pas d'operation — et le signaler serait un
    faux positif, l'espece qui fait desapprendre a lire les verdicts. Un batch
    jamais cree, lui, ne laisse aucune place au doute.
    """
    if journal_ouvert:
        return None
    total = sum(annonce.values())
    if total <= 0:
        return None
    return Incoherence(
        code="journal_absent_malgre_des_actions_annoncees",
        message=(
            f"le payload annonce {total} action(s) disque mais AUCUN journal "
            "d'apply n'a ete ouvert : ces deplacements ne sont pas annulables"
        ),
        annonce={c: v for c, v in annonce.items() if v},
        journal={"batch": None},
        reserve=(
            "ne dit PAS ce qui a bouge — sans journal, le detail est perdu. "
            "Dit seulement que l'annonce ne repose sur rien d'enregistre."
        ),
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
    cle = os.path.normcase(os.path.normpath(brut))
    # RETIRER le separateur final, sinon les partages RESEAU echappent.
    #
    # Pour un chemin UNC, `\\serveur\partage` EST la racine : `normpath` lui
    # garde son separateur final, exactement comme a `d:\`. Or la source d'une
    # operation arrive sans ce separateur. Les deux formes ne se rencontraient
    # donc jamais, et une ligne du plan imbriquee sous un dossier reseau mis en
    # quarantaine n'etait PAS vue — un trou invisible sur un poste a lettres de
    # lecteur, qui n'ont pas ce comportement.
    #
    # Le repli `or cle` protege le cas degenere ou tout serait separateur.
    return cle.rstrip("\\/") or cle


def verifier_granularite_des_operations(
    observations: Sequence[Mapping[str, Any]],
) -> List[Incoherence]:
    """Un `op_type` qui dit FICHIER sur une destination qui est un DOSSIER.

    C'EST LE CONTROLE QUE J'AVAIS ECARTE A TORT
    --------------------------------------------
    En lisant le correctif de #1103 j'avais conclu que l'`op_type` etait
    honnete — `QUARANTINE_DIR`, un dossier — et j'en avais deduit qu'un controle
    de granularite n'aurait rien vu. C'est FAUX, et l'issue le dit mot pour mot :
    le dossier partage partait journalise `QUARANTINE_FILE`.

    Le mecanisme l'explique : `folder / row.video` avec `row.video` vide vaut
    `folder`, et le code poursuivait sur la branche FICHIER. Le type enregistre
    contredisait donc la nature de ce qui bougeait — un `is_dir()` sur la
    destination suffisait a le voir.

    Cet invariant est complementaire de
    `verifier_operations_qui_emportent_d_autres_lignes` : celui-ci attrape le cas
    ou le dossier emporte d'AUTRES lignes du plan, celui-la le cas ou il n'en
    emporte aucune mais reste un dossier deplace sous un type FICHIER.

    L'observation `dst_est_dossier` est fournie par l'appelant : ce module reste
    pur, et un `is_dir()` par operation est borne par le nombre d'operations.

    Args:
        observations: `{"op_type", "dst_path", "dst_est_dossier"}` par operation.
            Une observation sans `dst_est_dossier` est IGNOREE — l'absence de
            mesure n'est pas une mesure negative.
    """
    trouvees: List[Incoherence] = []
    for obs in observations or ():
        try:
            op_type = str(obs.get("op_type") or "")
            est_dossier = obs.get("dst_est_dossier")
        except AttributeError:
            continue
        if not op_type.endswith("_FILE") or est_dossier is not True:
            continue
        trouvees.append(
            Incoherence(
                code="op_type_fichier_sur_un_dossier",
                message=(
                    f"une operation {op_type} porte sur une DESTINATION qui est un dossier "
                    "— c'est la signature de #1103"
                ),
                annonce={"op_type": op_type, "granularite_declaree": "FICHIER"},
                journal={"dst_path": str(obs.get("dst_path") or ""), "dst_est_dossier": True},
            )
        )
    return trouvees


def verifier_operations_qui_emportent_d_autres_lignes(
    operations: Sequence[Mapping[str, Any]],
    dossiers_par_ligne: Mapping[str, str],
) -> List[Incoherence]:
    """#1103 : une seule operation de quarantaine emportait TOUT un dossier.

    Le mecanisme de #1103 : `quarantine_row` resolvait la video par
    `folder / row.video`, et `PlanRow.video` « can be empty » — `folder / ""`
    vaut `folder`. Pour tout `kind` autre que `single`, ce dossier est PARTAGE
    entre plusieurs lignes du plan, et le mettre en quarantaine emportait les
    films des AUTRES lignes.

    La question est donc GEOMETRIQUE, et une comparaison de chemins y repond sans
    une seule E/S — elle reste vraie apres coup, quand la source n'existe plus.
    Complementaire de `verifier_granularite_des_operations` (cf. son docstring).

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
            # RENORMALISER l'ancetre, sans quoi les partages RESEAU echappent.
            #
            # `os.path.dirname` rend une racine UNC AVEC son separateur final
            # (`\\nas\films\`) alors que `_cle_de_chemin` d'une source la rend
            # SANS (`\\nas\films`). Les deux ne se rencontraient donc jamais, et
            # une ligne imbriquee sous un dossier reseau mis en quarantaine
            # n'etait PAS vue. Les chemins a lettre de lecteur n'ont pas ce
            # defaut, ce qui rendait le trou invisible sur un poste ordinaire.
            parent = _cle_de_chemin(os.path.dirname(cle))
            if parent == cle:  # racine atteinte : `dirname` s'y rend lui-meme
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
    journal_ouvert: bool = True,
) -> Verdict:
    """Compare le payload rendu a l'utilisateur aux deux journaux du batch.

    Args:
        annonce: le payload d'apply (`ApplyResult` aplati, ou le dict rendu).
        operations: les lignes `apply_operations` du batch (cle `op_type`).
        evenements_audit: les evenements `apply_audit.jsonl` (cle `event`).
        journal_ouvert: False quand `insert_apply_batch` a echoue et que le
            batch n'a JAMAIS ete cree. Par defaut True : sans ce defaut, tous
            les appelants existants rougiraient des la pose, et un garde qui
            mord tout le monde se fait desarmer dans l'heure.
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
        _verifier_deplacements_tus(annonce_des_deplacements, comptes),
        _verifier_journal_absent(annonce_des_deplacements, journal_ouvert),
    ):
        if inc is not None:
            trouvees.append(inc)
    return Verdict(incoherences=trouvees, comptes_journal=comptes)


#: Les statuts d'undo que `apply_operations.undo_status` peut porter.
STATUTS_UNDO: tuple[str, ...] = ("PENDING", "DONE", "FAILED", "SKIPPED")


def comparer_undo_annonce_et_journal(
    annonce: Mapping[str, Any],
    statuts_avant: Mapping[str, int],
    statuts_apres: Mapping[str, int],
) -> List[Incoherence]:
    """Le triangle sur l'UNDO — et pourquoi il se lit en DELTA.

    L'undo annonce `counts: {done, skipped, failed, irreversible}` et marque
    chaque operation dans `apply_operations.undo_status`. L'appariement est
    MESURE, pas suppose : chaque `done += 1` est suivi d'un
    `_mark_undo_status(DONE)`, chaque `failed += 1` d'un `FAILED`. Ce sont donc
    bien deux vues de la MEME population — contrairement au compte de
    quarantaine, retire pour cette raison exacte.

    POURQUOI LE DELTA, ET PAS L'ETAT
    ---------------------------------
    Un batch peut etre annule plusieurs fois : `_build_undo_preview_payload` ne
    filtre pas sur `undo_status`. Apres deux passages, le journal porte la SOMME
    des deux, alors que `counts` ne decrit que le dernier. Comparer des etats
    absolus produirait donc un faux positif a chaque reprise. On compare les
    ECARTS entre avant et apres.

    LA DIVERGENCE EST ATTEIGNABLE, ET ELLE COUTE CHER
    --------------------------------------------------
    `_mark_undo_status` avale `sqlite3.Error` et `OSError` DELIBEREMENT : « le
    statut en base est un ARTEFACT DE RAPPORT », son echec ne doit jamais
    interrompre une restauration en cours. Une base verrouillee fait donc
    annoncer N fichiers restaures alors que le journal en garde moins — et au
    prochain essai ces operations seront REJOUEES, puisque l'undo complet ne
    filtre pas sur le statut.

    Args:
        annonce: le `counts` du payload d'undo.
        statuts_avant: comptes par `undo_status` AVANT la boucle.
        statuts_apres: comptes par `undo_status` APRES.
    """

    def _delta(statut: str) -> int:
        return int(statuts_apres.get(statut, 0) or 0) - int(statuts_avant.get(statut, 0) or 0)

    def _annonce(cle: str) -> int:
        try:
            return int((annonce or {}).get(cle) or 0)
        except (TypeError, ValueError):
            return 0

    trouvees: List[Incoherence] = []

    restaures_annonces, restaures_inscrits = _annonce("done"), _delta("DONE")
    if restaures_annonces != restaures_inscrits:
        trouvees.append(
            Incoherence(
                code="undo_compte_restaure_diverge",
                message=(
                    f"l'undo annonce {restaures_annonces} restauration(s) mais le journal "
                    f"n'en a inscrit que {restaures_inscrits}"
                ),
                annonce={"done": restaures_annonces},
                journal={"delta_DONE": restaures_inscrits},
                reserve=(
                    "un statut non persiste ne veut PAS dire que le fichier n'a pas bouge : "
                    "`_mark_undo_status` s'execute APRES la restauration. Le risque est le "
                    "REJEU au prochain essai, pas la perte."
                ),
            )
        )

    echecs_annonces, echecs_inscrits = _annonce("failed"), _delta("FAILED")
    if echecs_annonces == 0 and echecs_inscrits > 0:
        trouvees.append(
            Incoherence(
                code="undo_succes_annonce_malgre_des_echecs",
                message=f"l'undo annonce failed=0 mais le journal a inscrit {echecs_inscrits} echec(s)",
                annonce={"failed": 0},
                journal={"delta_FAILED": echecs_inscrits},
            )
        )
    return trouvees

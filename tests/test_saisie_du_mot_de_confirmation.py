"""La modale de danger sait exiger un MOT TAPE — et « Tout réinitialiser » l'exige.

LE DEFAUT. `settings.reset_all_user_data` refuse tout appel dont `confirmation`
ne vaut pas exactement « RESET » (`reset_support.py:266`). Aucun ecran ne pouvait
produire ce mot : `dangerConfirmModal` n'avait aucune affordance de saisie. La
capacite — supprimer base, reglages, historique et caches, apres sauvegarde ZIP —
etait donc INATTEIGNABLE depuis toute l'application. C'etait la seule des dix
methodes de la vague B3 restee dans ce cas, et le tri des routes orphelines la
declarait « NON cablable » pour cette raison precise.

CE QUE CES TESTS EPROUVENT, dans l'ordre de ce qui ferait le plus de degats :

1. LE MOT TAPE PART TEL QUEL. Envoyer la constante attendue a la place rendrait
   le garde du backend decoratif : il verifierait un mot que le front lui aurait
   souffle, quoi que l'utilisateur ait ecrit. C'est le meme piege qu'un test qui
   verifie sa propre copie plutot que le code livre.

2. LES DEUX VERROUS SONT INDEPENDANTS. Le decompte ne doit pas armer le bouton
   quand le mot manque, et le mot ne doit pas l'armer pendant le decompte. Les
   melanger redonnerait un clic-reflexe sur l'action la plus destructive de
   l'application.

3. LA COMPARAISON EST EXACTE. « reset » n'est pas « RESET » ; le backend
   refuserait de toute facon, et un ecran qui promet l'inverse fabrique un echec
   la ou l'utilisateur croyait avoir agi.

Le DOM est reduit au strict necessaire : ce sont la logique d'armement et le
payload qui sont eprouves, pas le rendu du navigateur. La PRESENCE du champ dans
le HTML produit est verifiee a part — sur la sortie de la fonction, jamais sur
son source.
"""

from __future__ import annotations

import unittest

from tests._jsexec import DASHBOARD, ROOT, require_node, run_module_test

_MODAL = DASHBOARD / "components" / "modal.js"

#: Un DOM minimal : `querySelector` rend des noeuds prefabriques au lieu
#: d'analyser le HTML. On n'eprouve pas le navigateur, on eprouve l'armement.
_STUBS = r"""
const $ = () => null;
const escapeHtml = (s) =>
  String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

globalThis.__html = "";
globalThis.__minuteurs = [];
globalThis.setInterval = (fn, ms) => { globalThis.__minuteurs.push(fn); return globalThis.__minuteurs.length; };
globalThis.clearInterval = () => {};

function noeud(extra) {
  return Object.assign(
    {
      disabled: false,
      value: "",
      textContent: "",
      isConnected: true,
      _ev: {},
      addEventListener(type, fn) { this._ev[type] = fn; },
      removeEventListener() {},
      focus() {},
      remove() {},
      // La modale cherche le compteur DANS le bouton de confirmation.
      querySelector(sel) { return globalThis.__noeuds[sel] || null; },
      querySelectorAll: () => [],
      declencher(type, ev) { if (this._ev[type]) return this._ev[type](ev || {}); },
    },
    extra || {}
  );
}

globalThis.__noeuds = {};
globalThis.document = {
  activeElement: null,
  addEventListener() {}, removeEventListener() {},
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  createElement() {
    return {
      id: "", className: "", style: {}, _ev: {},
      setAttribute() {}, removeAttribute() {},
      // L'ETAT INITIAL DU BOUTON EST UN ATTRIBUT HTML, pas une affectation JS.
      // Un DOM factice qui l'ignore laisserait le bouton arme des le depart et
      // rendrait vert un clic qui, dans un navigateur, ne partirait jamais. On
      // interprete donc ce seul attribut, comme le ferait le navigateur.
      set innerHTML(v) {
        globalThis.__html = v;
        const b = globalThis.__noeuds["[data-danger-confirm]"];
        if (b) b.disabled = /data-danger-confirm[^>]*\sdisabled/.test(v);
      },
      get innerHTML() { return globalThis.__html; },
      querySelector(sel) { return globalThis.__noeuds[sel] || null; },
      querySelectorAll: () => [],
      addEventListener(type, fn) { this._ev[type] = fn; },
      removeEventListener() {},
      remove() {},
      appendChild() {},
      contains: () => false,
    };
  },
  body: { appendChild() {}, removeChild() {} },
};

/** Prepare les noeuds que la modale ira chercher, et rend le trio utile. */
globalThis.preparer = () => {
  const annuler = noeud();
  const confirmer = noeud();
  const saisie = noeud();
  globalThis.__noeuds = {
    "[data-danger-cancel]": annuler,
    "[data-danger-confirm]": confirmer,
    "[data-danger-saisie]": saisie,
    "[data-danger-countdown]": noeud(),
  };
  return { annuler, confirmer, saisie };
};
"""

_EXTRA = (
    "export const __danger = dangerConfirmModal;\n"
    "export const __show = showModal;\n"
    "export const __close = closeModal;\n"
    "export const __courante = modaleCourante;\n"
)
_EXIT = "\nprocess.exit(0);\n"


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(_MODAL, stubs=_STUBS, extra=_EXTRA, driver=driver + _EXIT, timeout=90)


class LeMotTAPEArmeLeBoutonTests(_Base):
    def test_sans_le_mot_le_bouton_reste_desarme(self) -> None:
        res = self._run(
            r"""
const { confirmer, saisie } = globalThis.preparer();
let confirme = false;
M.__danger({ title: "Tout effacer ?", requireTyped: "RESET", countdownSeconds: 0,
             onConfirm: () => { confirme = true; } });
const auDepart = confirmer.disabled;

saisie.value = "RESE";
saisie.declencher("input");
const partiel = confirmer.disabled;

confirmer.declencher("click");
__emit({ auDepart, partiel, confirme });
"""
        )
        self.assertTrue(res["auDepart"], "le bouton est arme AVANT toute saisie")
        self.assertTrue(res["partiel"], "un mot incomplet arme deja le bouton")
        self.assertFalse(res["confirme"], "l'action est partie sans le mot")

    def test_le_mot_EXACT_arme_le_bouton(self) -> None:
        res = self._run(
            r"""
const { confirmer, saisie } = globalThis.preparer();
M.__danger({ title: "Tout effacer ?", requireTyped: "RESET", countdownSeconds: 0, onConfirm: () => {} });
saisie.value = "RESET";
saisie.declencher("input");
__emit({ arme: !confirmer.disabled });
"""
        )
        self.assertTrue(res["arme"], "le mot exact n'arme pas le bouton : l'action reste inatteignable")

    def test_la_casse_COMPTE(self) -> None:
        """Le backend compare `!= "RESET"` : accepter « reset » a l'ecran
        fabriquerait un echec la ou l'utilisateur croit avoir agi."""
        res = self._run(
            r"""
const { confirmer, saisie } = globalThis.preparer();
M.__danger({ title: "T", requireTyped: "RESET", countdownSeconds: 0, onConfirm: () => {} });
saisie.value = "reset";
saisie.declencher("input");
__emit({ arme: !confirmer.disabled });
"""
        )
        self.assertFalse(res["arme"], "« reset » a ete accepte : le backend le refusera")

    def test_les_espaces_de_BORD_sont_tolerees(self) -> None:
        """Un copier-coller emporte souvent une espace. Le refuser serait une
        rigueur sans objet : le mot, lui, est bien celui-la."""
        res = self._run(
            r"""
const { confirmer, saisie } = globalThis.preparer();
M.__danger({ title: "T", requireTyped: "RESET", countdownSeconds: 0, onConfirm: () => {} });
saisie.value = "  RESET  ";
saisie.declencher("input");
__emit({ arme: !confirmer.disabled });
"""
        )
        self.assertTrue(res["arme"])


class LesDeuxVerrousSontINDEPENDANTSTests(_Base):
    def test_la_fin_du_decompte_n_arme_PAS_sans_le_mot(self) -> None:
        """Sinon le delai de la regle n3 devient le SEUL verrou, et le mot tape
        n'est plus qu'une decoration que le temps finit par lever."""
        res = self._run(
            r"""
const { confirmer } = globalThis.preparer();
M.__danger({ title: "T", requireTyped: "RESET", countdownSeconds: 1, onConfirm: () => {} });
// Le minuteur pose par la modale, execute jusqu'a expiration.
globalThis.__minuteurs.forEach((tic) => tic());
__emit({ arme: !confirmer.disabled });
"""
        )
        self.assertFalse(
            res["arme"],
            "le decompte a arme le bouton alors que le mot n'est pas tape",
        )

    def test_le_mot_n_arme_PAS_pendant_le_decompte(self) -> None:
        res = self._run(
            r"""
const { confirmer, saisie } = globalThis.preparer();
M.__danger({ title: "T", requireTyped: "RESET", countdownSeconds: 3, onConfirm: () => {} });
saisie.value = "RESET";
saisie.declencher("input");
__emit({ arme: !confirmer.disabled });
"""
        )
        self.assertFalse(res["arme"], "le mot a court-circuite le delai de la regle n3")

    def test_les_deux_ensemble_arment(self) -> None:
        res = self._run(
            r"""
const { confirmer, saisie } = globalThis.preparer();
M.__danger({ title: "T", requireTyped: "RESET", countdownSeconds: 1, onConfirm: () => {} });
saisie.value = "RESET";
saisie.declencher("input");
globalThis.__minuteurs.forEach((tic) => tic());
__emit({ arme: !confirmer.disabled });
"""
        )
        self.assertTrue(res["arme"], "mot tape ET decompte fini : le bouton doit s'armer")


class UneActionENGAGEEneSeReARMEPasTests(_Base):
    """Le clic desarme le bouton pour empecher une double soumission, mais la
    modale reste AFFICHEE tant que `onConfirm` n'a pas resolu — et un wipe dure.
    Sans garde, retoucher le champ pendant ce temps re-armait le bouton : un
    second « Tout reinitialiser » partait pendant le premier."""

    def test_retoucher_le_champ_pendant_l_action_ne_rearme_PAS(self) -> None:
        res = self._run(
            r"""
const { confirmer, saisie } = globalThis.preparer();
let departs = 0;
let debloquer;
M.__danger({
  title: "T", requireTyped: "RESET", countdownSeconds: 0,
  onConfirm: () => { departs += 1; return new Promise((r) => { debloquer = r; }); },
});
saisie.value = "RESET";
saisie.declencher("input");
confirmer.declencher("click");          // l'action part et ne resout PAS
const desarmeApresClic = confirmer.disabled;

// L'utilisateur retouche le champ pendant que le wipe tourne.
saisie.value = "RESE";
saisie.declencher("input");
saisie.value = "RESET";
saisie.declencher("input");
const rearme = !confirmer.disabled;

confirmer.declencher("click");          // un second clic ne doit RIEN lancer
debloquer && debloquer();
__emit({ desarmeApresClic, rearme, departs });
"""
        )
        self.assertTrue(res["desarmeApresClic"], "le clic ne desarme pas le bouton")
        self.assertFalse(res["rearme"], "retoucher le champ a RE-ARME une action deja en vol")
        self.assertEqual(res["departs"], 1, "l'action est partie DEUX fois")


class LaSAISIEEstTRANSMISEAuRappelTests(_Base):
    def test_onConfirm_recoit_CE_QUI_A_ETE_TAPE(self) -> None:
        """Si l'appelant devait fournir la constante lui-meme, le garde du
        backend ne verifierait plus rien : il relirait ce que le front lui a
        souffle."""
        res = self._run(
            r"""
const { confirmer, saisie } = globalThis.preparer();
let recu = null;
M.__danger({ title: "T", requireTyped: "RESET", countdownSeconds: 0,
             onConfirm: (mot) => { recu = mot; } });
saisie.value = "RESET";
saisie.declencher("input");
confirmer.declencher("click");
__emit({ recu });
"""
        )
        self.assertEqual(res["recu"], "RESET", "la saisie de l'utilisateur n'est pas transmise")

    def test_la_saisie_part_AUSSI_par_la_branche_closeBeforeConfirm(self) -> None:
        """`dangerConfirmModal` a DEUX chemins de confirmation : celui qui ferme
        la modale avant de lancer l'action (pour que la progression soit visible)
        et celui qui attend. Les deux doivent transmettre la saisie — sinon la
        capacite se perdrait au premier appelant qui demande le premier chemin,
        et le backend recevrait une confirmation vide."""
        res = self._run(
            r"""
const { confirmer, saisie } = globalThis.preparer();
let recu = "PAS APPELE";
M.__danger({ title: "T", requireTyped: "RESET", countdownSeconds: 0,
             closeBeforeConfirm: true, onConfirm: (mot) => { recu = mot; } });
saisie.value = "RESET";
saisie.declencher("input");
await confirmer.declencher("click");
__emit({ recu });
"""
        )
        self.assertEqual(res["recu"], "RESET", "la branche closeBeforeConfirm perd la saisie")


class LeChampEstREELLEMENTRenduTests(_Base):
    def test_le_HTML_produit_porte_le_champ_et_le_mot(self) -> None:
        """Assertion sur la SORTIE de la fonction, jamais sur son source : c'est
        le HTML livre au navigateur qui est lu ici."""
        res = self._run(
            r"""
globalThis.preparer();
M.__danger({ title: "T", requireTyped: "RESET", countdownSeconds: 0, onConfirm: () => {} });
const avec = globalThis.__html;
globalThis.__html = "";
globalThis.preparer();
M.__danger({ title: "T", countdownSeconds: 0, onConfirm: () => {} });
__emit({ avec, sans: globalThis.__html });
"""
        )
        self.assertIn("data-danger-saisie", res["avec"], "le champ de saisie n'est pas rendu")
        self.assertIn("RESET", res["avec"], "le mot a taper n'est pas montre a l'utilisateur")
        self.assertNotIn(
            "data-danger-saisie",
            res["sans"],
            "le champ apparait sur des modales qui n'exigent aucun mot",
        )


class LeCONTENEURSaitQuiIlPorteTests(_Base):
    """LE VRAI `modal.js`, pas un stub. Les trois modales de contenu partagent un
    conteneur unique ; c'est ici que vit la seule reponse possible a « suis-je
    encore la modale a l'ecran ? ».

    Les batteries des trois modules eprouvent leur JETON, mais avec un stub de
    `showModal` : mutation faite, deux mutants de `modal.js` y survivaient — non
    par faiblesse d'assertion, mais parce que ces tests-la n'executent pas ce
    fichier. Ils sont donc eprouves ICI.
    """

    def test_ouvrir_annonce_le_proprietaire(self) -> None:
        res = self._run(
            r"""
globalThis.preparer();
M.__show({ title: "T", body: "", actions: [], proprietaire: "simulateur" });
__emit({ courante: M.__courante() });
"""
        )
        self.assertEqual(res["courante"], "simulateur")

    def test_ouvrir_une_AUTRE_modale_change_le_proprietaire(self) -> None:
        """C'est le cas qui detruisait une modale sous l'utilisateur : le module
        precedent doit pouvoir constater qu'il n'est plus a l'ecran."""
        res = self._run(
            r"""
globalThis.preparer();
M.__show({ title: "A", body: "", actions: [], proprietaire: "simulateur" });
M.__show({ title: "B", body: "", actions: [], proprietaire: "regles" });
__emit({ courante: M.__courante() });
"""
        )
        self.assertEqual(res["courante"], "regles", "le proprietaire n'a pas change : le jeton ne perimerait rien")

    def test_FERMER_relache_le_proprietaire(self) -> None:
        res = self._run(
            r"""
globalThis.preparer();
M.__show({ title: "T", body: "", actions: [], proprietaire: "simulateur" });
M.__close();
__emit({ courante: M.__courante() });
"""
        )
        self.assertEqual(res["courante"], "", "une modale FERMEE laisse encore son module se croire a l'ecran")

    def test_fermer_SANS_modale_ouverte_relache_quand_meme(self) -> None:
        """`closeModal` sort tot quand aucun overlay n'existe. Si le proprietaire
        n'etait relache qu'apres cette sortie, une fermeture deja consommee
        laisserait le module se croire courant."""
        res = self._run(
            r"""
globalThis.preparer();
M.__show({ title: "T", body: "", actions: [], proprietaire: "simulateur" });
globalThis.document.getElementById = () => null;
M.__close();
__emit({ courante: M.__courante() });
"""
        )
        self.assertEqual(res["courante"], "")

    def test_une_modale_SANS_proprietaire_n_en_usurpe_aucun(self) -> None:
        """Les autres appelants de `showModal` ne passent pas `proprietaire` : ils
        doivent laisser le champ VIDE, pas heriter du precedent."""
        res = self._run(
            r"""
globalThis.preparer();
M.__show({ title: "A", body: "", actions: [], proprietaire: "simulateur" });
M.__show({ title: "B", body: "", actions: [] });
__emit({ courante: M.__courante() });
"""
        )
        self.assertEqual(res["courante"], "", "une modale sans proprietaire a herite de celui d'avant")


class LeMotTAPEEstRAREEtCEstVouluTests(unittest.TestCase):
    """LE CRITERE, VERROUILLE — sinon la saisie s'etend par habitude et cesse de
    proteger.

    Le depot compte une vingtaine de confirmations dangereuses ; TROIS seulement
    portent un mot a taper. Deux conditions, ENSEMBLE :

      1. la perte est IRRECUPERABLE PAR L'APPLICATION (ni undo, ni corbeille, ni
         restauration depuis l'interface) ;
      2. la portee n'est PAS une selection que l'utilisateur vient de faire.

    Ce que cela EXCLUT, et pourquoi — verifie dans le code, pas suppose :
    « supprimer N films » appelle `mark_for_deletion_bulk` et ne fait que
    MARQUER ; « lancer l'apply » a un undo ; « regenerer le token » se refait ;
    « re-calculer les scores » se recalcule. Aucune ne remplit les DEUX
    conditions.

    Ce test echoue si un mot apparait ailleurs sans que la liste soit mise a
    jour — c'est-a-dire sans que quelqu'un ait repasse par le critere.
    """

    #: Les seules formes autorisees a exiger un mot, et pourquoi.
    _AUTORISES = (
        "requireTyped: conf.motAConfirmer",  # table des actions : porte reset_all_user_data
        'requireTyped: "VIDER"',  # purge integrale du bucket _review
    )

    def test_aucun_mot_n_a_ete_ajoute_sans_repasser_par_le_critere(self) -> None:
        vue = (ROOT / "web" / "dashboard" / "views" / "parametres.js").read_text(encoding="utf-8")
        lignes = [
            ligne.strip()
            for ligne in vue.splitlines()
            if "requireTyped" in ligne and not ligne.strip().startswith(("//", "*", "<!--"))
        ]
        inconnues = [l for l in lignes if not any(a in l for a in self._AUTORISES)]
        self.assertEqual(
            inconnues,
            [],
            "un mot a taper est apparu sur un site non recense. Repasser par le critere "
            "(irrecuperable ET portee non choisie), puis mettre a jour _AUTORISES.",
        )

    def test_le_RESTE_du_dashboard_n_en_porte_aucun(self) -> None:
        """Les autres ecrans n'ont que des actions reversibles ou scopees."""
        ailleurs = sorted(
            f.name
            for f in (ROOT / "web" / "dashboard").rglob("*.js")
            if f.name not in {"parametres.js", "modal.js"} and "requireTyped" in f.read_text(encoding="utf-8")
        )
        self.assertEqual(ailleurs, [], f"un mot a taper est apparu hors du perimetre recense : {ailleurs}")


if __name__ == "__main__":
    unittest.main()

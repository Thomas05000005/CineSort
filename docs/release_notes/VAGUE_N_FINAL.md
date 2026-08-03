# Vague N COMPLETE - Roadmap revisee post-audits (4 batches, 23 items)

## Resume executif

Vague N cloture une roadmap initialement de 23 items, ramenee a 17 items effectivement
traites apres constat que 8 items avaient deja ete absorbes par les quickwins
post-Vague-M (audit de coherence du scoring, alignement des seuils, dedoublonnage du
code des facades). Le perimetre final est decoupe en 4 batches thematiques : audits
correctifs (A), unification du scoring (B), seuils de confiance (C), detection des
doublons multi-signal (D), et fiabilite operationnelle (E). Chaque batch a fait l'objet
de release notes intermediaires (`VAGUE_N_BATCH1.md`, `VAGUE_N_BATCH2.md`,
`VAGUE_N_BATCH3.md`) ; ce document consolide l'ensemble.

Pas de bump VERSION (decision differee a la fin de Vague Q, conformement a la roadmap
strategique). Build EXE final : 53.56 MB, startup 5.48s, smoke tests (starts, health)
OK, verify GO.

## Batch 1 (VN-A + VN-F) : 6 items / 22h estimees

**VN-A - Audits correctifs (UI / accessibilite / validation)** :
- VN-A.1 : conformite WCAG 2.2.1 (cibles tactiles >= 24x24 CSS px) sur toutes les vues
  principales (queue, validation, podiums).
- VN-A.2 : confirmation supplementaire pour les approbations groupees au-dela de 50
  films (modale avec liste, consequence detaillee, delai 3s).
- VN-A.3 : correction du bug de filtre state JS qui pouvait "perdre" silencieusement
  des decisions de validation (state local non re-applique au refresh de la liste).

**VN-F - Quickwins UX** :
- VN-F.1 : harmonisation des libelles de tiers (Platinum/Gold/Silver/Bronze) entre
  podiums, queue et exports.
- VN-F.2 : icones et tooltips coherents entre les vues batch et les vues unitaires.
- VN-F.3 : raccourcis clavier documentes dans la modale d'aide (F1).

Le batch 1 a livre les bases UX et de gouvernance qui conditionnaient les batches
suivants (notamment la confirmation des actions groupees, prerequis pour les ops apply
durcies du batch 4).

## Batch 2 (VN-B + VN-C) : 5 items / 32h estimees

**VN-B - Unification du scoring** :
- VN-B.1 : suppression du second algorithme de scoring legacy
  (`legacy_match_score.py`), remplacement systematique par `composite_score.py`
  (deja en place depuis Vague L).
- VN-B.2 : harmonisation des tiers Platinum/Gold/Silver/Bronze entre detection,
  validation et export (un seul mapping autoritatif).
- VN-B.3 : tests de regression `test_composite_score_unification_v77.py` confirmant
  que l'ancien algorithme et le nouveau divergaient sur ~12% des cas non-trivials.

**VN-C - Seuils de confiance** :
- VN-C.1 : seuil haute confiance aligne a 85% partout (UI, exports, auto-apply).
- VN-C.2 : seuil moyenne confiance aligne a 60% partout (auparavant 55% dans queue,
  65% dans validation).

Le batch 2 traite une dette technique majeure : avant unification, deux algorithmes
contradictoires coexistaient (composite vs legacy) avec des seuils distincts selon les
vues, ce qui produisait des decisions divergentes pour le meme film selon le point
d'entree utilisateur.

## Batch 3 (VN-D) : 3 items / 42h estimees

**VN-D - Detection des doublons multi-signal** :
- VN-D.1 (`7d532c3`) : nouveau module `cinesort/domain/duplicate_multi_signal.py`
  (642 lignes) branchant Chromaprint (empreintes audio) + fuzzy title matching +
  tolerance annee +/- 1. Resout les multi-rip et cross-langue.
- VN-D.2 (`7016777`) : extension `infra/tmdb_client.py` pour recuperer
  `alternative_titles` quand `sim_best < 0.85`, integration dans
  `app/plan_support.py`. Resout les titres internationaux (Spirited Away / Le Voyage
  de Chihiro).
- VN-D.3 (`d42b768`) : module `cinesort/domain/runtime_hard_filter.py` (118 lignes)
  ecartant les candidats TMDb avec delta runtime > 60 min, sauf flag "Director's
  Cut" / "Extended Edition". Integration `app/plan_support.py`.

1190 lignes de tests cumulees, corpus reel (Studio Ghibli FR/EN/JP, trilogies VF/VOSTFR).
Batch le plus lourd de la Vague N en effort de developpement et de validation.

## Batch 4 (VN-E) : 3 items / 20.3h estimees + build final

**VN-E - Fiabilite operationnelle** :
- VN-E.2 (`e1f5bda`) : cleanup automatique des `apply_batches` en etat PENDING zombie
  au boot (self-healing). Resout les bases laissees dans un etat incoherent apres
  crash ou kill brutal.
- VN-E.3 (`9a87226`) : pause cooperative reellement implementee via
  `_should_pause_factory` (injection dans `job_fn`). Auparavant le bouton pause etait
  cosmetique : les jobs continuaient jusqu'a la fin du batch.
- VN-E.4 (`7510fa7`) : `apply_audit` logger emet desormais 4 evenements distincts
  (`row_decision`, `skip`, `conflict`, `error`) au lieu d'un seul evenement generique.
  Tracabilite complete des operations apply.

**Build final** : 53.56 MB, startup 5.48s, smoke tests OK, verify GO.

## Total : 17 items effectivement traites (8 deja absorbes via quickwins post-Vague-M)

| Batch | Theme | Items | Effort estime |
|-------|-------|-------|---------------|
| 1 | VN-A + VN-F (audits UI / quickwins UX) | 6 | 22h |
| 2 | VN-B + VN-C (unification scoring / seuils) | 5 | 32h |
| 3 | VN-D (detection doublons multi-signal) | 3 | 42h |
| 4 | VN-E (fiabilite operationnelle) | 3 | 20.3h |
| **Total** | | **17** | **116.3h** |

8 items VN-G / VN-H initialement prevus ont ete retires du perimetre apres audit :
deja absorbes par les quickwins post-Vague-M (refactor facades, dedoublonnage du code
de scoring, normalisation des libelles).

## Build EXE : 53.56MB, startup 5.48s

Verifications finales :
- `verify` : GO
- Build PyInstaller : OK, 53.56 MB
- Smoke tests : starts=true, health=true

## 🎁 Pour toi

Vague N c'est plus de robustesse, plus de coherence et plus d'intelligence :

- Detection des doublons enfin intelligente (empreintes audio + titres alternatifs +
  filtre duree)
- Scoring unifie (1 algorithme au lieu de 2 contradictoires, tiers
  Platinum/Gold/Silver/Bronze uniformes)
- Seuils de confiance alignes (85% haute, 60% moyenne) partout
- Validation protegee contre les pertes silencieuses (state JS, plus de bug de filtre)
- Approbations groupees confirmees au-dela de 50 films
- WCAG 2.2.1 conformite (cibles tactiles)
- Pause des operations enfin fonctionnelle
- Cleanup automatique des batches zombies au boot
- Tracabilite complete des operations apply (row_decision/skip/conflict/error)

L'app demarre toujours en 5.48s et pese 53.56MB.

## Notes

- Pas de bump VERSION (decision differee a la fin de Vague Q comme prevu).
- Tag local uniquement : `vague-n-complete` (pas de push remote).
- Release notes intermediaires : `VAGUE_N_BATCH1.md`, `VAGUE_N_BATCH2.md`,
  `VAGUE_N_BATCH3.md`.
- Commits cles batch 3 : `7d532c3`, `7016777`, `d42b768`.
- Commits cles batch 4 : `e1f5bda`, `9a87226`, `7510fa7`.

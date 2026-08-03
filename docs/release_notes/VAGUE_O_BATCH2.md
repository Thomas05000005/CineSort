# Vague O batch 2 - VO-D OpType StrEnum ex nihilo

## Resume technique

Deuxieme batch de la Vague O : introduction d'une `StrEnum` Python 3.13 `OpType`
(RENAME / MOVE / NOOP) comme single source of truth pour `RenameProposal.op_type`,
avec backward compatibility absolue via les aliases `OP_TYPE_*` derives de
`OpType.<member>.value`. 2 phases (definition + migration des call-sites tests),
zero impact production, aucun bump VERSION, aucune nouvelle dependance.

## Changements par item

### VO-D : OpType StrEnum

- **VO-D-1** (`22e74fc`) - `feat(vo-d-1)`: ajoute la `StrEnum OpType`
  (`RENAME`/`MOVE`/`NOOP`) dans `cinesort/domain/probe_models.py` comme source
  unique de verite pour `RenameProposal.op_type`. Les constantes `OP_TYPE_*`
  existantes deviennent des alias derives de `OpType.<member>.value` : la
  StrEnum garantit `OpType.RENAME == "RENAME"` (equality + isinstance str),
  donc la backward compat est totale. Helper `OpType.from_str()` pour
  normaliser des entrees externes (case insensitive, strip) avec `ValueError`
  explicite sur valeur inconnue. 198 lignes de tests dedies
  (`test_op_type_strenum_v77.py`).
- **VO-D-2** (`1fbf998`) - `refactor(vo-d-2)`: migre les 4 instanciations
  `RenameProposal(op_type=OP_TYPE_*)` dans `test_probe_models_extensions_v77.py`
  vers `OpType.RENAME/MOVE/NOOP` pour type safety + IDE/mypy discovery.
  Strategie pragmatique : assignment migre vers `OpType.*`, comparaisons
  `== "RENAME"` conservees (StrEnum equality fonctionne), aliases `OP_TYPE_*`
  preserves dans `__all__`. Bonus durcissement `RenameProposal.to_dict()` :
  normalisation `OpType -> str` pur pour garantir l'invariant json-safe quel
  que soit le type d'entree.

## Tests

- 24/24 PASS sur `test_op_type_strenum_v77.py` (nouveau, VO-D-1).
- 24/24 PASS sur `test_probe_models_extensions_v77.py` (migre, VO-D-2).
- 44 PASS / 0 FAIL sur l'union `apply_audit + apply_core + probe_models`.
- Pas de regression VN-E.4 `apply_audit_events_emitted`.
- JS frontend `historique.js` INTOUCHE : `op.op_type` cote dashboard
  utilise le vocabulaire journal/apply (`MOVE_FILE`/`MOVE_DIR`/`QUARANTINE`/...),
  vocabulaire separe de `RenameProposal.op_type`, zero confusion possible.

## 🎁 Pour toi

Sous le capot, le typage des operations est plus rigoureux (StrEnum Python 3.13)
ce qui prepare des verifications plus precises pour les vagues suivantes. Aucun
changement visible cote utilisateur.

## Notes

- Pas de bump VERSION (decision differee, coherent avec Vague N + VO batch 1).
- Tag local uniquement : `vague-o-batch2` (pas de push remote).
- Commits inclus : `22e74fc`, `1fbf998`.
- Zero fichier production modifie hors definition (`probe_models.py`).

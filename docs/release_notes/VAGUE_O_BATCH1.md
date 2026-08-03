# Vague O batch 1 - VO-A SQLite pragmas profils + NAS validation

## Resume technique

Premier batch de la Vague O (Performance & infra) : optimisation systematique des
parametres SQLite (PRAGMAs) selon le type de stockage detecte (SSD local, HDD local,
NAS SMB, fallback), avec garde-fou anti-corruption sur les partages reseau et benchmark
optionnel depuis les parametres. 4 commits couvrant les 4 phases (backend, migration, UI,
NAS validation). Aucun bump VERSION, aucune nouvelle dependance externe.

## Changements par item

### VO-A : profils SQLite + NAS validation

- **VO-A backend** (`1ab45ca`) - `feat(vo-a-backend)`: nouveau module
  `cinesort/infra/pragma_profile.py` (4 profils SQLite : `ssd_local`, `hdd_local`,
  `nas_smb`, `fallback`) avec detection automatique du type de stockage. Refactorisation
  de `connect_sqlite()` pour appliquer le profil adapte (journal_mode, synchronous,
  cache_size, mmap_size, temp_store, wal_autocheckpoint). Profil `nas_smb` force
  `synchronous=FULL` et desactive WAL pour eviter la corruption sur partages reseau.
- **VO-A migration** (`17556ee`) - `feat(vo-a-migration)`: migration 028 introduisant la
  table `pragma_history` qui trace chaque application de profil (timestamp, profil
  applique, valeurs effectives) pour audit et debug. Apply trace persiste pour comparer
  perf avant/apres entre profils.
- **VO-A UI** (`ea1dd16`) - `feat(vo-a-ui)`: nouvelle section "Avance" dans les parametres
  permettant de visualiser le profil actif et de le forcer manuellement (override de la
  detection automatique). Integration de `dangerConfirmModal` en mode EXCLUSIVE pour le
  changement de profil (action consideree dangereuse car impacte durabilite et perf).
- **VO-A NAS** (`c61b335`) - `feat(vo-a-nas)`: module `nas_validation` ajoutant un
  benchmark lancable depuis les parametres (mesure latence write/read/fsync reels) +
  `DB_LOCAL_GUARD` qui detecte les chemins UNC (`\\serveur\share`) au demarrage et
  affiche un avertissement si la DB est sur un partage reseau (risque corruption + perf
  degradee).

## Tests

- Tests unitaires sur la detection de profil (SSD vs HDD vs UNC vs fallback).
- Tests de migration 028 sur base PRE-EXISTANTE (ancien schema) + base fraiche : ordre
  CREATE TABLE -> ALTER -> CREATE INDEX respecte.
- Verification adversaire R2 sur les motifs NOGO precedents (VO-C/VO-D/VO-B traites
  dans le commit `1fec4dd`).
- Benchmark `nas_validation` valide manuellement sur SSD NVMe local + share SMB OMV.
- DB_LOCAL_GUARD declenche correctement sur chemin UNC en config de test.

## 🎁 Pour toi

La base de donnees SQLite est maintenant optimisee selon ton type de stockage (SSD local,
disque dur, NAS SMB). Detection automatique. Garde-fou anti-corruption activee sur SMB.
Si la DB est sur un partage reseau, l'app previent au lancement. Tu peux aussi lancer un
benchmark depuis les parametres pour mesurer la perf reelle.

## Notes

- Pas de bump VERSION (decision differee, coherent avec les batches Vague N).
- Tag local uniquement : `vague-o-batch1` (pas de push remote).
- Commits inclus : `1ab45ca`, `17556ee`, `ea1dd16`, `c61b335`.

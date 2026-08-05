# Vague N batch 1 - VN-A heritage + VN-F hygiene

## Resume technique

Premier batch de la Vague N : consolidation de l'heritage probe quality (VN-A1 a VN-A5) et hygiene
code mort + alignement canonique (VN-F.1 a VN-F.4). 9 commits, aucune nouvelle dependance, aucun
bump VERSION. Travail majoritairement interne : tokens design system unifies, securite UI
(focus trap + XSS), conformite WCAG 2.2.1, et nettoyage des chemins legacy dans le moteur de scan.

## Changements par item

### VN-A : heritage probe quality

- **VN-A1** (`defbbf6`) - `feat(vn-a1)`: flag probe quality rendu visible dans l'UI + cleanup
  des tokens couleurs orphelins.
- **VN-A2** (`0ffbd39`) - `fix(vn-a2)`: ajout du style `.toast--warning` manquant et unification
  des z-index tokens entre modales / toasts / overlays.
- **VN-A3** (`7ef81e9`) - `fix(vn-a3)`: focus trap sur les modales + hardening XSS dans les
  helpers de rendu, en preservant l'API publique de `dangerConfirmModal`.
- **VN-A4** (`0596f64`) - `fix(vn-a4)`: conformite WCAG 2.2.1 (cible toast 24x24 minimum) et
  verification SHA256 fail-closed sur `auto_install`.
- **VN-A5** (`83157c5`) - `feat(vn-a5)`: lot technique groupe -- DevTools conditionnels (build),
  normalisation NFC des chemins, fallback codec, lecture `file_size` consolidee, invalidation
  cache via `mtime`, parite mediainfo.

### VN-F : hygiene code mort

- **VN-F.1** (`f5bc7a8`) - `refactor(vn-f.1)`: centralisation de `_channels_label` dans
  `codec_ranks.format_audio_channels` (suppression des duplications).
- **VN-F.2** (`7bc5dae`) - `feat(vn-f.2)`: expose le toggle `include_subtitles` dans les profils
  qualite (alignement avec le reste de la config).
- **VN-F.3** (`0470292`) - `refactor(vn-f.3)`: suppression de `stream_scan_targets` et
  `iter_scan_targets` (chemins legacy non utilises).
- **VN-F.4** (`8a5e95e`) - `refactor(vn-f.4)`: alignement de `RenameProposal.op_type` sur la
  forme UPPERCASE canonique.

## Tests

- Suite de tests unitaires verte sur les 9 items (probe quality, codec ranks, scan engine,
  rename proposals, UI modales).
- Smoke test build local OK : `exe_starts=true`, `health_ok=true`.
- WCAG 2.2.1 verifie manuellement (target sizes toasts).
- Verification adversaire : XSS payloads dans `dangerConfirmModal`, focus trap stresses sur
  modales empilees.

## 🎁 Pour toi

On a applique 9 ameliorations techniques de la Vague N (heritage probe quality + design system +
WCAG + DevTools + hygiene code mort). Aucun changement visible cote utilisateur, mais l'app est
plus solide et plus accessible.

## Notes

- Pas de bump VERSION (decision differee a fin Vague Q, coherent avec Vague M hotfix 1).
- Tag local uniquement : `vague-n-batch1` (pas de push remote).
- Commits inclus : `defbbf6`, `0ffbd39`, `7ef81e9`, `0596f64`, `83157c5`, `f5bc7a8`, `7bc5dae`,
  `0470292`, `8a5e95e`.

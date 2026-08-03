"""Fake probes pour harness panne synthetique (ITER13).

Ces shims simulent des binaires ffprobe/mediainfo defaillants pour tester la
resilience CineSort face aux SMB/NAS pathologiques (lents, intermittents,
injoignables) SANS dependre d'un vrai NAS.

LIMITE HONNETE: panne SIMULEE pas vrai NAS. La validation B humaine sur vrai
partage SMB instable reste a faire.

Activation:
- CINESORT_FAKE_PROBE=slow|flaky : selectionne le shim a injecter
- PATH=scripts/fake_probes:$PATH : interception transparente
- Compteur d'appels: %TEMP%/cinesort_fake_probe_count.txt (flaky)
"""

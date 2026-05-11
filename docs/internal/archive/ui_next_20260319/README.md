# Archive UI Next - 2026-03-19

Decision:
- l'UI stable devient l'unique source de verite runtime a court terme;
- `preview` reste la seule variante dev supportee et continue de s'appuyer sur `web/index.html`;
- l'ancien prototype `next` est archive pour reference uniquement.

Pourquoi cette archive:
- forte duplication avec l'UI stable;
- aucune valeur backend exclusive par rapport a l'UI stable;
- pas de workflow de preuve visuelle ni de packaging aussi robuste que le chemin stable.

Ce dossier contient:
- `prototype_web/`: le prototype HTML/CSS/JS `next` retire du chemin `web/` actif;
- `ui_next_contracts_snapshot.py.txt`: l'ancien test de contrat `next`, conserve comme trace.

Statut:
- non package;
- non lance au runtime;
- non maintenu activement;
- consultation historique uniquement.

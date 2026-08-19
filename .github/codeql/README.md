# Model pack CodeQL — écrit, mesuré, PAS ENCORE BRANCHÉ

Ce dossier déclare `cinesort.infra.log_scrubber.scrub_secrets` comme **barrière
d'assainissement** pour CodeQL. L'énoncé est vrai et vaut pour ses ~9 usages.

**Il n'est pas actif aujourd'hui**, et ce fichier dit exactement pourquoi, pour
que la prochaine tentative ne repaie pas la même mesure.

## Ce qui a été essayé, et ce que la CI a répondu

Le câblage passait par un fichier de configuration :

```yaml
packs:
  python:
    - cinesort/python-models
```

Verdict de la CI, sans ambiguïté :

```
A fatal error occurred: 'cinesort/python-models' not found
in the registry 'https://ghcr.io/v2/'.
```

**`packs:` n'accepte que des packs PUBLIÉS sur un registre.** Un pack local du
dépôt n'est pas résolu par ce chemin. Et l'échec n'est pas cosmétique : il a fait
rougir `Analyze python`, qui est un **check REQUIS** — un défaut d'observabilité
non bloquant était en passe de devenir un blocage de fusion. Le câblage a donc
été retiré dans la foulée, le workflow restauré à l'identique.

## Le contexte, qui borne l'urgence

L'alerte `py/clear-text-storage-sensitive-data` était **déjà ouverte sur `main`**
(`cinesort/infra/tmdb_client.py:225`) — à l'endroit où le message partait
réellement en clair. Le correctif qui pose le scrub a décalé la ligne à 232, et
CodeQL l'a comptée comme neuve.

Autrement dit : **le code est plus sûr qu'avant, c'est l'outil qui ne le sait pas
encore.** Il n'y a donc pas d'urgence — seulement une alerte qui reste ouverte.

## Les pistes non essayées

1. **Publier le pack** sur GHCR sous le compte du dépôt, puis le référencer par
   son nom. C'est le chemin que `packs:` attend.
2. **`--additional-packs`** via `CODEQL_ACTION_EXTRA_OPTIONS`, qui accepte un
   chemin local — non documenté pour ce cas d'usage, à éprouver.
3. **Écarter l'alerte** dans l'onglet Sécurité avec la justification ci-dessus.
   C'est une décision de posture, elle appartient au propriétaire du dépôt.

## Le point non tranché, si la piste 1 ou 2 aboutit

Le `kind` attendu par `barrierModel` pour la famille « clear-text » n'est pas
documenté publiquement. Trois valeurs plausibles sont déclarées dans
`models/log-scrubber.model.yml` ; une valeur inconnue est **ignorée** par CodeQL,
donc sur-déclarer ne casse rien et la CI dira laquelle mord.

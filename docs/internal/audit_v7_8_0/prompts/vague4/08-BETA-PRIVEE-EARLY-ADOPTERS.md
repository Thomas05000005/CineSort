# V4-08 — Beta privée 20-50 early adopters (template + canal)

**Branche** : `docs/beta-private-onboarding`
**Worktree** : `.claude/worktrees/docs-beta-private-onboarding/`
**Effort** : 2-3h instance + ton timing diffusion (1-2 semaines)
**Mode** : 🟠 Solo+prep — instance prépare templates et canal feedback, **toi** diffuses
**Fichiers à créer** :
- `docs/beta/ANNOUNCE_TEMPLATE.md` (annonce à diffuser)
- `docs/beta/WELCOME_TEMPLATE.md` (message de bienvenue early adopter)
- `docs/beta/FEEDBACK_FORM.md` (questions clés à poser)
- `docs/beta/INSTRUCTIONS.md` (instructions install + premiers pas)
- `docs/beta/CHECKLIST_DIFFUSION.md` (étape par étape pour toi)
- `.github/DISCUSSION_TEMPLATE/` (templates pour GitHub Discussions beta)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b docs/beta-private-onboarding .claude/worktrees/docs-beta-private-onboarding audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/docs-beta-private-onboarding
pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu créés UNIQUEMENT des templates markdown + GitHub
Discussion templates. Aucune diffusion réelle, aucun changement de code.

LANGUE : tout en français, ton accueillant et concret.

---

## CONTEXTE

L'utilisateur a 2000 personnes en attente de CineSort. Avant de pousser tout le
monde sur la version publique, on veut une **beta privée 20-50 early adopters**
pour :
1. Trouver les bugs critiques sur des configs variées
2. Valider l'UX réelle (pas l'UX théorique)
3. Avoir des témoignages utilisables pour le launch (preuve sociale)
4. Construire un noyau de communauté engagée

---

## MISSION

### Étape 1 — Annonce template

Crée `docs/beta/ANNOUNCE_TEMPLATE.md` :

```markdown
# 🎬 Beta privée CineSort v7.6.0 — Cherche 20-50 testeurs

> **TL;DR** : Tu organises tes films sur Windows ? J'ai une app qui te fait gagner 10h
> par mois. Beta privée gratuite, retour souhaité dans 2 semaines.

---

## C'est quoi CineSort

**Une app desktop Windows** qui range et renomme automatiquement ta bibliothèque de
films. Détection TMDb, score de qualité réel (analyse perceptuelle vidéo+audio),
sync Jellyfin/Plex/Radarr, dashboard accessible depuis ton téléphone.

100% francophone, 100% local (zéro télémétrie), licence MIT (open source).

## Pourquoi une beta privée ?

J'ai 2000 personnes en attente de la version publique. Avant de release officiellement,
je cherche **20 à 50 personnes** pour tester sur leurs vraies bibliothèques et me
remonter ce qui marche / casse.

## Profil idéal

- Utilisateur Windows 10 ou 11
- Bibliothèque de films sur disque local (au moins 50 films, idéalement 500+)
- Bonus : utilise Jellyfin / Plex / Radarr
- Bonus : à l'aise pour donner du feedback en français (texte ou audio)

## Ce que je te demande

- ⏱ Tester ~30 min spread sur 1-2 semaines (pas tout d'un coup)
- 🐛 Me remonter ce qui crashe ou bug
- 💡 Me dire ce qui est confus dans l'UX
- ⭐ Si tu kiffes : témoignage 2-3 phrases utilisable pour le launch officiel

## Ce que je te donne

- 🎁 Accès gratuit définitif (l'app reste gratuite après le launch aussi)
- 🏷 Mention "Founding Beta Tester" sur le repo GitHub si tu veux
- 🚀 Influence directe : tes feedbacks pèsent fort sur la v7.7 et au-delà
- 🍿 Une app qui te fait vraiment gagner du temps

## Comment participer

Réponds à ce post / ce DM / ce mail avec :
1. Ton OS (Win10 ou Win11)
2. Ton volume approximatif de films
3. Tu utilises Jellyfin/Plex/Radarr ? Lequel ?
4. Une raison pour laquelle tu galères avec ta biblio actuelle (pour qualifier)

Je sélectionne 20-50 personnes parmi les volontaires et j'envoie le binaire + un
guide de démarrage rapide dans la semaine.

## Calendrier

- **Recrutement** : 1 semaine
- **Beta active** : 2 semaines
- **Public release** : ~3 semaines après début

Merci pour ton temps ! 🙏
```

### Étape 2 — Message de bienvenue early adopter

Crée `docs/beta/WELCOME_TEMPLATE.md` :

```markdown
# Bienvenue dans la beta CineSort 🎬

Salut [PRÉNOM],

Merci d'avoir accepté de tester CineSort en beta ! Voilà tout ce dont tu as besoin
pour démarrer.

## 1. Téléchargement

[LIEN_RELEASE_PRIVATE] (lien privé GitHub, ne pas partager)

Télécharge `CineSort_v7.6.0-beta.exe` (~51 MB).

## 2. Installation

Pas d'install. Double-clique le `.exe`. C'est portable, autonome, pas d'admin requis.

⚠ Windows Defender ou ton AV peut afficher un warning au premier lancement (binaire
pas signé en beta). Clic "Plus d'info" → "Exécuter quand même". C'est attendu.

## 3. Premier lancement (5 min)

L'app va te proposer un wizard en 5 étapes. Pour la beta, je suggère :

1. **Bienvenue** → suivant
2. **Dossier racine** → choisis 1 dossier de films (commence petit, 50-200 films)
3. **Clé TMDb** → optionnel pour ce premier test (saute si tu n'en as pas)
4. **Test rapide** → laisse tourner
5. **Terminé** → tu arrives sur l'accueil

## 4. Workflow à tester

### Indispensable
- [ ] Lance un scan de ton dossier
- [ ] Vérifie que les films sont bien identifiés
- [ ] Va dans Validation, regarde quelques propositions
- [ ] Tente un Apply en **dry-run** d'abord
- [ ] Si OK, tente un Apply réel sur 1-2 films

### Bonus
- [ ] Active une intégration (Jellyfin / Plex / Radarr) si tu en as une
- [ ] Teste le dashboard distant depuis ton téléphone (`http://<ip-pc>:8642/dashboard/`)
- [ ] Joue avec les 4 thèmes (Studio / Cinema / Luxe / Neon)

## 5. Feedback

À la fin de ton test (peu importe quand dans les 2 semaines), remplis ce formulaire
court (5 min) : [LIEN_FORMULAIRE_GOOGLE_FORMS]

Ou ouvre une discussion sur le repo privé : [LIEN_DISCUSSIONS_PRIVATE]

Pour les bugs critiques (crash, perte de fichiers), envoie-moi un message direct
+ le fichier de log : Aide → Ouvrir le dossier des logs → `cinesort.log`.

## 6. Recommandations sécurité

- Tu peux faire un backup de ton dossier de films AVANT le premier apply (par
  précaution, même si CineSort a un système d'undo)
- Le dashboard distant (port 8642) n'est PAS exposé sur internet par défaut. Si
  tu veux y accéder hors LAN, utilise un VPN ou Tailscale, JAMAIS de NAT direct
- Les paramètres / clés API sont stockés localement, chiffrés DPAPI Windows

## Questions ?

Réponds à ce mail / ce DM, je suis dispo.

Encore merci 🙏

[TON_NOM]
```

### Étape 3 — Formulaire feedback

Crée `docs/beta/FEEDBACK_FORM.md` :

```markdown
# Formulaire feedback beta CineSort

À utiliser pour créer un Google Forms / Typeform / GitHub Discussion.

## Section 1 — Profil

1. Pseudo / prénom (pour te citer si tu veux un témoignage)
2. OS : Win10 / Win11
3. Volume approximatif de films testés (0-50 / 50-500 / 500-2000 / 2000+)
4. Intégrations utilisées (Jellyfin / Plex / Radarr / Aucune)

## Section 2 — Premiers pas

5. Le wizard d'install était : Très simple / Simple / Confus / Bloquant
   - Si Confus/Bloquant : raconte-moi
6. Le premier scan a-t-il fonctionné ? Oui / Non / Partiellement
   - Si Non/Partiellement : décris

## Section 3 — Workflow critique

7. As-tu réussi à faire un Apply réel ? Oui / Non
8. As-tu eu besoin de l'undo ? Oui / Non
   - Si Oui : ça a fonctionné ? Oui / Non
9. La précision des renommages TMDb : Excellente / Bonne / Moyenne / Mauvaise
   - Note un exemple où c'était mal détecté (titre + année)

## Section 4 — UX

10. La sidebar est-elle claire ? Oui / Non — détaille
11. Les empty states (écrans vides) t'orientent-ils bien vers la prochaine action ? Oui / Non
12. Les tooltips ⓘ glossaire sont-ils utiles ? Oui / Non / Pas remarqué
13. Les 4 thèmes : tu en préfères un ? Lequel ? Pourquoi ?

## Section 5 — Bugs

14. As-tu rencontré un crash ? Oui / Non
    - Si Oui : décris + envoie cinesort.log si possible
15. Liste les bugs visuels ou fonctionnels rencontrés

## Section 6 — Volet "wow"

16. Qu'est-ce qui t'a le plus surpris (en bien) ?
17. Qu'est-ce qui t'a le plus frustré ?

## Section 7 — Témoignage

18. Acceptes-tu d'être cité dans le launch officiel ? Oui / Non
19. Si oui : 2-3 phrases qui résument ton expérience

## Section 8 — Net Promoter Score

20. Sur une échelle de 0-10, recommanderais-tu CineSort à un ami cinéphile ?

Merci ! 🙏
```

### Étape 4 — Instructions de diffusion pour toi

Crée `docs/beta/CHECKLIST_DIFFUSION.md` :

```markdown
# V4-08 — Checklist diffusion beta privée

## Avant de diffuser

- [ ] Le binaire `CineSort_v7.6.0-beta.exe` est buildé via `build_windows.bat`
- [ ] Le binaire est uploadé sur GitHub Release **privée** (draft) avec tag `v7.6.0-beta1`
- [ ] Le repo GitHub a "Discussions" activé
- [ ] J'ai créé une catégorie Discussion "Beta v7.6.0" privée
- [ ] J'ai créé un Google Forms / Typeform avec les questions de `FEEDBACK_FORM.md`
- [ ] J'ai customisé `WELCOME_TEMPLATE.md` avec mon nom + les 3 placeholders LIEN
- [ ] J'ai customisé `ANNOUNCE_TEMPLATE.md` (tone/wording si je veux)

## Canaux de diffusion

Choisir 3-5 canaux maximum (qualité > quantité) :

- [ ] **Reddit** — r/jellyfin, r/PleX, r/selfhosted, r/france (si fr-friendly)
- [ ] **Discord** — communautés home media FR (Plex FR, Jellyfin FR, etc.)
- [ ] **Twitter/X / Mastodon** — thread + hashtags #Plex #Jellyfin #Film
- [ ] **Linuxfr / Korben** — si réseau personnel
- [ ] **Hacker News** — Show HN (post anglais nécessaire — adapter ANNOUNCE)
- [ ] **Liste perso** — les 2000 en attente (mail ou Discord/Slack)

## Sélection des early adopters

- [ ] Cible 30 réponses, sélectionner 20-50 selon profils variés
- [ ] Diversité : Win10/Win11, petits/grands volumes, débutants/power users, avec/sans
      intégrations
- [ ] Envoyer le `WELCOME_TEMPLATE.md` customisé à chacun (ou en bulk avec mail merge)

## Pendant la beta (2 semaines)

- [ ] Check le formulaire feedback tous les 2-3 jours
- [ ] Répondre aux questions sur GitHub Discussions sous 48h max
- [ ] Si bug critique remonté → fix immédiat + nouveau binaire `v7.6.0-beta2`
- [ ] Tenir un journal des findings dans `audit/results/v4-08-beta-feedback.md`

## Après la beta

- [ ] Compiler les feedbacks
- [ ] Lister les fixes nécessaires avant le launch officiel
- [ ] Faire les fixes (peut-être une vague V5-01 dédiée)
- [ ] Compiler les témoignages pour le launch
- [ ] Annoncer le launch officiel avec changelog beta → public
```

### Étape 5 — GitHub Discussion templates

Crée `.github/DISCUSSION_TEMPLATE/beta-feedback.yml` :

```yaml
title: "[Beta v7.6.0] "
labels: ["beta-v7.6.0"]
body:
  - type: markdown
    attributes:
      value: |
        Merci pour ton feedback de beta ! Tu peux aussi remplir le formulaire
        plus structuré : [LIEN_FORMULAIRE]

  - type: dropdown
    id: severity
    attributes:
      label: Niveau
      options:
        - 🐛 Bug bloquant
        - ⚠ Bug important
        - 💡 Suggestion
        - 🎉 Feedback positif
        - ❓ Question

  - type: textarea
    id: content
    attributes:
      label: Ton retour
    validations:
      required: true

  - type: input
    id: os
    attributes:
      label: OS
      placeholder: Win11 build 26200
```

Et `.github/DISCUSSION_TEMPLATE/general.yml` (pour les questions hors beta) :

```yaml
title: "[Question] "
labels: ["question"]
body:
  - type: textarea
    id: question
    attributes:
      label: Ta question
    validations:
      required: true
```

### Étape 6 — Tests structurels

Crée `tests/test_v4_08_beta_artifacts.py` :

```python
"""V4-08 — Vérifie que tous les templates beta sont présents."""
from __future__ import annotations
import unittest
from pathlib import Path


class BetaArtifactsTests(unittest.TestCase):
    REQUIRED = [
        "docs/beta/ANNOUNCE_TEMPLATE.md",
        "docs/beta/WELCOME_TEMPLATE.md",
        "docs/beta/FEEDBACK_FORM.md",
        "docs/beta/CHECKLIST_DIFFUSION.md",
        ".github/DISCUSSION_TEMPLATE/beta-feedback.yml",
        ".github/DISCUSSION_TEMPLATE/general.yml",
    ]

    def test_all_present(self):
        for f in self.REQUIRED:
            with self.subTest(file=f):
                self.assertTrue(Path(f).is_file(), f"Manquant: {f}")

    def test_announce_in_french(self):
        content = Path("docs/beta/ANNOUNCE_TEMPLATE.md").read_text(encoding="utf-8")
        # Quelques mots français caractéristiques
        for word in ["bibliothèque", "francophone", "gratuit"]:
            self.assertIn(word.lower(), content.lower(), f"Mot manquant: {word}")

    def test_welcome_has_placeholders(self):
        content = Path("docs/beta/WELCOME_TEMPLATE.md").read_text(encoding="utf-8")
        for ph in ["[PRÉNOM]", "[LIEN_RELEASE_PRIVATE]", "[LIEN_FORMULAIRE_GOOGLE_FORMS]"]:
            self.assertIn(ph, content, f"Placeholder manquant: {ph}")


if __name__ == "__main__":
    unittest.main()
```

### Étape 7 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_v4_08_beta_artifacts -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
```

### Étape 8 — Commits

- `docs(beta): announce template + welcome message + feedback form (V4-08)`
- `docs(beta): diffusion checklist for user`
- `docs(github): discussion templates for beta + general`
- `test(beta): structural validation of beta artifacts`

---

## LIVRABLES

- Annonce diffusable (à adapter aux canaux)
- Message de bienvenue prêt avec 3 placeholders à remplacer
- Formulaire feedback structuré
- Checklist de diffusion étape-par-étape pour l'utilisateur
- 2 templates GitHub Discussions
- Tests structurels
- 4 commits sur `docs/beta-private-onboarding`

## ⚠ Pour l'utilisateur après le merge

1. Adapte les templates avec ton nom + ton wording
2. Crée Google Forms avec les questions de `FEEDBACK_FORM.md`
3. Build le binaire beta + upload sur GitHub Release privée
4. Suis `CHECKLIST_DIFFUSION.md` étape par étape
5. Fix les feedbacks critiques avant le launch officiel

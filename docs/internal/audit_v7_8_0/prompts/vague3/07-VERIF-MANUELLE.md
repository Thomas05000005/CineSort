# V3-07 — Verification manuelle focus visible

Apres merge de `fix/focus-visible-studio` :

1. Lancer l'app : `python app.py`
2. Pour chaque theme (Studio, Cinema, Luxe, Neon) :
   - Aller dans Parametres -> Apparence -> changer theme
   - Appuyer sur Tab plusieurs fois sur n'importe quelle vue
   - Verifier que le focus est **clairement visible** (anneau colore + halo)
3. Resultats attendus :
   - **Studio** (bleu) -> ring **jaune ambre** (`#FBBF24`)
   - **Cinema** (rouge) -> ring **blanc** (`#FFFFFF`)
   - **Luxe** (or) -> ring **or vif** (`#FFD700`)
   - **Neon** (violet) -> ring **cyan vif** (`#00FFFF`)
4. Si focus invisible sur un theme -> ajuster `--focus-ring` dans
   `web/shared/themes.css` (et `web/themes.css` legacy).
5. Verifier au clic souris : pas de ring affiche (`:not(:focus-visible)`).

WCAG 2.4.7 (AA) requiert un focus visible avec contraste >= 3:1.
Les valeurs choisies offrent un contraste >= 7:1 (AAA) sur leur fond respectif.

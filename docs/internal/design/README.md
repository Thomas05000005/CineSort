# UI Design Workspace

Zone de travail locale pour une phase UI/design premium quand Figma n'est pas disponible
ou quand une partie du travail doit avancer directement depuis le repo.

Principes:
- ne pas modifier le produit depuis cette zone sans lot d'implementation explicite
- observer l'interface reelle via le preview web avant toute proposition
- separer le travail en audit, direction, variantes, implementation, QA/polish
- documenter les choix par ecran et par lot

Ordre recommande:
1. [01-audit.md](./01-audit.md)
2. [02-direction.md](./02-direction.md)
3. [03-variants.md](./03-variants.md)
4. [04-implementation-plan.md](./04-implementation-plan.md)
5. [05-qa-polish.md](./05-qa-polish.md)
6. [06-ui-directions.md](./06-ui-directions.md)
7. [07-interface-structures.md](./07-interface-structures.md)
8. [08-component-families.md](./08-component-families.md)
9. [09-figma-brief.md](./09-figma-brief.md)
10. [10-design-system-foundation.md](./10-design-system-foundation.md)
11. [11-key-screen-mockups.md](./11-key-screen-mockups.md)
12. [12-local-source-of-truth.md](./12-local-source-of-truth.md)
13. [13-visual-variants-to-choose.md](./13-visual-variants-to-choose.md)
14. [14-design-to-code-implementation-plan.md](./14-design-to-code-implementation-plan.md)

Source canonique locale:
- [12-local-source-of-truth.md](./12-local-source-of-truth.md)

Ecrans prioritaires:
- home
- dashboard
- quality
- validate
- review
- duplicates
- apply
- settings
- logs

Sources de verite locales:
- preview web: `python scripts/run_ui_preview.py --dev`
- captures recommandees: `python scripts/capture_ui_preview.py --dev --recommended`
- controle visuel: `python scripts/visual_check_ui_preview.py --dev`

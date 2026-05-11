# CineSort / CineSort working rules

## General
- For any non-trivial task, start with a short plan before coding.
- Preserve current product behavior unless a change is explicitly requested.
- Prefer incremental refactors over big-bang rewrites.
- Do not start GitHub/CI/release work unless explicitly requested.

## Validation
- After meaningful changes, run:
  - pre-commit run --all-files
  - check_project.bat

## UI / UX
- For UI and UX tasks, use $playwright and $screenshot when available.
- Prioritize comprehension, product reliability, and clear wording over visual novelty.
- Keep the desktop-first positioning explicit.

## UI / Design phase
- For UI and design tasks, observe the real interface before changing it.
- Prefer $playwright and $screenshot for visual inspection.
- If Figma is available, use it as the visual source of truth before large UI/CSS changes.
- Do not redesign blindly from code only if the task asks for a premium UI pass.
- Always separate:
  1. audit
  2. direction
  3. variants
  4. implementation
  5. QA/polish
- For any significant UI task, present 2 to 4 options with tradeoffs before implementation when a design choice is subjective.


## UI / Design premium workflow
- For significant UI/design tasks, always start with a short plan.
- Observe the real interface before changing it.
- Prefer $playwright and $screenshot for visual inspection.
- If Figma is available, use it as the visual source of truth for major UI redesign work.
- If Figma is unavailable or blocked by plan limits, do not stop the UI/design phase:
  - switch to a repo-local design brief/spec
  - propose 2 to 4 design options in markdown
  - get a clear choice before implementation
  - continue implementation with Playwright + Screenshot verification
- Separate UI work into:
  1. audit
  2. direction
  3. variants
  4. implementation
  5. QA/polish
- For subjective design choices, always present options with tradeoffs before implementation.
- Do not touch GitHub/CI/release work during UI/design phases unless explicitly requested.

## UI / UX tasks
- For UI and UX tasks, use $playwright and $screenshot when available.
- If Playwright CLI is unavailable, stop and report the missing Node/npm prerequisite instead of guessing visually.

## Security
- For security-sensitive tasks, use Security Best Practices when available.
- Do not persist secrets in the repository.

## Reporting
- After each lot, always report:
  1. what changed
  2. why
  3. files touched
  4. checks run
  5. what remains

## Terminal
- Prefer PowerShell 7 (`pwsh`) over Windows PowerShell 5.1 for local tooling tasks.
- If terminal rendering issues appear in Windows PowerShell 5.1, retry in `pwsh` or VS Code terminal before diagnosing the tool itself.
# Repository guidance

## Project

Saeed Nasser — Oasis Journey is a single-page Arabic RTL HTML5 Canvas game. The public entry point is `index.html`.

## Guardrails

- Preserve Arabic RTL layout and mobile touch controls.
- Keep the game usable on desktop and mobile.
- Do not add secrets, personal data, analytics, or server dependencies.
- Prefer small, reviewable changes.
- Update `CHANGELOG.md` for user-visible behavior changes.
- Update bilingual documentation when features or controls change.

## Validation

1. Extract the inline JavaScript from `index.html`.
2. Run `node --check` on the extracted script.
3. Exercise movement, jump, fire, dash, pause, sound, restart, and mobile controls.
4. Verify the title screen and all three environments at common mobile and desktop sizes.

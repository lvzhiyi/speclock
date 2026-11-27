# UI Standards

Maintain design sources, themes, and shared styling rules here; per-screen design values and visual diffs live in the design index, and screen completion status lives in task cards.

<!-- Note: distinguish original design values from project-wide rules; never present inferred values as authoritative design specs. -->

## Design Source

- Authoritative Design: see [Design Index](../product/design/index.md).

## Theme & Style Entrypoints

- Theme / Style Entrypoint: {{e.g. lib/resources/theme.dart / src/styles}}
- Precedence: screen-specific design values override global defaults; keep overrides in page style files with node references.

## Colors, Typography & Spacing

<!-- Note: fill in after reading shared styles from the design tool; write "TBD" until inspected. -->

## States & Responsiveness

- Verify normal, focused, error, disabled, and loading states; unwired actions must not show fake "success" feedback.
- Responsiveness: {{narrow screens, text scaling, keyboard, dark mode, or applicable targets}}

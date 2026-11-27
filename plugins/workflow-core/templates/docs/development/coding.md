# Coding Standards

Maintain project-specific coding conventions here; language/framework idioms come from stack plugins, and module-specific implementation notes do not belong here.

<!-- Note: write "TBD" for anything not detectable. -->

- Formatting & Static Analysis: {{formatter and linter config files, e.g. analysis_options.yaml / .eslintrc}}
- Naming: {{naming conventions for types, members, and files}}
- Comments: {{e.g. docstrings for public functions/classes; explain non-obvious business invariants}}
- Dependencies: verify lockfiles when updating dependencies; never introduce credentials, production URLs, or real sensitive data.

## Generated Code

- {{generation command and output path}}; never hand-edit generated files — update the source and review the regenerated diff.

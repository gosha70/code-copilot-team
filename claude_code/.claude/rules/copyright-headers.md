
# Copyright Header Rules

When a project's CLAUDE.md contains a `## Copyright & Licensing` section,
add a copyright header to every **new** source file you create.

## Trigger

Check for a `## Copyright & Licensing` section in the **project** CLAUDE.md
(the one in the project root — not the global `~/.claude/CLAUDE.md`).

If present, extract:
- **Company** from the `- **Company**: …` line
- **License** from the `- **License**: …` line

## Which files get headers

Apply to new files with these extensions:
`.py`, `.sh`, `.bash`, `.java`, `.kt`, `.js`, `.ts`, `.tsx`, `.jsx`,
`.go`, `.rs`, `.c`, `.cpp`, `.h`, `.css`, `.scss`, `.html`, `.xml`,
`.yaml`, `.yml`, `.toml`

Do **not** add headers to:
- Auto-generated files (contain `@generated`, `Code generated`, or similar markers)
- `__init__.py` files (conventionally empty or trivial)
- Lock files (`package-lock.json`, `poetry.lock`, `yarn.lock`, etc.)
- JSON / JSONC (no comment syntax)
- Files you **did not create** — never modify existing files just to add a header

## Header format

Compose the header as two lines:

1. `Copyright (c) <year> <Company> - All Rights Reserved.`
2. `This software may be used and distributed according to the terms of the <License> license.`

Use the current calendar year.

### By file type

**Python / Shell / YAML / TOML / Ruby** — hash comments:
```
# Copyright (c) <year> <Company> - All Rights Reserved.
# This software may be used and distributed according to the terms of the <License> license.
```

**Java / Kotlin / JavaScript / TypeScript / Go / Rust / C / C++** — line comments:
```
// Copyright (c) <year> <Company> - All Rights Reserved.
// This software may be used and distributed according to the terms of the <License> license.
```

**HTML / XML** — block comment:
```
<!-- Copyright (c) <year> <Company> - All Rights Reserved. -->
<!-- This software may be used and distributed according to the terms of the <License> license. -->
```

**CSS / SCSS** — block comment:
```
/* Copyright (c) <year> <Company> - All Rights Reserved. */
/* This software may be used and distributed according to the terms of the <License> license. */
```

## Placement

Place the header at the very top of the file, before any imports or declarations.

Exceptions:
- If the file begins with a shebang (`#!/…`), place the header on line 2.
- If the file begins with `<?xml` or `<!DOCTYPE`, place the header after that line.

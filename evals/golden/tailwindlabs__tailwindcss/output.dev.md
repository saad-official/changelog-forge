## tailwindlabs/tailwindcss v4.2.4...v4.3.0

This release adds several new utility classes and directives, including support for arbitrary selector &:has conversion, enhanced `@variant` syntax, functional utility defaults, and new scrollbar, scrollbar-gutter, zoom, and tab-size utilities. It also includes numerous fixes to resolver behavior, canonicalization, TypeScript typings, and code generation, along with internal dependency updates and test improvements.

### Features

- The `@variant` directive now accepts comma-separated variants and a colon syntax for stacking, simplifying variant usage. ([#19996](https://github.com/tailwindlabs/tailwindcss/pull/19996))
- `@utility` handlers now try next handler on null, enabling multiple definitions. ([#19777](https://github.com/tailwindlabs/tailwindcss/pull/19777))
- Added --default(…) support in functional utilities, allowing defaults for missing values or modifiers. ([#19989](https://github.com/tailwindlabs/tailwindcss/pull/19989))
- Introduced scrollbar-auto, scrollbar-thin, scrollbar-none, scrollbar-thumb-&lt;color>, and scrollbar-track-&lt;color> utilities. ([#19981](https://github.com/tailwindlabs/tailwindcss/pull/19981))
- Introduced `scrollbar-gutter-auto`, `scrollbar-gutter-stable`, and `scrollbar-gutter-both` classes mapping to `scrollbar-gutter` CSS. ([#20018](https://github.com/tailwindlabs/tailwindcss/pull/20018))
- Introduced `zoom-50`, `zoom-[1.1]`, and `zoom-(--value)` classes mapping to `zoom` CSS, positioned after `transform` in property order. ([#20020](https://github.com/tailwindlabs/tailwindcss/pull/20020))
- Introduced `tab-2` and `tab-[12px]` classes mapping to `tab-size` CSS, added to property order near text layout properties. ([#20022](https://github.com/tailwindlabs/tailwindcss/pull/20022))
- Arbitrary selector &:has is converted to has-[] variant during canonicalization. ([#19991](https://github.com/tailwindlabs/tailwindcss/pull/19991))

### Fixes

- Exported Config type now resolves correctly in TS. ([#19707](https://github.com/tailwindlabs/tailwindcss/pull/19707))
- customJsResolver now returns undefined for non-JS files so `@plugin` resolves to the JS entry. ([#19949](https://github.com/tailwindlabs/tailwindcss/pull/19949))
- Resolver now uses importer path and aliasOnly logic for relative files. ([#19965](https://github.com/tailwindlabs/tailwindcss/pull/19965))
- inputBasePath now falls back to base when result.opts.from is missing. ([#19980](https://github.com/tailwindlabs/tailwindcss/pull/19980))
- Canonicalization now keeps '_' and wraps expressions with parentheses for readability. ([#19986](https://github.com/tailwindlabs/tailwindcss/pull/19986))
- Canonicalization skips unit normalization for arbitrary values. ([#19988](https://github.com/tailwindlabs/tailwindcss/pull/19988))
- Upgrade codemod skips inline style properties. ([#19918](https://github.com/tailwindlabs/tailwindcss/pull/19918))
- Removed generation of CSS for start and end utilities without values. ([#20003](https://github.com/tailwindlabs/tailwindcss/pull/20003))
- Enforced presence of --value(…) in functional `@utility` definitions. ([#20005](https://github.com/tailwindlabs/tailwindcss/pull/20005))
- Ensured whitespace around operators in calc expressions during canonicalization. ([#20011](https://github.com/tailwindlabs/tailwindcss/pull/20011))
- Features.Variants added to feature bitmask in `@tailwindcss/vite.` ([#19966](https://github.com/tailwindlabs/tailwindcss/pull/19966))

### Docs

- Minor typos corrected. ([#19878](https://github.com/tailwindlabs/tailwindcss/pull/19878))

### Internal

- Version bump to 4.3.0, updating numerous package.json files and integration tests. ([#20023](https://github.com/tailwindlabs/tailwindcss/pull/20023))
- Dependencies updated in all packages. ([#19957](https://github.com/tailwindlabs/tailwindcss/pull/19957))
- Dependencies in playgrounds bumped. ([#19954](https://github.com/tailwindlabs/tailwindcss/pull/19954))
- NAPI related dependencies bumped. ([#19982](https://github.com/tailwindlabs/tailwindcss/pull/19982))
- CI workflows now use Node v18 images for NAPI-RS. ([#19983](https://github.com/tailwindlabs/tailwindcss/pull/19983))
- Bumped enhanced-resolve to 5.21.0, adding promise API and new options. ([#19998](https://github.com/tailwindlabs/tailwindcss/pull/19998))
- Bumped `listhen` to 1.10.0, adding `extraURLs` support and IPv4 link-local filtering. ([#20017](https://github.com/tailwindlabs/tailwindcss/pull/20017))
- Added source map visualization utilities for tests, printing source locations and highlighted symbols. ([#19997](https://github.com/tailwindlabs/tailwindcss/pull/19997))
- Adjusted integration test utilities to improve CI stability. ([#19995](https://github.com/tailwindlabs/tailwindcss/pull/19995))
- Updated tests to use correct variants, `@reference`, Vitest mocks, and modern assertions. ([#19999](https://github.com/tailwindlabs/tailwindcss/pull/19999))
- Replaced inline snapshots with explicit expectations and added pretty helper for test outputs. ([#20013](https://github.com/tailwindlabs/tailwindcss/pull/20013))
- Test suite now imports `@tailwindcss/node` from `src/` instead of `dist/` to avoid source map warnings. ([#20015](https://github.com/tailwindlabs/tailwindcss/pull/20015))
- Test code updated to reference `example-*` utilities instead of `tab-*` for future-proofing. ([#20021](https://github.com/tailwindlabs/tailwindcss/pull/20021))

<sub>Generated by Changelog Forge from 33 commits in [v4.2.4...v4.3.0](https://github.com/tailwindlabs/tailwindcss/compare/v4.2.4...v4.3.0). Every link was checked against the commits in this range.</sub>

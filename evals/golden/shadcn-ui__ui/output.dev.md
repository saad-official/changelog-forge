## shadcn-ui/ui shadcn@4.21.0...shadcn@4.21.1

This release extracts the registry code into a new `@shadcn/registry` package and adds extensive community registry entries. It also introduces OIDC configuration, updates next.js handling for forwarded headers, and improves reduced‑motion behavior. Several fixes address SVG viewBox handling, logo rendering, and component dependencies.

### Features

Key functional additions and restructuring.

- The registry code was extracted into a new package `@shadcn/registry`, which `shadcn` now depends on; existing exports remain unchanged. ([#12087](https://github.com/shadcn-ui/ui/pull/12087))
- Added OIDC configuration in `apps/v4/next.config.mjs`. ([afda008](https://github.com/shadcn-ui/ui/commit/afda0085e042a06ceb4d6e97ebd4f5025d389076))
- Added ranking logic based on health and catalog size in `apps/v4/lib/registry-health/rank.ts` and updated related monitoring and documentation. ([#12058](https://github.com/shadcn-ui/ui/pull/12058))
- Added `@corsair-ui` to the registry directory in `apps/v4/registry/directory.json`. ([#12033](https://github.com/shadcn-ui/ui/pull/12033))
- Updated the Sona UI registry domain in `apps/v4/registry/directory.json`. ([#11764](https://github.com/shadcn-ui/ui/pull/11764))
- Added `@quiz-ui` to the registry directory in `apps/v4/registry/directory.json`. ([#11753](https://github.com/shadcn-ui/ui/pull/11753))
- Added community registries including `@slidecn`, `@emailcn`, `@amap`, `@ark-cn`, `@styleui`, `@buzzform`, `@ratneshc`, `@nostalgia-ui`, and `@bits-ui` to `apps/v4/registry/directory.json`. ([#11925](https://github.com/shadcn-ui/ui/pull/11925), [#11861](https://github.com/shadcn-ui/ui/pull/11861), [#11915](https://github.com/shadcn-ui/ui/pull/11915), [#11924](https://github.com/shadcn-ui/ui/pull/11924), [#11976](https://github.com/shadcn-ui/ui/pull/11976), [#12037](https://github.com/shadcn-ui/ui/pull/12037), [#12052](https://github.com/shadcn-ui/ui/pull/12052), [#12059](https://github.com/shadcn-ui/ui/pull/12059))

### Fixes

Corrections to SVG handling, component behavior, and configuration.

- The shimmer reduced-motion handling was moved into the utility, so `hover:shimmer` no longer animates when reduced motion is enabled. ([#12061](https://github.com/shadcn-ui/ui/pull/12061))
- Corrected SVG viewBox quotes in `apps/v4/registry/directory.json` and `packages/shadcn/src/utils/updaters/update-css.ts` for namespace and validation checks. ([#11807](https://github.com/shadcn-ui/ui/pull/11807))
- Updated `apps/v4/next.config.mjs` to serve OIDC home RSC payloads using forwarded headers. ([3ba91b1](https://github.com/shadcn-ui/ui/commit/3ba91b1cc83e1bbe4ab35a422ff2a694849c5048))
- Set `fill='none'` directly on the stroke path for the `@notra` logo entry in `apps/v4/registry/directory.json` to prevent it from rendering as a solid fill. ([#12054](https://github.com/shadcn-ui/ui/pull/12054))
- Set `fill='none'` on paths and adjusted the `viewBox` for the `@voraui` logo in `apps/v4/registry/directory.json` so arcs stay outlined. ([#12034](https://github.com/shadcn-ui/ui/pull/12034))
- Updated the homepage and URL of the `@sekei` entry from `sekei.xyz` to `sekei.design` in `apps/v4/registry/directory.json`. ([#12044](https://github.com/shadcn-ui/ui/pull/12044))
- Updated chat component dependencies in registry files, fixed base style references in `message-scroller.mdx` files, and added chat components to `UI_COMPONENTS` in `apps/v4/lib/components.ts`. ([#12057](https://github.com/shadcn-ui/ui/pull/12057))

### Docs

- Updated the `@7ovr` description in `apps/v4/registry/directory.json` to accurately reflect the current project state. ([#11972](https://github.com/shadcn-ui/ui/pull/11972))
- Updated the `@snapcn` description in `apps/v4/registry/directory.json` to specify animation and motion graphics for product demo videos. ([#12017](https://github.com/shadcn-ui/ui/pull/12017))

### Internal

- All shadcn starter templates were refreshed with latest framework scaffolds, dependency versions, lockfiles, and Node requirements. ([#12062](https://github.com/shadcn-ui/ui/pull/12062))
- Release PR updated package versions and changelogs for `@shadcn/registry` and `shadcn`. ([#12063](https://github.com/shadcn-ui/ui/pull/12063))
- Bumped Next, Astro, Postcss, Undici, and other packages, and updated test snapshots and lockfiles. ([#11862](https://github.com/shadcn-ui/ui/pull/11862))
- Updated `.github/dependabot.yml` to group minor and patch updates. ([949bcd3](https://github.com/shadcn-ui/ui/commit/949bcd39ca8ec57bf95db0c941150f81b73441bc))
- Updated `.github/dependabot.yml` to ignore major version bumps for `@types/node`. ([2bf0398](https://github.com/shadcn-ui/ui/commit/2bf0398b5b5913a523cddad5530a3cb114d218f9))
- Update `.github/dependabot.yml` to split the root dependency group. ([2b3e6d4](https://github.com/shadcn-ui/ui/commit/2b3e6d4f8d9161fe5c19340dc383aade392012dd))
- Added `.github/workflows/signed-commits-close.yml` and updated `.github/workflows/signed-commits.yml` to automatically close pull requests carrying unverified commits after two weeks. ([#11977](https://github.com/shadcn-ui/ui/pull/11977))
- Replaced `@aliimam` with `@designali` in `apps/v4/registry/directory.json`. ([#11765](https://github.com/shadcn-ui/ui/pull/11765))
- Updated `apps/v4/next.config.mjs` and `apps/v4/registry/directory.json`. ([ec76284](https://github.com/shadcn-ui/ui/commit/ec762842adec04518a70bbe258f7aa1486e53357))
- Bumped packages including `react`, `react-dom`, `vite`, and `tailwindcss` in `templates/react-router-app/package.json`. ([92d1c42](https://github.com/shadcn-ui/ui/commit/92d1c42aad5aba7dfdb3e1f3015010bb2185bcfe))
- Bumped packages like `cn`, `react`, and `prettier` in `templates/start-app/package.json`. ([9b13df1](https://github.com/shadcn-ui/ui/commit/9b13df1bca2a7b9633b19b2efc5733696632d69f))
- Bumped packages including `turbo`, `react`, `vite`, and `eslint` in `templates/vite-monorepo/package.json` and related files. ([293f64f](https://github.com/shadcn-ui/ui/commit/293f64f604bace8b6b83634cb16e31387873e0ab))
- Bumped `react`, `react-dom`, and build tools in `templates/vite-app/package.json`. ([#11863](https://github.com/shadcn-ui/ui/pull/11863))
- Bumped `@types/node` in `templates/vite-app/package.json`. ([#11880](https://github.com/shadcn-ui/ui/pull/11880))
- Bump dependencies including `next`, `react`, and tools in `templates/next-app/package.json`. ([#11868](https://github.com/shadcn-ui/ui/pull/11868))
- Bump `@types/node` from `20.19.10` to `20.19.43` in `templates/start-app/package.json`. ([#11886](https://github.com/shadcn-ui/ui/pull/11886))
- Bump `@types/node` from `24.12.4` to `24.13.3` in `templates/vite-monorepo/pnpm-lock.yaml`. ([#11885](https://github.com/shadcn-ui/ui/pull/11885))
- Bump `@types/node` from `22.19.19` to `22.20.1` in `templates/react-router-app/pnpm-lock.yaml`. ([#11884](https://github.com/shadcn-ui/ui/pull/11884))
- Bump `eslint` from `9.26.0` to `10.10.0` in `templates/next-app/package.json`. ([#11876](https://github.com/shadcn-ui/ui/pull/11876))
- Bump `jsdom` from `28.1.0` to `30.0.1` in `templates/start-app/package.json`. ([#11875](https://github.com/shadcn-ui/ui/pull/11875))

<sub>Generated by Changelog Forge from 44 commits in [shadcn@4.21.0...shadcn@4.21.1](https://github.com/shadcn-ui/ui/compare/shadcn@4.21.0...shadcn@4.21.1). Every link was checked against the commits in this range.</sub>

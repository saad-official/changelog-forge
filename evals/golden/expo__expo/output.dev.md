## expo/expo expo@58.0.2...expo@58.0.3

This release adds several new UI modifiers, a CLI tool for generating TypeScript types, and network permission handling for the dev launcher. It also includes numerous bug fixes such as SQLite connection handling, flash overlay removal, and improved stack trace reporting. Internal updates include removal of a custom TextDecoder, refined asset handling, and performance optimizations in JavaScript value handling.

### Features

- Introduces `expo-modules-cli` binary with `generate-types` command to generate TypeScript types. ([#50233](https://github.com/expo/expo/pull/50233))
- Added `expo-modules-cli` with the `generate-types` command and added the `enableRemoteNotifications` option to `expo-notifications`. ([#50929](https://github.com/expo/expo/pull/50929))
- Adds `navigationBarTitleDisplayMode` and `toolbarTitleDisplayMode` modifiers to expo-ui. ([#50687](https://github.com/expo/expo/pull/50687))
- Dev‑launcher now asks for the local network permission via a new LocalNetworkPermission helper before launching NSD discovery. ([#50951](https://github.com/expo/expo/pull/50951))
- Added `smooth`, `snappy`, and `bouncy` spring animation presets to `Animation` in `@expo/ui` via `AnimationConfig.swift` and associated TypeScript wrappers. ([#50984](https://github.com/expo/expo/pull/50984))

### Fixes

- Corrects SQLite statement handling to preserve connections and invalidate wrappers on cleanup. ([#50121](https://github.com/expo/expo/pull/50121))
- The flash now clears the foreground on the same root view that was used to set it, preventing a white overlay after unmounting. ([#50950](https://github.com/expo/expo/pull/50950))
- Added missing UIKit imports to Swift files that use UIImage, enabling SwiftPM builds. ([#50961](https://github.com/expo/expo/pull/50961))
- Replaced data.length with Buffer.byteLength(data, 'utf8') when setting the Content‑Length header. ([#49305](https://github.com/expo/expo/pull/49305))
- Replaced ContactsViewController with CNContactViewController(forNewContact:) and fixed the return type to boolean. ([#50957](https://github.com/expo/expo/pull/50957))
- `getRoutesCore()` and `getContextKey()` now use `getPlatformFromFilePath()` to handle `.web`, `.ios`, etc. correctly. ([#49035](https://github.com/expo/expo/pull/49035))
- `getPlatformPreset()` now merges the base mapper into web and node presets, restoring tsconfig path aliases. ([#50444](https://github.com/expo/expo/pull/50444))
- Made resetting native state in `SharedObject.release()` best effort and added a released flag to `SharedObjectNativeState` to support frozen shared objects. ([#50970](https://github.com/expo/expo/pull/50970))
- Changes write permission check to avoid opening files, preventing scan triggers. ([#50817](https://github.com/expo/expo/pull/50817))
- Adds guard to avoid UUID collisions in CocoaPods post_install. ([#50946](https://github.com/expo/expo/pull/50946))
- `INTERNAL_CALLSITES_REGEX` was updated to exclude a catch-all for node_modules, preserving library frames. ([#50973](https://github.com/expo/expo/pull/50973))
- `parseErrorStack` no longer drops frames containing `node_modules`, enabling full stack traces. ([#50974](https://github.com/expo/expo/pull/50974))
- Collapsed stacks are only dropped if they lack an error message; thrown error stacks are always printed. ([#50975](https://github.com/expo/expo/pull/50975))

### Performance

- `JavaScriptValue.withUnownedValue(in:_:)` and default `decode` now borrow values, avoiding unnecessary copies. ([#50960](https://github.com/expo/expo/pull/50960))
- `JavaScriptArray.mapUnowned` and `JavaScriptObject.withUnownedProperty` now provide unowned values, and decoders use them. ([#50980](https://github.com/expo/expo/pull/50980))
- `build-xcframework.sh` now builds with `SWIFT_SERIALIZE_DEBUGGING_OPTIONS=NO` and `SWIFT_ENABLE_EXPLICIT_MODULES=NO` to omit absolute paths. ([#50354](https://github.com/expo/expo/pull/50354))

### Docs

- Synced documentation pages and commands JSON data for EAS CLI in `docs/pages/eas/cli.mdx` and `docs/ui/components/EASCLIReference/data/eas-cli-commands.json`. ([#51002](https://github.com/expo/expo/pull/51002))
- Updated account type and audit log documentation in `docs/pages/accounts/account-types.mdx` and `docs/pages/accounts/audit-logs.mdx` regarding protected channels. ([#50931](https://github.com/expo/expo/pull/50931))
- Deletes /preview redirects from docs redirect files. ([#50945](https://github.com/expo/expo/pull/50945))

### Internal

- Removed custom TextDecoder implementation; Expo now relies on Hermes TextDecoder and no longer provides a UTF‑8 polyfill. ([#50853](https://github.com/expo/expo/pull/50853))
- Unified static and streaming CSS asset handling, preserving Metro order and removing duplicate link generation. ([#50016](https://github.com/expo/expo/pull/50016))
- Implemented a generic cache in JavaScriptRuntime using typed keys, reducing lookup overhead. ([#50888](https://github.com/expo/expo/pull/50888))
- Modified JavaScriptValue.write to move values into the result slot and updated related utilities for efficient handling. ([#50937](https://github.com/expo/expo/pull/50937))
- Updated NativeViewManagerAdapter to map aria-* props to native accessibility props, fixing SymbolView and other Expo views. ([#50959](https://github.com/expo/expo/pull/50959))
- Modified expo-audio web player to catch play() rejections, reset isPlaying, and emit error status updates. ([#50972](https://github.com/expo/expo/pull/50972))
- Implemented startBindingTimeout and atomic continuation handling in AudioRecordingServiceConnection to prevent hanging promises. ([#50883](https://github.com/expo/expo/pull/50883))
- Added ./plugin to package.json exports for expo-font, expo-image, expo-maps, expo-router, expo-web-browser, and expo-updates to support typed config plugins. ([#50965](https://github.com/expo/expo/pull/50965))
- Introduced noApsEntitlement flag in NotificationsPluginProps to skip adding aps-environment entitlement when only local notifications are used. ([#50891](https://github.com/expo/expo/pull/50891))
- Made delay() and repeat() return new immutable ChainableAnimation instances, preventing side effects on Animation.default and shared animations. ([#50927](https://github.com/expo/expo/pull/50927))
- Replaced Prettier with oxfmt in MavenPublicationExtension and removed Prettier from root package.json. ([#47438](https://github.com/expo/expo/pull/47438))
- Jest 30 is now used throughout the monorepo, with updated configurations and test environments. ([#50427](https://github.com/expo/expo/pull/50427))
- Added `decodableKinds` property to `JavaScriptDecodable` in `JavaScriptDecodableKindsTests.swift` and core JSI files. ([#50905](https://github.com/expo/expo/pull/50905))
- Upgraded `vale-action` to version `v3.0.0` in `.github/workflows/docs-pr.yml` and `.github/workflows/docs.yml`. ([#50964](https://github.com/expo/expo/pull/50964))
- Updated Vale version to `3.24.0` in `docs/.vale-version.json`. ([#50963](https://github.com/expo/expo/pull/50963))
- Skipped EAS/GH workflows for `changeset-release/*` branches to avoid redundant runs. ([#50930](https://github.com/expo/expo/pull/50930))
- Allowed early merge of Version Packages PRs, deferring precompile wait to publish tasks. ([#50928](https://github.com/expo/expo/pull/50928))
- Reordered dependencies alphabetically, removed devDependencies that duplicate dependencies, and moved root dependencies to devDependencies. ([#50390](https://github.com/expo/expo/pull/50390))
- Updated EAS_UPDATE_UPLOAD_EMBEDDED_BUNDLE documentation for SDK 58+ and added tabs for SDK 57 and below. ([#50307](https://github.com/expo/expo/pull/50307))
- Bumped react-native-web to version 0.21.3 across the workspace. ([#50458](https://github.com/expo/expo/pull/50458))
- Aligned lodash, semver, `@types/semver`, and `@vercel/ncc` to the highest ranges present in the repo. ([#50391](https://github.com/expo/expo/pull/50391))
- Aligned `@types/jest` to ^29.5.12 across the workspace. ([#50420](https://github.com/expo/expo/pull/50420))
- Aligned memfs to ^3.6.0 across the workspace. ([#50422](https://github.com/expo/expo/pull/50422))
- Updates package.json dependencies to a single version range. ([#50423](https://github.com/expo/expo/pull/50423), [#50424](https://github.com/expo/expo/pull/50424), [#50425](https://github.com/expo/expo/pull/50425), [#50426](https://github.com/expo/expo/pull/50426))
- Updates expo-ui CHANGELOG to correct entry. ([#50942](https://github.com/expo/expo/pull/50942))
- Adds test-suite-macos workflow to run on main. ([#50952](https://github.com/expo/expo/pull/50952))
- Introduces YAML anchors in GitHub Actions workflows. ([#50954](https://github.com/expo/expo/pull/50954))
- Bumps devcert, ws-tunnel, sdk-runtime-versions, xcpretty to latest. ([#50955](https://github.com/expo/expo/pull/50955))
- Adds lock files for iOS pods. ([9d37bc5](https://github.com/expo/expo/commit/9d37bc5bed441a53ed5b9b7ebcb8df8766304573))
- The build script sets STRIP_SWIFT_SYMBOLS=NO to keep Swift symbol names in the prebuilt JSI framework. ([#50698](https://github.com/expo/expo/pull/50698))
- Updated the README in expo-template-default to use the correct directory names. ([#50443](https://github.com/expo/expo/pull/50443))
- Exported config plugin types for Expo Router and added a guard to limit their display to the main reference page. ([#50442](https://github.com/expo/expo/pull/50442))
- Replaced query-string with URLSearchParams in expo-router, updating stringifySearchParams and related utilities. ([#50725](https://github.com/expo/expo/pull/50725))
- Modified expo-camera web implementation to fire onCameraReady only after video frame is available, and relaxed takePictureAsync frame requirement. ([#50884](https://github.com/expo/expo/pull/50884))
- Removed POST_NOTIFICATIONS check from AudioRecorder.prepareRecording, allowing background recording on Android 13+ without notification permission. ([#50968](https://github.com/expo/expo/pull/50968))
- Synced SDK 58 docs data and updated related JSON files. ([#50933](https://github.com/expo/expo/pull/50933))
- `getRoutes.test.ios.ts` now uses `toThrow` in place of `toThrowError`. ([#50986](https://github.com/expo/expo/pull/50986))

<sub>Generated by Changelog Forge from 64 commits in [expo@58.0.2...expo@58.0.3](https://github.com/expo/expo/compare/expo@58.0.2...expo@58.0.3). Every link was checked against the commits in this range.</sub>

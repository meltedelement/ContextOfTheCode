# React Frontend Code Review

## Overview

The frontend is a React 19 + TypeScript dashboard built with Create React App. It has three main sections, each backed by its own component:

| Component | Purpose | Data Source |
|---|---|---|
| `MetricsSection` | System metrics cards + line charts | `GET /api/metrics?source=local` |
| `TransportMap` | Google Maps with bus markers + time slider | `GET /api/metrics?source=transport_api` |
| `MobileSection` | Per-mobile-device metrics cards + charts | `GET /api/metrics?source=mobile_app` |

Config is loaded from a TOML file served as a static asset (`public/config.toml`), parsed client-side with `smol-toml`, and distributed via React Context.

**Key dependencies:** React 19, axios, chart.js / react-chartjs-2, @react-google-maps/api, smol-toml.

---

## `App.tsx` — Clean Entry Point

### Strengths

- **Config-driven architecture.** All magic numbers (API base URL, colours, poll intervals, map centre, snapshot limits) live in `config.toml` and flow through `ConfigContext`. No hardcoded values in components.
- **TOML for frontend config** is an unusual but smart choice — it mirrors the backend's `config.toml`, giving the project a unified configuration language. `smol-toml` is a lightweight parser (~4 KB).
- **Clean loading state.** Returns `null` while config is loading, preventing child components from rendering with undefined config.

### Issues

1. **No error state for config loading (line 15).** If `fetch("/config.toml")` fails (network error, 404), the app silently stays on a blank screen forever. The `catch` only logs to console. Should show an error message to the user.

2. **Unsafe `as unknown as FrontendConfig` cast (line 14).** The TOML parse result is blindly cast to `FrontendConfig`. If any field is missing or has the wrong type, the error won't surface until a child component blows up with `Cannot read property of undefined`. Runtime validation (e.g. a simple shape check, or Zod) would catch this at the boundary.

3. **No `<title>` or favicon configuration.** The page title is still the CRA default. Minor, but noticeable in a demo tab.

---

## `ConfigContext.ts` — Simple, Effective

### Strengths

- Typed interface with all config sections clearly defined.
- `createContext<FrontendConfig | null>(null)` with null default — forces consumers to handle the loading state.

### Issues

4. **`ms_per_sec = 1000` is a config value (config.toml line 5).** This is a physical constant, not a configuration choice. No one should ever change it. Having it in config implies it's tuneable. It should be a code constant. If a judge asks "why is 1000 milliseconds per second configurable?" you'll be on the back foot.

5. **Colour opacity values are hex string suffixes (`"22"`, `"55"`, `"11"`) (config.toml lines 8-10).** These are appended to hex colour codes like `"#2196F3" + "22"` to form `"#2196F322"`. This works with 8-digit hex colour notation (RGBA), but it's an unusual pattern that isn't self-documenting. A reader would need to know that `"22"` means ~13% opacity. A comment in the config or using decimal opacity values would clarify intent.

---

## `MetricsSection.tsx` — Solid Dashboard Component

### Strengths

- **Device grouping.** Snapshots are grouped by `device_id` and each device gets its own card. Handles multiple local collectors naturally.
- **Dynamic metric discovery.** `metricNames` is computed from the actual data, not hardcoded. If a new metric is added to the local collector, it automatically appears.
- **Live/Stale indicator.** Compares `collected_at` against `Date.now()` with configurable `stalenessSecs` threshold. Good UX for knowing if collection is actually running.
- **Polling with cleanup.** `setInterval` + `clearInterval` on effect cleanup. Correct React lifecycle management.
- **`useMemo` on device groups and metric names** — avoids recomputing on every render.
- **`animation: false` on charts (line 67).** For a polling dashboard that updates every 5 seconds, chart animations would be jarring. Good call.

### Issues

6. **Full re-fetch on every poll interval (lines 239-245).** Every 5 seconds, the component fetches ALL snapshots from the API (up to `limit=5000` per config). Unlike `TransportMap` which uses delta fetching with a `since` cursor, `MetricsSection` re-downloads the entire dataset every poll. For 5000 snapshots with ~4 metrics each, that's ~20,000 metric objects every 5 seconds. This is the single biggest performance concern in the frontend.

7. **`Snapshot` and `Metric` interfaces are duplicated** across `MetricsSection.tsx`, `TransportMap.tsx`, and `MobileSection.tsx`. Three identical interface definitions. Should be in a shared `types.ts` file. If the API response shape changes, you need to update three files.

8. **`MetricChart` is also duplicated** — near-identical component exists in both `MetricsSection.tsx` (lines 44-77) and `MobileSection.tsx` (lines 68-101). Same props, same chart options, same styling. Extract to a shared component.

9. **Linear search for metrics by name (lines 175, 203).** `latest.metrics.find((m) => m.metric_name === name)` is called once per metric name per render. With 4 metrics this is negligible, but the pattern is O(n*m) where n is metric names and m is metrics per snapshot. A `Map<string, Metric>` would be cleaner.

10. **No `AbortController` on the fetch (lines 248-252).** If the component unmounts during a fetch (e.g. navigation), the `setSnapshots` call fires on an unmounted component. React 19 handles this more gracefully than older versions, but `TransportMap` already does it correctly with `AbortController` — this component should too for consistency.

11. **Metadata section shows redundant information.** "Device" and "Device Name" both show `latest.device_name`. "Source" appears in both the metadata grid and the badge in the header. Wasted screen real estate in a card that's already information-dense.

---

## `TransportMap.tsx` — Most Complex, Most Impressive

### Strengths

- **Delta fetching with `since` cursor (lines 124-145).** After the initial load, only new snapshots are fetched. This is dramatically more efficient than re-fetching everything — critical when tracking hundreds of buses.
- **Sliding window with `maxSnapshots` cap (line 139).** Prevents unbounded memory growth during long sessions. Old snapshots are sliced off the front.
- **Time clustering (lines 35-50).** `clusterTimestamps()` groups timestamps within 30 seconds into collection intervals. This means the slider snaps to logical "collection cycles" rather than individual snapshot timestamps. Smart abstraction.
- **Vehicle deduplication in `displayedVehicles` (lines 178-184).** When multiple snapshots exist for the same vehicle in a cluster, only the latest is shown. Prevents duplicate markers.
- **Live/Stale/Historical tri-state.** The slider distinguishes between "live" (tracking latest data), "stale" (live but no recent data), and "historical" (user has scrubbed back). The `isLiveRef` + `isLive` dual tracking keeps the ref in sync with the state for use inside callbacks.
- **`AbortController` for fetch cleanup (lines 153-159).** Both `fetchInitial` and `fetchDelta` accept a signal and abort cleanly on unmount. Textbook.
- **Comprehensive abort error filtering (line 119).** Checks `ERR_CANCELED`, `AbortError`, and `CanceledError` — covers axios and native fetch abort patterns.

### Issues

12. **Google Maps API key in `process.env.REACT_APP_GOOGLE_MAPS_API_KEY` (line 87).** CRA embeds this into the JavaScript bundle at build time. Anyone viewing the page source can see the key. For a public-facing app, you'd need to restrict the key to your domain in the Google Cloud Console. For a demo, fine, but be ready for the question.

13. **`initialLimit = 20000` default (line 67).** The initial fetch loads up to 20,000 snapshots. Each snapshot has 2-3 metrics. The GET endpoint returns them as a JSON array that gets parsed, then the component iterates them to compute timestamps and clusters. On a slow connection or with a large dataset, this causes a noticeable loading delay and a memory spike. No loading indicator is shown beyond the brief "No data yet" message.

14. **`useJsApiLoader` is called on every render of `TransportMap` (line 86).** The hook internally memoizes, but if the component unmounts and remounts, it re-loads the Google Maps script. In practice this rarely happens, but it's worth noting.

15. **`selectedSnap` fallback (line 202-203).** If no snapshot exists at or before the selected time, it falls back to the last snapshot in the array. This could show a snapshot from a completely different time period, which would make the metadata (collected_at, received_at, latency) misleading.

16. **`reduce` for min/max timestamps (lines 96-97).** `timestamps.reduce((a, b) => Math.min(a, b))` on a 20,000-element array is fine performance-wise, but `Math.min(...timestamps)` would be more readable. However, `Math.min(...)` would blow the call stack on 20,000 elements, so `reduce` is actually the correct choice here. Worth a comment explaining why.

17. **No debouncing on the slider (lines 162-168).** Moving the slider rapidly fires `onChange` for every pixel, each triggering a state update that recomputes `displayedVehicles` via `useMemo`. The `useMemo` itself is fast, but rapid state updates cause rapid re-renders of the entire map with all markers. Debouncing or throttling the slider would smooth this out.

18. **`latencyMs` can be misleading for transport data (line 206).** For the transport collector, `received_at - collected_at` includes both network latency *and* queue delay (the snapshot may have waited in Redis before upload). The label says "Latency" without qualification. For system metrics (10s interval, no queue backlog), it's approximately accurate. For transport data (60s interval, batched upload), it could be minutes. Worth clarifying.

---

## `MobileSection.tsx` — Clever Parsing of Flat Data

### Strengths

- **`parseMobileMetric()` (lines 55-64) correctly reverses the collector's metric naming convention.** The mobile collector packs all devices into a single snapshot with names like `mobile_{uuid}_{field}`. This parser extracts the UUID and field name correctly, knowing that UUIDs contain no underscores.
- **Feed-level staleness (line 276).** Correctly reasons that since all mobile users appear in every snapshot, staleness is a feed-level property, not per-device. Well-documented with a comment.
- **Error state handling (line 218, 271).** Unlike `MetricsSection`, this component tracks and displays fetch errors. Good UX.
- **`values.length < 2` guard on charts (line 188).** Skips charts when there's insufficient data for a meaningful line. Prevents empty chart containers.

### Issues

19. **Same full re-fetch pattern as `MetricsSection` (lines 220-228).** No delta fetching. Reloads up to 1000 snapshots every 5 seconds.

20. **`parseMobileMetric` assumes UUIDs contain no underscores (line 58).** It splits on the first `_` after the `mobile_` prefix. This works for UUIDs (`550e8400-e29b-41d4-a716-446655440000` — hyphens, not underscores). But if anyone uses a non-UUID `user_id` with underscores (e.g. `john_doe`), the parsing breaks silently — `userId` becomes `john` and `field` becomes `doe_battery_level`. The assumption is reasonable but not validated or documented in the code.

21. **Duplicated chart component and card styling.** The `MetricChart` component and the "current metric value cards" rendering logic in `MobileDeviceSection` (lines 152-174) is nearly identical to `DeviceSection` in `MetricsSection.tsx` (lines 173-195). Same inline styles, same colour cycling, same value formatting. This is a copy-paste that should be extracted.

---

## Cross-Component Issues

### Duplicate Code

22. **`Snapshot` / `Metric` interfaces** — identical in 3 files. Extract to `types.ts`.

23. **`MetricChart` component** — identical in `MetricsSection.tsx` and `MobileSection.tsx`. Extract to `MetricChart.tsx`.

24. **Device header styling** — the card header with device name, aggregator, source badge, and Live/Stale indicator uses the same inline styles across all three components. Extract to a shared `DeviceHeader` component.

25. **Metric value card rendering** — same pattern in `MetricsSection` and `MobileSection`. Same inline styles, same `value % 1 === 0` formatting logic.

### Inline Styles

26. **All styling is inline `style={{}}` objects.** There's no CSS file used beyond the CRA default `index.css`. Every component has dozens of inline style objects with hardcoded colours, font sizes, paddings, and border radii. This makes the UI:
   - **Hard to change globally** — want to adjust the border radius from `10px` to `8px`? Find and update every component.
   - **Hard to read** — JSX is cluttered with style objects that obscure the component structure.
   - **Not cacheable** — inline styles generate new objects on every render (though React's reconciler handles this without layout thrash).

   For a project of this size, even CSS modules or a simple shared `styles.ts` constants file would be a significant improvement. A judge looking at code quality will notice this.

### Data Fetching

27. **No shared data-fetching hook.** All three components implement the same pattern: `useState` for snapshots, `useCallback` for the fetch function, `useEffect` for polling with cleanup. This could be a single `usePolledSnapshots(source, limit, pollInterval)` hook. `TransportMap`'s delta-fetch variant would extend the base hook.

28. **No loading states for initial fetch.** `MetricsSection` and `MobileSection` show "No data yet" during the initial load. There's no spinner or "Loading..." indicator. If the API is slow, the user sees empty sections for several seconds.

### Test Coverage

29. **`App.test.tsx` still has the CRA boilerplate test (line 6: `getByText(/learn react/i)`).** This test will fail because the app no longer contains "learn react" text. It's a broken test that signals the test suite hasn't been maintained.

---

## `public/config.toml` — Frontend Configuration

### Strengths

- Clean separation of concerns: UI settings, per-section sources, map defaults.
- `api_base = ""` means the frontend uses relative URLs, which work with CRA's `proxy` setting in development and with same-origin deployment in production.

### Issues

30. **`proxy` in `package.json` points to `http://100.67.157.90:5000` (line 37).** Same hardcoded Tailscale IP as the backend config. Works for your setup but worth explaining during the demo.

31. **No `poll_interval` for the `system` section.** `MetricsSection` defaults to `pollInterval = 5000` (5 seconds) internally. The `transport` section has no `poll_interval` either — `TransportMap` defaults to `30000` (30 seconds) internally. Only `mobile_app` has it in config. Inconsistent — either all sections should have it in config, or none should.

---

## `package.json` — Dependency Notes

32. **TypeScript 4.9.5 with React 19.** React 19's type definitions target TypeScript 5.x. This can cause type errors with newer `@types/react` packages. Works for now, but a `typescript: "^5.0"` bump would be safer.

33. **Testing libraries in `dependencies`, not `devDependencies`.** `@testing-library/*`, `@types/jest`, and `@types/node` are in the main `dependencies` block. These are dev-only packages. In a CRA project this doesn't affect the bundle (CRA handles tree-shaking), but it's technically incorrect and a code quality tell.

---

## Summary Table

| Severity | Issue | File | Line(s) |
|---|---|---|---|
| **Performance** | `MetricsSection` re-fetches ALL data every 5s (no delta) | `MetricsSection.tsx` | 239-245 |
| **Performance** | `MobileSection` same full re-fetch pattern | `MobileSection.tsx` | 220-228 |
| **Performance** | Initial 20,000 snapshot load with no loading indicator | `TransportMap.tsx` | 67, 105-121 |
| **Bug** | `App.test.tsx` is broken (CRA boilerplate, tests for deleted text) | `App.test.tsx` | 6 |
| **Bug** | Config load failure shows blank screen, no error | `App.tsx` | 15, 18 |
| **Robustness** | Unsafe `as unknown as FrontendConfig` cast, no validation | `App.tsx` | 14 |
| **DRY** | `Snapshot`/`Metric` interfaces duplicated in 3 files | All 3 components | — |
| **DRY** | `MetricChart` component duplicated in 2 files | `MetricsSection`, `MobileSection` | — |
| **DRY** | Device header + metric cards inline styles duplicated | All 3 components | — |
| **Style** | All styling is inline — no CSS modules, no shared constants | All components | — |
| **Config** | `ms_per_sec = 1000` is a physical constant, not config | `config.toml` | 5 |
| **Config** | `poll_interval` only configurable for `mobile_app`, not others | `config.toml` | — |
| **Deps** | Test libraries in `dependencies` not `devDependencies` | `package.json` | 7-12 |
| **Deps** | TypeScript 4.9 with React 19 type defs | `package.json` | 22 |

---

## Priority Fixes Before Presenting

### Must-fix
- Delete or fix `App.test.tsx` (broken test is worse than no test)
- Extract `Snapshot`/`Metric` interfaces to a shared `types.ts`
- Extract `MetricChart` to its own file
- Add error state to `App.tsx` config loading

### Should-fix
- Add delta fetching to `MetricsSection` (match `TransportMap`'s pattern)
- Add loading indicators for initial data fetch
- Remove `ms_per_sec` from config, make it a code constant
- Add `poll_interval` to all config sections for consistency
- Move test libraries to `devDependencies`

### Be ready to discuss
- Why TOML for frontend config (consistency with backend, human-readable, no build step needed to change)
- Delta fetching in `TransportMap` vs full re-fetch in other components — why the difference and what you'd do to unify
- Google Maps API key exposure and how to mitigate
- The time slider + clustering mechanism (this is the most impressive UI feature)
- Inline styles trade-off: fast to prototype vs hard to maintain
- Why `animation: false` on charts (polling dashboard, not a static report)

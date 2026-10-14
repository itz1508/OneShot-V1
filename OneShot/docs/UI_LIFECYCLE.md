# UI lifecycle reducer (implemented)

**Status:** implemented. The runtime module is `frontend/lifecycle.js`; the behavioural tests are `frontend/tests/lifecycle.test.mjs`. This document is a *reference for the pattern that is already in the code* — not a design proposal.

## 1. Why a reducer

The UI shuttles between a small, fixed set of screens: `SourceManagement`, `Starting`, `ProcessDisplay`, `Pausing`, `Paused`, `EditorReview`. Click-handlers that flip multiple booleans drift over time and let impossible combinations through (`accepted && paused && !jobId`). A single reducer with an explicit transition table makes the legal paths visible and testable, and it keeps the UI code free of inline state mutation.

The pattern matches React's `useReducer` guidance exactly. The vanilla ES-module implementation keeps the OneShot frontend bundler-free; the function signature mirrors React so a future wrapper can delegate without rewriting rules:

```js
// React
const [state, dispatch] = useReducer(lifecycleReducer, INITIAL_STATE);
```

```js
// Vanilla, implemented today
import { createLifecycleStore } from './lifecycle.js';
const store = createLifecycleStore();            // store.getState() + store.dispatch(event)
const stop = store.subscribe(s => render(s));    // useEffect-equivalent cleanup contract
```

## 2. Transition table

| From \ Event | `START_REQUESTED` | `OPERATION_ACCEPTED` | `START_REJECTED` | `PAUSE_REQUESTED` | `PAUSE_CONFIRMED` | `PAUSE_FAILED` | `RESUME_CONFIRMED` | `STOP_FINALIZED` | `FINALIZED` | `FILE_SELECTED` | `REVIEW_CLOSED` | `REVIEW_OPENED` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `SourceManagement` | → `Starting` | — | — | — | — | — | — | — | — | → `EditorReview` | — | — |
| `Starting`         | — | → `ProcessDisplay` | → `EditorReview` | — | — | — | — | — | — | — | — | — |
| `ProcessDisplay`   | — | — | — | → `Pausing` | — | — | — | — | → `EditorReview` | — | — | → `EditorReview` |
| `Pausing`          | — | — | — | — | → `Paused` | → `ProcessDisplay` | — | — | — | — | — | — |
| `Paused`           | — | — | — | — | — | — | → `ProcessDisplay` | → `EditorReview` | — | — | — | — |
| `EditorReview`     | → `Starting` | — | — | — | — | — | — | — | — | — | → `SourceManagement` | — |

An empty cell is a **forbidden** transition. The reducer returns the current state unchanged when it hits one, which the test suite asserts (e.g. `SourceManagement + PAUSE_CONFIRMED → SourceManagement`).

## 3. Pause requires backend confirmation

Clicking **Pause** flips the UI to `Pausing` only. The screen must not advance to `Paused` until a backend `PAUSE_CONFIRMED` event arrives. If the backend reports `PAUSE_FAILED`, the UI returns to `ProcessDisplay`. This is enforced by:

- the reducer (no `PAUSE_CONFIRMED` row from `ProcessDisplay`);
- the port adapter (`attachLifecyclePort`) is the only place that dispatches the confirmed/failed events;
- `frontend/tests/lifecycle.test.mjs::reducer: pause requires backend confirmation` locks the behaviour.

The same rule applies to `START_REQUESTED → Starting`; the UI leaves `Starting` only on `OPERATION_ACCEPTED` or `START_REJECTED` — never on an optimistic client assumption.

## 4. Port adapter (external-event boundary)

```js
import { createLifecycleStore, attachLifecyclePort } from './lifecycle.js';
import { mapToLifecycleEvent } from './events.js';   // project-specific adapter

const store = createLifecycleStore();
const stop = attachLifecyclePort(store, (dispatch) => {
  const sse = new EventSource('/api/conversations/' + cid + '/events/stream');
  const onActivity = (msg) => {
    const event = mapToLifecycleEvent(JSON.parse(msg.data));
    if (event) dispatch(event);
  };
  sse.addEventListener('activity', onActivity);
  return () => sse.close();   // cleanup; matches React useEffect(() => () => …, [])
});

store.subscribe((s) => render(s));
// …
stop();   // on unmount / logout
```

The reducer and the store **never** perform I/O. The port adapter owns subscribe/unsubscribe so swapping SSE for polling, or wiring the same reducer behind a React component, only touches the adapter.

## 5. React equivalence (reference only — not an invocation to migrate)

For a React component the same reducer wires in via `useReducer`:

```jsx
import { useReducer, useEffect } from 'react';
import { lifecycleReducer, INITIAL_STATE } from './lifecycle.js';
import { subscribeLifecycle } from './port.js';

export function useProcessLifecycle(port) {
  const [state, dispatch] = useReducer(lifecycleReducer, INITIAL_STATE);
  useEffect(() => subscribeLifecycle(port, dispatch), [port]);
  return [state, dispatch];
}
```

Rules of Hooks remain in force (top-level only, consistent order, include all reactive dependencies). The vanilla module above is deliberately framework-free so the OneShot build keeps `node build.mjs` as a plain copy step.

## 6. What this document is not

- Not a backlog item: the module and its tests exist in the shipped tree.
- Not a React migration plan: the frontend remains vanilla ES modules.
- Not a design mockup: there are no screens, no controls, no visuals here that are not already rendered by `frontend/app.js`.

## 7. See also

- `frontend/lifecycle.js` — the implementation.
- `frontend/tests/lifecycle.test.mjs` — 14 test cases, run via `npm test` or `make test-frontend`.
- `docs/WORKFLOWS.md` — the workflow-to-code anchors (D-01 … D-08), where the UI lifecycle is referenced from the "UI lifecycle (reducer pattern)" section at the bottom.


## 7. Reconsidered: React modernization

The mission brief asked for the React option to be reconsidered on real evidence rather than ruled out by assumption. The comparison, grounded in the shipped tree:

| Dimension | Keep vanilla ES modules (shipped) | Introduce React |
|---|---|---|
| Reducer shape | `lifecycleReducer(state, event)` already matches `useReducer`. The vanilla store (`createLifecycleStore`) exposes `getState()` + `dispatch()`; `attachLifecyclePort(store, bind)` returns a disposer, matching `useEffect(() => () => cleanup())`. | Same reducer under `useReducer`; no logic difference. |
| Bundle | No bundler, no npm `react`/`react-dom` runtime, 0 KB of framework code served to the operator. `npm run build` is 20 lines of `copyFile`. | Requires a bundler (Vite / esbuild / Rollup), an entry runtime of ~45 KB gzipped React + ReactDOM, plus a build graph to maintain. |
| Tests | 57 `node --test` cases run in ~0.4 s against the pure modules. Pure-reducer snapshots (`frontend/tests/visual_states.test.mjs`) cover each of the six screens. | Equivalent coverage needs either `@testing-library/react` + jsdom (slower start, more dependencies) or a reducer suite — i.e. what we already have. |
| E2E | `tests/e2e_browser.py` (Playwright on real Chromium against the built dist) passes end-to-end: login → attach source → start job → verify Apply + restart persistence. | Would need to be rewritten against the React DOM, and the same E2E would still be required. |
| Migration cost | Zero. | Rewriting `app.js` component-by-component (login, workspace, sources, review, process, presend dialog, settings panel) is a multi-week effort for the same user-visible outcome. |
| Future React wrapper | Trivial — `lifecycleReducer` and the pure helpers in `workspace.js` are already shaped for `useReducer`/`useMemo`. Introducing React later means wrapping, not rewriting. | — |

**Decision — retained as implementation:** keep vanilla ES modules. The React Hooks patterns the brief cites (declarative state machine, "mock every state", "remove non-essential state", pause-requires-backend-confirmation, impression listener) are applied in the shipped tree without React itself. The reducer signature keeps a future React wrapper cheap if a product reason to adopt it appears. No real-E2E or UX quality gain is visible today that would justify the migration cost.

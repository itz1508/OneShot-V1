/**
 * UI lifecycle reducer. Pure, framework-free, and matches the React Hooks
 * guidance in `docs/UI_LIFECYCLE.md` section 2 (the useReducer transition
 * table). Vanilla JS keeps the existing OneShot frontend bundler-free while
 * still giving the UI a deterministic, test-anchored state machine.
 *
 * Export shape mirrors React's useReducer so a future useReducer() wrapper
 * can delegate here without rewriting rules:
 *     const [state, dispatch] = useReducer(lifecycleReducer, initialState);
 */

export const INITIAL_STATE = Object.freeze({
  screen: 'SourceManagement',
  outcome: null,
  jobId: null,
});

/**
 * Permitted transition table. Each row is the current screen; each key is an
 * event name; the value is the next screen. A missing cell means the
 * transition is forbidden and the reducer must return the current state
 * unchanged.
 */
export const TRANSITIONS = Object.freeze({
  SourceManagement: Object.freeze({
    START_REQUESTED: 'Starting',
    FILE_SELECTED:   'EditorReview',
  }),
  Starting: Object.freeze({
    OPERATION_ACCEPTED: 'ProcessDisplay',
    START_REJECTED:     'EditorReview',
  }),
  ProcessDisplay: Object.freeze({
    PAUSE_REQUESTED: 'Pausing',
    FINALIZED:       'EditorReview',
    REVIEW_OPENED:   'EditorReview',
  }),
  Pausing: Object.freeze({
    PAUSE_CONFIRMED: 'Paused',
    PAUSE_FAILED:    'ProcessDisplay',
  }),
  Paused: Object.freeze({
    RESUME_CONFIRMED: 'ProcessDisplay',
    STOP_FINALIZED:   'EditorReview',
  }),
  EditorReview: Object.freeze({
    REVIEW_CLOSED:    'SourceManagement',
    START_REQUESTED:  'Starting',
  }),
});

/** Pure reducer. Never performs I/O. */
export function lifecycleReducer(state, event) {
  if (!event || typeof event.type !== 'string') return state;
  const row = TRANSITIONS[state.screen];
  if (!row) return state;
  const next = row[event.type];
  if (!next) return state;

  let outcome = state.outcome;
  if (event.type === 'FINALIZED') outcome = event.outcome ?? state.outcome;
  else if (event.type === 'STOP_FINALIZED') outcome = 'stopped';
  else if (event.type === 'START_REQUESTED') outcome = null;

  let jobId = state.jobId;
  if (event.type === 'OPERATION_ACCEPTED' && event.jobId !== undefined) jobId = event.jobId;
  if (event.type === 'START_REQUESTED' || event.type === 'REVIEW_CLOSED') jobId = null;

  return Object.freeze({ screen: next, outcome, jobId });
}

/**
 * Minimal observable store, equivalent in semantics to the (state, dispatch)
 * pair returned by React's useReducer. subscribe(listener) is the
 * useEffect-equivalent attach/detach boundary that the official React guide
 * recommends for connecting to external systems.
 */
export function createLifecycleStore(initial = INITIAL_STATE) {
  let state = initial;
  const listeners = new Set();

  function getState() { return state; }

  function dispatch(event) {
    const next = lifecycleReducer(state, event);
    if (next === state) return state;
    state = next;
    for (const listener of listeners) listener(state);
    return state;
  }

  function subscribe(listener) {
    if (typeof listener !== 'function') throw new TypeError('listener must be a function');
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  }

  return { getState, dispatch, subscribe };
}

/**
 * Adapter for an external event source (e.g. the existing SSE stream wired
 * in app.js). The adapter owns the subscribe/unsubscribe boundary so the
 * reducer stays pure. Returns a disposer, matching the cleanup contract of
 * React's useEffect return value.
 *
 *   const stop = attachLifecyclePort(store, (dispatch) => {
 *     const sse = new EventSource('/api/.../events/stream');
 *     sse.addEventListener('activity', m => dispatch(mapToLifecycleEvent(m)));
 *     return () => sse.close();
 *   });
 */
export function attachLifecyclePort(store, bind) {
  if (typeof bind !== 'function') throw new TypeError('bind must be a function');
  const disposer = bind(store.dispatch);
  if (disposer != null && typeof disposer !== 'function') {
    throw new TypeError('bind must return a disposer function or nothing');
  }
  return () => { if (disposer) disposer(); };
}

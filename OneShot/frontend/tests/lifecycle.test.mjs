import test from 'node:test';
import assert from 'node:assert/strict';
import {
  INITIAL_STATE,
  TRANSITIONS,
  lifecycleReducer,
  createLifecycleStore,
  attachLifecyclePort,
} from '../lifecycle.js';

// Reducer purity -------------------------------------------------------------

test('reducer: initial state matches the diagram root', () => {
  assert.equal(INITIAL_STATE.screen, 'SourceManagement');
  assert.equal(INITIAL_STATE.outcome, null);
  assert.equal(INITIAL_STATE.jobId, null);
});

test('reducer: unknown events return the same state identity', () => {
  const s = INITIAL_STATE;
  assert.equal(lifecycleReducer(s, { type: 'DOES_NOT_EXIST' }), s);
  assert.equal(lifecycleReducer(s, {}), s);
  assert.equal(lifecycleReducer(s, null), s);
});

test('reducer: SourceManagement -> Starting on START_REQUESTED', () => {
  const next = lifecycleReducer(INITIAL_STATE, { type: 'START_REQUESTED' });
  assert.equal(next.screen, 'Starting');
  assert.equal(next.outcome, null);
  assert.equal(next.jobId, null);
});

test('reducer: Starting -> ProcessDisplay carries jobId when OPERATION_ACCEPTED', () => {
  const starting = lifecycleReducer(INITIAL_STATE, { type: 'START_REQUESTED' });
  const running = lifecycleReducer(starting, { type: 'OPERATION_ACCEPTED', jobId: 'abc' });
  assert.equal(running.screen, 'ProcessDisplay');
  assert.equal(running.jobId, 'abc');
});

test('reducer: Starting -> EditorReview on START_REJECTED', () => {
  const starting = lifecycleReducer(INITIAL_STATE, { type: 'START_REQUESTED' });
  const rejected = lifecycleReducer(starting, { type: 'START_REJECTED' });
  assert.equal(rejected.screen, 'EditorReview');
});

test('reducer: pause requires backend confirmation (Pausing != Paused)', () => {
  const starting = lifecycleReducer(INITIAL_STATE, { type: 'START_REQUESTED' });
  const running = lifecycleReducer(starting, { type: 'OPERATION_ACCEPTED' });
  const pausing = lifecycleReducer(running, { type: 'PAUSE_REQUESTED' });
  assert.equal(pausing.screen, 'Pausing', 'click Pause flips to Pausing, not Paused');
  const paused = lifecycleReducer(pausing, { type: 'PAUSE_CONFIRMED' });
  assert.equal(paused.screen, 'Paused');
});

test('reducer: Pausing -> ProcessDisplay on PAUSE_FAILED', () => {
  const paused = lifecycleReducer(
    lifecycleReducer(
      lifecycleReducer(INITIAL_STATE, { type: 'START_REQUESTED' }),
      { type: 'OPERATION_ACCEPTED' },
    ),
    { type: 'PAUSE_REQUESTED' },
  );
  assert.equal(paused.screen, 'Pausing');
  assert.equal(lifecycleReducer(paused, { type: 'PAUSE_FAILED' }).screen, 'ProcessDisplay');
});

test('reducer: FINALIZED records outcome, STOP_FINALIZED sets stopped', () => {
  const running = lifecycleReducer(
    lifecycleReducer(INITIAL_STATE, { type: 'START_REQUESTED' }),
    { type: 'OPERATION_ACCEPTED' },
  );
  const done = lifecycleReducer(running, { type: 'FINALIZED', outcome: 'completed' });
  assert.equal(done.screen, 'EditorReview');
  assert.equal(done.outcome, 'completed');

  const paused = lifecycleReducer(
    lifecycleReducer(running, { type: 'PAUSE_REQUESTED' }),
    { type: 'PAUSE_CONFIRMED' },
  );
  const stopped = lifecycleReducer(paused, { type: 'STOP_FINALIZED' });
  assert.equal(stopped.screen, 'EditorReview');
  assert.equal(stopped.outcome, 'stopped');
});

// Forbidden transitions ------------------------------------------------------

test('reducer: forbidden transitions never change state', () => {
  // SourceManagement cannot go straight to Paused.
  assert.equal(lifecycleReducer(INITIAL_STATE, { type: 'PAUSE_CONFIRMED' }).screen,
               'SourceManagement');
  // Paused cannot accept START_REQUESTED directly.
  const paused = lifecycleReducer(
    lifecycleReducer(
      lifecycleReducer(
        lifecycleReducer(INITIAL_STATE, { type: 'START_REQUESTED' }),
        { type: 'OPERATION_ACCEPTED' },
      ),
      { type: 'PAUSE_REQUESTED' },
    ),
    { type: 'PAUSE_CONFIRMED' },
  );
  assert.equal(paused.screen, 'Paused');
  assert.equal(lifecycleReducer(paused, { type: 'START_REQUESTED' }).screen, 'Paused');
});

test('reducer: review loop EditorReview -> SourceManagement -> Starting', () => {
  const review = lifecycleReducer(
    lifecycleReducer(INITIAL_STATE, { type: 'FILE_SELECTED' }),
    { type: 'REVIEW_CLOSED' },
  );
  assert.equal(review.screen, 'SourceManagement');
  const starting = lifecycleReducer(review, { type: 'START_REQUESTED' });
  assert.equal(starting.screen, 'Starting');
});

// Transition table shape -----------------------------------------------------

test('TRANSITIONS covers every screen in INITIAL_STATE closure', () => {
  const reachable = new Set(['SourceManagement']);
  let changed = true;
  while (changed) {
    changed = false;
    for (const screen of reachable) {
      const row = TRANSITIONS[screen];
      assert.ok(row, `screen ${screen} missing from TRANSITIONS`);
      for (const next of Object.values(row)) {
        if (!reachable.has(next)) { reachable.add(next); changed = true; }
      }
    }
  }
  for (const screen of Object.keys(TRANSITIONS)) {
    assert.ok(reachable.has(screen), `screen ${screen} is declared but unreachable`);
  }
});

// Store + port adapter -------------------------------------------------------

test('createLifecycleStore: notifies subscribers only on real transitions', () => {
  const store = createLifecycleStore();
  const seen = [];
  const unsub = store.subscribe(s => seen.push(s.screen));
  store.dispatch({ type: 'DOES_NOT_EXIST' });
  store.dispatch({ type: 'START_REQUESTED' });
  store.dispatch({ type: 'OPERATION_ACCEPTED', jobId: 'xyz' });
  unsub();
  store.dispatch({ type: 'PAUSE_REQUESTED' });
  assert.deepEqual(seen, ['Starting', 'ProcessDisplay']);
  assert.equal(store.getState().screen, 'Pausing');
});

test('attachLifecyclePort: returns a disposer that cleans up the bind', () => {
  const store = createLifecycleStore();
  let bound = false;
  const stop = attachLifecyclePort(store, (dispatch) => {
    bound = true;
    dispatch({ type: 'START_REQUESTED' });
    return () => { bound = false; };
  });
  assert.ok(bound);
  assert.equal(store.getState().screen, 'Starting');
  stop();
  assert.equal(bound, false);
});

test('attachLifecyclePort: rejects non-function bind and non-function disposer', () => {
  const store = createLifecycleStore();
  assert.throws(() => attachLifecyclePort(store, null), /function/);
  assert.throws(() => attachLifecyclePort(store, () => 42), /disposer/);
});

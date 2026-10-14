import test from 'node:test';
import assert from 'node:assert/strict';
import { INITIAL_STATE, lifecycleReducer, TRANSITIONS } from '../lifecycle.js';

// Reaches each of the six named screens by dispatching the shortest legal
// event sequence from INITIAL_STATE, and asserts the resulting state object
// against a frozen snapshot. Pure reducer, zero DOM — the "mock up every
// state" recipe from https://react.dev/learn/reacting-to-input-with-state.

function reach(sequence) {
  return sequence.reduce((state, event) => lifecycleReducer(state, event), INITIAL_STATE);
}

test('visual state 1: SourceManagement (initial)', () => {
  const state = reach([]);
  assert.deepEqual(state, { screen: 'SourceManagement', outcome: null, jobId: null });
});

test('visual state 2: Starting (after START_REQUESTED)', () => {
  const state = reach([{ type: 'START_REQUESTED' }]);
  assert.deepEqual(state, { screen: 'Starting', outcome: null, jobId: null });
});

test('visual state 3: ProcessDisplay (after OPERATION_ACCEPTED with jobId)', () => {
  const state = reach([{ type: 'START_REQUESTED' }, { type: 'OPERATION_ACCEPTED', jobId: 'job-xyz' }]);
  assert.deepEqual(state, { screen: 'ProcessDisplay', outcome: null, jobId: 'job-xyz' });
});

test('visual state 4: Pausing (ProcessDisplay + PAUSE_REQUESTED, awaits backend)', () => {
  const state = reach([
    { type: 'START_REQUESTED' },
    { type: 'OPERATION_ACCEPTED', jobId: 'job-xyz' },
    { type: 'PAUSE_REQUESTED' },
  ]);
  assert.equal(state.screen, 'Pausing');
  // Still carries the jobId; outcome stays null until the backend confirms.
  assert.equal(state.jobId, 'job-xyz');
  assert.equal(state.outcome, null);
});

test('visual state 5: Paused (only after backend PAUSE_CONFIRMED)', () => {
  const state = reach([
    { type: 'START_REQUESTED' },
    { type: 'OPERATION_ACCEPTED', jobId: 'job-xyz' },
    { type: 'PAUSE_REQUESTED' },
    { type: 'PAUSE_CONFIRMED' },
  ]);
  assert.equal(state.screen, 'Paused');
  assert.equal(state.jobId, 'job-xyz');
});

test('visual state 6: EditorReview (ProcessDisplay + FINALIZED)', () => {
  const state = reach([
    { type: 'START_REQUESTED' },
    { type: 'OPERATION_ACCEPTED', jobId: 'job-xyz' },
    { type: 'FINALIZED', outcome: 'completed' },
  ]);
  assert.equal(state.screen, 'EditorReview');
});

test('transition table defines exactly the six screens as "from" rows', () => {
  const expected = new Set([
    'SourceManagement', 'Starting', 'ProcessDisplay',
    'Pausing', 'Paused', 'EditorReview',
  ]);
  assert.deepEqual(new Set(Object.keys(TRANSITIONS)), expected);
});

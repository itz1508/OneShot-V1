/** Pure workspace admission/projection rules used by the real UI. */
export const ACTIVE_JOB = new Set(['queued','running']);
export const FINAL_JOB = new Set(['completed','blocked','failed']);
export function startBlocker({ connected, selected, dirty, pending, sessionActive, promptMessageId, unsentPrompt = false }) {
  if (!connected) return 'System connection is unavailable';
  if (sessionActive) return 'System composer is read-only while Agent session is active';
  if (pending) return 'An operation is already in progress';
  if (unsentPrompt) return 'Send or clear the unsent System message before Start';
  if (!promptMessageId) return 'Send a System objective before processing';
  if (!selected.length) return 'Select at least one source';
  if (selected.some(id => dirty.has(id))) return 'Save draft changes before processing selected originals';
  return null;
}
export function shouldShowProcess({accepted, status, userChangedDetail}) {
  return accepted && ACTIVE_JOB.has(status) && !userChangedDetail;
}
export function nextCursor(previous, events) {
  return events.reduce((max, item) => Math.max(max, item.seq), previous);
}
export function isTerminal(status) { return FINAL_JOB.has(status); }

/** Retrieve every committed event page before using terminal state to stop.
 * A single /events response is bounded to 500 records. Without draining,
 * finishing a run with >500 events would silently drop the remaining history.
 * The caller can render only a bounded recent window, retaining older events
 * in server storage and preserving the monotonically increasing cursor.
 */
export async function replayEventPages(loadPage, after, {pageSize=500, maxPages=25}={}) {
  if(!Number.isSafeInteger(after) || after<0)throw new RangeError('Invalid event cursor');
  const collected=[];
  let cursor=after;
  for(let page=0;page<maxPages;page++) {
    const events=await loadPage(cursor,pageSize);
    if(!Array.isArray(events))throw new TypeError('Event page must be an array');
    if(events.length>pageSize)throw new Error('Event page exceeds limit');
    for(const item of events){
      if(!Number.isSafeInteger(item.seq) || item.seq<=cursor){
        throw new Error('Event sequence does not advance');
      }
      cursor=item.seq;
      collected.push(item);
    }
    if(events.length<pageSize)return {events:collected,cursor,complete:true};
  }
  return {events:collected,cursor,complete:false};
}

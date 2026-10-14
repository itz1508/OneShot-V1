/** System Chat pre-send review. No network, persistence, or Agent ownership. */
const LABELS = new Map([
  ['objective','Objective'],['goal','Objective'],['request','Objective'],['task','Objective'],['intent','Objective'],
  ['output','Expected output'],['expected output','Expected output'],['deliverable','Expected output'],['result','Expected output'],
  ['constraint','Constraints'],['constraints','Constraints'],['requirement','Constraints'],['requirements','Constraints'],
  ['must','Constraints'],['do not','Constraints'],['scope','Scope'],['source scope','Scope'],['files','Scope']
]);
const COLON_LABEL = /^\s*(?:#{1,4}\s*)?([A-Za-z][A-Za-z ]{0,28})\s*:\s*(.*)$/;
const HEADING = /^\s*#{1,4}\s+([A-Za-z][A-Za-z ]{0,28})\s*$/;
export const MESSAGE_LIMIT = 100_000; // existing MessageCreate.content max_length
export const SUMMARY_LIMIT = 12_000;

/** Only copy explicit headings; this is not semantic summarization. */
export function draftContextSummary(original) {
  const sections=[];
  let heading=null;
  let lines=[];
  const flush=()=>{
    if(heading){const value=lines.join('\n').trim();if(value)sections.push(`${heading}:\n${value}`);}
    lines=[];
  };
  let fence=null;
  for(const line of original.split(/\r?\n/)) {
    const fenceMatch=/^\s{0,3}(`{3,}|~{3,})/.exec(line);
    if(fenceMatch){
      const marker=fenceMatch[1];
      if(!fence){fence={char:marker[0],length:marker.length};}
      else if(marker[0]===fence.char && marker.length>=fence.length){fence=null;}
      continue;
    }
    if(fence || /^\s{0,3}>/.test(line))continue;
    const match=COLON_LABEL.exec(line);
    const mark=match ? null : HEADING.exec(line);
    if(match || mark) {
      flush();
      heading=LABELS.get((match||mark)[1].trim().toLowerCase())||null;
      if(heading && match && match[2])lines.push(match[2]);
    } else if(heading) lines.push(line);
  }
  flush();
  const draft=sections.join('\n\n');
  // Do not silently truncate or misrepresent a partial extraction.
  return draft.length<=SUMMARY_LIMIT ? draft : '';
}

/** The exact user-approved payload, preserving all original bytes as text characters. */
export function reviewedMessage(original, summary) {
  if(typeof original!=='string' || !original.trim())throw new Error('Enter a message before sending.');
  if(typeof summary!=='string')throw new TypeError('Summary must be text');
  if(summary.length>SUMMARY_LIMIT)throw new Error('Review summary is too long.');
  const payload=summary.trim()
    ? `Reviewed context summary (user approved; not independently verified):\n${summary.trim()}\n\nOriginal user input (verbatim):\n${original}`
    : original;
  if(payload.length>MESSAGE_LIMIT)throw new Error(`Approved message exceeds the ${MESSAGE_LIMIT}-character server limit.`);
  return payload;
}

/** Freeze original and submit the exact approved preview, without re-reading edits at send time. */
export function createPreSendController({send, onSaved, onError, onChange}) {
  let review=null;
  let pending=false;
  const change=()=>onChange?.(review ? {...review,pending} : null);
  return {
    get review(){return review ? {...review,pending}:null;},
    open({original,conversationId}) {
      if(pending || review)throw new Error('Finish the current review first.');
      if(typeof original!=='string' || !original.trim())throw new Error('Enter a message before reviewing.');
      const summary=draftContextSummary(original);
      review={original,summary,conversationId,payload:reviewedMessage(original,summary),requestKey:crypto.randomUUID()};
      change();return this.review;
    },
    editSummary(summary) {
      if(!review || pending)throw new Error('Review is not editable.');
      if(summary.length>SUMMARY_LIMIT)throw new Error('Review summary is too long.');
      // If a POST was attempted, its key is bound to that exact payload.
      // Editing after uncertain commit creates a new request identity.
      review={...review,summary,payload:reviewedMessage(review.original,summary),
              requestKey:review.attempted ? crypto.randomUUID() : review.requestKey,attempted:false};
      change();return this.review;
    },
    cancel() {
      if(pending)return false;
      review=null;change();return true;
    },
    async approve({currentOriginal,conversationId}) {
      if(!review || pending)return false;
      if(currentOriginal!==review.original || conversationId!==review.conversationId){
        onError?.(new Error('Input or conversation changed. Cancel and review the current input again.'));
        return false;
      }
      // Snapshot the complete payload before awaiting a network response.
      const approved={...review};
      pending=true;review={...review,attempted:true};change();
      try {
        const saved=await send(approved.conversationId,approved.payload,approved.requestKey);
        if(saved?.content!==approved.payload)throw new Error('Saved message differs from approved input; verify server state.');
        review=null;onSaved?.(saved,approved);change();return true;
      }catch(error){onError?.(error);return false;}
      finally{pending=false;change();}
    }
  };
}

"""Deterministic, system-owned context preparation for a saved user request.

This is NOT a semantic intent classifier. Extract explicit headings only and
preserve verbatim current intent. Earlier messages are untrusted references, not
privileged instructions; selected sources are supplied separately by Scanner.
"""
from dataclasses import dataclass
import re

# Labels are recognized only when explicitly authored; free text is not inferred.
_HEADINGS = {
    'intent': {'objective', 'goal', 'request', 'task', 'intent'},
    'expected_output': {'output', 'expected output', 'deliverable', 'result'},
    'constraints': {'constraints', 'constraint', 'requirements', 'requirement', 'must', 'do not'},
    'scope': {'scope', 'source scope', 'files'},
}
_LABEL_TO_KEY = {label: key for key, labels in _HEADINGS.items() for label in labels}
_LABEL = re.compile(r'^\s*(?:#{1,4}\s*)?([A-Za-z][A-Za-z ]{0,28})\s*:\s*(.*)$')
_MARKDOWN_HEADING = re.compile(r'^\s*#{1,4}\s+([A-Za-z][A-Za-z ]{0,28})\s*$')
MAX_HISTORY_MESSAGES = 4
MAX_HISTORY_CHARS = 6000


@dataclass(frozen=True)
class InputContext:
    """Snapshot-scoped, read-only context assembled before Generate."""
    objective_message_id: str
    objective: str
    explicit_sections: tuple[tuple[str, str], ...]
    history: tuple[tuple[str, str], ...]
    omitted_history_count: int
    selected_sources: tuple[tuple[str, str, int, str], ...]

    def metadata(self) -> dict:
        """Safe event/preview facts; intentionally excludes text contents."""
        return {
            'objective_message_id': self.objective_message_id,
            'explicit_sections': [label for label, _ in self.explicit_sections],
            'prior_message_ids': [mid for mid, _ in self.history],
            'omitted_history_count': self.omitted_history_count,
            'source_ids': [sid for sid, _, _, _ in self.selected_sources],
        }

    def provider_context(self) -> dict:
        """Untrusted references: separate from the current objective and source evidence."""
        return {
            'objective_message_id': self.objective_message_id,
            'explicit_sections': [{'field': key, 'verbatim': value} for key, value in self.explicit_sections],
            'conversation_history': [
                {'message_id': mid, 'verbatim': text, 'role': 'earlier_user_context'}
                for mid, text in self.history
            ],
            'omitted_history_count': self.omitted_history_count,
            'selected_source_identity': [
                {'source_id': sid, 'name': name, 'version': version, 'sha256': digest}
                for sid, name, version, digest in self.selected_sources
            ],
        }


def explicit_sections(text: str) -> tuple[tuple[str, str], ...]:
    """Extract only user-authored labelled fields; no semantic paraphrases."""
    sections: list[tuple[str, str]] = []
    field: str | None = None
    lines: list[str] = []

    def flush() -> None:
        nonlocal lines
        if field is not None:
            value = '\n'.join(lines).strip()
            if value:
                sections.append((field, value))
        lines = []

    fence: tuple[str,int] | None = None
    for line in text.splitlines():
        # Fenced and blockquoted examples are source data, never authority-bearing
        # user headings. Keep server extraction aligned with frontend/presend.js.
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            token=marker.group(1)
            if fence is None:
                fence=(token[0],len(token))
            elif token[0]==fence[0] and len(token)>=fence[1]:
                fence=None
            continue
        if fence or re.match(r'^\s{0,3}>', line):
            continue
        match = _LABEL.match(line)
        heading = _MARKDOWN_HEADING.match(line) if match is None else None
        key = _LABEL_TO_KEY.get((match or heading).group(1).strip().lower()) if (match or heading) else None
        if match or heading:
            # Any heading ends the previous explicit section. Unrecognized
            # headings must not be silently folded into the prior constraint.
            flush()
            field = key
            lines = [match.group(2)] if key and match and match.group(2) else []
        elif field is not None:
            lines.append(line)
    flush()
    return tuple(sections)


def build_input_context(store, *, conversation_id: str, objective_message_id: str,
                        selected_sources: tuple[dict, ...]) -> InputContext:
    """Use only saved messages from the same conversation, up to the frozen objective.

    SQLite rowid is used for admission order so a future message cannot enter
    a queued job that executes later. No content is silently truncated: prior
    messages exceeding the budget are omitted and counted explicitly.
    """
    objective_row = store.one(
        "SELECT rowid,content FROM messages WHERE conversation_id=? AND id=? AND channel='system'",
        (conversation_id, objective_message_id),
    )
    if not objective_row or not objective_row['content'].strip():
        raise ValueError('Saved System objective unavailable')
    total_prior = store.one(
        "SELECT COUNT(*) AS n FROM messages WHERE conversation_id=? AND channel='system' AND rowid<?",
        (conversation_id, objective_row['rowid']),
    )['n']
    prior = store.all(
        "SELECT id,content FROM messages WHERE conversation_id=? AND channel='system' AND rowid<? "
        "ORDER BY rowid DESC LIMIT ?",
        (conversation_id, objective_row['rowid'], MAX_HISTORY_MESSAGES),
    )
    recent: list[tuple[str, str]] = []
    total = 0
    for row in prior:
        content = row['content']
        if len(recent) == MAX_HISTORY_MESSAGES or total + len(content) > MAX_HISTORY_CHARS:
            break
        recent.append((row['id'], content))
        total += len(content)
    recent.reverse()
    return InputContext(
        objective_message_id=objective_message_id,
        objective=objective_row['content'],
        explicit_sections=explicit_sections(objective_row['content']),
        history=tuple(recent),
        omitted_history_count=total_prior - len(recent),
        selected_sources=tuple((s['id'], s['name'], s['version'], s['sha256']) for s in selected_sources),
    )

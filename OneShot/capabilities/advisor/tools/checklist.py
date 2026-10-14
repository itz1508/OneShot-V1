"""Grounded structural preparation checklist; never asserts semantic completeness."""
from dataclasses import dataclass
@dataclass(frozen=True)
class Item:
    source_id:str
    label:str
    satisfied:bool
    evidence:str
@dataclass(frozen=True)
class Checklist:
    items:tuple[Item,...]
    @property
    def ready(self):return bool(self.items) and all(x.satisfied for x in self.items)
    @property
    def blockers(self):return [x.label for x in self.items if not x.satisfied]

def prepare(observations:list[dict],objective:str='')->Checklist:
    items=[Item('','objective',bool(objective.strip()),
                'Explicit persisted System objective' if objective.strip() else 'No System objective provided')];seen=set()
    if not observations:return Checklist((Item('','scope',False,'No sources selected'),))
    for s in observations:
        ident=bool(s['id'] and s['sha256'] and s['id'] not in seen);seen.add(s['id'])
        items.extend((
            Item(s['id'],'identity',ident,'Selected source ID and original content hash'),
            Item(s['id'],'coverage',s['coverage']=='complete',s.get('limitation') or s['coverage']),
            Item(s['id'],'content',bool(s['text'].strip()),'Text content available' if s['text'].strip() else 'No readable text'),
        ))
    return Checklist(tuple(items))

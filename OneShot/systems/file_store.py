"""Immutable source bytes, not a capability and not an external provider."""
from pathlib import Path
import os, hashlib, re

class FileStore:
    def __init__(self,root:Path):self.root=root;self.root.mkdir(parents=True,exist_ok=True)
    def put(self,raw:bytes)->str:
        digest=hashlib.sha256(raw).hexdigest();p=self.root/digest[:2]/digest;p.parent.mkdir(parents=True,exist_ok=True)
        if not p.exists():
            tmp=p.with_name(p.name+'.'+os.urandom(6).hex()+'.tmp')
            try:
                with tmp.open('xb') as f:
                    f.write(raw);f.flush();os.fsync(f.fileno())
                # Concurrent writers may store the same bytes; atomic replacement is harmless.
                os.replace(tmp,p)
            finally:tmp.unlink(missing_ok=True)
        if self.read(digest)!=raw:raise ValueError('Original source verification failed')
        return digest
    def read(self,digest:str)->bytes:
        if not re.fullmatch(r'[a-f0-9]{64}',digest):raise ValueError('Bad source hash')
        raw=(self.root/digest[:2]/digest).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Original source integrity failure')
        return raw
    def sanity(self)->None:
        """Confirm the content-addressed root exists and can round-trip a probe byte."""
        if not self.root.is_dir():raise RuntimeError(f"FileStore root missing: {self.root}")
        probe=b"oneshot-filestore-sanity"
        digest=self.put(probe)
        if self.read(digest)!=probe:raise RuntimeError("FileStore round-trip failed")

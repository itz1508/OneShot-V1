"""Source reading (text only). Refuse formats we cannot accurately inspect."""
from pathlib import PurePath
TEXT={'.txt','.md','.py','.ts','.tsx','.js','.jsx','.json','.toml','.yaml','.yml','.csv','.html','.css','.xml','.log'}
def read(name:str,raw:bytes)->str:
    if PurePath(name).suffix.lower() not in TEXT:raise ValueError('Unsupported text file type')
    try:return raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:raise ValueError('Unreadable UTF-8 source') from exc

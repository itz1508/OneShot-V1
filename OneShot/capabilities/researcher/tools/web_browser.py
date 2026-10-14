"""Bounded URL registration. NO automatic fetching of untrusted external links."""
from urllib.parse import urlsplit
import ipaddress

def validate(url:str)->str:
    p=urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):raise ValueError('Public HTTPS URL required')
    host=p.hostname.lower().rstrip('.')
    try:ipaddress.ip_address(host)
    except ValueError:pass
    else:raise ValueError('IP address references not allowed')
    if '.' not in host or host in ('localhost','localhost.localdomain') or host.endswith(('.localhost','.local','.internal','.test')):
        raise ValueError('Local domains not allowed')
    return url

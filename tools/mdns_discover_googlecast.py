#!/usr/bin/env python3
import argparse, json, os, socket, time
from pathlib import Path
from zeroconf import InterfaceChoice, ServiceBrowser, ServiceListener, Zeroconf
SERVICE='_googlecast._tcp.local.'

def props(p):
    out={}
    for k,v in p.items():
        kk=k.decode(errors='ignore') if isinstance(k,bytes) else str(k)
        out[kk]=(v.decode(errors='ignore') if isinstance(v,bytes) else '' if v is None else str(v))
    return out
class L(ServiceListener):
    def __init__(self): self.services={}
    def add_service(self,zc,t,n):
        i=zc.get_service_info(t,n,timeout=3000)
        if not i: return
        pr=props(i.properties); item={'service_name':n,'server':i.server,'addresses':[socket.inet_ntoa(a) for a in i.addresses],'port':i.port,'properties':pr,'cast_name':pr.get('fn') or n,'seen_at':int(time.time())}
        self.services[n]=item; print(json.dumps(item,ensure_ascii=False),flush=True)
    def update_service(self,zc,t,n): self.add_service(zc,t,n)
    def remove_service(self,zc,t,n): self.services.pop(n,None)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--seconds',type=int,default=30); ap.add_argument('--json-output',default=os.getenv('CAST_CACHE_FILE','./data/cast_cache.json')); ap.add_argument('--interfaces',default=os.getenv('CAST_IFACE_IP',''))
    a=ap.parse_args(); zc=Zeroconf(interfaces=[x.strip() for x in a.interfaces.split(',') if x.strip()] if a.interfaces else InterfaceChoice.All); l=L(); ServiceBrowser(zc,SERVICE,l)
    time.sleep(a.seconds); zc.close(); out=Path(a.json_output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(list(l.services.values()),indent=2,ensure_ascii=False)); print('cache gravado em',out)
if __name__=='__main__': main()

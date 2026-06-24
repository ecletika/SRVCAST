#!/usr/bin/env python3
import os, subprocess, time, requests

BACKEND_URL=os.getenv('BACKEND_URL','http://127.0.0.1:8080')
GATEWAY_TOKEN=os.getenv('GATEWAY_TOKEN','troca-este-token-gateway')
GUEST_NET=os.getenv('GUEST_NET','10.50.0.0/16')
CAST_NET=os.getenv('CAST_NET','10.60.0.0/24')
APPLY=os.getenv('APPLY','1')=='1'
INTERVAL=int(os.getenv('INTERVAL_SECONDS','10'))
NFT=os.getenv('NFT_BIN','nft')


def get_acl():
    r=requests.get(f'{BACKEND_URL}/api/acl.json',headers={'x-gateway-token':GATEWAY_TOKEN},timeout=5)
    r.raise_for_status(); return r.json().get('pairs',[])

def render(pairs):
    rules=['table inet hotelcast {',' chain forward {','  type filter hook forward priority 0; policy accept;','  ip saddr '+GUEST_NET+' ip daddr '+CAST_NET+' drop']
    for p in pairs:
        g=p['guest_ip']; c=p['cast_ip']
        rules.append(f'  ip saddr {g} ip daddr {c} tcp dport {{8008,8009,8443}} accept')
        rules.append(f'  ip saddr {g} ip daddr {c} udp accept')
    rules += [' }','}']
    return '\n'.join(rules)+'\n'

def apply(conf):
    if not APPLY: print(conf); return
    subprocess.run([NFT,'delete','table','inet','hotelcast'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    subprocess.run([NFT,'-f','-'],input=conf.encode(),check=True)

def loop(once=False):
    while True:
        apply(render(get_acl()))
        if once: break
        time.sleep(INTERVAL)

if __name__=='__main__':
    import sys
    loop('--once' in sys.argv)

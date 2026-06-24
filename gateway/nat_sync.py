#!/usr/bin/env python3
import os, subprocess
NFT=os.getenv('NFT_BIN','nft')
WAN=os.getenv('WAN_IFACE','').strip()
GUEST=os.getenv('GUEST_NET','10.50.0.0/16')
CAST=os.getenv('CAST_NET','10.60.0.0/24')
APPLY=os.getenv('APPLY','1')=='1'
if not WAN:
    print('WAN_IFACE vazio; NAT não configurado.'); raise SystemExit(0)
conf=f'''table ip hotelcast_nat {{
 chain postrouting {{
  type nat hook postrouting priority srcnat; policy accept;
  oifname "{WAN}" ip saddr {{ {GUEST}, {CAST} }} masquerade
 }}
}}
'''
if APPLY:
    subprocess.run([NFT,'delete','table','ip','hotelcast_nat'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    subprocess.run([NFT,'-f','-'],input=conf.encode(),check=True)
else:
    print(conf)

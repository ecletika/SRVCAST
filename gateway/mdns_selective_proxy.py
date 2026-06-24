#!/usr/bin/env python3
"""Proxy mDNS seletivo para HotelCast.
MVP: escuta perguntas UDP/5353 e responde só quando o IP do hóspede tem pareamento ativo.
Para produção, mantenha cast_cache.json atualizado com tools/mdns_discover_googlecast.py.
"""
import json, os, socket, struct, time, requests

BACKEND_URL=os.getenv('BACKEND_URL','http://127.0.0.1:8080')
GATEWAY_TOKEN=os.getenv('GATEWAY_TOKEN','troca-este-token-gateway')
CACHE=os.getenv('CAST_CACHE_FILE','/opt/hotelcast-gateway/data/cast_cache.json')
BIND=os.getenv('GUEST_IFACE_IP','0.0.0.0')
PORT=5353
REFRESH=int(os.getenv('REFRESH_SECONDS','5'))
SERVICE=b'\x0b_googlecast\x04_tcp\x05local\x00'

def labels(name):
    out=b''
    for part in name.strip('.').split('.'):
        b=part.encode(); out+=bytes([len(b)])+b
    return out+b'\x00'

def load_cache():
    try: return json.load(open(CACHE))
    except Exception: return []

def acl():
    r=requests.get(f'{BACKEND_URL}/api/acl.json',headers={'x-gateway-token':GATEWAY_TOKEN},timeout=3)
    r.raise_for_status(); return {p['guest_ip']:p for p in r.json().get('pairs',[])}

def qname(packet):
    i=12; parts=[]
    while i<len(packet):
        l=packet[i]; i+=1
        if l==0: break
        parts.append(packet[i:i+l]); i+=l
    return b'.'.join(parts).decode(errors='ignore')

def rr(name, typ, ttl, data):
    return labels(name)+struct.pack('!HHIH',typ,1,ttl,len(data))+data

def answer(query, pair, casts):
    cast=None
    for c in casts:
        ips=c.get('addresses') or []
        if pair['cast_ip'] in ips or c.get('cast_name')==pair.get('cast_name'):
            cast=c; break
    if not cast:
        cast={'cast_name':pair.get('cast_name','Chromecast-'+pair['room_number']),'addresses':[pair['cast_ip']],'port':8009,'properties':{}}
    instance=cast.get('cast_name') or pair.get('cast_name') or ('Chromecast-'+pair['room_number'])
    srv=f'{instance}._googlecast._tcp.local'
    target=cast.get('server') or f'{instance.replace(" ","-")}.local'
    props=cast.get('properties') or {'fn':instance,'md':'Chromecast','id':pair['room_number']}
    txt=b''.join(bytes([len(k.encode()+b"="+str(v).encode())])+k.encode()+b'='+str(v).encode() for k,v in props.items() if len(k.encode()+b"="+str(v).encode())<255)
    ip=socket.inet_aton((cast.get('addresses') or [pair['cast_ip']])[0])
    ans=[rr('_googlecast._tcp.local','PTR'.__hash__() and 12,120,labels(srv)), rr(srv,33,120,struct.pack('!HHH',0,0,int(cast.get('port',8009)))+labels(target)), rr(srv,16,120,txt), rr(target,1,120,ip)]
    return query[:2]+b'\x84\x00'+query[4:6]+struct.pack('!HHH',len(ans),0,0)+query[12:]+b''.join(ans)

def main():
    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    s.bind((BIND,PORT))
    print('mDNS seletivo ouvindo em',BIND,PORT,flush=True)
    last=0; pairs={}; casts=[]
    while True:
        data,addr=s.recvfrom(4096)
        now=time.time()
        if now-last>REFRESH:
            try: pairs=acl(); casts=load_cache(); last=now
            except Exception as e: print('refresh erro',e,flush=True)
        src=addr[0]
        if '_googlecast._tcp.local' not in qname(data): continue
        pair=pairs.get(src)
        if not pair: continue
        s.sendto(answer(data,pair,casts),(src,PORT))
        print(src,'->',pair['room_number'],pair['cast_ip'],flush=True)

if __name__=='__main__': main()

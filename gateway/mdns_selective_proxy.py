#!/usr/bin/env python3
"""Proxy mDNS seletivo para SRVCAST/HotelCast.

Escuta perguntas multicast UDP/5353 de clientes Guest e responde apenas
quando o IP do hóspede tem pareamento ativo no backend.

Importante: este serviço deve rodar no host Ubuntu, não dentro do Docker,
porque precisa escutar multicast na interface Guest.
"""
import json
import os
import socket
import struct
import time

import requests

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8080")
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN", "troca-este-token-gateway")
CACHE = os.getenv("CAST_CACHE_FILE", "/opt/hotelcast-gateway/data/cast_cache.json")
GUEST_IFACE_IP = os.getenv("GUEST_IFACE_IP", "0.0.0.0")
PORT = 5353
MCAST_GRP = "224.0.0.251"
REFRESH = int(os.getenv("REFRESH_SECONDS", "5"))


def labels(name: str) -> bytes:
    out = b""
    for part in name.strip(".").split("."):
        b = part.encode()
        out += bytes([len(b)]) + b
    return out + b"\x00"


def load_cache():
    try:
        return json.load(open(CACHE))
    except Exception:
        return []


def acl():
    r = requests.get(
        f"{BACKEND_URL}/api/acl.json",
        headers={"x-gateway-token": GATEWAY_TOKEN},
        timeout=3,
    )
    r.raise_for_status()
    return {p["guest_ip"]: p for p in r.json().get("pairs", [])}


def qname(packet: bytes) -> str:
    i = 12
    parts = []
    while i < len(packet):
        l = packet[i]
        i += 1
        if l == 0:
            break
        if i + l > len(packet):
            break
        parts.append(packet[i : i + l])
        i += l
    return b".".join(parts).decode(errors="ignore")


def rr(name: str, typ: int, ttl: int, data: bytes) -> bytes:
    return labels(name) + struct.pack("!HHIH", typ, 1, ttl, len(data)) + data


def txt_record(props: dict) -> bytes:
    out = b""
    for k, v in props.items():
        item = k.encode() + b"=" + str(v).encode()
        if len(item) < 255:
            out += bytes([len(item)]) + item
    return out


def answer(query: bytes, pair: dict, casts: list) -> bytes:
    cast = None
    for c in casts:
        ips = c.get("addresses") or []
        if pair["cast_ip"] in ips or c.get("cast_name") == pair.get("cast_name"):
            cast = c
            break

    if not cast:
        cast = {
            "cast_name": pair.get("cast_name", "Chromecast-" + pair["room_number"]),
            "addresses": [pair["cast_ip"]],
            "port": 8009,
            "properties": {},
        }

    instance = cast.get("cast_name") or pair.get("cast_name") or ("Chromecast-" + pair["room_number"])
    srv = f"{instance}._googlecast._tcp.local"
    target = cast.get("server") or f"{instance.replace(' ', '-')}.local"
    props = cast.get("properties") or {"fn": instance, "md": "Chromecast", "id": pair["room_number"]}
    addr = (cast.get("addresses") or [pair["cast_ip"]])[0]

    answers = [
        rr("_googlecast._tcp.local", 12, 120, labels(srv)),
        rr(srv, 33, 120, struct.pack("!HHH", 0, 0, int(cast.get("port", 8009))) + labels(target)),
        rr(srv, 16, 120, txt_record(props)),
        rr(target, 1, 120, socket.inet_aton(addr)),
    ]

    return query[:2] + b"\x84\x00" + query[4:6] + struct.pack("!HHH", len(answers), 0, 0) + query[12:] + b"".join(answers)


def make_socket() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except Exception:
        pass

    # Para multicast mDNS, normalmente devemos bindar 0.0.0.0:5353
    # e entrar no grupo 224.0.0.251 pela interface Guest.
    s.bind(("", PORT))

    iface_ip = GUEST_IFACE_IP if GUEST_IFACE_IP and GUEST_IFACE_IP != "0.0.0.0" else "0.0.0.0"
    mreq = socket.inet_aton(MCAST_GRP) + socket.inet_aton(iface_ip)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
    return s


def main():
    sock = make_socket()
    print(f"mDNS seletivo ouvindo UDP/{PORT} grupo {MCAST_GRP} iface_ip={GUEST_IFACE_IP}", flush=True)
    last = 0
    pairs = {}
    casts = []

    while True:
        data, addr = sock.recvfrom(4096)
        src = addr[0]
        now = time.time()

        if now - last > REFRESH:
            try:
                pairs = acl()
                casts = load_cache()
                last = now
                print(f"ACL ativa: {len(pairs)} pareamento(s)", flush=True)
            except Exception as exc:
                print("refresh erro", exc, flush=True)

        if "_googlecast._tcp.local" not in qname(data):
            continue

        pair = pairs.get(src)
        if not pair:
            print(src, "consultou _googlecast mas não tem pareamento", flush=True)
            continue

        sock.sendto(answer(data, pair, casts), (src, PORT))
        print(src, "-> quarto", pair["room_number"], "cast", pair["cast_ip"], flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""SRVCAST selective mDNS proxy.

Runs on the Ubuntu host, listens to Guest-network mDNS questions on UDP/5353,
and replies only when the source guest IP has an active pairing in the backend.

Features:
- DNS-SD/mDNS answer format accepted by YouTube/Chromecast clients
- Google Cast PTR, subtype PTR, SRV, TXT and A records
- low TTL for hotel testing
- cache-flush on SRV/TXT/A records
- goodbye packets when a guest is disconnected or changes rooms
- manual cleanup mode: --goodbye-all
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import time
from typing import Dict, Iterable, List, Optional, Tuple

import requests

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8080")
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN", "troca-este-token-gateway")
CAST_CACHE_FILE = os.getenv("CAST_CACHE_FILE", "/opt/hotelcast-gateway/data/cast_cache.json")
GUEST_IFACE_IP = os.getenv("GUEST_IFACE_IP", "0.0.0.0")
REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "5"))

MDNS_GROUP = "224.0.0.251"
MDNS_PORT = 5353
CAST_PORT = 8009
TEST_TTL = int(os.getenv("MDNS_TTL", "10"))

GOOGLECAST_SERVICE = "_googlecast._tcp.local"
GOOGLECAST_SUBTYPES = [
    "_233637DE._sub._googlecast._tcp.local",
    "_CC1AD845._sub._googlecast._tcp.local",
]


def log(*args) -> None:
    print(*args, flush=True)


def dns_labels(name: str) -> bytes:
    out = b""
    for part in name.strip(".").split("."):
        raw = part.encode()
        out += bytes([len(raw)]) + raw
    return out + b"\x00"


def read_dns_name(packet: bytes, offset: int) -> Tuple[str, int]:
    parts: List[bytes] = []
    jumped = False
    end = offset
    seen = 0

    while offset < len(packet) and seen < 40:
        seen += 1
        length = packet[offset]

        if length == 0:
            offset += 1
            if not jumped:
                end = offset
            break

        if (length & 0xC0) == 0xC0:
            if offset + 1 >= len(packet):
                break
            pointer = ((length & 0x3F) << 8) | packet[offset + 1]
            if not jumped:
                end = offset + 2
            offset = pointer
            jumped = True
            continue

        offset += 1
        if offset + length > len(packet):
            break
        parts.append(packet[offset : offset + length])
        offset += length
        if not jumped:
            end = offset

    return b".".join(parts).decode(errors="ignore"), end


def parse_questions(packet: bytes) -> List[Tuple[str, int, int]]:
    if len(packet) < 12:
        return []

    qdcount = struct.unpack("!H", packet[4:6])[0]
    offset = 12
    questions: List[Tuple[str, int, int]] = []

    for _ in range(qdcount):
        name, offset = read_dns_name(packet, offset)
        if offset + 4 > len(packet):
            break
        qtype, qclass = struct.unpack("!HH", packet[offset : offset + 4])
        offset += 4
        questions.append((name, qtype, qclass))

    return questions


def rr(name: str, rrtype: int, ttl: int, data: bytes, cache_flush: bool = False) -> bytes:
    dns_class = 0x8001 if cache_flush else 1
    return dns_labels(name) + struct.pack("!HHIH", rrtype, dns_class, ttl, len(data)) + data


def txt_record(properties: Dict[str, object]) -> bytes:
    out = b""
    for key, value in properties.items():
        item = key.encode() + b"=" + str(value).encode()
        if len(item) < 255:
            out += bytes([len(item)]) + item
    return out


def safe_instance_name(name: str) -> str:
    return str(name or "Chromecast").strip().replace(" ", "-")


def load_cast_cache() -> List[dict]:
    try:
        with open(CAST_CACHE_FILE, "r") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except Exception as exc:
        log("cast cache erro", exc)
    return []


def load_acl() -> Dict[str, dict]:
    response = requests.get(
        f"{BACKEND_URL}/api/acl.json",
        headers={"x-gateway-token": GATEWAY_TOKEN},
        timeout=3,
    )
    response.raise_for_status()
    return {pair["guest_ip"]: pair for pair in response.json().get("pairs", [])}


def find_cast(pair: dict, casts: List[dict]) -> dict:
    for cast in casts:
        addresses = cast.get("addresses") or []
        if pair.get("cast_ip") in addresses or cast.get("cast_name") == pair.get("cast_name"):
            return cast

    return {
        "cast_name": pair.get("cast_name") or f"Chromecast-{pair.get('room_number', '')}",
        "addresses": [pair.get("cast_ip")],
        "port": CAST_PORT,
        "properties": {},
    }


def cast_records_identity(pair: dict, cast: dict) -> Tuple[str, str, str, str, Dict[str, object]]:
    props = dict(cast.get("properties") or {})

    visible_name = (
        props.get("fn")
        or cast.get("raw_name")
        or cast.get("cast_name")
        or pair.get("cast_name")
        or f"Quarto {pair.get('room_number', '')}"
    )

    instance = safe_instance_name(str(visible_name))
    service_instance = f"{instance}.{GOOGLECAST_SERVICE}"
    target = cast.get("server") or f"{instance}.local"
    ip = (cast.get("addresses") or [pair.get("cast_ip")])[0]

    if not props:
        room = str(pair.get("room_number", ""))
        props = {
            "id": room,
            "cd": room,
            "rm": "",
            "ve": "05",
            "md": "Chromecast",
            "ic": "/setup/icon.png",
            "fn": visible_name,
            "ca": "4101",
            "st": "0",
            "bs": room[:8],
            "nf": "1",
            "rs": "",
        }

    return str(visible_name), service_instance, target, ip, props


def query_googlecast_names(questions: Iterable[Tuple[str, int, int]]) -> List[str]:
    names: List[str] = []
    for name, qtype, _qclass in questions:
        if qtype != 12:  # PTR
            continue
        if name == GOOGLECAST_SERVICE or name.endswith("._sub._googlecast._tcp.local"):
            if name not in names:
                names.append(name)
    return names


def is_googlecast_query(questions: Iterable[Tuple[str, int, int]]) -> bool:
    for name, _qtype, _qclass in questions:
        if (
            name == GOOGLECAST_SERVICE
            or name.endswith("._sub._googlecast._tcp.local")
            or name.endswith("._googlecast._tcp.local")
            or name.endswith(".local")
        ):
            return True
    return False


def make_answer(query: bytes, pair: dict, casts: List[dict]) -> bytes:
    questions = parse_questions(query)
    cast = find_cast(pair, casts)
    _visible_name, service_instance, target, ip, props = cast_records_identity(pair, cast)

    ptr_names = query_googlecast_names(questions) or [GOOGLECAST_SERVICE]

    answers: List[bytes] = []
    for name in ptr_names:
        answers.append(rr(name, 12, TEST_TTL, dns_labels(service_instance)))

    answers.append(
        rr(
            service_instance,
            33,  # SRV
            TEST_TTL,
            struct.pack("!HHH", 0, 0, int(cast.get("port", CAST_PORT))) + dns_labels(target),
            cache_flush=True,
        )
    )
    answers.append(rr(service_instance, 16, TEST_TTL, txt_record(props), cache_flush=True))
    answers.append(rr(target, 1, TEST_TTL, socket.inet_aton(ip), cache_flush=True))

    # mDNS response with zero question section. This matters for Android/YouTube.
    header = query[:2] + b"\x84\x00" + b"\x00\x00" + struct.pack("!HHH", len(answers), 0, 0)
    return header + b"".join(answers)


def possible_instances_for_cast(pair: dict, cast: dict) -> List[Tuple[str, str, str]]:
    names = set()
    props = cast.get("properties") or {}

    candidates = [
        props.get("fn"),
        cast.get("raw_name"),
        cast.get("cast_name"),
        pair.get("cast_name"),
        f"Chromecast-{pair.get('room_number', '')}",
        f"Quarto {pair.get('room_number', '')}",
    ]

    for candidate in candidates:
        if candidate:
            names.add(safe_instance_name(str(candidate)))

    ip = (cast.get("addresses") or [pair.get("cast_ip")])[0]
    results: List[Tuple[str, str, str]] = []
    for name in names:
        results.append((f"{name}.{GOOGLECAST_SERVICE}", f"{name}.local", ip))
        if cast.get("server"):
            results.append((f"{name}.{GOOGLECAST_SERVICE}", cast["server"], ip))
    return results


def make_goodbye_packet(instances: Iterable[Tuple[str, str, str]]) -> bytes:
    answers: List[bytes] = []

    for service_instance, target, ip in instances:
        answers.append(rr(GOOGLECAST_SERVICE, 12, 0, dns_labels(service_instance)))
        for subtype in GOOGLECAST_SUBTYPES:
            answers.append(rr(subtype, 12, 0, dns_labels(service_instance)))
        answers.append(
            rr(
                service_instance,
                33,
                0,
                struct.pack("!HHH", 0, 0, CAST_PORT) + dns_labels(target),
                cache_flush=True,
            )
        )
        answers.append(rr(service_instance, 16, 0, b"\x00", cache_flush=True))
        try:
            answers.append(rr(target, 1, 0, socket.inet_aton(ip), cache_flush=True))
        except Exception:
            pass

    return b"\x00\x00\x84\x00\x00\x00" + struct.pack("!HHH", len(answers), 0, 0) + b"".join(answers)


def set_multicast_interface(sock: socket.socket) -> None:
    if GUEST_IFACE_IP and GUEST_IFACE_IP != "0.0.0.0":
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(GUEST_IFACE_IP))
        except Exception as exc:
            log("erro IP_MULTICAST_IF", exc)


def send_goodbye(sock: socket.socket, pair: dict, casts: List[dict], guest_ip: Optional[str], reason: str) -> None:
    cast = find_cast(pair, casts)
    packet = make_goodbye_packet(possible_instances_for_cast(pair, cast))
    set_multicast_interface(sock)

    for _ in range(3):
        try:
            sock.sendto(packet, (MDNS_GROUP, MDNS_PORT))
        except Exception as exc:
            log("erro goodbye multicast", exc)

        if guest_ip:
            try:
                sock.sendto(packet, (guest_ip, MDNS_PORT))
            except Exception as exc:
                log("erro goodbye unicast", exc)

        time.sleep(0.25)

    log("goodbye enviado", reason, "guest", guest_ip, "room", pair.get("room_number"), "cast", pair.get("cast_ip"))


def make_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except Exception:
        pass

    sock.bind(("", MDNS_PORT))

    iface_ip = GUEST_IFACE_IP if GUEST_IFACE_IP and GUEST_IFACE_IP != "0.0.0.0" else "0.0.0.0"
    membership = socket.inet_aton(MDNS_GROUP) + socket.inet_aton(iface_ip)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
    set_multicast_interface(sock)
    return sock


def goodbye_all() -> None:
    sock = make_socket()
    casts = load_cast_cache()

    fake_pairs = []
    for cast in casts:
        ip = (cast.get("addresses") or ["0.0.0.0"])[0]
        digits = "".join(ch for ch in str(cast.get("cast_name", "")) if ch.isdigit()) or "0"
        fake_pairs.append({"room_number": digits, "cast_name": cast.get("cast_name"), "cast_ip": ip})

    for pair in fake_pairs:
        send_goodbye(sock, pair, casts, None, "manual/all")


def main() -> None:
    if "--goodbye-all" in sys.argv:
        goodbye_all()
        return

    sock = make_socket()
    log(f"mDNS seletivo ouvindo UDP/{MDNS_PORT} grupo {MDNS_GROUP} iface_ip={GUEST_IFACE_IP}")

    pairs: Dict[str, dict] = {}
    previous_pairs: Dict[str, dict] = {}
    casts = load_cast_cache()
    last_refresh = 0.0

    while True:
        data, addr = sock.recvfrom(4096)
        src_ip = addr[0]

        if src_ip == GUEST_IFACE_IP:
            continue

        now = time.time()
        if now - last_refresh > REFRESH_SECONDS:
            try:
                new_pairs = load_acl()
                casts = load_cast_cache()

                for guest_ip, old_pair in list(previous_pairs.items()):
                    new_pair = new_pairs.get(guest_ip)
                    if not new_pair:
                        send_goodbye(sock, old_pair, casts, guest_ip, "removed")
                    elif (
                        new_pair.get("cast_ip") != old_pair.get("cast_ip")
                        or new_pair.get("room_number") != old_pair.get("room_number")
                    ):
                        send_goodbye(sock, old_pair, casts, guest_ip, "changed")

                pairs = new_pairs
                previous_pairs = dict(new_pairs)
                last_refresh = now
                log(f"ACL ativa: {len(pairs)} pareamento(s)")
            except Exception as exc:
                log("refresh erro", exc)

        questions = parse_questions(data)
        if not is_googlecast_query(questions):
            continue

        pair = pairs.get(src_ip)
        if not pair:
            log(src_ip, "consultou _googlecast mas não tem pareamento")
            continue

        response = make_answer(data, pair, casts)
        names = [question[0] for question in questions]

        try:
            sock.sendto(response, (src_ip, MDNS_PORT))
        except Exception as exc:
            log("erro resposta unicast", exc)

        try:
            sock.sendto(response, (MDNS_GROUP, MDNS_PORT))
        except Exception as exc:
            log("erro resposta multicast", exc)

        log(src_ip, "-> quarto", pair.get("room_number"), "cast", pair.get("cast_ip"), "perguntas:", ",".join(names))


if __name__ == "__main__":
    main()

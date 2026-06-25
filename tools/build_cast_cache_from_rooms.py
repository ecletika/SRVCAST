#!/usr/bin/env python3
"""Build SRVCAST cast_cache.json from registered rooms.

This script runs on the Ubuntu host. It reads /opt/hotelcast-gateway/.env,
asks the backend for registered rooms, then queries each Chromecast's
/setup/eureka_info endpoint to get real device name and id.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional

import requests
import urllib3

urllib3.disable_warnings()

ENV_FILE = Path(os.getenv("SRVCAST_ENV_FILE", "/opt/hotelcast-gateway/.env"))
OUT_FILE = Path(os.getenv("CAST_CACHE_FILE", "/opt/hotelcast-gateway/data/cast_cache.json"))


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_json(url: str, timeout: int = 5) -> Optional[dict]:
    try:
        response = requests.get(url, timeout=timeout, verify=False)
        if response.ok:
            return response.json()
    except Exception:
        pass
    return None


def get_eureka_info(ip: str) -> Dict:
    return (
        get_json(f"http://{ip}:8008/setup/eureka_info?options=detail")
        or get_json(f"http://{ip}:8008/setup/eureka_info")
        or get_json(f"https://{ip}:8443/setup/eureka_info?options=detail")
        or {}
    )


def safe_server_name(name: str) -> str:
    return str(name or "Chromecast").strip().replace(" ", "-") + ".local"


def main() -> int:
    load_env_file(ENV_FILE)

    backend_url = os.getenv("BACKEND_URL", "http://127.0.0.1:8080")
    admin_token = os.getenv("ADMIN_TOKEN")

    if not admin_token:
        print(f"ERRO: ADMIN_TOKEN não encontrado em {ENV_FILE}", file=sys.stderr)
        return 1

    rooms_response = requests.get(
        f"{backend_url}/admin/rooms",
        headers={"x-admin-token": admin_token},
        timeout=5,
    )

    try:
        rooms = rooms_response.json()
    except Exception:
        print("ERRO: /admin/rooms não retornou JSON", file=sys.stderr)
        print(rooms_response.text[:500], file=sys.stderr)
        return 1

    if not rooms_response.ok or not isinstance(rooms, list):
        print("ERRO: não consegui buscar quartos", file=sys.stderr)
        print(json.dumps(rooms, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1

    items = []

    for room in rooms:
        cast_ip = room.get("cast_ip")
        if not cast_ip:
            continue

        info = get_eureka_info(cast_ip)

        name = info.get("name") or room.get("cast_name") or f"Chromecast-{room.get('room_number')}"
        device_id = (info.get("ssdp_udn") or "").replace("uuid:", "") or str(room.get("room_number"))
        model = info.get("model_name") or "Chromecast"

        item = {
            "cast_name": room.get("cast_name") or name,
            "addresses": [cast_ip],
            "port": 8009,
            "server": safe_server_name(name),
            "raw_name": name,
            "raw_ip": info.get("ip_address"),
            "raw_mac": info.get("mac_address"),
            "properties": {
                "id": device_id,
                "cd": device_id,
                "rm": "",
                "ve": "05",
                "md": model,
                "ic": "/setup/icon.png",
                "fn": name,
                "ca": "4101",
                "st": "0",
                "bs": device_id[:8],
                "nf": "1",
                "rs": "",
            },
        }
        items.append(item)
        print(f"OK: {room.get('room_number')} {cast_ip} -> {name} / {device_id}")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n")

    print(f"\nGravado: {OUT_FILE}")
    print(json.dumps(items, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

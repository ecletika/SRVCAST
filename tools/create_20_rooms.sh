#!/usr/bin/env bash
set -euo pipefail
if [[ -f .env ]]; then set -a; source .env; set +a; elif [[ -f /etc/hotelcast-gateway.env ]]; then set -a; source /etc/hotelcast-gateway.env; set +a; fi
BASE=${BASE:-${BACKEND_URL:-http://127.0.0.1:8080}}
ADMIN_TOKEN=${ADMIN_TOKEN:-troca-este-token-admin}
CAST_PREFIX=${CAST_PREFIX:-10.60.0.}
START_ROOM=${START_ROOM:-101}
END_ROOM=${END_ROOM:-120}
START_IP_LAST_OCTET=${START_IP_LAST_OCTET:-101}
for room in $(seq "$START_ROOM" "$END_ROOM"); do
  octet=$((START_IP_LAST_OCTET + room - START_ROOM))
  ip="${CAST_PREFIX}${octet}"
  echo "Criando/atualizando quarto $room -> $ip"
  curl -fsS -X POST "$BASE/admin/rooms" -H "x-admin-token: $ADMIN_TOKEN" -H 'content-type: application/json' -d "{\"room_number\":\"$room\",\"cast_name\":\"Chromecast-$room\",\"cast_ip\":\"$ip\"}" >/dev/null
  echo ok
done

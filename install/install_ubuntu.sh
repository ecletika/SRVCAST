#!/usr/bin/env bash
set -euo pipefail
APP_DIR=${APP_DIR:-/opt/hotelcast-gateway}
ENV_FILE=${ENV_FILE:-/etc/hotelcast-gateway.env}
SRC_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if [[ $EUID -ne 0 ]]; then echo "Rode com sudo" >&2; exit 1; fi

apt-get update

# Ubuntu 24.04: use the Ubuntu docker.io + docker-compose-v2 packages together.
# Do not mix docker.io with Docker CE's docker-compose-plugin/containerd.io packages,
# because that can trigger: containerd.io Conflicts: containerd.
apt-get install -y python3-venv python3-pip nftables iproute2 curl jq openssl rsync
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  apt-get install -y docker.io docker-compose-v2
fi

systemctl enable --now docker nftables
mkdir -p "$APP_DIR" "$APP_DIR/data"
rsync -a --delete --exclude .venv --exclude data "$SRC_DIR/" "$APP_DIR/"
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$APP_DIR/.env.example" "$ENV_FILE"
  sed -i "s/^ADMIN_TOKEN=.*/ADMIN_TOKEN=$(openssl rand -hex 24)/" "$ENV_FILE"
  sed -i "s/^GATEWAY_TOKEN=.*/GATEWAY_TOKEN=$(openssl rand -hex 24)/" "$ENV_FILE"
fi
cp "$ENV_FILE" "$APP_DIR/.env"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"
printf 'net.ipv4.ip_forward=1\n' >/etc/sysctl.d/99-hotelcast-gateway.conf
sysctl --system >/dev/null
if systemctl list-unit-files | grep -q '^avahi-daemon.service'; then systemctl disable --now avahi-daemon || true; fi
cp "$APP_DIR/gateway/firewall-sync.service" /etc/systemd/system/hotelcast-firewall-sync.service
cp "$APP_DIR/gateway/nat-sync.service" /etc/systemd/system/hotelcast-nat-sync.service
cat >/etc/systemd/system/hotelcast-mdns-selective-proxy.service <<'EOF'
[Unit]
Description=HotelCast selective mDNS proxy
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
WorkingDirectory=/opt/hotelcast-gateway
EnvironmentFile=/etc/hotelcast-gateway.env
ExecStart=/opt/hotelcast-gateway/.venv/bin/python /opt/hotelcast-gateway/gateway/mdns_selective_proxy.py
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
cd "$APP_DIR" && docker compose up -d --build
systemctl enable --now hotelcast-nat-sync hotelcast-firewall-sync hotelcast-mdns-selective-proxy
cat <<EOF
Instalado em $APP_DIR
Edite: sudo nano $ENV_FILE
Criar quartos: cd $APP_DIR && sudo bash tools/create_20_rooms.sh
EOF

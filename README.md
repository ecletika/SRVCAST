# SRVCAST / HotelCast Gateway MVP

Sistema para hotel com pareamento por QR code e isolamento por quarto.

O objetivo é que o hóspede veja e controle somente o Chromecast do quarto dele, mesmo conectado ao Wi-Fi geral do hotel.

## Componentes

- Backend FastAPI com SQLite.
- QR code por quarto em `/tv/101`, `/tv/102`, etc.
- Sessão `IP do hóspede -> quarto -> Chromecast`.
- Firewall dinâmica via nftables.
- Proxy mDNS seletivo para `_googlecast._tcp.local`.
- Script para criar quartos 101 a 120.
- Instalador Ubuntu.

## Instalação rápida no Ubuntu

```bash
git clone https://github.com/ecletika/SRVCAST.git
cd SRVCAST
sudo bash install/install_ubuntu.sh
```

Depois veja as interfaces reais:

```bash
ip -br addr
ip route
sudo nano /etc/hotelcast-gateway.env
```

Ajuste principalmente:

```env
GUEST_NET=10.50.0.0/16
CAST_NET=10.60.0.0/24
GUEST_IFACE=enp2s0
CAST_IFACE=enp3s0
GUEST_IFACE_IP=10.50.0.1
CAST_IFACE_IP=10.60.0.1
WAN_IFACE=enp1s0
```

Reinicie:

```bash
sudo cp /etc/hotelcast-gateway.env /opt/hotelcast-gateway/.env
cd /opt/hotelcast-gateway
sudo docker compose up -d --build
sudo systemctl restart hotelcast-nat-sync hotelcast-firewall-sync hotelcast-mdns-selective-proxy
```

## Criar os 20 quartos

```bash
cd /opt/hotelcast-gateway
sudo bash tools/create_20_rooms.sh
```

Por padrão:

```text
101 -> 10.60.0.101
102 -> 10.60.0.102
...
120 -> 10.60.0.120
```

## Tela da TV

No browser/kiosk da TV do quarto 101:

```text
http://10.50.0.1:8080/tv/101
```

## Descobrir Chromecasts reais

```bash
cd /opt/hotelcast-gateway
sudo .venv/bin/python tools/mdns_discover_googlecast.py --seconds 30 --json-output ./data/cast_cache.json
sudo systemctl restart hotelcast-mdns-selective-proxy
```

## Monitoramento

```bash
sudo systemctl status hotelcast-firewall-sync --no-pager
sudo systemctl status hotelcast-mdns-selective-proxy --no-pager
sudo journalctl -u hotelcast-mdns-selective-proxy -f
```

## Checkout

```bash
source /etc/hotelcast-gateway.env
curl -X POST http://127.0.0.1:8080/admin/checkout/101 -H "x-admin-token: $ADMIN_TOKEN"
```

## Atenção

O Ubuntu precisa ver o IP real de cada hóspede. Não coloque NAT entre o Wi-Fi de hóspedes e este gateway.

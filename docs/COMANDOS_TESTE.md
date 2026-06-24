# Comandos de teste

## Backend

```bash
curl http://127.0.0.1:8080/health
```

## Listar quartos

```bash
source /etc/hotelcast-gateway.env
curl -H "x-admin-token: $ADMIN_TOKEN" http://127.0.0.1:8080/admin/rooms | jq
```

## Criar sessão manual pelo QR

Abra na TV/navegador:

```text
http://10.50.0.1:8080/tv/101
```

Depois escaneie o QR pelo telemóvel conectado à rede Guest.

## Ver ACL ativa

```bash
source /etc/hotelcast-gateway.env
curl -H "x-gateway-token: $GATEWAY_TOKEN" http://127.0.0.1:8080/api/acl.json | jq
```

## Ver regras nftables

```bash
sudo nft list table inet hotelcast
sudo nft list table ip hotelcast_nat
```

## Simular firewall sem aplicar

```bash
cd /opt/hotelcast-gateway
sudo APPLY=0 .venv/bin/python gateway/firewall_sync.py --once
```

## Logs mDNS seletivo

```bash
sudo journalctl -u hotelcast-mdns-selective-proxy -f
```

Ao abrir o botão Cast no telemóvel já pareado, o log deve mostrar algo como:

```text
10.50.12.34 -> respondeu Chromecast-101/10.60.0.101 quarto 101
```

## Descobrir Casts

```bash
cd /opt/hotelcast-gateway
sudo .venv/bin/python tools/mdns_discover_googlecast.py --seconds 30 --json-output ./data/cast_cache.json
cat ./data/cast_cache.json | jq
sudo systemctl restart hotelcast-mdns-selective-proxy
```

## Checkout

```bash
source /etc/hotelcast-gateway.env
curl -X POST -H "x-admin-token: $ADMIN_TOKEN" http://127.0.0.1:8080/admin/checkout/101
```

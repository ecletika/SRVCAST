# Instalação no Ubuntu Server

Este projeto assume um Ubuntu Server a fazer gateway/roteamento entre a rede dos hóspedes e a rede dos Chromecasts.

## 1) Descobrir nomes das interfaces

```bash
ip -br addr
ip route
```

Exemplo de desenho:

```text
WAN / Internet: enp1s0
Guest Wi-Fi:    enp2s0 -> 10.50.0.1/16
Cast TVs:       enp3s0 -> 10.60.0.1/24
```

## 2) Instalar

```bash
cd hotelcast-gateway
sudo bash install/install_ubuntu.sh
```

## 3) Editar configuração real

```bash
sudo nano /etc/hotelcast-gateway.env
```

Campos importantes:

```env
PUBLIC_BASE_URL=http://10.50.0.1:8080
GUEST_NET=10.50.0.0/16
CAST_NET=10.60.0.0/24
GUEST_IFACE=enp2s0
CAST_IFACE=enp3s0
GUEST_IFACE_IP=10.50.0.1
CAST_IFACE_IP=10.60.0.1
WAN_IFACE=enp1s0
```

Depois:

```bash
sudo cp /etc/hotelcast-gateway.env /opt/hotelcast-gateway/.env
cd /opt/hotelcast-gateway
sudo docker compose up -d --build
sudo systemctl restart hotelcast-nat-sync hotelcast-firewall-sync hotelcast-mdns-selective-proxy
```

## 4) Criar quartos

Por padrão cria 101 a 120 com Casts 10.60.0.101 a 10.60.0.120:

```bash
cd /opt/hotelcast-gateway
sudo bash tools/create_20_rooms.sh
```

## 5) Descobrir Chromecasts reais

Execute com os Chromecasts ligados na rede Cast:

```bash
cd /opt/hotelcast-gateway
sudo .venv/bin/python tools/mdns_discover_googlecast.py --seconds 30 --json-output ./data/cast_cache.json
sudo systemctl restart hotelcast-mdns-selective-proxy
```

Se o cache não existir, o proxy mDNS sintetiza anúncios básicos usando os IPs cadastrados. O cache real é melhor porque preserva TXT records verdadeiros de cada Chromecast.

## 6) Teste de pareamento

1. Abra na TV ou navegador do quarto 101:

```text
http://10.50.0.1:8080/tv/101
```

2. Escaneie o QR com o telemóvel conectado ao Wi-Fi de hóspedes.
3. Veja a sessão:

```bash
curl http://10.50.0.1:8080/api/me
```

4. Veja ACL ativa:

```bash
source /etc/hotelcast-gateway.env
curl -H "x-gateway-token: $GATEWAY_TOKEN" http://127.0.0.1:8080/api/acl.json | jq
```

## 7) Comandos de diagnóstico

```bash
sudo systemctl status hotelcast-firewall-sync --no-pager
sudo systemctl status hotelcast-mdns-selective-proxy --no-pager
sudo journalctl -u hotelcast-mdns-selective-proxy -f
sudo nft list ruleset
```

## 8) Checkout

```bash
source /etc/hotelcast-gateway.env
curl -X POST -H "x-admin-token: $ADMIN_TOKEN" http://127.0.0.1:8080/admin/checkout/101
sudo systemctl restart hotelcast-firewall-sync
```

## Observações importantes

- Não use Avahi reflector no Guest/Cast, porque ele pode anunciar todos os Casts para todos os hóspedes.
- O `hotelcast-mdns-selective-proxy` responde por hóspede, com base no IP que escaneou o QR.
- O Wi-Fi dos hóspedes não deve fazer NAT antes de chegar ao gateway; o gateway precisa ver o IP real de cada telemóvel.
- Configure DHCP reservation para os Chromecasts ou IP fixo, senão a associação quarto -> Cast quebra.

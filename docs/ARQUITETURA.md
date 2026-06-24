# HotelCast Gateway — arquitetura

Objetivo: um hóspede só deve ver/controlar o Chromecast do seu próprio quarto, mesmo que esteja conectado ao AP/SSID errado.

## Componentes

1. **Backend HotelCast**
   - Guarda quartos e IPs dos Chromecasts.
   - Gera QR code por quarto.
   - Cria sessão `guest_ip -> cast_ip` quando o hóspede escaneia o QR.
   - Expira sessões no checkout ou por TTL.

2. **Gateway Linux**
   - Roteia entre rede Guest e rede Cast.
   - Executa `gateway/firewall_sync.py`.
   - Aplica regras nftables para permitir só pares autorizados.

3. **Proxy mDNS seletivo**
   - Executa `gateway/mdns_selective_proxy.py`.
   - Escuta consultas `_googlecast._tcp.local` vindas da rede Guest.
   - Consulta `/api/acl.json`.
   - Responde para cada IP de hóspede apenas com o Chromecast pareado.
   - Não é reflector: não repete todos os anúncios entre redes.

4. **NAT opcional**
   - `gateway/nat_sync.py` ativa masquerade se `WAN_IFACE` estiver definido.

## Topologia recomendada

```text
Internet
  |
Router principal / WAN
  |
Ubuntu HotelCast Gateway
  |-- Guest: 10.50.0.0/16
  |-- Cast:  10.60.0.0/24
```

Chromecasts com DHCP reservation/fixo:

```text
101 -> 10.60.0.101
102 -> 10.60.0.102
...
120 -> 10.60.0.120
```

## Fluxo

1. TV do quarto abre `http://gateway:8080/tv/101`.
2. Backend mostra QR code temporário.
3. Hóspede escaneia.
4. Backend cria sessão com o IP do telemóvel.
5. `firewall_sync.py` libera `guest_ip -> cast_ip`.
6. `mdns_selective_proxy.py` responde discovery só com o Cast certo.
7. No checkout, `POST /admin/checkout/101` remove sessões ativas.

## Fluxo mDNS

```text
Telemóvel 10.50.12.34 pergunta: _googlecast._tcp.local
       |
       v
mdns_selective_proxy consulta ACL
       |
       v
ACL: 10.50.12.34 -> quarto 101 -> 10.60.0.101
       |
       v
Resposta unicast: só Chromecast-101
```

## Segurança

- QR expira por tempo.
- Um IP de hóspede só fica ativo em um quarto por vez.
- Checkout desativa sessões do quarto.
- mDNS/SSDP direto para a rede Cast é bloqueado na firewall.
- Hóspedes não autorizados não recebem resposta mDNS e não conseguem tráfego para `CAST_NET`.

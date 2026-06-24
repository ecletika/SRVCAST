# Exemplo Netplan — ajuste antes de aplicar

Veja os nomes reais:

```bash
ip -br link
```

Exemplo `/etc/netplan/01-hotelcast.yaml`:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp1s0:
      dhcp4: true
    enp2s0:
      addresses:
        - 10.50.0.1/16
    enp3s0:
      addresses:
        - 10.60.0.1/24
```

Aplicar:

```bash
sudo netplan try
sudo netplan apply
```

Depois, aponte o DHCP dos APs/rede Guest para gateway `10.50.0.1` e DNS conforme a tua rede. Os Chromecasts devem ficar na rede `10.60.0.0/24`, de preferência com reservas fixas de DHCP.

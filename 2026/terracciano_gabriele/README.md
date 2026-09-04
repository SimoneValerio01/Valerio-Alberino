# Firewall SDN con Ryu e Mininet

Questo progetto realizza un semplice firewall SDN usando:

- Ryu come controller
- Mininet per creare la rete
- Open vSwitch come switch virtuale
- OpenFlow 1.3 per la comunicazione tra controller e switch

## Topologia

La rete è composta da tre host collegati allo stesso switch:

```text
          Ryu
           |
          s1
       /   |   \
      h1   h2   h3
```

Gli indirizzi IP sono:

- h1: 10.0.0.1
- h2: 10.0.0.2
- h3: 10.0.0.3

## Regole del firewall

Il controller applica due regole principali.

La prima blocca completamente la comunicazione tra h1 e h3:

```text
h1 <-> h3 BLOCCATO
```

La seconda blocca solamente il traffico TCP da h2 verso h3 sulla porta 5201:

```text
h2 -> h3 TCP porta 5201 BLOCCATO
```

Quindi h2 può normalmente fare ping verso h3, ma non può usare il servizio `iperf3` sulla porta 5201.

## Struttura del progetto

```text
ncis-firewall-sdn/
├── controller/
│   └── firewall.py
├── topology/
│   └── network.py
├── tests/
│   └── test_firewall.py
├── docs/
└── README.md
```

`firewall.py` contiene il controller Ryu e le regole del firewall.

`network.py` crea la rete con Mininet.

`test_firewall.py` verifica automaticamente che le regole funzionino.

## Avvio del progetto

Servono due terminali.

Nel primo terminale si avvia Ryu:

```bash
cd ~/ncis-firewall-sdn
source ~/ryu-env/bin/activate
ryu-manager controller/firewall.py
```

Nel secondo terminale si pulisce Mininet e si avvia la rete:

```bash
cd ~/ncis-firewall-sdn
sudo mn -c
sudo python3 topology/network.py
```

Una volta aperta la console Mininet è possibile fare un primo controllo con:

```bash
pingall
```

h1 e h3 non devono comunicare, mentre gli altri host devono comunicare normalmente.

## Test automatici

Con Ryu già avviato, è possibile eseguire:

```bash
sudo mn -c
sudo python3 tests/test_firewall.py
```

Il risultato corretto è:

```text
[PASS] h1 -> h2 allowed
[PASS] h2 -> h3 allowed
[PASS] h1 -> h3 blocked
[PASS] TCP h2 -> h3:5201 blocked

4/4 TESTS PASSED
```

## Controllo delle regole OpenFlow

Dentro Mininet è possibile vedere le regole installate nello switch con:

```bash
sh ovs-ofctl -O OpenFlow13 dump-flows s1
```

Tra le regole devono comparire quelle che bloccano:

```text
10.0.0.1 -> 10.0.0.3
10.0.0.3 -> 10.0.0.1
10.0.0.2 -> 10.0.0.3 TCP porta 5201
```

## Obiettivo

L'obiettivo del progetto è mostrare come un controller SDN possa programmare uno switch tramite OpenFlow e decidere quale traffico consentire e quale bloccare.
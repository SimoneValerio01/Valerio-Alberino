# Emulazione di una rete per datacenter
Utilizza ComNetsEmu (una fork di mininet) e Ryu (per il controller SDN) per emulare il comportamento
di una rete SDN con più computer, implementando meccanismi di isolamento (per separare i tenant) e
scaling automatico basato sul traffico in entrata.

## Macchina virtuale ComNetsEmu
Hosta il **load balancer** e lo **scaler**, inclusi all'interno dello stesso file con la configurazione
mininet cosi da utilizzare i meccanismi di ComNetsEmu tramite VNFManager per aggiungere o rimuovere
i container.

Per avviare il main:
```bash

sudo python3 Main.py --controller-ip CONTR-IP --controller-port CONTR-PORT
```

## Macchina virtuale Ryu
Utilizzata per avviare il controller SDN, necessario per l'utilizzo delle tecnologie SDN all'interno
della rete.

Per avviare il controller:
```bash

ryu-manager Controller.py --ofg-tcp-listen-port 6653
```

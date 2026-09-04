import time

from comnetsemu.net import VNFManager

import LoadBalancer


# Un pool per servizio. In 'computers' metto gli host su cui creare i
# container, cioè quelli del tenant 10 per la calcolatrice e computer3
# per il chatbot. Il gateway del load balancer può raggiungere entrambi i tenant
SERVIZI = {
    "calc": {"immagine": "calculator:latest",
             "script": "/app/calc.py",
             "percorso": "/compute",
             "computers": ["computer1", "computer2"]},
    "chat": {"immagine": "chatbot:latest",
             "script": "/app/chatbot.py",
             "percorso": "/chat",
             "computers": ["computer3"]},
}

BASE_PORT = 5000              # porta del primo backend, poi 5001, 5002, ...

SCALE_UP_THRESHOLD = 0.80     # utilizzo del pool oltre il quale si aggiunge un backend
SCALE_DOWN_THRESHOLD = 0.30   # utilizzo sotto il quale se ne toglie uno
SCALE_DOWN_COOLDOWN = 10      # secondi consecutivi sotto soglia prima di togliere
MONITOR_INTERVAL = 0.1        # ogni quanto il monitor guarda l'utilizzo
AVVIO_BACKEND = 1             # secondi di attesa perché il backend inizi ad ascoltare


MIN_CONTAINERS = 1
MAX_PER_COMPUTER = 3


# -- stato -----------------------------------------------------------------

net = None
mgr = None

container = {}

# Progressivo per nome e porta. È condiviso fra i pool perché due container
# sullo stesso DockerHost si dividono lo stesso spazio di porte, anche se
# sono di servizi diversi. Non decide più su quale computer va il container,
# quello lo sceglie dove()
contatore = 0

"""
ESEMPIO:

contatore parte da 0 e non torna mai indietro

scale_up("calc") -> calc0 su computer1, porta 5000, /compute
scale_up("chat") -> chat1 su computer3, porta 5001, /chat
scale_up("calc") -> calc2 su computer2, porta 5002, /compute

container = {"calc0": {"servizio": "calc", "computer": "computer1"},
             "chat1": {"servizio": "chat", "computer": "computer3"},
             "calc2": {"servizio": "calc", "computer": "computer2"}}

Il computer è quello meno carico fra quelli del servizio, quindi calc0 e
calc2 finiscono su computer diversi e il pool cresce in larghezza prima di
riempire un singolo host
"""


# -- ciclo di vita dei container -------------------------------------------


def avvia(topologia):
    """Prende la rete già costruita e ci attacca il VNFManager"""
    global net, mgr
    net = topologia
    mgr = VNFManager(net)


def ferma():
    """Spegne i container e il VNFManager. La rete la ferma il chiamante"""
    for nome in list(container):
        scale_down(nome)
    if mgr is not None:
        mgr.stop()


def quanti(servizio):
    """Ritorna quanti container sono accesi nel pool di quel servizio"""
    totale = 0
    for c in container.values():
        if c["servizio"] == servizio:
            totale += 1
    return totale


def tetto(servizio):
    """Container massimi del pool, cioè MAX_PER_COMPUTER per ogni suo computer"""
    return MAX_PER_COMPUTER * len(SERVIZI[servizio]["computers"])


def dove(servizio):
    """Computer meno carico fra quelli del servizio, None se sono tutti pieni.

    Conto i container invece di ruotare con il contatore globale perché il
    contatore lo incrementa anche l'altro servizio, quindi la rotazione
    saltava dei turni e poteva mandare un container su un computer già pieno
    mentre l'altro era libero
    """
    scelto = None
    minimo = 0
    for computer in SERVIZI[servizio]["computers"]:
        occupati = 0
        for c in container.values():
            if c["computer"] == computer:
                occupati += 1
        if occupati >= MAX_PER_COMPUTER:
            continue
        if scelto is None or occupati < minimo:
            scelto = computer
            minimo = occupati
    return scelto


def scale_up(servizio):
    """
    Crea un container del servizio dato e ritorna {"nome", "url", "servizio"}.
    Se il pool è già al tetto ritorna None e non crea niente.
    """
    global contatore
    computer = dove(servizio)
    if computer is None:
        return None

    conf = SERVIZI[servizio]
    n = contatore
    contatore += 1

    nome = f"{servizio}{n}"
    porta = BASE_PORT + n

    # I container che stanno sullo stesso DockerHost condividono il network
    # namespace, quindi hanno lo stesso IP e devo dare a ognuno la sua porta
    mgr.addContainer(nome, computer, conf["immagine"],
                     f"python3 {conf['script']} {porta}")

    # addContainer ritorna appena il container esiste, ma Flask dentro ci
    # mette un attimo ad ascoltare. Senza questa attesa le prime richieste
    # al backend nuovo si prendono un 502
    time.sleep(AVVIO_BACKEND)

    url = f"http://{net.get(computer).IP()}:{porta}{conf['percorso']}"
    container[nome] = {"servizio": servizio, "computer": computer}
    print(f"scale up: {nome} su {computer}")
    return {"nome": nome, "url": url, "servizio": servizio}


def scale_down(nome):
    """Distrugge il container indicato. True se esisteva"""
    if nome not in container:
        return False

    mgr.removeContainer(nome)
    del container[nome]
    print(f"scale down: {nome}")
    return True


# -- politica di scaling ---------------------------------------------------


def avvia_pool():
    """Crea un backend per servizio, prima di aprire il load balancer al traffico"""
    for servizio in SERVIZI:
        LoadBalancer.aggiungi_backend(scale_up(servizio))


def monitor_loop():
    """
    Politica di scaling, applicata a ogni pool individualmente.
    In base al carico, decido se allocare o deallocare le risorse per 
    ogni servizio.
    """
    sotto_soglia_da = {}
    for servizio in SERVIZI:
        sotto_soglia_da[servizio] = None

    while True:
        time.sleep(MONITOR_INTERVAL)

        letture = {}
        for servizio in SERVIZI:
            letture[servizio] = LoadBalancer.utilizzo(servizio)

        for servizio in SERVIZI:
            u = letture[servizio]
            attivi = quanti(servizio)

            if u >= SCALE_UP_THRESHOLD:
                sotto_soglia_da[servizio] = None
                if attivi < tetto(servizio):
                    LoadBalancer.aggiungi_backend(scale_up(servizio))

            elif u < SCALE_DOWN_THRESHOLD and attivi > MIN_CONTAINERS:
                if sotto_soglia_da[servizio] is None:
                    sotto_soglia_da[servizio] = time.time()
                elif time.time() - sotto_soglia_da[servizio] >= SCALE_DOWN_COOLDOWN:
                    # Prima lo tolgo dal servizio e poi lo spengo, cosi non
                    # gli arriva addosso nessuna richiesta mentre muore
                    nome = LoadBalancer.togli_backend(servizio)
                    if nome is not None:
                        scale_down(nome)
                        sotto_soglia_da[servizio] = None
            else:
                sotto_soglia_da[servizio] = None

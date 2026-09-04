import threading
import time

import requests
from flask import Flask, request, jsonify


PORTA = 8081                  # porta su cui il load balancer riceve le richieste
MAX_PER_ENDPOINT = 3          # richieste contemporanee per endpoint
MAX_WAIT = 30                 # secondi max di attesa di uno slot libero
TIMEOUT = 10                  # secondi di attesa della risposta del backend

app = Flask(__name__)


# -- stato condiviso -------------------------------------------------------

lock = threading.Lock()
# slot_libero usa lo stesso mutex di lock
slot_libero = threading.Condition(lock)

# nome -> {"url", "servizio", "richieste"}, lo riempie lo scaling. I backend
# dei vari servizi stanno qui dentro tutti insieme, ma formano pool separati,
# cioè si sceglie e si conta sempre a parità di servizio. Un utilizzo
# aggregato su servizi diversi non vorrebbe dire niente.
endpoints = {}

"""
ESEMPIO:

ogni computer ha 3 container MASSIMI

c1 ha 2 container c2 ne ha 1 e c3 3

computer 1 -> 10.0.0.1
endpoints:
    url:
        http://10.0.0.1:5000/compute
        http://10.0.0.1:5001/compute
    servizio: calc
    richiste: n

computer 2 -> 10.0.0.2
endpoints:
    url:
        http://10.0.0.2:5000/compute
    servizio: calc
    richieste: n

computer 3 -> 10.0.0.3
endpoints:
    url:
        http://10.0.0.3:5000/chat
        http://10.0.0.3:5001/chat
        http://10.0.0.3:5002/chat
    servizio: chat
    richieste: n
"""




# -- scelta dell'endpoint --------------------------------------------------


def utilizzo(servizio):
    """Frazione di slot occupati nel pool di quel servizio.
    Se il pool è vuoto ritorna 1.0. Capacità zero conta come pieno, cosi
    lo scaling aggiunge un backend invece di dividere per zero.
    """
    with lock:
        capacita = 0
        totale = 0
        for endpoint in endpoints.values():
            if endpoint["servizio"] == servizio:
                capacita += MAX_PER_ENDPOINT
                totale += endpoint["richieste"]
        return totale / capacita if capacita else 1.0


def endpoint_libero(servizio):
    """Ritorna l'endpoint meno carico"""
    scelto = None
    for nome, endpoint in endpoints.items():
        if endpoint["servizio"] != servizio or endpoint["richieste"] >= MAX_PER_ENDPOINT:
            continue
        # Se il nuovo endpoint ha un carico minore, lo preferisco a quello vecchio
        if scelto is None or endpoint["richieste"] < endpoints[scelto]["richieste"]:
            scelto = nome
    return scelto


def prendi_endpoint(servizio):
    """
    Occupa uno slot sull'endpoint meno carico, aspettando se sono tutti pieni.
    Se la richiesta non viene servita entro un tempo massimo, viene inviato un errore 503
    """
    scadenza = time.time() + MAX_WAIT
    with slot_libero:
        while True:
            nome = endpoint_libero(servizio)
            if nome is not None:
                endpoints[nome]["richieste"] += 1
                return nome

            rimasto = scadenza - time.time()
            if rimasto <= 0:
                return None
            slot_libero.wait(rimasto)


def rilascia_endpoint(nome):
    """Libera lo slot occupato dalla richiesta appena finita."""
    with slot_libero:
        # nel frattempo togli_backend può averlo tolto dal servizio
        if nome in endpoints:
            endpoints[nome]["richieste"] -= 1
        slot_libero.notify()

# -- backend in servizio ---------------------------------------------------


def aggiungi_backend(backend):
    """Mette in servizio un backend appena creato dallo scaling."""
    if backend is None:
        return
    with slot_libero:
        endpoints[backend["nome"]] = {"url": backend["url"],
                                      "servizio": backend["servizio"],
                                      "richieste": 0}
        # qui notify_all e non notify, perché un backend nuovo porta
        # MAX_PER_ENDPOINT posti tutti insieme
        slot_libero.notify_all()


def togli_backend(servizio):
    """Toglie dal servizio un endpoint inattivo di quel pool e ne ritorna il nome."""
    with lock:
        # si prende il più recente fra quelli fermi. Prima esce dal servizio
        # qui, poi lo scaling lo spegne, cosi non gli arriva addosso nessuna
        # richiesta mentre il container muore
        for nome in reversed(list(endpoints)):
            if endpoints[nome]["servizio"] == servizio and endpoints[nome]["richieste"] == 0:
                del endpoints[nome]
                return nome
        return None


# -- ingressi HTTP ---------------------------------------------------------


def servi(servizio):
    """Inoltra la richiesta in corso a un backend di quel servizio."""
    nome = prendi_endpoint(servizio)
    if nome is None:
        return jsonify({"errore": f"nessuno slot libero entro {MAX_WAIT}s"}), 503

    try:
        risposta = requests.post(
            endpoints[nome]["url"],
            json=request.get_json(silent=True),
            timeout=TIMEOUT,
        )
        return risposta.content, risposta.status_code, {
            "Content-Type": risposta.headers.get("Content-Type", "application/json")
        }
    except requests.RequestException as e:
        return jsonify({"errore": f"backend {nome} non raggiungibile: {e}"}), 502
    finally:
        # sta nel finally cosi il posto torna libero anche se il backend
        # va in timeout
        rilascia_endpoint(nome)


# Un endpoint per servizio. Cambia solo il pool da cui si pesca, tutto il
# resto sta in servi(), quindi aggiungerne uno sono due righe.
@app.post("/compute")
def compute():
    return servi("calc")


@app.post("/chat")
def chat():
    return servi("chat")


@app.get("/stato")
def stato():
    """Backend in servizio e richieste in corso."""
    with lock:
        stato_endpoints = {}
        for nome, endpoint in endpoints.items():
            stato_endpoints[nome] = {"servizio": endpoint["servizio"],
                                     "richieste": endpoint["richieste"]}
        return jsonify(stato_endpoints)


def avvia_flask():
    app.run(host="0.0.0.0", port=PORTA, threaded=True, use_reloader=False)

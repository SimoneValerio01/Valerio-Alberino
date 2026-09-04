import threading
import time

import requests


URL = "http://localhost:8081"

POLLING_INTERVAL = 5          # ogni quanti secondi chiedo lo stato
POLLING_NUMBER = 2            # numero di letture dello stato dopo un test
SCALE_DOWN_POLLING_NUMBER = 6 # letture dello stato nel test dello scale down
STRESS_TEST_REQUESTS = 20     # richieste al secondo per endpoint nello stress test
REQUESTS_NUMBER = 5           # numero di raffiche dello stress test


def compute(a, b, op):
    print(f"POST {URL}/compute  a={a}  b={b}  op={op}")
    risposta = requests.post(f"{URL}/compute", json={"a": a, "b": b, "op": op}, timeout=60)
    print(f"     {risposta.status_code}  {risposta.text.strip()}")


def chat(messaggio):
    print(f"POST {URL}/chat  messaggio={messaggio}")
    risposta = requests.post(f"{URL}/chat", json={"messaggio": messaggio}, timeout=60)
    print(f"     {risposta.status_code}  {risposta.text.strip()}")


def controlla(richieste, n_polling):
    for richiesta in richieste:
        richiesta.join()

    for _ in range(n_polling):
        stato = requests.get(f"{URL}/stato", timeout=5).json()
        calc_up = 0
        chat_up = 0
        for endpoint in stato.values():
            if endpoint["servizio"] == "calc":
                calc_up += 1
            else:
                chat_up += 1
        print(f"container up   calc={calc_up}  chat={chat_up}")
        time.sleep(POLLING_INTERVAL)


if __name__ == "__main__":
    # Semplice test di verifica degli endpoint
    print("=== TEST 1 ===")
    compute(2, 3, "+")
    time.sleep(1)
    chat("ciao")
    time.sleep(1)
    controlla([], POLLING_NUMBER)

    # Scale up test -> riempio la coda in modo da triggerare uno scale up
    print("=== TEST 2 ===")
    richieste = []
    for _ in range(3):
        calcolatrice = threading.Thread(target=compute, args=(2, 3, "+"))
        chatbot = threading.Thread(target=chat, args=("ciao",))
        calcolatrice.start()
        chatbot.start()
        richieste.append(calcolatrice)
        richieste.append(chatbot)
    controlla(richieste, POLLING_NUMBER)

    # Stress test -> Mando molte più richieste di quanto gli endpoint possano
    # sopportare. Dovrei vedere uno scale up massimo per entrambi e il fallimento
    # di alcune richieste
    print("=== TEST 3 ===")
    richieste = []
    for _ in range(REQUESTS_NUMBER):
        for _ in range(STRESS_TEST_REQUESTS):
            calcolatrice = threading.Thread(target=compute, args=(2, 3, "+"))
            chatbot = threading.Thread(target=chat, args=("ciao",))
            calcolatrice.start()
            chatbot.start()
            richieste.append(calcolatrice)
            richieste.append(chatbot)
        time.sleep(1)
    controlla(richieste, POLLING_NUMBER)

    # Scale down test -> Verifico che i container vengano rimossi dopo un periodo
    # di inattività
    print("=== TEST 4 ===")
    controlla([], SCALE_DOWN_POLLING_NUMBER)

import sys
import time

from flask import Flask, request, jsonify

app = Flask(__name__)

RISPOSTE = {
    "ciao": "Ciao! Come stai?",
    "come stai": "Bene, grazie! E tu?",
    "chi sei": "Sono un assistente virtuale.",
    "grazie": "Figurati!",
    "arrivederci": "A presto!",
}

DEFAULT = "Non ho capito, prova con 'ciao'."


@app.route('/chat', methods=['POST'])
def chat():
    messaggio = request.get_json().get('messaggio', '')
    time.sleep(1)  # carico di lavoro a durata fissa, come calc.py
    return jsonify({'risposta': RISPOSTE.get(messaggio, DEFAULT)})


if __name__ == '__main__':
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    app.run(host='0.0.0.0', port=porta)

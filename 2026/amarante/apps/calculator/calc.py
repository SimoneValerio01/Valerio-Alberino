import sys
import time

from flask import Flask, request, jsonify

app = Flask(__name__)


def calcola(a, b, op):
    if op == '+':
        return a + b
    if op == '-':
        return a - b
    if op == '*':
        return a * b
    if op == '/':
        return a / b if b != 0 else None
    return None


@app.route('/compute', methods=['POST'])
def compute():
    dati = request.get_json()
    op = dati.get('op', '+')

    time.sleep(1)  # carico di lavoro a durata fissa: tempo di servizio costante

    if op not in ('+', '-', '*', '/'):
        return jsonify({'error': f'operazione sconosciuta: {op}'}), 400

    return jsonify({'result': calcola(dati['a'], dati['b'], op)})


if __name__ == '__main__':
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    app.run(host='0.0.0.0', port=porta)

import threading

from mininet.cli import CLI
from mininet.log import setLogLevel

import LoadBalancer
import Scaling
from TopologyWithVLAN import build_topology, parse_args


if __name__ == "__main__":
    args = parse_args()
    setLogLevel("info")

    net = build_topology(args.controller_ip, args.controller_port)
    Scaling.avvia(net)
    Scaling.avvia_pool()

    threading.Thread(target=Scaling.monitor_loop, daemon=True).start()
    threading.Thread(target=LoadBalancer.avvia_flask, daemon=True).start()

    # la rete Mininet deve restare nel thread principale per prendere
    # l'input dell'utente
    print(f"Load balancer su :{LoadBalancer.PORTA} -- /compute e /chat")
    print("'exit' per chiudere")
    CLI(net)

    Scaling.ferma()
    net.stop()

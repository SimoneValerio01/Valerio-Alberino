import argparse

from comnetsemu.net import Containernet
from comnetsemu.node import DockerHost
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel


GATEWAY_IP = '10.0.0.254'     # indirizzo del load balancer sulla rete emulata
GATEWAY_TENANT = 10           # tenant in cui entra il gateway

# Il gateway si affaccia anche sul tenant 20, dove gira il chatbot: è il
# solo componente con un piede in tutti e due i tenant, esattamente come
# un gateway vero. Gli host restano isolati fra loro.
CHAT_TENANT = 20
GATEWAY_IP_CHAT = '10.0.0.253'

# sovrascrivibili da riga di comando con --controller-ip / --controller-port
DEFAULT_CONTROLLER_IP = '192.168.5.144'
DEFAULT_CONTROLLER_PORT = 6653


def parse_args():
    ap = argparse.ArgumentParser(description='Topologia multi-tenant con VLAN.')
    ap.add_argument('--controller-ip', default=DEFAULT_CONTROLLER_IP,
                    help='IP del controller Ryu (default: %(default)s)')
    ap.add_argument('--controller-port', type=int, default=DEFAULT_CONTROLLER_PORT,
                    help='porta OpenFlow del controller (default: %(default)s)')
    return ap.parse_args()


def build_topology(controller_ip, controller_port):
    net = Containernet(controller=RemoteController, link=TCLink, switch=OVSSwitch)

    net.addController('c0', ip=controller_ip, port=controller_port)

    s1 = net.addSwitch('s1')

    computer1 = net.addHost('computer1', cls=DockerHost, dimage='ubuntu:trusty', docker_args={})
    computer2 = net.addHost('computer2', cls=DockerHost, dimage='ubuntu:trusty', docker_args={})
    computer3 = net.addHost('computer3', cls=DockerHost, dimage='ubuntu:trusty', docker_args={})

    net.addLink(computer1, s1, bw=10)
    net.addLink(computer2, s1, bw=10)
    net.addLink(computer3, s1, bw=10)

    net.start()

    # Gateway nel namespace root: è da qui che il load balancer raggiunge
    # i backend. I frame devono essere TAGGATI, perché per il controller
    # la porta LOCAL dello switch è un trunk (TRUNK_PORTS): non taggati
    # verrebbero scartati senza tenant.
    s1.cmd(f"ip link del s1.{GATEWAY_TENANT} 2>/dev/null")
    s1.cmd('ip link set s1 up')          # la porta LOCAL nasce DOWN
    s1.cmd(f"ip link add link s1 name s1.{GATEWAY_TENANT} type vlan id {GATEWAY_TENANT}")
    s1.cmd(f"ip addr add {GATEWAY_IP}/8 dev s1.{GATEWAY_TENANT}")
    s1.cmd(f"ip link set s1.{GATEWAY_TENANT} up")

    # Secondo piede, nel tenant 20. I due tenant condividono la subnet
    # 10.0.0.0/8, quindi qui l'indirizzo è /32 e la rotta verso
    # computer3 è esplicita: con un /8 anche su s1.20 il kernel
    # sceglierebbe l'interfaccia sbagliata e i pacchetti uscirebbero
    # taggati 10, dove computer3 non è.
    s1.cmd(f"ip link del s1.{CHAT_TENANT} 2>/dev/null")
    s1.cmd(f"ip link add link s1 name s1.{CHAT_TENANT} type vlan id {CHAT_TENANT}")
    s1.cmd(f"ip addr add {GATEWAY_IP_CHAT}/32 dev s1.{CHAT_TENANT}")
    s1.cmd(f"ip link set s1.{CHAT_TENANT} up")
    s1.cmd(f"ip route add {computer3.IP()}/32 dev s1.{CHAT_TENANT} src {GATEWAY_IP_CHAT}")

    return net


if __name__ == '__main__':
    args = parse_args()
    setLogLevel('info')
    net = build_topology(args.controller_ip, args.controller_port)
    CLI(net)
    net.stop()

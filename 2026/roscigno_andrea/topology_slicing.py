from mininet.topo import Topo
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from functools import partial

class SliceTopo(Topo):
    def build(self):
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')
        s3 = self.addSwitch('s3')
        s4 = self.addSwitch('s4')

        h1 = self.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')
        h2 = self.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02')
        h3 = self.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:00:03')
        h4 = self.addHost('h4', ip='10.0.0.4/24', mac='00:00:00:00:00:04')

        # Link Host -> Switch
        self.addLink(h1, s1, port1=0, port2=1)
        self.addLink(h2, s1, port1=0, port2=2)
        self.addLink(h3, s4, port1=0, port2=3)
        self.addLink(h4, s4, port1=0, port2=4)

        # Link Inter-switch
        self.addLink(s1, s2, port1=3, port2=1, bw=10)
        self.addLink(s1, s3, port1=4, port2=1, bw=1)
        self.addLink(s2, s4, port1=2, port2=1, bw=10)
        self.addLink(s3, s4, port1=2, port2=2, bw=1)

def run():
    topo = SliceTopo()
    ovs13 = partial(OVSSwitch, protocols='OpenFlow13')
    
    net = Mininet(
        topo=topo,
        controller=lambda name: RemoteController(name, ip='127.0.0.1', port=6653),
        switch=ovs13,
        link=TCLink,
        autoSetMacs=False
    )

    info('*** Avvio rete\n')
    net.start()
    info('*** Test con ping all\n')
    net.pingAll()
    info('*** Avvio CLI\n')
    CLI(net)
    info('*** Arresto rete\n')
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    run()

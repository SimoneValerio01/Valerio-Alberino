from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, vlan


# porta -> tenant
PORT_TENANT = {
    1: 10,
    2: 10,
    3: 20,
}

TRUNK_PORTS = {ofproto_v1_3.OFPP_LOCAL}

ETH_TYPE_8021Q = 0x8100

# Fra due regole che matchano lo stesso pacchetto vince la priorità più
# alta, non il match più specifico. Il salto 100/1 lascia spazio in mezzo.
GUARD_PRIORITY = 100          # scarta i frame taggati su porta di accesso
LEARNED_PRIORITY = 1          # inoltro appreso: sopra il table-miss, sotto le guardie
TABLE_MISS_PRIORITY = 0       # match vuoto, ultima spiaggia: manda al controller


class VlanByPortSwitch(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(VlanByPortSwitch, self).__init__(*args, **kwargs)
        # { (dpid, tenant): { mac: porta } }.
        self.mac_to_port = {}

    # -- configurazione iniziale dello switch ------------------------------

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        # datapath: lo switch che ha appena fatto l'handshake (uno per switch).
        # ofproto: le costanti della versione negoziata.
        # parser: le classi con cui si costruiscono i messaggi.
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        self.install_access_guards(datapath)

        # table-miss -> match vuoto, manda tutto al controller
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, TABLE_MISS_PRIORITY, match, actions)

    def install_access_guards(self, datapath):
        """
        Se un frame ethernet che non proviene dalla porta di Trunk contiene un
        VLAN ID, allora scarta il pacchetto.
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        for port in PORT_TENANT:
            if port in TRUNK_PORTS:
                continue
            # in_port: una regola per porta, perché sul trunk i frame
            # taggati sono legittimi. Per evitare che il dispositivo riceva
            # frame con VLAN ID impostati manualmente dai dispositivi per
            # aggirare i meccanismi di sicurezza, scarto tutti i pacchetti che
            # hanno VLAN ID e che non provengono dal Trunk
            match = parser.OFPMatch(
                in_port=port,
                vlan_vid=(ofproto.OFPVID_PRESENT, ofproto.OFPVID_PRESENT),
            )
            self.add_flow(datapath, GUARD_PRIORITY, match, [])  # [] = drop
            self.logger.info(f"guardia: frame taggati scartati sulla porta {port}")

    def add_flow(self, datapath, priority, match, actions):
        """Chiede allo switch di aggiungere una regola."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

        mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                match=match, instructions=inst)
        datapath.send_msg(mod)

    # -- logica di tenant --------------------------------------------------

    def tenant_of(self, in_port, vlan_hdr):
        """
        Tenant del frame in ingresso, None se il frame non è ammissibile.
        """
        if in_port in TRUNK_PORTS:
            return vlan_hdr.vid if vlan_hdr else None
        if vlan_hdr is not None:
            return None
        return PORT_TENANT.get(in_port)

    def ports_of(self, tenant, exclude):
        """Ritorna una lista di porte associate al tenant (compreso il trunk)"""
        ports = [p for p, t in PORT_TENANT.items() if t == tenant and p != exclude]
        ports += [p for p in TRUNK_PORTS if p != exclude]
        return ports

    def build_actions(self, parser, ofproto, tenant, tagged_in, out_ports):
        """
        Aggiunge una logica per aggiungere/rimuovere l'header VLAN in base
        alla sorgente e alla destinazione.
        ESEMPIO: se la sorgente è un device e la destinazione il Trunk bisogna
        aggiugnere l'header VLAN, se la sorgente e la destinazione sono entrambi device
        bisogna inoltrare il pacchetto senza aggiungere o rimuovere l'header VLAN.
        """
        actions = []
        tagged = tagged_in
        for port in sorted(out_ports, key=lambda p: p in TRUNK_PORTS):
            want_tagged = port in TRUNK_PORTS
            if want_tagged and not tagged:
                actions.append(parser.OFPActionPushVlan(ETH_TYPE_8021Q))
                actions.append(parser.OFPActionSetField(
                    vlan_vid=(ofproto.OFPVID_PRESENT | tenant)))
                tagged = True
            elif not want_tagged and tagged:
                actions.append(parser.OFPActionPopVlan())
                tagged = False
            actions.append(parser.OFPActionOutput(port))
        return actions

    # -- inoltro -----------------------------------------------------------

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """
        Decide cosa fare di un pacchetto che nessuna regola copre.
        Ci arriva solo il primo pacchetto di ogni flusso.
        """
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        vlan_hdr = pkt.get_protocol(vlan.vlan)   # None se il frame non è taggato

        # Verifica chi è il tenant che ha inviato il messaggio
        tenant = self.tenant_of(in_port, vlan_hdr)
        if tenant is None:
            self.logger.info(f"scartato: porta {in_port} non assegnata, "
                             "o frame taggato su porta di accesso")
            return

        # Meccanismo di auto apprendimento
        src, dst = eth.src, eth.dst
        key = (dpid, tenant)
        self.mac_to_port.setdefault(key, {})
        self.mac_to_port[key][src] = in_port

        self.logger.info(f"packet in dpid={dpid} tenant={tenant} "
                         f"src={src} dst={dst} in_port={in_port}")

        known = self.mac_to_port[key].get(dst)
        if known is not None:
            out_ports = [known]
        else:
            # Se il destinatario non è noto, mando il pacchetto a tutti
            # i device che appartengono allo stesso tenant. Non faccio
            # broadcast perché altrimenti manderei i pacchetti anche ai device
            # di tenant diversi
            out_ports = self.ports_of(tenant, exclude=in_port)

        if not out_ports:
            return

        tagged_in = vlan_hdr is not None
        actions = self.build_actions(parser, ofproto, tenant, tagged_in, out_ports)

        # Se non conosco la destinazione devo installare una flow entry nello switch.
        # Questa regola è diversa in base a se è presente un VLAN tag o meno
        if known is not None:
            if tagged_in:
                match = parser.OFPMatch(
                    in_port=in_port, eth_src=src, eth_dst=dst,
                    vlan_vid=(ofproto.OFPVID_PRESENT | tenant))
            else:
                match = parser.OFPMatch(
                    in_port=in_port, eth_src=src, eth_dst=dst, vlan_vid=0)

            self.add_flow(datapath, LEARNED_PRIORITY, match, actions)

        # Dato che lo switch manda l'intero pacchetto al controller, dopo aver
        # applicato la regola devo rimandare il pacchetto cosi che lo switch possa
        # instradarlo
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=ofproto.OFP_NO_BUFFER,
                                  in_port=in_port, actions=actions,
                                  data=msg.data)
        datapath.send_msg(out)

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types

class TopologySliceController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(TopologySliceController, self).__init__(*args, **kwargs)
        
        # Dizionario 
        self.mac_to_port = {}
        
        self.H = {
            'h1': '00:00:00:00:00:01', 'h2': '00:00:00:00:00:02',
            'h3': '00:00:00:00:00:03', 'h4': '00:00:00:00:00:04'
        }

        # Definizione porte di slice per ogni switch
        self.slice_ports = {
            1: {'upper': [1, 3], 'lower': [2, 4]},
            2: {'upper': [1, 2], 'lower': []},
            3: {'upper': [],     'lower': [1, 2]},
            4: {'upper': [1, 3], 'lower': [2, 4]}
        }

    def add_flow(self, datapath, priority, match, actions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                match=match, instructions=inst)
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        ofproto = dp.ofproto
        parser = dp.ofproto_parser
        
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, match, actions)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofproto = dp.ofproto
        parser = dp.ofproto_parser
        in_port = msg.match['in_port']
        dpid = dp.id

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src

        # Apprendimento mac_to_port
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        # 1. Identificazione Slice
        if src in [self.H['h1'], self.H['h3']]:
            slice_type = 'upper'
        elif src in [self.H['h2'], self.H['h4']]:
            slice_type = 'lower'
        else:
            return

        valid_ports = self.slice_ports[dpid][slice_type]
        
        # Sicurezza: ignora se la porta d'ingresso non appartiene alla slice
        if not valid_ports or in_port not in valid_ports:
            return

        # 2. Decisione Routing
        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
            # Isolamento: se la destinazione è fuori dalla slice, scarta
            if out_port not in valid_ports:
                return 
        else:
            # Broadcast o destinazione sconosciuta: manda sull'altra porta della slice
            out_port = valid_ports[0] if valid_ports[1] == in_port else valid_ports[1]

        actions = [parser.OFPActionOutput(out_port)]

        # 3. Installa flusso e inoltra pacchetto
        match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
        self.add_flow(dp, 1, match, actions)

        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        dp.send_msg(out)

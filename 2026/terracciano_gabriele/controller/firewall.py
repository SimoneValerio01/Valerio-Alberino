from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types


BLOCKED_PAIRS = [
    ("10.0.0.1", "10.0.0.3"),
]


BLOCKED_TCP_SERVICES = [
    ("10.0.0.2", "10.0.0.3", 5201),
]


class SDNFirewall(app_manager.RyuApp):

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(SDNFirewall, self).__init__(*args, **kwargs)

        self.mac_to_port = {}

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):

        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        self.logger.info(
            "Switch connected: %s",
            datapath.id
        )


        match = parser.OFPMatch()

        actions = [
            parser.OFPActionOutput(
                ofproto.OFPP_CONTROLLER,
                ofproto.OFPCML_NO_BUFFER
            )
        ]

        self.add_flow(
            datapath,
            priority=0,
            match=match,
            actions=actions
        )


        for host_a, host_b in BLOCKED_PAIRS:

            self.install_ip_drop_rule(
                datapath,
                host_a,
                host_b
            )

            self.install_ip_drop_rule(
                datapath,
                host_b,
                host_a
            )

            self.logger.info(
                "Firewall policy: %s <-> %s BLOCKED",
                host_a,
                host_b
            )

        for src_ip, dst_ip, dst_port in BLOCKED_TCP_SERVICES:

            self.install_tcp_drop_rule(
                datapath,
                src_ip,
                dst_ip,
                dst_port
            )

            self.logger.info(
                "Firewall policy: TCP %s -> %s port %s BLOCKED",
                src_ip,
                dst_ip,
                dst_port
            )

    def install_ip_drop_rule(self, datapath, src_ip, dst_ip):

        parser = datapath.ofproto_parser

        match = parser.OFPMatch(
            eth_type=0x0800,
            ipv4_src=src_ip,
            ipv4_dst=dst_ip
        )

        self.add_flow(
            datapath,
            priority=100,
            match=match,
            actions=[]
        )

    def install_tcp_drop_rule(
        self,
        datapath,
        src_ip,
        dst_ip,
        dst_port
    ):

        parser = datapath.ofproto_parser

        match = parser.OFPMatch(
            eth_type=0x0800,
            ip_proto=6,
            ipv4_src=src_ip,
            ipv4_dst=dst_ip,
            tcp_dst=dst_port
        )

        self.add_flow(
            datapath,
            priority=200,
            match=match,
            actions=[]
        )

    def add_flow(self, datapath, priority, match, actions):

        parser = datapath.ofproto_parser

        instructions = [
            parser.OFPInstructionActions(
                datapath.ofproto.OFPIT_APPLY_ACTIONS,
                actions
            )
        ]

        flow_mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=instructions
        )

        datapath.send_msg(flow_mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):

        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        dpid = datapath.id

        self.mac_to_port.setdefault(dpid, {})

        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)

        eth = pkt.get_protocol(ethernet.ethernet)

        if eth is None:
            return

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        src = eth.src
        dst = eth.dst

        self.mac_to_port[dpid][src] = in_port

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [
            parser.OFPActionOutput(out_port)
        ]

        if out_port != ofproto.OFPP_FLOOD:

            match = parser.OFPMatch(
                in_port=in_port,
                eth_src=src,
                eth_dst=dst
            )

            self.add_flow(
                datapath,
                priority=1,
                match=match,
                actions=actions
            )

        data = None

        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data
        )

        datapath.send_msg(out)
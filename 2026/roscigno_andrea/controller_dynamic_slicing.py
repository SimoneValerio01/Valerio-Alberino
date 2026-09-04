# controller_dynamic_slicing.py
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub

class DynamicSliceController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(DynamicSliceController, self).__init__(*args, **kwargs)

        self.datapaths = {}
        self.monitor_interval = 2
        self.bandwidth_threshold = 1000000 / 8  # 1 Mbps in byte/s

        self.video_stats = {1: 0, 4: 0}
        self.current_speeds = {1: 0.0, 4: 0.0}
        self.global_slice_state = 'UPPER'  # Default: Upper slice libera

        self.monitor_thread = hub.spawn(self._monitor)

        self.H = {
            'h1': '00:00:00:00:00:01', 'h2': '00:00:00:00:00:02',
            'h3': '00:00:00:00:00:03', 'h4': '00:00:00:00:00:04'
        }
        self.PORT_MAP = {
            1: {'h1': 1, 'h2': 2, 's2': 3, 's3': 4},
            2: {'s1': 1, 's4': 2},
            3: {'s1': 1, 's4': 2},
            4: {'s2': 1, 's3': 2, 'h3': 3, 'h4': 4}
        }

    def _monitor(self):
        while True:
            for dp in list(self.datapaths.values()):
                if dp.id in [1, 4]:
                    parser = dp.ofproto_parser
                    req = parser.OFPFlowStatsRequest(dp)
                    dp.send_msg(req)
            hub.sleep(self.monitor_interval)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        body = ev.msg.body
        dpid = ev.msg.datapath.id

        if dpid not in [1, 4]:
            return

        current_video_bytes = 0
        for flow in body:
            if flow.priority == 300:
                if 'udp_dst' in flow.match and flow.match['udp_dst'] == 9999:
                    current_video_bytes += flow.byte_count

        prev_bytes = self.video_stats[dpid]
        if prev_bytes == 0:
            delta_bytes = 0
        else:
            delta_bytes = max(0, current_video_bytes - prev_bytes)

        self.video_stats[dpid] = current_video_bytes
        self.current_speeds[dpid] = delta_bytes / self.monitor_interval

        max_video_speed = max(self.current_speeds[1], self.current_speeds[4])
        is_congested = max_video_speed > self.bandwidth_threshold

        if is_congested and self.global_slice_state == 'UPPER':
            self.logger.info(f"*** VIDEO RILEVATO ({max_video_speed*8/1e6:.2f} Mbps). Traffico Standard -> LOWER.")
            self.apply_slice_policy('LOWER')
        elif not is_congested and self.global_slice_state == 'LOWER':
            if max_video_speed < (self.bandwidth_threshold / 2):
                self.logger.info(f"*** VIDEO TERMINATO ({max_video_speed*8/1e6:.2f} Mbps). Traffico Standard -> UPPER.")
                self.apply_slice_policy('UPPER')

    def apply_slice_policy(self, target_slice):
        self.global_slice_state = target_slice
        for dpid, dp in self.datapaths.items():
            parser = dp.ofproto_parser
            if dpid == 1:
                out_port = self.PORT_MAP[1]['s3'] if target_slice == 'LOWER' else self.PORT_MAP[1]['s2']
                for in_p in [1, 2]:
                    for dst in ['h3', 'h4']:
                        match = parser.OFPMatch(in_port=in_p, eth_type=0x0800, eth_dst=self.H[dst])
                        self.add_flow(dp, 250, match, [parser.OFPActionOutput(out_port)])
            elif dpid == 4:
                out_port = self.PORT_MAP[4]['s3'] if target_slice == 'LOWER' else self.PORT_MAP[4]['s2']
                for in_p in [3, 4]:
                    for dst in ['h1', 'h2']:
                        match = parser.OFPMatch(in_port=in_p, eth_type=0x0800, eth_dst=self.H[dst])
                        self.add_flow(dp, 250, match, [parser.OFPActionOutput(out_port)])

    def add_flow(self, datapath, priority, match, actions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                match=match, instructions=inst)
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(datapath.id, None)
            self.video_stats.pop(datapath.id, None)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        dpid = dp.id
        parser = dp.ofproto_parser
        self.datapaths[dpid] = dp

        # 0. Drop default
        self.add_flow(dp, 0, parser.OFPMatch(), [])

        # 1. ARP Management
        if dpid == 1:
            match = parser.OFPMatch(eth_type=0x0806)
            actions = [parser.OFPActionOutput(1), parser.OFPActionOutput(2), parser.OFPActionOutput(4)]
            self.add_flow(dp, 100, match, actions)
        elif dpid == 3:
            match = parser.OFPMatch(eth_type=0x0806)
            self.add_flow(dp, 100, match, [parser.OFPActionOutput(ofproto_v1_3.OFPP_FLOOD)])
        elif dpid == 4:
            match = parser.OFPMatch(eth_type=0x0806)
            actions = [parser.OFPActionOutput(3), parser.OFPActionOutput(4), parser.OFPActionOutput(2)]
            self.add_flow(dp, 100, match, actions)

        # 2. Regole Switch
        if dpid == 1:
            # Video verso S2
            self.add_flow(dp, 300, parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=9999, in_port=1), [parser.OFPActionOutput(self.PORT_MAP[1]['s2'])])
            self.add_flow(dp, 300, parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=9999, in_port=2), [parser.OFPActionOutput(self.PORT_MAP[1]['s2'])])

            # Video locale H1 <-> H2 (Priorità 310: deve prevalere sull'uplink 300,
            # altrimenti un flusso video diretto all'host locale verrebbe comunque
            # inviato verso S2 dalla regola generica sopra)
            self.add_flow(dp, 310, parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=9999,
                                                    eth_src=self.H['h1'], eth_dst=self.H['h2']),
                          [parser.OFPActionOutput(2)])
            self.add_flow(dp, 310, parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=9999,
                                                    eth_src=self.H['h2'], eth_dst=self.H['h1']),
                          [parser.OFPActionOutput(1)])

            # Traffico locale H1 <-> H2 (Priorità 260: non deve uscire su S2/S3)
            self.add_flow(dp, 260, parser.OFPMatch(eth_type=0x0800, in_port=1, eth_dst=self.H['h2']), [parser.OFPActionOutput(2)])
            self.add_flow(dp, 260, parser.OFPMatch(eth_type=0x0800, in_port=2, eth_dst=self.H['h1']), [parser.OFPActionOutput(1)])

            # Consegna da transito verso host locali
            self.add_flow(dp, 290, parser.OFPMatch(eth_type=0x0800, in_port=3, eth_dst=self.H['h1']), [parser.OFPActionOutput(1)])
            self.add_flow(dp, 290, parser.OFPMatch(eth_type=0x0800, in_port=3, eth_dst=self.H['h2']), [parser.OFPActionOutput(2)])
            self.add_flow(dp, 200, parser.OFPMatch(eth_type=0x0800, in_port=4, eth_dst=self.H['h1']), [parser.OFPActionOutput(1)])
            self.add_flow(dp, 200, parser.OFPMatch(eth_type=0x0800, in_port=4, eth_dst=self.H['h2']), [parser.OFPActionOutput(2)])

            # Default dinamico iniziale su S1: UPPER SLICE (Priorità 250)
            for in_p in [1, 2]:
                for dst in ['h3', 'h4']:
                    match = parser.OFPMatch(in_port=in_p, eth_type=0x0800, eth_dst=self.H[dst])
                    self.add_flow(dp, 250, match, [parser.OFPActionOutput(self.PORT_MAP[1]['s2'])])

        elif dpid in [2, 3]:
            p = 300 if dpid == 2 else 200
            self.add_flow(dp, p, parser.OFPMatch(in_port=1, eth_type=0x0800), [parser.OFPActionOutput(2)])
            self.add_flow(dp, p, parser.OFPMatch(in_port=2, eth_type=0x0800), [parser.OFPActionOutput(1)])

        elif dpid == 4:
            # Video verso S2
            self.add_flow(dp, 300, parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=9999, in_port=3), [parser.OFPActionOutput(self.PORT_MAP[4]['s2'])])
            self.add_flow(dp, 300, parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=9999, in_port=4), [parser.OFPActionOutput(self.PORT_MAP[4]['s2'])])

            # Video locale H3 <-> H4 (Priorità 310: deve prevalere sull'uplink 300)
            self.add_flow(dp, 310, parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=9999,
                                                    eth_src=self.H['h3'], eth_dst=self.H['h4']),
                          [parser.OFPActionOutput(4)])
            self.add_flow(dp, 310, parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=9999,
                                                    eth_src=self.H['h4'], eth_dst=self.H['h3']),
                          [parser.OFPActionOutput(3)])

            # Traffico locale H3 <-> H4 (Priorità 260: non deve uscire su S2/S3)
            self.add_flow(dp, 260, parser.OFPMatch(eth_type=0x0800, in_port=3, eth_dst=self.H['h4']), [parser.OFPActionOutput(4)])
            self.add_flow(dp, 260, parser.OFPMatch(eth_type=0x0800, in_port=4, eth_dst=self.H['h3']), [parser.OFPActionOutput(3)])

            # Consegna da transito verso host locali
            self.add_flow(dp, 290, parser.OFPMatch(eth_type=0x0800, in_port=1, eth_dst=self.H['h3']), [parser.OFPActionOutput(3)])
            self.add_flow(dp, 290, parser.OFPMatch(eth_type=0x0800, in_port=1, eth_dst=self.H['h4']), [parser.OFPActionOutput(4)])
            self.add_flow(dp, 200, parser.OFPMatch(eth_type=0x0800, in_port=2, eth_dst=self.H['h3']), [parser.OFPActionOutput(3)])
            self.add_flow(dp, 200, parser.OFPMatch(eth_type=0x0800, in_port=2, eth_dst=self.H['h4']), [parser.OFPActionOutput(4)])

            # Default dinamico iniziale su S4: UPPER SLICE (Priorità 250)
            for in_p in [3, 4]:
                for dst in ['h1', 'h2']:
                    match = parser.OFPMatch(in_port=in_p, eth_type=0x0800, eth_dst=self.H[dst])
                    self.add_flow(dp, 250, match, [parser.OFPActionOutput(self.PORT_MAP[4]['s2'])])

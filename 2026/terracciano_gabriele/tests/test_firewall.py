import os
import re
import sys
import time


PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

sys.path.insert(0, PROJECT_ROOT)


from mininet.log import setLogLevel
from topology.network import create_network


def get_packet_loss(output):

    match = re.search(
        r'(\d+(?:\.\d+)?)% packet loss',
        output
    )

    if match:
        return float(match.group(1))

    return None


def print_result(name, success):

    if success:
        print(f"[PASS] {name}")
    else:
        print(f"[FAIL] {name}")

    return success


def main():

    setLogLevel('warning')

    print()
    print("========================================")
    print("        SDN FIREWALL TESTS")
    print("========================================")
    print()

    net = create_network()

    passed = 0
    total = 0

    try:

        net.start()

        time.sleep(2)

        h1 = net.get('h1')
        h2 = net.get('h2')
        h3 = net.get('h3')

        # TEST 1
        # h1 -> h2 deve essere consentito

        output = h1.cmd(
            'ping -c 3 -W 1 10.0.0.2'
        )

        loss = get_packet_loss(output)

        success = loss == 0

        total += 1

        if print_result(
            "h1 -> h2 allowed",
            success
        ):
            passed += 1

        # TEST 2
        # h2 -> h3 deve essere consentito

        output = h2.cmd(
            'ping -c 3 -W 1 10.0.0.3'
        )

        loss = get_packet_loss(output)

        success = loss == 0

        total += 1

        if print_result(
            "h2 -> h3 allowed",
            success
        ):
            passed += 1

        # TEST 3
        # h1 -> h3 deve essere bloccato

        output = h1.cmd(
            'ping -c 3 -W 1 10.0.0.3'
        )

        loss = get_packet_loss(output)

        success = loss == 100

        total += 1

        if print_result(
            "h1 -> h3 blocked",
            success
        ):
            passed += 1

        # TEST 4
        # TCP h2 -> h3:5201 deve essere bloccato

        h3.cmd(
            'iperf3 -s -D'
        )

        time.sleep(1)

        server_check = h3.cmd(
            "ss -ltn | grep -q ':5201 ' ; echo $?"
        )

        server_running = (
            server_check.strip() == '0'
        )

        tcp_result = h2.cmd(
            "timeout 5s iperf3 "
            "-c 10.0.0.3 -t 2 "
            ">/dev/null 2>&1 ; echo $?"
        )

        try:
            tcp_exit_code = int(
                tcp_result.strip()
            )
        except ValueError:
            tcp_exit_code = 0

        success = (
            server_running
            and tcp_exit_code != 0
        )

        total += 1

        if print_result(
            "TCP h2 -> h3:5201 blocked",
            success
        ):
            passed += 1

        h3.cmd(
            'pkill iperf3 >/dev/null 2>&1 || true'
        )

    finally:

        net.stop()

    print()
    print("========================================")
    print(
        f"        {passed}/{total} TESTS PASSED"
    )
    print("========================================")
    print()

    if passed == total:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
# multicast_demo.py - Demonstrates IP multicast functionality for peer-to-peer networking
#
# This script shows how to use IP multicast to discover peers on a local network.
# It continuously sends "Hello" messages to a multicast group and listens for
# messages from other peers. This is useful for service discovery in distributed systems.
#
# Multicast vs Broadcast:
# - Multicast is more efficient than broadcast for group communication
# - Multicast traffic is only delivered to interested hosts (those who joined the group)
# - Multicast addresses are in the range 224.0.0.0 to 239.255.255.255
#
# Usage: Simply run the script with Python 3
# $ python multicast_demo.py
import socket
import struct
import threading
import time
import platform

MULTICAST_GROUP = '224.1.1.1'
MULTICAST_PORT = 54545
MESSAGE_INTERVAL = 2  # seconds

peer_name = platform.node() or socket.gethostname()


def send_multicast():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    # Set Time-to-Live to 1 to stay in LAN
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack('b', 1))

    while True:
        msg = f"Hello from {peer_name}"
        sock.sendto(msg.encode(), (MULTICAST_GROUP, MULTICAST_PORT))
        print(f"[SENT] {msg}")
        time.sleep(MESSAGE_INTERVAL)


def receive_multicast():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        sock.bind(('', MULTICAST_PORT))  # Bind to multicast port on all interfaces
    except Exception as e:
        print(f"[ERROR] Could not bind: {e}")
        return

    # Join multicast group
    mreq = struct.pack('4sL', socket.inet_aton(MULTICAST_GROUP), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    print(f"[LISTENING] for multicast on {MULTICAST_GROUP}:{MULTICAST_PORT}...\n")

    while True:
        try:
            data, addr = sock.recvfrom(1024)
            print(f"[RECEIVED from {addr}] {data.decode()}")
        except Exception as e:
            print(f"[ERROR] recvfrom failed: {e}")


if __name__ == "__main__":
    threading.Thread(target=send_multicast, daemon=True).start()
    receive_multicast()

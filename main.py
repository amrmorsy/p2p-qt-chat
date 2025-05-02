import sys
import socket
import threading
import time
import ipaddress
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QPushButton,
    QListWidget,
    QLineEdit,
    QTextEdit,
    QLabel,
    QDialog,
)
from PySide6.QtCore import QTimer, Signal, QObject

# Network configuration constants
BROADCAST_PORT = 54545
DEFAULT_CHAT_PORT = 54546
BROADCAST_INTERVAL = 2  # Seconds between broadcasts
PEER_TIMEOUT = 10       # Seconds until a peer is considered offline

# Get this machine's name for identification
peer_name = socket.gethostname()

def get_local_ip():
    """Get the local IP address of this machine"""
    try:
        # Best method: create a dummy connection to get local address
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        # Fallback method if network is unavailable
        return socket.gethostbyname(socket.gethostname())

# Get local IP once at startup
peer_ip = get_local_ip()

if __name__ == "__main__":
    # Only process command line args when running the file directly
    CHAT_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CHAT_PORT
else:
    # When imported (like for testing), use the default port
    CHAT_PORT = DEFAULT_CHAT_PORT

# Store discovered peers: peer_id -> (ip, port, last_seen)
peers = {}

def get_broadcast_address():
    """Calculate the broadcast address for the local network"""
    try:
        net = ipaddress.IPv4Network(peer_ip + "/24", strict=False)
        return str(net.broadcast_address)
    except Exception as e:
        print(f"[ERROR] Broadcast calculation failed: {e}")
        return "255.255.255.255"  # Fallback to global broadcast

class ChatSession(QObject):
    """Handles the network communication for a single chat"""
    new_message = Signal(str)  # Signal emitted when a message is received

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        # Start receiving messages in a background thread
        threading.Thread(target=self.receive_loop, daemon=True).start()

    def send(self, msg):
        """Send a message to the connected peer"""
        try:
            self.conn.sendall(msg.encode())
        except Exception as e:
                print(f"[SEND ERROR] {e}")
                self.new_message.emit("[Send Failed]")

    def receive_loop(self):
        """Background thread that receives messages"""
        print("[DEBUG] Starting receive loop")
        while True:
            try:
                data = self.conn.recv(1024)
                if not data:
                    print("[DEBUG] Connection closed by peer")
                    break
                self.new_message.emit(data.decode())
            except Exception as e:
                print(f"[RECEIVE ERROR] {e}")
                break
        self.new_message.emit("[Connection Closed]")
        self.conn.close()

class ChatWindow(QDialog):
    """Dialog window for a single chat conversation"""
    def __init__(self, conn, title):
        super().__init__()
        self.setWindowTitle(title)
        self.setMinimumSize(400, 300)

        # Message display area
        self.display = QTextEdit()
        self.display.setReadOnly(True)

        # Text input for sending messages
        self.input = QLineEdit()
        self.input.returnPressed.connect(self.send_message)

        # Layout setup
        layout = QVBoxLayout()
        layout.addWidget(QLabel(title))
        layout.addWidget(self.display)
        layout.addWidget(self.input)
        self.setLayout(layout)

        # Create chat session and connect to message signal
        self.session = ChatSession(conn)
        self.session.new_message.connect(self.append_message)

    def send_message(self):
        """Send the message in the input field"""
        text = self.input.text().strip()
        if text:
            self.session.send(text)
            self.append_message(f"You: {text}")
            self.input.clear()

    def append_message(self, msg):
        """Add a message to the chat display"""
        self.display.append(msg)

class MainWindow(QMainWindow):
    """Main application window that shows peer list and manages chat windows"""
    # Signal to safely open chat windows from non-GUI threads
    open_chat_signal = Signal(object, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"P2P Chat - {peer_name} ({CHAT_PORT})")
        self.setMinimumSize(400, 500)

        self.chat_windows = []  # ✅ Holds open chat windows (fixes GC issue)

        # UI elements for peer list and connection
        self.peer_list = QListWidget()
        self.connect_btn = QPushButton("Connect to Peer")
        self.connect_btn.clicked.connect(self.connect_to_peer)

        # Layout setup
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Peers on LAN:"))
        layout.addWidget(self.peer_list)
        layout.addWidget(self.connect_btn)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # Connect signal to handler
        self.open_chat_signal.connect(self.open_chat_window)

        # Timer for refreshing the peer list
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_peers)
        self.timer.start(3000)  # Update every 3 seconds

        # Start network-related background threads
        self.start_threads()

    def start_threads(self):
        """Start all the background threads for network operations"""
        threading.Thread(target=self.broadcast_presence, daemon=True).start()
        threading.Thread(target=self.listen_for_broadcasts, daemon=True).start()
        threading.Thread(target=self.listen_for_incoming_chat, daemon=True).start()
        threading.Thread(target=self.cleanup_peers, daemon=True).start()

    def broadcast_presence(self):
        """Periodically announce this peer's presence on the network"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        broadcast_ip = get_broadcast_address()
        print(f"[BROADCASTING TO] {broadcast_ip}:{BROADCAST_PORT}")

        while True:
            try:
                msg = f"{peer_name}:{peer_ip}:{CHAT_PORT}"
                sock.sendto(msg.encode(), (broadcast_ip, BROADCAST_PORT))
                time.sleep(BROADCAST_INTERVAL)
            except Exception as e:
                print(f"[ERROR] Failed to broadcast: {e}")

    def listen_for_broadcasts(self):
        """Listen for broadcast announcements from other peers"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", BROADCAST_PORT))
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                msg = data.decode()
                name, ip, port = msg.split(":")
                port = int(port)
                # Skip our own broadcasts
                if ip == peer_ip and port == CHAT_PORT:
                    continue
                peer_id = f"{name}@{ip}:{port}"
                peers[peer_id] = (ip, port, time.time())
            except Exception as e:
                    print(f"[BROADCAST ERROR] {e}")

    def listen_for_incoming_chat(self):
        """Accept incoming TCP connections for chat"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((peer_ip, CHAT_PORT))
            sock.listen()
            print(f"[TCP LISTENING] {peer_ip}:{CHAT_PORT}")
        except Exception as e:
            print(f"[ERROR] TCP bind failed: {e}")
            return
        while True:
            conn, addr = sock.accept()
            # Use signal to safely create UI elements from this thread
            self.open_chat_signal.emit(conn, f"Chat from {addr[0]}")

    def cleanup_peers(self):
        """Remove peers that haven't been seen recently"""
        while True:
            now = time.time()
            # Use list() to avoid modifying dict during iteration
            for peer_id in list(peers):
                if now - peers[peer_id][2] > PEER_TIMEOUT:
                    del peers[peer_id]
            time.sleep(5)

    def refresh_peers(self):
        """Update the UI list of available peers"""
        self.peer_list.clear()
        for peer_id in peers:
            self.peer_list.addItem(peer_id)

    def connect_to_peer(self):
        """Initiate a connection to the selected peer"""
        items = self.peer_list.selectedItems()
        if not items:
            return
        peer_id = items[0].text()
        ip, port, _ = peers[peer_id]
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((ip, port))
            self.open_chat_window(sock, f"Chat with {peer_id}")
        except Exception as e:
            self.statusBar().showMessage(f"Failed to connect: {e}")

    def open_chat_window(self, conn, title):
        """Open a new chat window for a connection"""
        win = ChatWindow(conn, title)
        win.show()
        self.chat_windows.append(win)  # ✅ Keep reference so window stays alive

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

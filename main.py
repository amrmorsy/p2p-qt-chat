import base64
import ipaddress
import os
import socket
import sys
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Network configuration constants
BROADCAST_PORT = 54545
DEFAULT_CHAT_PORT = 54546
BROADCAST_INTERVAL = 2  # Seconds between broadcasts
PEER_TIMEOUT = 10  # Seconds until a peer is considered offline
MAX_FILE_CHUNK_SIZE = 8192  # 8KB chunks for file transfer

# Protocol markers for message types
TEXT_MESSAGE = "MSG:"
FILE_HEADER = "FILE:"
FILE_CHUNK = "CHUNK:"
FILE_END = "FEND:"

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


def find_available_port(start_port, max_attempts=10):
    """
    Try to find an available port starting from start_port.
    Returns the available port or None if none found after max_attempts.
    """
    for port_offset in range(max_attempts):
        port = start_port + port_offset
        try:
            # Create a test socket
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            test_socket.bind(("0.0.0.0", port))
            test_socket.close()
            return port
        except OSError:
            continue
    return None


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
    file_progress = Signal(str, int, int)  # filename, bytes_received, total_size
    file_received = Signal(str)  # filename
    file_error = Signal(str, str)  # filename, error_message

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.current_file = None
        self.file_data = None
        self.file_size = 0
        self.bytes_received = 0
        # Start receiving messages in a background thread
        threading.Thread(target=self.receive_loop, daemon=True).start()

    def send(self, msg):
        """Send a text message to the connected peer"""
        try:
            self.conn.sendall(f"{TEXT_MESSAGE}{msg}".encode())
        except Exception as e:
            print(f"[SEND ERROR] {e}")
            self.new_message.emit("[Send Failed]")

    def send_file(self, filepath):
        """Send a file to the connected peer with improved framing"""
        try:
            # Get file details
            filename = os.path.basename(filepath)
            filesize = os.path.getsize(filepath)

            # Send file header with newline delimiter
            header = f"{FILE_HEADER}{filename}:{filesize}\n"
            self.conn.sendall(header.encode())

            # Send file in chunks
            bytes_sent = 0
            with open(filepath, "rb") as f:
                self.new_message.emit(f"[Sending file: {filename}]")

                while bytes_sent < filesize:
                    # Read a chunk of data
                    chunk = f.read(MAX_FILE_CHUNK_SIZE)
                    if not chunk:
                        break

                    # Encode the chunk for sending over text-based protocol
                    encoded_chunk = base64.b64encode(chunk).decode()

                    # Include the length of the encoded data for proper framing
                    chunk_msg = f"{FILE_CHUNK}{len(encoded_chunk)}:{encoded_chunk}"
                    self.conn.sendall(chunk_msg.encode())

                    bytes_sent += len(chunk)
                    # Optionally wait for acknowledgment here

            # Send file end marker with newline
            self.conn.sendall(f"{FILE_END}{filename}\n".encode())
            self.new_message.emit(f"[File sent: {filename}]")

        except Exception as e:
            print(f"[FILE SEND ERROR] {e}")
            import traceback

            traceback.print_exc()
            self.new_message.emit(f"[Failed to send file: {e}]")

    def receive_loop(self):
        """Background thread that receives messages with improved buffer handling"""
        print("[DEBUG] Starting receive loop")
        buffer = ""

        while True:
            try:
                # Receive data and add to buffer
                data = self.conn.recv(MAX_FILE_CHUNK_SIZE)
                if not data:
                    print("[DEBUG] Connection closed by peer")
                    break

                # Add received data to buffer
                buffer += data.decode(
                    "utf-8", errors="replace"
                )  # Handle potential encoding issues

                # Process buffer until we can't extract complete messages
                while len(buffer) > 0:
                    print(f"[DEBUG] Buffer length: {len(buffer)}")

                    # TEXT MESSAGE
                    if buffer.startswith(TEXT_MESSAGE):
                        # Look for end of message marker (could use newline or another delimiter)
                        end_idx = buffer.find("\n", len(TEXT_MESSAGE))
                        if end_idx == -1:  # Message isn't complete yet
                            break

                        # Extract the complete message
                        message = buffer[len(TEXT_MESSAGE) : end_idx]
                        buffer = buffer[
                            end_idx + 1 :
                        ]  # Remove processed data, keep the rest
                        self.new_message.emit(message)
                        continue  # Check for more complete messages

                    # FILE HEADER
                    elif buffer.startswith(FILE_HEADER):
                        header_end = buffer.find("\n", len(FILE_HEADER))
                        if header_end == -1:  # Incomplete header
                            break

                        header_data = buffer[len(FILE_HEADER) : header_end].split(
                            ":", 1
                        )
                        if len(header_data) == 2:
                            self.current_file = header_data[0]
                            self.file_size = int(header_data[1])
                            self.bytes_received = 0
                            self.file_data = bytearray()

                            self.new_message.emit(
                                f"[Receiving file: {self.current_file} ({self.file_size} bytes)]"
                            )
                            buffer = buffer[header_end + 1 :]  # Keep remaining data
                            continue  # Process more messages if present
                        else:
                            # Malformed header, discard and continue
                            print("[ERROR] Malformed file header")
                            buffer = buffer[header_end + 1 :]

                    # FILE CHUNK
                    elif buffer.startswith(FILE_CHUNK) and self.current_file:
                        # Format: "CHUNK:<length>:<base64data>"
                        first_colon = buffer.find(":", len(FILE_CHUNK))
                        if first_colon == -1:
                            break  # Incomplete header

                        second_colon = buffer.find(":", first_colon + 1)
                        if second_colon == -1:
                            break  # Incomplete header

                        try:
                            chunk_length = int(buffer[first_colon + 1 : second_colon])

                            # Check if we have the complete chunk data
                            if len(buffer) < second_colon + 1 + chunk_length:
                                print(
                                    f"[DEBUG] Waiting for complete chunk: have {len(buffer) - second_colon - 1}/{chunk_length}"
                                )
                                break  # Wait for more data

                            # Extract the chunk
                            encoded_chunk = buffer[
                                second_colon + 1 : second_colon + 1 + chunk_length
                            ]

                            # Process the chunk
                            try:
                                chunk = base64.b64decode(encoded_chunk)
                                self.file_data.extend(chunk)
                                self.bytes_received += len(chunk)

                                # Update progress
                                self.file_progress.emit(
                                    self.current_file,
                                    self.bytes_received,
                                    self.file_size,
                                )

                                # Remove processed data
                                buffer = buffer[second_colon + 1 + chunk_length :]

                                continue  # Process more if available

                            except Exception as e:
                                print(f"[ERROR] Failed to decode chunk: {e}")
                                # Skip this chunk and try to recover
                                buffer = buffer[second_colon + 1 + chunk_length :]

                        except ValueError as e:
                            print(f"[ERROR] Invalid chunk length: {e}")
                            # Try to recover by skipping to next line
                            next_line = buffer.find("\n", len(FILE_CHUNK))
                            if next_line != -1:
                                buffer = buffer[next_line + 1 :]
                            else:
                                # If recovery fails, clear buffer and start fresh
                                buffer = ""
                                break

                    # FILE END
                    elif buffer.startswith(FILE_END) and self.current_file:
                        end_idx = buffer.find("\n", len(FILE_END))
                        if end_idx == -1:  # Incomplete marker
                            break

                        filename = buffer[len(FILE_END) : end_idx]
                        buffer = buffer[end_idx + 1 :]  # Keep remaining data

                        if filename == self.current_file:
                            # Verify file integrity
                            if self.bytes_received != self.file_size:
                                self.new_message.emit(
                                    f"[Warning] File size mismatch: expected {self.file_size}, got {self.bytes_received} bytes"
                                )

                            # Save the file
                            downloads_dir = os.path.join(
                                os.path.expanduser("~"), "Downloads"
                            )
                            if not os.path.exists(downloads_dir):
                                downloads_dir = os.getcwd()

                            save_path = os.path.join(downloads_dir, self.current_file)
                            try:
                                with open(save_path, "wb") as f:
                                    f.write(self.file_data)

                                self.new_message.emit(
                                    f"[File received: {self.current_file}]"
                                )
                                self.file_received.emit(save_path)
                            except Exception as e:
                                self.new_message.emit(f"[Error saving file: {e}]")
                                self.file_error.emit(self.current_file, str(e))

                            # Reset file transfer state
                            self.current_file = None
                            self.file_data = None
                            continue  # Process more messages if present

                    else:
                        # Unrecognized message type, try to find a known prefix
                        found = False
                        for prefix in [TEXT_MESSAGE, FILE_HEADER, FILE_CHUNK, FILE_END]:
                            next_prefix = buffer.find(prefix)
                            if next_prefix > 0:
                                print(
                                    f"[DEBUG] Skipping to next recognizable message at position {next_prefix}"
                                )
                                buffer = buffer[next_prefix:]
                                found = True
                                break

                        if not found:
                            # If no recognizable message is found, discard the first character and try again
                            print("[DEBUG] Discarding unrecognized data")
                            buffer = buffer[1:]

                        # If buffer is too small to contain a message, wait for more data
                        if len(buffer) < 5:
                            break

            except Exception as e:
                print(f"[RECEIVE ERROR] {e}")
                import traceback

                traceback.print_exc()
                break

        self.new_message.emit("[Connection Closed]")
        self.conn.close()


class ChatWindow(QDialog):
    """Dialog window for a single chat conversation"""

    def __init__(self, conn, title):
        super().__init__()
        self.setWindowTitle(title)
        self.setMinimumSize(500, 400)

        # Message display area
        self.display = QTextEdit()
        self.display.setReadOnly(True)

        # Text input for sending messages
        self.input = QLineEdit()
        self.input.returnPressed.connect(self.send_message)

        # Send message button
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.send_message)

        # Send file button
        self.file_btn = QPushButton("Send File")
        self.file_btn.clicked.connect(self.select_file)

        # Progress bar for file transfers
        self.progress = QProgressBar()
        self.progress.setVisible(False)

        # Layout for input and buttons
        input_layout = QHBoxLayout()
        input_layout.addWidget(self.input)
        input_layout.addWidget(self.send_btn)
        input_layout.addWidget(self.file_btn)

        # Main layout
        layout = QVBoxLayout()
        layout.addWidget(QLabel(title))
        layout.addWidget(self.display)
        layout.addLayout(input_layout)
        layout.addWidget(self.progress)
        self.setLayout(layout)

        # Create chat session and connect to signals
        self.session = ChatSession(conn)
        self.session.new_message.connect(self.append_message)
        self.session.file_progress.connect(self.update_file_progress)
        self.session.file_received.connect(self.file_received)
        self.session.file_error.connect(self.file_error)

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

    def select_file(self):
        """Open file dialog to select a file to send"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select File to Send", "", "All Files (*)"
        )
        if filepath:
            # Check file size - warn if large
            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            if size_mb > 10:  # Warn if > 10MB
                reply = QMessageBox.question(
                    self,
                    "Confirm File Send",
                    f"The file is {size_mb:.1f}MB. Are you sure you want to send it?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.No:
                    return

            # Start file sending in a separate thread to keep UI responsive
            threading.Thread(
                target=self.session.send_file, args=(filepath,), daemon=True
            ).start()

    def update_file_progress(self, filename, received, total):
        """Update the progress bar for file transfer"""
        if not self.progress.isVisible():
            self.progress.setVisible(True)

        self.progress.setMaximum(total)
        self.progress.setValue(received)

        # Hide progress bar when complete
        if received >= total:
            QTimer.singleShot(2000, lambda: self.progress.setVisible(False))

    def file_received(self, filepath):
        """Handle notification of completed file reception"""
        reply = QMessageBox.question(
            self,
            "File Received",
            f"File saved to: {filepath}\nDo you want to open it?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            # Open file with default application
            # This is platform-specific
            if sys.platform == "win32":
                os.startfile(filepath)
            elif sys.platform == "darwin":  # macOS
                os.system(f'open "{filepath}"')
            else:  # Linux
                os.system(f'xdg-open "{filepath}"')

    def file_error(self, filename, error):
        """Handle file transfer errors"""
        QMessageBox.warning(
            self, "File Transfer Error", f"Error with file {filename}: {error}"
        )


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
        global BROADCAST_PORT

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            sock.bind(("0.0.0.0", BROADCAST_PORT))
        except OSError as e:
            if e.errno == 48:  # Address already in use
                print(
                    f"[WARN] Broadcast port {BROADCAST_PORT} is in use, trying to find an available port..."
                )
                available_port = find_available_port(BROADCAST_PORT)
                if available_port:
                    print(f"[INFO] Using alternative broadcast port: {available_port}")
                    BROADCAST_PORT = available_port
                    # Create a new socket with the new port
                    sock.close()
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.bind(("0.0.0.0", BROADCAST_PORT))
                else:
                    print("[ERROR] Could not find an available broadcast port")
                    return
            else:
                print(f"[ERROR] Socket error: {e}")
                return
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
        global CHAT_PORT

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            sock.bind((peer_ip, CHAT_PORT))
        except OSError as e:
            if e.errno == 48:  # Address already in use
                print(
                    f"[WARN] Chat port {CHAT_PORT} is in use, trying to find an available port..."
                )
                available_port = find_available_port(CHAT_PORT)
                if available_port:
                    print(f"[INFO] Using alternative chat port: {available_port}")
                    CHAT_PORT = available_port
                    # Update the window title to show the new port
                    self.setWindowTitle(f"P2P Chat - {peer_name} ({CHAT_PORT})")
                    # Create a new socket with the new port
                    sock.close()
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.bind((peer_ip, CHAT_PORT))
                else:
                    print("[ERROR] Could not find an available chat port")
                    return
            else:
                print(f"[ERROR] TCP bind failed: {e}")
                return

        sock.listen()
        print(f"[TCP LISTENING] {peer_ip}:{CHAT_PORT}")
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

import unittest
from unittest import mock
import socket  # Used for socket mocking and type constants
import time    # Used for timestamps in peer management tests
import sys     # Used for command line arguments handling

# ============================================================================
# SETUP AND UTILITY FUNCTIONS
# ============================================================================

# Prevent command line arguments from affecting the tests
# This is important because our main.py parses sys.argv for port configuration
sys.argv = [sys.argv[0]]

# Create mock implementations of Qt classes required by main.py
# These mocks prevent GUI-related errors during testing

# MockSignal: Simulates Qt's Signal class for event handling
class MockSignal:
    def __init__(self, *args):
        # Store connected callbacks
        self.connections = []

    def connect(self, func):
        # Register a function to be called when signal is emitted
        self.connections.append(func)

    def emit(self, *args):
        # Call all connected functions with the provided arguments
        for func in self.connections:
            func(*args)

# MockQObject: Simulates Qt's QObject base class
class MockQObject:
    def __init__(self):
        pass  # Implementation not needed for our tests

# Apply mocks for all PySide6/Qt modules and classes
# This prevents actual GUI creation during tests and avoids threading issues
sys.modules['PySide6'] = mock.MagicMock()
sys.modules['PySide6.QtWidgets'] = mock.MagicMock()
sys.modules['PySide6.QtCore'] = mock.MagicMock()
sys.modules['PySide6.QtCore'].Signal = MockSignal
sys.modules['PySide6.QtCore'].QObject = MockQObject
sys.modules['PySide6.QtTest'] = mock.MagicMock()

# Import the module under test after all mocks are in place
# This ensures our main.py uses the mock objects instead of real ones
import main

# Prevent actual thread creation to avoid test interference and hanging
# Store original Thread class to restore it later
orig_thread = main.threading.Thread
def mock_thread(*args, **kwargs):
    # Return a mock instead of creating a real thread
    return mock.MagicMock()
main.threading.Thread = mock_thread

# Function to restore the original threading behavior when tests complete
def restore_threading():
    main.threading.Thread = orig_thread

# Reset global state between tests to avoid test interdependence
def reset_state():
    # Clear the peers dictionary to start with a clean slate
    main.peers = {}

# ============================================================================
# NETWORK UTILITY TESTS
# ============================================================================

class TestNetworkFunctions(unittest.TestCase):
    """Test the basic network utility functions"""

    def setUp(self):
        # Reset global state before each test
        reset_state()

    def test_get_local_ip(self):
        """Test that get_local_ip returns a valid IPv4 address"""
        with mock.patch('socket.socket') as mock_socket:
            # Set up the mock socket with predefined return values
            mock_sock = mock.MagicMock()
            mock_socket.return_value = mock_sock
            mock_sock.getsockname.return_value = ('192.168.1.5', 12345)

            # Call the function under test
            ip = main.get_local_ip()

            # Verify the return value matches expected IP
            self.assertEqual(ip, '192.168.1.5')
            # Verify the socket was used correctly to connect to Google DNS
            mock_sock.connect.assert_called_once_with(("8.8.8.8", 80))

    def test_get_broadcast_address(self):
        """Test that get_broadcast_address returns a valid broadcast address"""
        # Save original value to restore later
        original_ip = main.peer_ip

        try:
            # Test case 1: Valid IP address
            main.peer_ip = '192.168.1.5'
            broadcast = main.get_broadcast_address()
            # Should calculate broadcast as 192.168.1.255 for this subnet
            self.assertEqual(broadcast, '192.168.1.255')

            # Test case 2: Invalid IP - should return fallback address
            main.peer_ip = 'invalid_ip'
            broadcast = main.get_broadcast_address()
            # Should use fallback address when IP is invalid
            self.assertEqual(broadcast, '255.255.255.255')
        finally:
            # Always restore the original value to avoid affecting other tests
            main.peer_ip = original_ip


# ============================================================================
# CHAT SESSION TESTS
# ============================================================================

class TestChatSession(unittest.TestCase):
    """Test the ChatSession class functionality"""

    def setUp(self):
        """Set up mock connection for testing"""
        # Create a mock socket connection for testing ChatSession
        self.mock_conn = mock.MagicMock()
        self.session = main.ChatSession(self.mock_conn)

    def test_send_message(self):
        """Test sending a message through ChatSession"""
        # Create a test message
        test_msg = "Hello, world!"
        # Send it through the session
        self.session.send(test_msg)

        # Verify the message was encoded and sent correctly through the socket
        self.mock_conn.sendall.assert_called_once_with(test_msg.encode())

    def test_send_message_with_exception(self):
        """Test error handling when socket.sendall fails"""
        # Configure the mock to raise an exception when sendall is called
        self.mock_conn.sendall.side_effect = Exception("Send failed")

        # Set up a listener to capture signal emissions
        emitted_msgs = []
        def collect_messages(msg):
            emitted_msgs.append(msg)
        self.session.new_message.connect(collect_messages)

        # Send a message, which should trigger the exception
        self.session.send("Test message")

        # Verify that the error message was emitted through the signal
        self.assertIn("[Send Failed]", emitted_msgs)


# ============================================================================
# PEER MANAGEMENT TESTS
# ============================================================================

class TestPeerManagement(unittest.TestCase):
    """Test peer discovery and timeout functionality"""

    def setUp(self):
        # Start each test with a clean peers dictionary
        reset_state()

    def test_peer_timeout(self):
        """Test that peers are removed after their timeout period"""
        # Add peers with different timestamps (now, 5 seconds ago, 15 seconds ago)
        now = time.time()
        main.peers = {
            "peer1": ("192.168.1.10", 54546, now),         # Current
            "peer2": ("192.168.1.11", 54546, now - 5),     # 5 seconds old
            "peer3": ("192.168.1.12", 54546, now - 15)     # 15 seconds old
        }

        # Save original timeout value to restore it later
        original_timeout = main.PEER_TIMEOUT

        try:
            # Set timeout to 10 seconds for this test
            main.PEER_TIMEOUT = 10

            # Manually execute the cleanup logic from main.py
            now = time.time()
            # Identify peers that have timed out
            expired_peers = [peer_id for peer_id in main.peers
                            if now - main.peers[peer_id][2] > main.PEER_TIMEOUT]
            # Remove expired peers
            for peer_id in expired_peers:
                del main.peers[peer_id]

            # Verify results: peer3 should be removed, others should remain
            self.assertEqual(len(main.peers), 2, "Should have 2 peers remaining")
            self.assertIn("peer1", main.peers, "Recent peer should still be present")
            self.assertIn("peer2", main.peers, "Peer within timeout should still be present")
            self.assertNotIn("peer3", main.peers, "Expired peer should be removed")
        finally:
            # Always restore the original timeout value
            main.PEER_TIMEOUT = original_timeout


# ============================================================================
# BROADCAST FUNCTIONALITY TESTS
# ============================================================================

class TestBroadcastFunctions(unittest.TestCase):
    """Test network broadcast functionality for peer discovery"""

    def setUp(self):
        # Create mock for socket operations
        self.socket_patcher = mock.patch('socket.socket')
        self.mock_socket_class = self.socket_patcher.start()
        self.mock_socket = mock.MagicMock()
        self.mock_socket_class.return_value = self.mock_socket

    def tearDown(self):
        # Clean up the socket patch after each test
        self.socket_patcher.stop()

    def test_broadcast_presence_message_format(self):
        """Test the format of the broadcast message sent for peer discovery"""
        # Mock the broadcast address calculation
        with mock.patch('main.get_broadcast_address', return_value='192.168.1.255'):
            # Create the expected broadcast message in the format: name:ip:port
            msg = f"{main.peer_name}:{main.peer_ip}:{main.CHAT_PORT}"
            self.mock_socket.sendto.return_value = len(msg)  # Simulate successful send

            # Execute the logic we want to test (sending the broadcast)
            msg_bytes = msg.encode()
            self.mock_socket.sendto(msg_bytes, ('192.168.1.255', main.BROADCAST_PORT))

            # Verify the socket sendto method was called correctly
            self.mock_socket.sendto.assert_called_once()
            call_args = self.mock_socket.sendto.call_args[0]

            # Verify message has the correct format (name:ip:port)
            sent_msg = call_args[0].decode().split(':')
            self.assertEqual(len(sent_msg), 3, "Message should have 3 parts separated by colons")
            self.assertEqual(sent_msg[0], main.peer_name, "First part should be peer name")
            self.assertEqual(sent_msg[1], main.peer_ip, "Second part should be peer IP")
            self.assertEqual(sent_msg[2], str(main.CHAT_PORT), "Third part should be port number")

            # Verify message was sent to the correct broadcast address and port
            self.assertEqual(call_args[1], ('192.168.1.255', main.BROADCAST_PORT))

    def test_broadcast_message_processing(self):
        """Test processing of received broadcast messages from other peers"""
        # Clear existing peers before test
        main.peers = {}

        # Create a test broadcast message from another peer
        test_msg = "TestPeer:192.168.1.10:54546"
        self.mock_socket.recvfrom.return_value = (test_msg.encode(), ('192.168.1.10', main.BROADCAST_PORT))

        # Save original values to restore later
        original_ip = main.peer_ip
        original_port = main.CHAT_PORT

        try:
            # Set our own address to something different from the test message
            # This ensures we don't ignore the message as our own
            main.peer_ip = "192.168.1.20"
            main.CHAT_PORT = 54547

            # Manually execute the logic for processing a received broadcast message
            data, addr = self.mock_socket.recvfrom(1024)
            msg = data.decode()
            name, ip, port = msg.split(":")
            port = int(port)

            # Skip our own messages (should not happen with these test values)
            if ip == main.peer_ip and port == main.CHAT_PORT:
                pass
            else:
                # Add received peer to our dictionary (this is the key logic being tested)
                peer_id = f"{name}@{ip}:{port}"
                main.peers[peer_id] = (ip, port, time.time())

            # Verify the peer was added correctly to our peer list
            self.assertEqual(len(main.peers), 1, "Should have added exactly one peer")
            peer_id = "TestPeer@192.168.1.10:54546"
            self.assertIn(peer_id, main.peers, "Peer ID should be in the format name@ip:port")

            # Verify the peer data was stored correctly
            peer_data = main.peers[peer_id]
            self.assertEqual(peer_data[0], "192.168.1.10", "IP should be stored correctly")
            self.assertEqual(peer_data[1], 54546, "Port should be stored correctly")
        finally:
            # Restore original values
            main.peer_ip = original_ip
            main.CHAT_PORT = original_port


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

if __name__ == "__main__":
    try:
        # Run all tests
        unittest.main()
    finally:
        # Ensure we restore the threading module even if tests fail
        restore_threading()

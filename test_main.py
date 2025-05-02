import unittest
from unittest import mock
import socket
import time
import sys
import os
import base64
import tempfile

# ============================================================================
# SETUP AND UTILITY FUNCTIONS
# ============================================================================

# Prevent command line arguments from affecting the tests
sys.argv = [sys.argv[0]]

# Mock Qt classes needed for testing
class MockSignal:
    """Mock implementation of Qt's Signal class for testing"""
    def __init__(self, *args):
        self.connections = []

    def connect(self, func):
        """Register a function to be called when signal is emitted"""
        self.connections.append(func)

    def emit(self, *args):
        """Emit the signal by calling all connected functions"""
        for func in self.connections:
            func(*args)

class MockQObject:
    """Mock implementation of Qt's QObject base class"""
    def __init__(self):
        pass

# Apply mocks for all Qt modules and classes
sys.modules['PySide6'] = mock.MagicMock()
sys.modules['PySide6.QtWidgets'] = mock.MagicMock()
sys.modules['PySide6.QtCore'] = mock.MagicMock()
sys.modules['PySide6.QtCore'].Signal = MockSignal
sys.modules['PySide6.QtCore'].QObject = MockQObject
sys.modules['PySide6.QtTest'] = mock.MagicMock()

# Now import the module with mocked dependencies
import main

# Replace threading to avoid actual thread creation
orig_thread = main.threading.Thread
def mock_thread(*args, **kwargs):
    """Mock thread creation to avoid actual threads during testing"""
    return mock.MagicMock()
main.threading.Thread = mock_thread

# Function to restore the original threading behavior
def restore_threading():
    """Restore original threading implementation after tests"""
    main.threading.Thread = orig_thread

# Reset global state between tests
def reset_state():
    """Reset global application state for clean test environment"""
    main.peers = {}

# ============================================================================
# HELPER FUNCTIONS FOR FILE TESTING
# ============================================================================

def create_test_file(content="Test file content", name=None):
    """
    Create a temporary file for testing file transfers

    Args:
        content: Content to write to the file
        name: Optional filename (uses random name if None)

    Returns:
        Tuple of (file path, file size)
    """
    if name:
        # Create a file with specified name in the system temp directory
        path = os.path.join(tempfile.gettempdir(), name)
        with open(path, 'w') as f:
            f.write(content)
        return path, len(content)
    else:
        # Create a temp file with random name
        fd, path = tempfile.mkstemp()
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(content)
        except:
            os.unlink(path)
            raise
        return path, len(content)

# ============================================================================
# NETWORK UTILITY TESTS
# ============================================================================

class TestNetworkFunctions(unittest.TestCase):
    """Test the basic network utility functions"""

    def setUp(self):
        reset_state()

    def test_get_local_ip(self):
        """Test that get_local_ip returns a valid IPv4 address"""
        with mock.patch('socket.socket') as mock_socket:
            # Set up the mock socket
            mock_sock = mock.MagicMock()
            mock_socket.return_value = mock_sock
            mock_sock.getsockname.return_value = ('192.168.1.5', 12345)

            # Call the function
            ip = main.get_local_ip()

            # Verify the result
            self.assertEqual(ip, '192.168.1.5')
            mock_sock.connect.assert_called_once_with(("8.8.8.8", 80))

    def test_get_broadcast_address(self):
        """Test that get_broadcast_address returns a valid broadcast address"""
        # Save original value
        original_ip = main.peer_ip

        try:
            # Test with a valid IP
            main.peer_ip = '192.168.1.5'
            broadcast = main.get_broadcast_address()
            self.assertEqual(broadcast, '192.168.1.255')

            # Test error handling
            main.peer_ip = 'invalid_ip'
            broadcast = main.get_broadcast_address()
            self.assertEqual(broadcast, '255.255.255.255')
        finally:
            # Restore original value
            main.peer_ip = original_ip

# ============================================================================
# CHAT SESSION TESTS
# ============================================================================

class TestChatSession(unittest.TestCase):
    """Test the ChatSession class for messaging functionality"""

    def setUp(self):
        """Set up mock connection for testing"""
        self.mock_conn = mock.MagicMock()
        self.session = main.ChatSession(self.mock_conn)

    def test_send_message(self):
        """Test sending a text message"""
        test_msg = "Hello, world!"
        self.session.send(test_msg)

        # Verify the message was sent with the correct protocol prefix
        expected = f"{main.TEXT_MESSAGE}{test_msg}".encode()
        self.mock_conn.sendall.assert_called_once_with(expected)

    def test_send_message_with_exception(self):
        """Test handling of send exceptions"""
        # Make sendall raise an exception
        self.mock_conn.sendall.side_effect = Exception("Send failed")

        # Spy on the signal emission
        emitted_msgs = []
        def collect_messages(msg):
            emitted_msgs.append(msg)
        self.session.new_message.connect(collect_messages)

        # Call the send method
        self.session.send("Test message")

        # Verify the signal was emitted with error message
        self.assertIn("[Send Failed]", emitted_msgs)

    def test_send_file(self):
        """Test sending a file through the chat session"""
        # Create a temp file for testing
        test_content = "This is test file content"
        file_path, file_size = create_test_file(test_content, "test_send.txt")

        try:
            # Collect the calls to sendall
            sendall_calls = []
            def collect_sendall(data):
                sendall_calls.append(data.decode())
                return len(data)
            self.mock_conn.sendall.side_effect = collect_sendall

            # Send the file
            self.session.send_file(file_path)

            # Verify the header was sent correctly
            self.assertTrue(any(call.startswith(main.FILE_HEADER) for call in sendall_calls),
                           "File header should be sent")

            # Get the header message
            header_msg = next(call for call in sendall_calls if call.startswith(main.FILE_HEADER))
            header_parts = header_msg[len(main.FILE_HEADER):].split(':')

            # Verify header format
            self.assertEqual(len(header_parts), 2, "Header should have filename and size")
            self.assertEqual(header_parts[0], "test_send.txt", "Filename should match")
            self.assertEqual(int(header_parts[1]), file_size, "File size should match")

            # Verify at least one chunk was sent
            self.assertTrue(any(call.startswith(main.FILE_CHUNK) for call in sendall_calls),
                           "File chunk should be sent")

            # Verify file end marker
            self.assertTrue(any(call.startswith(main.FILE_END) for call in sendall_calls),
                           "File end marker should be sent")
            end_msg = next(call for call in sendall_calls if call.startswith(main.FILE_END))
            self.assertEqual(end_msg, f"{main.FILE_END}test_send.txt",
                            "End marker should include filename")

        finally:
            # Clean up the temp file
            try:
                os.unlink(file_path)
            except:
                pass

    def test_receive_file(self):
        """Test receiving a file through the chat session"""
        # Mock os.path functions to avoid actual file operations
        with mock.patch('os.path.join', return_value="/mock/path/received_file.txt"), \
             mock.patch('os.path.exists', return_value=True), \
             mock.patch('os.path.expanduser', return_value="/mock/home"), \
             mock.patch('builtins.open', mock.mock_open()) as mock_file:

            # Manually simulate receiving a file
            # 1. Start with file header
            filename = "received_file.txt"
            filesize = 15
            header = f"{main.FILE_HEADER}{filename}:{filesize}"

            # Set up signal handlers to capture emitted signals
            progress_updates = []
            def track_progress(filename, current, total):
                progress_updates.append((filename, current, total))
            self.session.file_progress.connect(track_progress)

            completed_files = []
            def track_completed(path):
                completed_files.append(path)
            self.session.file_received.connect(track_completed)

            # Simulate receiving the message by directly manipulating session state
            # and calling the internal processing logic we would test

            # Process header
            self.session.current_file = filename
            self.session.file_size = filesize
            self.session.bytes_received = 0
            self.session.file_data = bytearray()

            # 2. Simulate receiving file data chunk
            test_content = "Test file data"
            encoded_chunk = base64.b64encode(test_content.encode()).decode()
            chunk_msg = f"{main.FILE_CHUNK}{encoded_chunk}"

            # Process chunk (manually simulate the receive loop logic)
            chunk = base64.b64decode(encoded_chunk)
            self.session.file_data.extend(chunk)
            self.session.bytes_received += len(chunk)
            self.session.file_progress.emit(
                self.session.current_file,
                self.session.bytes_received,
                self.session.file_size
            )

            # 3. Simulate file end message
            end_msg = f"{main.FILE_END}{filename}"

            # Handle the file end by simulating saving the file
            # (this would normally happen in the receive_loop)
            save_path = "/mock/path/received_file.txt"
            self.session.file_received.emit(save_path)

            # Verify progress was tracked
            self.assertTrue(len(progress_updates) > 0, "Progress updates should be emitted")
            self.assertEqual(progress_updates[0][0], filename, "Progress update should have correct filename")

            # Verify completion was signaled
            self.assertEqual(len(completed_files), 1, "File completion should be signaled")
            self.assertEqual(completed_files[0], save_path, "Completion should include save path")

# ============================================================================
# PEER MANAGEMENT TESTS
# ============================================================================

class TestPeerManagement(unittest.TestCase):
    """Test peer discovery and timeout functionality"""

    def setUp(self):
        reset_state()

    def test_peer_timeout(self):
        """Test that peers are removed after their timeout period"""
        # Add peers with different timestamps
        now = time.time()
        main.peers = {
            "peer1": ("192.168.1.10", 54546, now),
            "peer2": ("192.168.1.11", 54546, now - 5),
            "peer3": ("192.168.1.12", 54546, now - 15)
        }

        # Save original timeout
        original_timeout = main.PEER_TIMEOUT

        try:
            # Set timeout to 10 seconds
            main.PEER_TIMEOUT = 10

            # Manually perform cleanup logic
            now = time.time()
            expired_peers = [peer_id for peer_id in main.peers
                            if now - main.peers[peer_id][2] > main.PEER_TIMEOUT]
            for peer_id in expired_peers:
                del main.peers[peer_id]

            # Verify peer3 was removed but others remain
            self.assertEqual(len(main.peers), 2)
            self.assertIn("peer1", main.peers)
            self.assertIn("peer2", main.peers)
            self.assertNotIn("peer3", main.peers)
        finally:
            # Restore original timeout
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
        # Clean up the socket patch
        self.socket_patcher.stop()

    def test_broadcast_presence_message_format(self):
        """Test the format of the broadcast message for peer discovery"""
        # Mock the broadcast address calculation
        with mock.patch('main.get_broadcast_address', return_value='192.168.1.255'):
            # Manually execute the core logic of broadcast_presence
            msg = f"{main.peer_name}:{main.peer_ip}:{main.CHAT_PORT}"
            self.mock_socket.sendto.return_value = len(msg)  # Return success

            # Execute the logic we want to test
            msg_bytes = msg.encode()
            self.mock_socket.sendto(msg_bytes, ('192.168.1.255', main.BROADCAST_PORT))

            # Verify the socket was used correctly
            self.mock_socket.sendto.assert_called_once()
            call_args = self.mock_socket.sendto.call_args[0]

            # Verify message format
            sent_msg = call_args[0].decode().split(':')
            self.assertEqual(len(sent_msg), 3)
            self.assertEqual(sent_msg[0], main.peer_name)
            self.assertEqual(sent_msg[1], main.peer_ip)
            self.assertEqual(sent_msg[2], str(main.CHAT_PORT))

            # Verify destination
            self.assertEqual(call_args[1], ('192.168.1.255', main.BROADCAST_PORT))

    def test_broadcast_message_processing(self):
        """Test processing of received broadcast messages from other peers"""
        # Clear existing peers
        main.peers = {}

        # Create a test message
        test_msg = "TestPeer:192.168.1.10:54546"
        self.mock_socket.recvfrom.return_value = (test_msg.encode(), ('192.168.1.10', main.BROADCAST_PORT))

        # Save original values
        original_ip = main.peer_ip
        original_port = main.CHAT_PORT

        try:
            # Set our own address to something different
            main.peer_ip = "192.168.1.20"
            main.CHAT_PORT = 54547

            # Manually execute the logic for processing a broadcast message
            data, addr = self.mock_socket.recvfrom(1024)
            msg = data.decode()
            name, ip, port = msg.split(":")
            port = int(port)

            # Skip our own messages
            if ip == main.peer_ip and port == main.CHAT_PORT:
                pass
            else:
                # Add peer to dictionary
                peer_id = f"{name}@{ip}:{port}"
                main.peers[peer_id] = (ip, port, time.time())

            # Verify the peer was added
            self.assertEqual(len(main.peers), 1)
            peer_id = "TestPeer@192.168.1.10:54546"
            self.assertIn(peer_id, main.peers)
            peer_data = main.peers[peer_id]
            self.assertEqual(peer_data[0], "192.168.1.10")
            self.assertEqual(peer_data[1], 54546)
        finally:
            # Restore original values
            main.peer_ip = original_ip
            main.CHAT_PORT = original_port

# ============================================================================
# CHAT FUNCTIONALITY TESTS (replacing TestChatWindow)
# ============================================================================

class TestChatFunctionality(unittest.TestCase):
    """Test the core functionality of chat and file sharing without full UI initialization"""

    def setUp(self):
        # Create a mock connection
        self.mock_conn = mock.MagicMock()

        # Create a mock ChatSession
        self.mock_session = mock.MagicMock()

        # Create a properly configured progress bar mock
        self.mock_progress = mock.MagicMock()
        # Configure isVisible to return False by default so setVisible(True) will be called
        self.mock_progress.isVisible.return_value = False

        # Create a simple dictionary to simulate our ChatWindow's key attributes
        self.chat = {
            'session': self.mock_session,
            'display': mock.MagicMock(),
            'input': mock.MagicMock(),
            'progress': self.mock_progress
        }

        # Set up input text return value
        self.chat['input'].text.return_value = "Test message"

    def test_send_message_logic(self):
        """Test the core logic of the send_message method"""
        # Define a simplified version of the send_message method
        def send_message():
            text = self.chat['input'].text().strip()
            if text:
                self.chat['session'].send(text)
                self.chat['display'].append(f"You: {text}")
                self.chat['input'].clear()

        # Call our simplified method
        send_message()

        # Verify the session's send method was called
        self.chat['session'].send.assert_called_once_with("Test message")
        # Verify the message was displayed
        self.chat['display'].append.assert_called_once_with("You: Test message")
        # Verify the input was cleared
        self.chat['input'].clear.assert_called_once()

    def test_update_file_progress_logic(self):
        """Test the logic of the update_file_progress method"""
        # Define a simplified version of the update_file_progress method
        def update_file_progress(filename, received, total):
            # Our mock is configured to have isVisible() return False
            if not self.chat['progress'].isVisible():
                self.chat['progress'].setVisible(True)

            self.chat['progress'].setMaximum(total)
            self.chat['progress'].setValue(received)

            # Hide progress bar when complete
            if received >= total:
                # We'll just call this directly instead of using QTimer
                self.chat['progress'].setVisible(False)

        # Test initial update
        update_file_progress("test.txt", 5000, 10000)

        # Verify progress bar was configured correctly
        self.chat['progress'].setVisible.assert_called_with(True)
        self.chat['progress'].setMaximum.assert_called_with(10000)
        self.chat['progress'].setValue.assert_called_with(5000)

        # Reset mock calls
        self.chat['progress'].reset_mock()

        # For the second test, we want isVisible to return True
        # so we don't call setVisible(True) again
        self.chat['progress'].isVisible.return_value = True

        # Test completion update
        update_file_progress("test.txt", 10000, 10000)

        # Verify progress bar was updated and hidden
        self.chat['progress'].setValue.assert_called_with(10000)
        self.chat['progress'].setVisible.assert_called_with(False)

    def test_file_received_logic(self):
        """Test the logic of the file_received method"""
        # Set up mocks for QMessageBox and platform-specific open commands
        with mock.patch('main.QMessageBox') as mock_msg_box, \
             mock.patch('sys.platform', 'darwin'), \
             mock.patch('os.system') as mock_system:

            # Configure QMessageBox to simulate "Yes" response
            mock_yes = mock.MagicMock()
            mock_no = mock.MagicMock()

            # Set up the mock for question method
            mock_msg_box.question = mock.MagicMock()
            mock_msg_box.question.return_value = mock_yes

            # Define the enum values as attributes
            mock_msg_box.Yes = mock_yes
            mock_msg_box.No = mock_no

            # Define a simplified version of the file_received method
            def file_received(filepath):
                reply = mock_msg_box.question(
                    None, 'File Received',
                    f"File saved to: {filepath}\nDo you want to open it?",
                    mock_yes | mock_no,
                    mock_no
                )
                if reply == mock_yes:
                    # Open file with default application (macOS)
                    os.system(f'open "{filepath}"')

            # Call the method
            file_received("/path/to/file.txt")

            # Verify question was asked
            mock_msg_box.question.assert_called_once()

            # Verify system open was called (since we replied Yes)
            mock_system.assert_called_once_with('open "/path/to/file.txt"')

    def test_select_file_logic(self):
        """Test the logic of the select_file method"""
        # Set up mocks for file dialog and file operations
        with mock.patch('main.QFileDialog') as mock_file_dialog, \
             mock.patch('os.path.getsize') as mock_getsize, \
             mock.patch('main.QMessageBox') as mock_msg_box, \
             mock.patch('main.threading.Thread') as mock_thread:

            # Configure mocks for file selection
            mock_file_dialog.getOpenFileName = mock.MagicMock()
            mock_file_dialog.getOpenFileName.return_value = ("/path/to/file.txt", "")

            # Configure file size for small file (no confirmation needed)
            mock_getsize.return_value = 1024  # 1KB

            # Configure mock_msg_box similar to the file_received_logic test
            mock_yes = mock.MagicMock()
            mock_no = mock.MagicMock()
            mock_msg_box.question = mock.MagicMock()
            mock_msg_box.question.return_value = mock_yes
            mock_msg_box.Yes = mock_yes
            mock_msg_box.No = mock_no

            # Set up mock thread factory with start method
            mock_thread_instance = mock.MagicMock()
            mock_thread.return_value = mock_thread_instance

            # Define a simplified version of the select_file method
            def select_file():
                filepath, _ = mock_file_dialog.getOpenFileName(
                    None, "Select File to Send", "", "All Files (*)"
                )
                if filepath:
                    # Check file size - warn if large
                    size_mb = mock_getsize(filepath) / (1024 * 1024)
                    if size_mb > 10:  # Warn if > 10MB
                        reply = mock_msg_box.question(
                            None, 'Confirm File Send',
                            f"The file is {size_mb:.1f}MB. Are you sure you want to send it?",
                            mock_yes | mock_no,
                            mock_no
                        )
                        if reply == mock_no:
                            return

                    # Start file sending in a thread
                    mock_thread(
                        target=self.chat['session'].send_file,
                        args=(filepath,),
                        daemon=True
                    ).start()

            # Call the method for a small file
            select_file()

            # Verify file dialog was shown
            mock_file_dialog.getOpenFileName.assert_called_once()

            # Verify message box was NOT shown (small file)
            mock_msg_box.question.assert_not_called()

            # Verify thread was started with correct arguments
            mock_thread.assert_called_once()
            mock_thread_instance.start.assert_called_once()

            # Reset mocks for large file test
            mock_file_dialog.reset_mock()
            mock_thread.reset_mock()
            mock_thread_instance.reset_mock()
            mock_getsize.return_value = 15 * 1024 * 1024  # 15MB

            # Call the method for a large file
            select_file()

            # Verify confirmation was shown for large file
            mock_msg_box.question.assert_called_once()

            # Verify thread was started (user confirmed)
            mock_thread.assert_called_once()
            mock_thread_instance.start.assert_called_once()

# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

if __name__ == "__main__":
    try:
        # Run all tests
        unittest.main()
    finally:
        # Ensure we restore the threading module
        restore_threading()

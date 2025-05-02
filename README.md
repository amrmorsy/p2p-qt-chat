# P2P Chat

A lightweight, zero-configuration peer-to-peer messaging and file sharing application for local networks. This serverless Python application automatically discovers other users on your LAN and enables direct messaging and file transfers without requiring any central infrastructure.

## Features

- 🔍 **Automatic peer discovery** on local networks
- 💬 **Direct messaging** between peers
- 📂 **File sharing** with progress tracking
- 🖥️ **Modern Qt-based** user interface
- 🧵 **Multi-threaded** for responsive performance
- 🔌 **Works offline** - no internet required
- 🧩 **Cross-platform** (Windows, macOS, Linux)

## How It Works

- **Peer Discovery**: Uses UDP broadcasting to announce presence and discover peers on the local network
- **Messaging**: Establishes direct TCP connections for reliable message delivery
- **File Transfer**: Sends files in chunks with progress indication and automatic saving
- **UI**: Multi-threaded architecture keeps the interface responsive during network operations

## Technologies

- Python 3.x
- PySide6 (Qt for Python)
- Socket programming (UDP/TCP)
- Multi-threading
- Base64 encoding for binary file transfers

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/p2p-chat.git
cd p2p-chat

# Set up a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install PySide6

# Run the application (optional: specify custom port)
python main.py [port]
```

## Usage

### Starting the Application

Run the application to connect to peers on your local network:

```bash
python main.py
```

You can optionally specify a custom port:

```bash
python main.py 54550
```

### Chatting with Peers

1. All available peers on your network will appear in the main window
2. Select a peer and click "Connect to Peer" to open a chat window
3. Type messages and press Enter to send them

### Sharing Files

1. In an open chat window, click the "Send File" button
2. Select the file you want to share
3. For large files (>10MB), confirm the file transfer
4. The recipient will see progress indication and get notified when the transfer is complete
5. Files are automatically saved to the recipient's Downloads folder

## Protocol Details

The application uses a simple text-based protocol for all communications:

- **Peer Discovery**: `hostname:ip:port` broadcasts over UDP
- **Text Messages**: `MSG:message_content` over TCP
- **File Headers**: `FILE:filename:filesize` over TCP
- **File Chunks**: `CHUNK:base64_encoded_data` over TCP
- **File End**: `FEND:filename` over TCP

## Testing

The application includes a comprehensive test suite covering network operations, messaging, and file sharing:

```bash
# Install test dependencies
pip install pytest pytest-qt

# Run tests
python -m unittest test_main.py

# Run tests with more detailed output
pytest test_main.py -v
```

The test suite includes:
- Network utility tests
- Message protocol tests
- File transfer tests
- Peer management tests
- UI functionality tests

## Future Enhancements

- End-to-end encryption for secure communications
- Group chat functionality
- Custom download locations for received files
- File transfer pause/resume capabilities
- Voice and video chat integration

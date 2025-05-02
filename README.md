# P2P Chat

A lightweight, zero-configuration peer-to-peer messaging application for local networks. This serverless Python application automatically discovers other users on your LAN and enables direct messaging without requiring any central infrastructure.

## Features

- 🔍 Automatic peer discovery on local networks
- 💬 Direct messaging between peers
- 🖥️ Modern Qt-based user interface
- 🧵 Multi-threaded for responsive performance
- 🔌 Works offline - no internet required
- 🧩 Cross-platform (Windows, macOS, Linux)

## Technologies

- Python 3.x
- PySide6 (Qt for Python)
- Socket programming (UDP/TCP)
- Multi-threading

## Quick Start

```bash
# Clone the repository
git clone https://github.com/yourusername/p2p-chat.git
cd p2p-chat

# Set up a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application (optional: specify custom port)
python main.py [port]
```

## How It Works

The application uses UDP broadcasting to announce presence and discover peers on the local network. When a connection is established, messages are sent directly between peers over TCP sockets. The multi-threaded architecture keeps the UI responsive while handling network operations in the background.

## Testing

```bash
# Run the test suite
python -m unittest test_main_stable.py
```

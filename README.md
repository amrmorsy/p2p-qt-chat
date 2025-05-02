# P2P Chat Application with PySide6 on the Local Network

A peer-to-peer (P2P) chat application using Python and PySide6 (Qt) for the GUI. The application allows users on the same local network to discover each other and establish direct chat connections.

## Key Components:

### 1. Network Discovery
- **Broadcasting Presence**: Every 2 seconds, the application broadcasts UDP packets containing the peer's name, IP address, and listening port to all devices on the local network.
- **Listening for Peers**: A separate thread continuously listens for similar broadcast messages from other peers running the same application.
- **Peer Management**: Discovered peers are stored in a dictionary with their connection details. Peers that haven't been seen for 10 seconds are removed.
- **Broadcast Address Calculation**: The application intelligently calculates the broadcast address based on the local IP address to ensure proper network coverage.

### 2. User Interface
- **Main Window**: Displays a list of available peers on the network.
- **Peer List**: Shows all currently discovered peers with a "Connect" button to initiate a chat.
- **Auto-Refresh**: The peer list refreshes automatically every 3 seconds.
- **Dynamic Port Assignment**: Supports custom port configuration via command-line arguments.

### 3. Chat Functionality
- **Connection Handling**: When a user clicks "Connect" for a peer, a TCP connection is established directly to that peer.
- **Chat Windows**: Each chat session opens in a separate window with a text area for message history and an input field.
- **Incoming Connections**: The application listens for incoming TCP connections on a designated port and creates a new chat window for each one.
- **Signal-Based Communication**: Uses Qt's signal/slot mechanism to safely update the UI from background threads.

### 4. Multithreading
- The application uses multiple threads to simultaneously:
  - Broadcast its presence
  - Listen for other peers' broadcasts
  - Clean up inactive peers
  - Listen for incoming chat connections
  - Send and receive chat messages in each active conversation



## Installation

#### Option 1: Using `uv` (recommended)
If you have `uv` installed, you can quickly set up the project:

```bash
# Install dependencies from pyproject.toml
uv pip install -e .
```

#### Option 2: Using pip with requirements.txt
```bash
# Create a virtual environment (optional but recommended)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Running the Application

Start the application with:
```bash
python main.py
```

For a custom chat port (default is 54546):
```bash
python main.py 54547
```

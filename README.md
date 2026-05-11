# MMT_Assignment1 - AsynapRous HTTP Server & Hybrid Chat Application

## 1. Overview
This is a Computer Networking project (CO3093/CO3094) that implements **AsynapRous**, a custom non-blocking HTTP server framework, along with a Hybrid Chat Application that utilizes both Client-Server and Peer-to-Peer (P2P) architectures.

### Core Features:
- **Custom Networking Framework:** Built entirely from scratch without external libraries like Flask or FastAPI. It implements an I/O Multiplexing mechanism using a custom Event Loop and the `select()` system call, delivering high performance with ultra-low latency.
- **Authentication & Session Management:** Supports user login and session management using Cookies (RFC 6265) and Basic Authentication (RFC 7235).
- **Hybrid P2P Chat:** A decentralized architecture where a central Tracker Server manages the active IP directory, while chat messages are transmitted directly between Peers (Fire-and-Forget P2P messaging) without routing through the Tracker.
- **Benchmarking:** Includes a heavy-load simulation tool (up to thousands of concurrent connections) to benchmark and identify the saturation points of Threading, Callback, and Asyncio models.

---

## 2. System Requirements
The source code strictly complies with **PEP 8** and **PEP 257** standards.
- **Required Environment:** Python 3.8 or higher.
- **Graphing Library for Benchmark (Optional):** 
  ```bash
  pip install matplotlib
  ```

---

## 3. How to Run the Hybrid Chat Application

To simulate a distributed network environment with multiple concurrent users, you need to open multiple command prompt (Terminal/PowerShell) windows. 
*Note: If you encounter `PermissionError: [WinError 10013]`, it means the default port is currently occupied by another background process on Windows. Simply change the port numbers in the commands below.*

### Step 1: Start the Central Tracker Server
The Tracker Server receives registrations and maintains the list of active network nodes (Peers). Open Terminal 1 and run:
```bash
python start_tracker.py --server-ip 0.0.0.0 --server-port 9090
```
> The Tracker Server will now listen at `127.0.0.1:9090`. (We changed it to 9090 to avoid the WinError 10013 conflict on your port 9000).

### Step 2: Start the Peer Clients (Chat Nodes)
Start 2 client nodes so they can chat with each other. Open 2 new Terminal windows.

**In Terminal 2 (Start Client 1 on port 8001):**
```bash
python start_chatapp.py --server-port 8001 --tracker-ip 127.0.0.1 --tracker-port 9090
```

**In Terminal 3 (Start Client 2 on port 8002):**
```bash
python start_chatapp.py --server-port 8002 --tracker-ip 127.0.0.1 --tracker-port 9090
```
> These Clients will automatically link to the Tracker Server running at port 9090. *(Make sure the `--tracker-port` always matches the port you chose in Step 1).*

### Step 3: Login and Chat via Web Browser
- Open your web browser (Incognito/Private mode is highly recommended to prevent cookie caching conflicts between 2 clients on the same machine).
- Access Client 1 at: **`http://127.0.0.1:8001/`**
- Access Client 2 at: **`http://localhost:8002/`**
- **Accounts:** You can use the pre-configured accounts located in the `db/account.txt` file (Format: `username:password`). Some available accounts are:
  - Username: `admin` | Password: `123456`
  - Username: `tai` | Password: `36363`
  - Username: `hoang` | Password: `11111`
- Log in using the HTML interface. The system will set an authentication Cookie and redirect you to the chat room. Your messages will be transmitted P2P directly from port 8001 to 8002 and vice versa!

---

## 4. Benchmarking Guide
To view detailed instructions on how to benchmark the raw network I/O performance of the system, please refer to the markdown file: **`benchmark.md`**.

**Quick Run Guide:**
```bash
# Start one of the Raw Servers (e.g., Callback mode)
python raw_benchmark_server.py --port 9020 --mode callback

# Generate heavy load (e.g., 6000 concurrent requests)
python benchmark_all.py -n 6000 --step 200

# Plot and export the benchmark chart from the CSV file
python plot_benchmark.py
```

---

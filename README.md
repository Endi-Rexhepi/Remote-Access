# Remote Access

A remote desktop tool I built in Python. One PC shares its screen, the other PC sees it and controls it with its own mouse and keyboard.

I built it to learn how remote desktop tools work under the hood: raw TCP sockets, my own message format, TLS, password authentication, brute-force protection and safe input handling. The whole networking part is written from scratch on top of Python's standard `socket` and `ssl` modules.

> **Status:** Windows only. Works on LAN. Over the internet it works with port forwarding; so far I tested that part on a simulated connection, see [LAN and WAN](#5-lan-and-wan).
>
> **Use it responsibly.** Only connect to computers you own or where the owner has agreed. This tool gives full control of the shared PC.

---

## Architecture

The project has two sides:

| Side | Runs on | What it does |
|---|---|---|
| **Server** (`server.py`) | the PC that is **shared** | captures the screen and sends it, receives mouse and keyboard events and performs them |
| **Client** (`client.py`) | the PC that **controls** | shows the remote screen in fullscreen, captures your mouse and keyboard and sends them |

### Connection flow

Every connection goes through the same steps, in this order. Nothing about the screen or the input is sent before the last step.

1. **TCP connect:** the client connects to the server.
2. **TLS handshake:** the connection gets encrypted. The client only trusts `server.crt`.
3. **Password:** the client sends the password inside TLS. The server first checks if the IP is blocked, then checks the password against the argon2 hash.
4. **Consent** (only if `REQUIRE_CONSENT = True`): the person at the shared PC gets an Allow / Deny popup for 30 seconds.
5. **Status:** the server answers with one number: 0 wrong password, 1 OK, 2 blocked, 3 denied. Anything other than 1 ends the connection.
6. **Resolution:** the client sends its screen size, so the server can map mouse positions correctly.
7. **Session:** the server sends screen frames, the client sends mouse and keyboard events.

The network part of the handshake (TLS, password, resolution) has a **5 second deadline**. A client that connects and stays silent gets dropped, so it can't block the server.

### During a session

**Server:** two threads share the connection.
- **Screen thread:** captures the screen, draws a circle where the mouse is, scales it down (`FRAME_SCALE`), encodes it as JPEG (`JPEG_QUALITY`) and sends it. Then it waits `FRAME_INTERVAL` seconds.
- **Input thread:** receives events, checks them and performs them with `pynput`.
- The **main thread** shows the "being controlled" window and waits until both threads finish. Then it releases any keys or mouse buttons that are still held down and closes the connection.

**Client:** one loop. It receives a frame, shows it in fullscreen, then sends the latest mouse position and one queued input event. Two `pynput` listeners capture the mouse and keyboard in the background. They only start **after** the server accepted the password.

### Message format

Every message is a **4-byte length** (big-endian) followed by the data. The receiver always reads the exact number of bytes, and checks the length against a limit before reading anything.

| Event type | Meaning | Data |
|---|---|---|
| 1 | mouse move | x, y |
| 2 | mouse button | x, y, button, pressed |
| 3 | scroll | x, y, dx, dy |
| 4 | special key (Shift, Enter, F5...) | pressed + key name, e.g. `Key.shift` |
| 5 | normal key | pressed + Windows virtual key code |

Normal keys are sent as **key codes**, not characters. That way shortcuts like Ctrl+C or Ctrl+V reach the shared PC as real key presses and work in every app.

Mouse buttons: 1 left, 2 right, 3 back (x1), 4 forward (x2), 5 middle.

### Files

| File | What it is |
|---|---|
| `server.py` | the server, runs on the shared PC |
| `client.py` | the client, runs on the controlling PC |
| `setup_password.py` | sets the server password (creates `server.pass`) |
| `keep_awake.py` | optional helper that stops the shared PC from going to sleep |
| `server.crt` / `server.key` | TLS certificate and private key, **you generate them** (not in the repo) |
| `server.pass` | the password hash, created by `setup_password.py` (not in the repo) |
| `server.log` | the server's log file, created when the server runs (not in the repo) |

---

## Security

Whoever controls the keyboard controls the computer. So I treated security as the main part of the project, not an extra. Before writing the fixes, I wrote down who could attack and what I protect, then fixed things step by step.

**What I protect:**
1. **Control** of the shared PC (mouse and keyboard)
2. **Privacy** of the screen and of what you type
3. **Availability:** the session can't be blocked or crashed

**Who I protect against:** someone on the same network (home, university or café Wi-Fi), bots that scan the internet for open ports, anyone in the middle of the connection, and a fake server pretending to be mine.

### What is in place

| Protection | How |
|---|---|
| **Encryption** | Everything goes through **TLS** (Python's `ssl` module). Nobody on the network can read the screen or the keystrokes. |
| **Server identity** | The client only trusts **my** certificate (`server.crt`) and checks its name (`SERVER_HOSTNAME`). A fake server can't get the password or the keystrokes. |
| **Password** | Stored only as an **argon2** hash in `server.pass`, never as plain text. It is sent only inside TLS. On startup, the server checks that `server.pass` is a valid hash. |
| **Brute-force protection** | After **3 wrong passwords**, an IP address is blocked until the server restarts. A blocked IP is refused **before** its password is even checked, so even the right password doesn't get it in. |
| **Consent** | With `REQUIRE_CONSENT = True`, the person at the shared PC has to click **Allow**. Deny, closing the popup or no answer within 30 seconds means no access. |
| **"Being controlled" window** | During a session, an always-on-top window shows who is in control, with a **Stop Remote Access** button. |
| **Kill switch** | **Ctrl+Alt+Q** on the shared PC (or the Stop button) ends the session and stops the server. |
| **Input validation** | Every message has a size limit. Event types, buttons, key names (allowlist), key codes (1 to 254), coordinates and scrolling are checked. Anything invalid ends the session. |
| **Timeouts** | 5 seconds for the handshake, so a silent client can't block the server. |
| **No stuck keys** | When a session ends, the server releases every key and mouse button that is still held down. |
| **Logging** | `server.log` records connections, wrong passwords, blocked IPs, denied connections and errors, with date and time. Passwords and keystrokes are **never** logged. |
| **Secrets stay local** | `server.key`, `server.pass` and `server.log` are in `.gitignore`. |

### Certificate and key

TLS needs a certificate (`server.crt`) and a private key (`server.key`). I use a **self-signed** certificate: there's no certificate authority, the client simply trusts exactly this one certificate. That's called **certificate pinning**.

They are generated with OpenSSL:

```bash
openssl req -x509 -newkey rsa:2048 -nodes -keyout server.key -out server.crt -days 365
```

- `server.key` is the **private key**. It never leaves the shared PC.
- `server.crt` is the **certificate**. Only this file is copied to the client PC.
- `-days 365`: the certificate is valid for **one year**. After that, both sides refuse to connect and you generate a new pair.

The exact steps are in [How to use](#how-to-use).

---

## How to use

### 1. Requirements

On **both** PCs:
- **Windows 10 or 11**
- **Python 3.10 or newer** (from [python.org](https://www.python.org/downloads/), with tkinter, which is included by default)
- the Python packages:
  ```bash
  pip install -r requirements.txt
  ```

On the **shared PC** you also need **OpenSSL**, once, to create the certificate. It comes with [Git for Windows](https://git-scm.com/download/win): run the command in **Git Bash**.

### 2. Set up the shared PC (server)

1. **Get the code** into a folder, e.g. with `git clone`.
2. **Set the password:**
   ```bash
   python setup_password.py
   ```
   Type it twice. It must be **8 to 40 characters**. This creates `server.pass`.
3. **Create the certificate and key** in the same folder (in Git Bash):
   ```bash
   openssl req -x509 -newkey rsa:2048 -nodes -keyout server.key -out server.crt -days 365
   ```
   OpenSSL asks a few questions. You can skip them with Enter, **except Common Name**: it must be the same as `SERVER_HOSTNAME` in `client.py` (default: `end`).
   To skip the questions completely, add `-subj "/CN=end"` at the end of the command.
4. **Check the settings** in `server.py` (see [Configuration](#configuration)).
5. **Start the server:**
   ```bash
   python server.py
   ```
   The first time, Windows Firewall asks whether Python may accept connections. Allow it.

### 3. Set up the controlling PC (client)

1. **Get the code** into a folder.
2. **Copy `server.crt`** from the shared PC into the same folder as `client.py`. Only this file. **Never copy `server.key`.**
3. **Edit the top of `client.py`:**
   ```python
   SERVER_IP = '192.168.1.20'   # the shared PC's IP address
   PORT = 12345                 # same as in server.py
   SERVER_HOSTNAME = 'end'      # the Common Name of server.crt
   ```
   On the shared PC, `ipconfig` shows its IP address ("IPv4 Address").
4. **Connect:**
   ```bash
   python client.py
   ```
   Type the password. If it's right (and the person at the shared PC clicks **Allow**, when consent is on), the remote screen opens in fullscreen.

### 4. During a session

- On the **client**, your mouse and keyboard control the shared PC.
- On the **shared PC**, a red window shows who is in control.
- **To end the session from the shared PC:** click **Stop Remote Access** or press **Ctrl+Alt+Q**. This also **stops the server**. Start it again for the next session.
- **To end the session from the client:** switch to the terminal (Alt+Tab) and press **Ctrl+C**. The server keeps running and waits for the next connection.
- The shared PC's log is in `server.log`, next to `server.py`.

### 5. LAN and WAN

**LAN (same network):** use the shared PC's local IP as `SERVER_IP`, like `192.168.x.x`. Nothing else needed.

**WAN (over the internet):** the client connects to the **public IP** of the shared PC's router.
1. **Check that you have a real public IP.** Compare the WAN IP in your router with the IP shown on a "what is my IP" website. If they are different, your provider uses **CGNAT** and port forwarding won't work. Mobile hotspots almost always use CGNAT, so the shared PC can't be reached through one (the client can use a hotspot without problems).
2. **Forward one port** in the router: `PORT` (default 12345) to the shared PC's local IP. Only this port, and only while you need it.
3. Set `SERVER_IP` in the client to the **public IP**. **Don't commit your public IP** to GitHub.
4. **Adjust the frames to the upload speed** of the shared PC's internet (run a speed test there). The upload is the limit, because the screen goes from the shared PC to you.

| Upload speed of the shared PC | Suggested settings in `server.py` |
|---|---|
| 50 Mbit/s or more | `FRAME_SCALE = 1.0`, `JPEG_QUALITY = 85` |
| about 20 Mbit/s (default) | `FRAME_SCALE = 0.75`, `JPEG_QUALITY = 70` |
| 10 Mbit/s or less | `FRAME_SCALE = 0.5`, `JPEG_QUALITY = 60`, `FRAME_INTERVAL = 0.1` |

These numbers come from a test with a simulated home connection and a text-heavy 1920×1080 desktop. With full size and quality 95, a frame was about 550 KB: fine on LAN, but on a 20 Mbit/s upload the picture arrived 0.4 seconds late at only 4 frames per second. With the default settings (0.75, quality 70) a frame is about 150 KB, text stays readable, and the same connection gives about 16 frames per second.

### keep_awake.py (optional)

If the shared PC goes to sleep, nobody can connect. `keep_awake.py` moves the mouse by one pixel and back when it hasn't moved for 20 seconds, for up to 15 days:

```bash
python keep_awake.py
```

Keep in mind the tradeoff: the PC then **never locks itself**. Anyone who is physically at that PC can use it.

---

## Configuration

All settings are constants in the code.

**`client.py`** (at the top)

| Setting | Default | Meaning |
|---|---|---|
| `SERVER_IP` | `'172.20.10.10'` | IP address of the shared PC (change this) |
| `PORT` | `12345` | must match the server |
| `SERVER_HOSTNAME` | `'end'` | must match the certificate's Common Name |

**`server.py`**

| Setting | Default | Meaning |
|---|---|---|
| `PORT` | `12345` | port the server listens on |
| `REQUIRE_CONSENT` | `True` | ask the person at the shared PC before every session. Set to `False` to reach your own PC when nobody is there. |
| `CONSENT_TIMEOUT` | `30` | seconds before an unanswered consent popup counts as Deny |
| `MAX_PASS_ATTEMPTS` | `3` | wrong passwords before an IP is blocked |
| `HANDSHAKE_TIMEOUT` | `5` | seconds a client has for the network part of the handshake |
| `FRAME_SCALE` | `0.75` | frame size: `1.0` is full size, `0.5` is half |
| `JPEG_QUALITY` | `70` | 0 to 100: lower means smaller frames but blurrier text |
| `FRAME_INTERVAL` | `0.03` | seconds between frames: higher means fewer frames per second |

---

## Known limitations

- **Windows only.** Some input parts (like the mouse side buttons and the "being controlled" window style) are Windows-specific.
- **The client captures input globally.** During a session, everything you type or click on the controlling PC is sent, even in other windows. **Don't type in other apps while a session is running.** This will be fixed with the UI (see [Future work](#future-work)).
- **One client at a time.** While a session is running, nobody else can connect.
- **The remote user can stop the server too.** The "being controlled" window is part of the screen they see, and Ctrl+Alt+Q pressed on the client is also sent to the shared PC.
- **IP blocking has limits.** Several people behind one router share one IP. Someone with many IPs gets 3 tries per IP. The block list is cleared when the server restarts. A strong password matters.
- **Same keyboard layout.** Keys are sent as key codes, so both PCs should use the same keyboard layout (for example both German or both US).
- **The certificate expires after one year** (with `-days 365`).
- **Slow uploads mean lag.** See the table in [LAN and WAN](#5-lan-and-wan).

---

## Troubleshooting

| What you see | What it means / what to do |
|---|---|
| `Connection failed: timed out` | Wrong `SERVER_IP` or `PORT`, the server isn't running, the firewall blocks it, or (WAN) port forwarding is missing or there's CGNAT. |
| `Connection failed: [WinError 10061] ... actively refused it` | The PC was reached, but nothing listens on that port: the server isn't running, or `PORT` is different on the two sides. |
| `... certificate verify failed: self-signed certificate` | The client's `server.crt` is not the one the server uses. Copy the current `server.crt` from the shared PC again. |
| `... certificate verify failed: Hostname mismatch` | The certificate's Common Name and `SERVER_HOSTNAME` in `client.py` are different. |
| `... certificate verify failed: certificate has expired` | Generate a new key and certificate and copy the new `server.crt` to the client. |
| `The password is incorrect!` | Wrong password. After 3 wrong ones, the IP is blocked. |
| `Too many failed attempts. You are blocked from this server.` | The IP is blocked until the server restarts. |
| `The person at the remote PC denied the connection.` | The person clicked Deny, closed the popup, or didn't answer within 30 seconds. |
| Server: `Please run the setup_password.py script ...` | `server.pass` is missing. Run `python setup_password.py`. |
| Server: `The private key and the certificate are not found ...` | Generate `server.key` and `server.crt` (see [step 2](#2-set-up-the-shared-pc-server)). |
| The picture lags or is choppy | Lower `FRAME_SCALE` / `JPEG_QUALITY` or raise `FRAME_INTERVAL` (see [LAN and WAN](#5-lan-and-wan)). |

---

## Future work

- **A simple UI:** fields for password, IP and port, the remote screen in a normal window, and an "end session" button.
- **Input only from the remote window.** With the UI, the client will read the keyboard and mouse from its own window instead of capturing them globally.
- **One executable** that asks "Share this PC" or "Connect to a PC", and creates the password and certificate on the first run.
- **Frame pacing:** the client confirms each frame, so the server never sends more than the connection can carry. This keeps the delay low on any connection.
- **macOS support.**

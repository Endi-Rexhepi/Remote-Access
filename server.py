import socket 
from PIL import ImageGrab, ImageDraw
import pyautogui
import cv2
import numpy as np
import struct
from pynput import mouse, keyboard
import threading
import time
import ssl
from pathlib import Path
import sys
from argon2 import PasswordHasher
import argon2
import logging
from tkinter import *

server_width, server_height = pyautogui.size()
RESOLUTION_SIZE = struct.calcsize(">II")
MIN_EVENT_SIZE = struct.calcsize('>II') + 1
MAX_EVENT_SIZE = 64
MAX_RESOLUTION = 16384
ALLOWED_KEYS = {k.name : k for k in keyboard.Key}
HANDSHAKE_TIMEOUT = 5
PASS_FILE = Path(__file__).parent / "server.pass"
CERT_FILE = Path(__file__).parent / "server.crt"
KEY_FILE = Path(__file__).parent / "server.key"
SERVER_LOG = Path(__file__).parent / "server.log"
MIN_PASSWORD_BYTES = 8
MAX_PASSWORD_BYTES = 160
STATUS_SUCCESS = 1
STATUS_FAILURE = 0
STATUS_BLOCKED = 2
STATUS_DENIED = 3
MAX_PASS_ATTEMPTS = 3
REQUIRE_CONSENT = True
CONSENT_TIMEOUT = 30

logging.basicConfig(handlers=[logging.FileHandler(SERVER_LOG, encoding="utf-8"), logging.StreamHandler()], format="%(asctime)s [%(levelname)s] %(message)s", level= logging.INFO, datefmt="%d/%m/%Y %H:%M:%S")

def screen_capture():
    img = ImageGrab.grab()
    draw = ImageDraw.Draw(img)
    mouse_pos =  pyautogui.position()
    ax = mouse_pos[0]
    ay = mouse_pos[1]
    bx = mouse_pos[0] + 10
    by = mouse_pos[1] + 10
    draw.ellipse((ax,ay,bx,by))
    img_np = np.array(img)
    img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
    success, jpg = cv2.imencode('.jpg', img_np)
    if success:
        jpg_bytes = jpg.tobytes()
        return jpg_bytes, len(jpg_bytes)
    else:
        logging.error('Failure on capturing the screen')

def recieve_data(no_bytes, deadline= None):
    d = b''
    while len(d) < no_bytes:    
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Handshake took too long")
            conn.settimeout(remaining)
        a = conn.recv(no_bytes - len(d))
        if not a:
            raise ConnectionError("The client has closed the connection")
        d += a
    return d

def kill_switch():
    logging.warning("Kill switch is pressed, closing the server.")
    catch_hotkey.set()
    if conn is not None:
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

def window_consent(ip):
    answer = False

    def consent_allow():
        nonlocal answer
        answer = True
        consent_window.destroy()

    def consent_deny():
        nonlocal answer
        answer = False
        consent_window.destroy()

    consent_window = Tk()
    consent_window.title("Server Window")
    consent_window.configure(bg="#b00020")
    consent_window.after(CONSENT_TIMEOUT * 1000, consent_deny)
    consent_window.protocol("WM_DELETE_WINDOW", consent_deny)
    consent_window.attributes("-topmost", True)

    frame = Frame(consent_window, bg="#b00020", padx=16, pady=12)
    frame.pack(fill="both", expand=True)

    label = Label(frame, text=f"Allow remote control from {ip}?", bg="#b00020", fg="white", font=("Times New Roman", 12, "bold"))
    label.pack(side="top", pady=(0, 10))

    buttons = Frame(frame, bg="#b00020")
    buttons.pack(side="top")

    allow_button = Button(buttons, text="Allow", width=10, command=consent_allow)
    deny_button = Button(buttons, text="Deny", width=10, command=consent_deny)
    allow_button.pack(side="left", padx=6)
    deny_button.pack(side="left", padx=6)

    consent_window.mainloop()

    return answer

def show_indicator(ip, screen_thread, mouse_thread):
    indicator = Tk()       
    indicator.attributes("-topmost", True)
    indicator.attributes("-toolwindow", True)   
    indicator.protocol("WM_DELETE_WINDOW", lambda: None) 
    indicator.title("Remote session active")

    frame = Frame(indicator, bg="#b00020", padx=14, pady=10)
    frame.pack(fill="both", expand=True)

    label = Label(frame, text=f"{ip} is controlling this PC.\nPress Ctrl+Alt+Q or click the button to stop.", bg="#b00020", fg="white", font=("Times New Roman", 11, "bold"), justify="left")
    label.pack(anchor="w")

    stop_button = Button(frame, text="Stop Remote Access", command=kill_switch)
    stop_button.pack(anchor="e", pady=(8, 0))

    def check_session():
        if screen_thread.is_alive() or mouse_thread.is_alive():
            indicator.after(200, check_session)
        else:
            indicator.destroy()

    indicator.after(200, check_session)

    indicator.mainloop()

def send_screen():
    while True:
        try:
            jpg_bytes, no_bytes = screen_capture()
        
            nbytes = struct.pack('>I', no_bytes)  

            conn.sendall(nbytes)
            conn.sendall(jpg_bytes)

            time.sleep(0.03)
        except Exception as e:
            if isinstance(e, (ConnectionError, OSError)):
                logging.info(f"Screen stream to {addr[0]} ended: {e!r}")
            else:
                logging.exception(f"Unexpected error in the screen thread ({addr[0]})")
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            break

def receive_mouse():
    while True:
        try:
            mouse_bytes_no = recieve_data(4)
            mouse_no = struct.unpack('>I', mouse_bytes_no)[0]
            if not (mouse_no >= MIN_EVENT_SIZE and mouse_no<=MAX_EVENT_SIZE): 
                raise ValueError(f"Invalid mouse/keyboard length: {mouse_no}")
            mouse_bytes = recieve_data(mouse_no)
            event_type = struct.unpack('>I', mouse_bytes[:4])[0]
            if event_type not in (1,2,3,4,5):
                raise ValueError(f"Invalid event type: {event_type}")

            if event_type == 1:
                if mouse_no !=12:
                    raise ValueError(f"Invalid mouse length: {mouse_no}")
                event_type, x, y = struct.unpack('>Iii', mouse_bytes)
                x = max(0, min(x, client_width - 1))
                y = max(0, min(y, client_height - 1))
                scaled_x = int(x*server_width/client_width)
                scaled_y = int(y*server_height/client_height)
                mouse_controller.position = (scaled_x, scaled_y)
            elif event_type == 2:
                if mouse_no !=20:
                    raise ValueError(f"Invalid mouse length: {mouse_no}")
                event_type, x, y, button, pressed = struct.unpack('>Iiiii', mouse_bytes)
                x = max(0, min(x, client_width - 1))
                y = max(0, min(y, client_height - 1))
                scaled_x = int(x*server_width/client_width)
                scaled_y = int(y*server_height/client_height)
                mouse_controller.position = (scaled_x, scaled_y)
                if button == 1:
                    button = mouse.Button.left
                elif button == 2:
                    button = mouse.Button.right
                elif button == 3:
                    button = mouse.Button.x1
                elif button == 4:
                    button = mouse.Button.x2
                elif button == 5:
                    button = mouse.Button.middle
                else:
                    raise ValueError(f"This button doesnt exist: {button}")
                
                if pressed == 1:
                    mouse_controller.press(button)
                    held_mouse_buttons.add(button)
                elif pressed == 0:
                    mouse_controller.release(button)    
                    held_mouse_buttons.discard(button)
                else:
                    raise ValueError(f"This action doesnt exist: {pressed}")
            elif event_type == 3:
                if mouse_no !=20:
                    raise ValueError(f"Invalid mouse length: {mouse_no}")
                event_type, x, y, dx, dy = struct.unpack('>Iiiii', mouse_bytes)
                dx = max(-10, min(dx, 10))
                dy = max(-10, min(dy, 10))
                mouse_controller.scroll(dx,dy)
            elif event_type == 4:
                event_type, pressed = struct.unpack('>II', mouse_bytes[:8]) 
                key_bytes = mouse_bytes[8:]
                key_string = key_bytes.decode('utf-8')
                
                if key_string.startswith('Key.'):
                    key_name = key_string[4:]
                    if key_name not in ALLOWED_KEYS:
                        raise ValueError(f"This key doesn't exist: {key_name}")
                    key = ALLOWED_KEYS[key_name]
                else:
                    raise ValueError(f"This is not a special key: {key_string!r}")
               
                if pressed == 1:
                    keyboard_controller.press(key)
                    held_keys.add(key)
                elif pressed == 0:
                    keyboard_controller.release(key)
                    held_keys.discard(key)
                else:
                    raise ValueError(f"This function doesn't exist: {pressed}")
            elif event_type == 5: 
                if mouse_no !=12:
                    raise ValueError(f"Invalid keyboard length: {mouse_no}")
                event_type, pressed, vk = struct.unpack(">III", mouse_bytes)
                if vk<1 or vk> 254:
                    raise ValueError(f"Invalid key code: {vk}")
                key = keyboard.KeyCode.from_vk(vk)
                if pressed == 1:
                    keyboard_controller.press(key)
                    held_keys.add(key)
                elif pressed == 0:
                    keyboard_controller.release(key)
                    held_keys.discard(key)
                else:
                    raise ValueError(f"This function doesn't exist: {pressed}")
        except Exception as e:
            if isinstance(e, (ConnectionError, OSError)):
                logging.info(f"Session with {addr[0]} ended: {e!r}")
            elif isinstance(e, (ValueError, struct.error)):
                logging.warning(f"Invalid input from {addr[0]}, ending the session: {e!r}")
            else:
                logging.exception(f"Unexpected error while handling input from {addr[0]}")
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            break

# def receive_keyboard():
#     while True
# HOST = '127.0.0.1'
PORT = 12345

mouse_controller = mouse.Controller()
keyboard_controller = keyboard.Controller()

if PASS_FILE.is_file():
    try:
        ph = PasswordHasher()
        hash_pass = PASS_FILE.read_text(encoding='utf-8')
        hash_pass = hash_pass.strip()
        dummy_pass = "hello12"
        ph.verify(hash_pass, dummy_pass)
    except argon2.exceptions.InvalidHashError as e:
        logging.error(f"The file is broken: {e}")
        sys.exit(1)
    except (OSError, ValueError) as e:
        logging.error(f"The file can’t be read: {e}")
        sys.exit(1)
    except argon2.exceptions.VerifyMismatchError:
        pass
    except argon2.exceptions.VerificationError as e:
        logging.error(f"The hash password is broken: {e}")
        sys.exit(1)
    else:
        logging.error("The dummy password matched the real password. Exit!")
        sys.exit(1)
else:
    logging.error("Please run the setup_password.py script in order to create a server.pass")
    sys.exit(1)

try:
    context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
except ssl.SSLError as e:
    logging.error(f"The certificate/key couldn't be loaded or is/are invalid: {e}")
    sys.exit(1)
except FileNotFoundError as e:
    cert_exists = CERT_FILE.is_file()
    key_exists = KEY_FILE.is_file()
    if not cert_exists and key_exists:
        logging.error(f"The certificate is not found: {CERT_FILE}. Please make sure to generate it before running the script")
    elif not key_exists and cert_exists:
        logging.error(f"The private key is not found: {KEY_FILE}. Please make sure to generate it before running the script")
    elif not cert_exists and not key_exists:
        logging.error(f"The private key and the certificate are not found: {CERT_FILE} , {KEY_FILE}. Please make sure to generate them before running the script")
    else: 
        logging.error(f"Unexpected file error: {e}")
    sys.exit(1)
except PermissionError:
    logging.error(f"Check read permissions on {CERT_FILE} , {KEY_FILE}")
    sys.exit(1)
except OSError as e:
    logging.error(f"Something wrong with {CERT_FILE} , {KEY_FILE}: {e}")
    sys.exit(1)

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind(('', PORT))
    s.listen()
    s.settimeout(1.0) 
    logging.info(f"Server listening on: {''}: {PORT}")

    failed_attempts = {}
    
    conn = None
    catch_hotkey = threading.Event()
    hotkey = keyboard.GlobalHotKeys({'<ctrl>+<alt>+q': kill_switch})
    hotkey.start()
    
    while True:
        if catch_hotkey.is_set():  
            break
        try:
            conn, addr = s.accept()
        except TimeoutError:
            continue
        except KeyboardInterrupt:
            logging.info("Server shut down by user.")
            break
        deadline = time.monotonic() + HANDSHAKE_TIMEOUT
        logging.info(f"CLIENT CONNECTED: {addr}")

        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Handshake took too long")
            conn.settimeout(remaining)
            conn = context.wrap_socket(conn, server_side=True)
        except OSError as e:
            logging.warning(f"TLS Handshake failed with {addr}: {e}")
            conn.close()
            continue

        try:
            password_length_bytes = recieve_data(4, deadline)
            password_length = struct.unpack('>I', password_length_bytes)[0]
            if password_length<MIN_PASSWORD_BYTES or password_length>MAX_PASSWORD_BYTES:
                raise ValueError(f"Invalid password length: {password_length}")
            client_password_bytes = recieve_data(password_length, deadline)
            count = failed_attempts.get(addr[0], 0)
            if count>= MAX_PASS_ATTEMPTS:
                logging.warning(f"This blocked client:  {addr[0]}, tried to connect again ({count} failed attempts)")
                password_status = struct.pack('>I', STATUS_BLOCKED)
                try:    
                    conn.sendall(password_status)
                except OSError as e:
                    logging.warning(f"The client has disconnected: {e}")
                conn.close()
                continue
            ph.verify(hash_pass, client_password_bytes)
            failed_attempts[addr[0]] = 0
            logging.info(f"The password is correct for  {addr}!")
            if REQUIRE_CONSENT:    
                answer = window_consent(addr[0])
                if answer:
                    deadline = time.monotonic() + HANDSHAKE_TIMEOUT
                else:
                    logging.warning(f"The server denied the connection with {addr[0]}")
                    password_status = struct.pack('>I', STATUS_DENIED)
                    conn.sendall(password_status)
                    conn.close()
                    continue
            password_status = struct.pack('>I', STATUS_SUCCESS)
            conn.sendall(password_status)
        except argon2.exceptions.VerifyMismatchError as e:
            count = failed_attempts.get(addr[0], 0)
            count = count + 1
            failed_attempts[addr[0]] = count
            logging.warning(f"The password is incorrect! Client on address: {addr[0]} entered an incorrect password {count} times!")
            if count>=MAX_PASS_ATTEMPTS:
                password_status = struct.pack('>I', STATUS_BLOCKED)
            else:
                password_status = struct.pack('>I', STATUS_FAILURE)
            try:    
                conn.sendall(password_status)
            except OSError as e:
                logging.warning(f"The client has disconnected: {e}")
            conn.close()
            continue
        except (ConnectionError, OSError, struct.error, ValueError) as e:
            logging.warning(f"Handshake failed: {e}, {addr}")
            conn.close()
            continue

        try:
            resolution_length = recieve_data(4, deadline)
            resolution_size = struct.unpack('>I', resolution_length)[0]
            if resolution_size != RESOLUTION_SIZE:
                raise ValueError(f"Invalid resolution length: {resolution_size}")
            resolution_bytes = recieve_data(resolution_size, deadline)
            client_width, client_height = struct.unpack('>II', resolution_bytes)
            if  not ((client_width>=1 and client_height>= 1) and (client_width<=MAX_RESOLUTION and client_height<=MAX_RESOLUTION)):
                raise ValueError(f"Invalid resolution parameters: {client_width}, {client_height}")
        except (ConnectionError, OSError, struct.error, ValueError) as e:
            logging.warning(f"Handshake failed: {e}, {addr}")
            conn.close()
        else:
            conn.settimeout(600)
            logging.info(f"Client resolution: {client_width}, {client_height}")
            logging.info(f"Server resolution: {server_width}, {server_height}")
            
            logging.info(f'Session started with: {addr}')

            held_keys = set()
            held_mouse_buttons = set()

            screen_thread = threading.Thread(target=send_screen)
            mouse_thread = threading.Thread(target=receive_mouse)

            screen_thread.start()
            mouse_thread.start()

            show_indicator()
            
            screen_thread.join()
            mouse_thread.join()
            
            for held_key in held_keys:
                try:
                    keyboard_controller.release(held_key)
                    logging.info(f"Released stuck key: {held_key}")
                except Exception as e:
                    logging.error(f"Failed to release {held_key}: {e!r}")

            for held_mouse_button in held_mouse_buttons:
                try:
                    mouse_controller.release(held_mouse_button)
                    logging.info(f"Released stuck button: {held_mouse_button}")
                except Exception as e:
                    logging.error(f"Failed to release {held_mouse_button}: {e!r}")
            conn.close()
    hotkey.stop()
    logging.info("Server stopped")

        
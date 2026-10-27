import socket
from PIL import ImageGrab, ImageDraw
import struct
import pyautogui
import cv2
import numpy as np
from pynput import mouse, keyboard
from queue import Queue
import ssl
import sys
import getpass
from pathlib import Path

s = socket.socket()

port = 12345

client_width, client_height = pyautogui.size()
MAX_FRAME_SIZE = 10*1024*1024
MIN_FRAME_SIZE = 100
CERT_FILE = Path(__file__).parent / "server.crt"
STATUS_SUCCESS = 1
STATUS_FAILURE = 0
STATUS_BLOCKED = 2


def recieve_data(no_bytes):
    d = b''
    while len(d) < no_bytes:    
        a = s.recv(no_bytes - len(d))
        if not a:
            raise ConnectionError("The server has closed the connection")
        d += a
    return d

events = Queue()

latest_mouse_position = None

def on_move(x, y):
    global latest_mouse_position
    latest_mouse_position = (x, y)

def on_click(x, y, button, pressed):
    if button == mouse.Button.left:
        button_pressed = 1
    elif button == mouse.Button.right:
        button_pressed = 2
    elif button == mouse.Button.x1:
        button_pressed = 3
    elif button == mouse.Button.x2:
        button_pressed = 4
    elif button == mouse.Button.middle:
        button_pressed = 5
    else:
        return

    if pressed:
        pressed_int = 1
    else:
        pressed_int = 0
    events.put((2, x, y, button_pressed, pressed_int))

def on_scroll(x, y, dx, dy):
    events.put((3, x, y, dx, dy))

mouse_listener = mouse.Listener(
    on_click=on_click,
    on_move=on_move,
    on_scroll=on_scroll
)


def on_press(key):
    if isinstance(key, keyboard.Key):
        key_bytes = str(key).encode('utf-8')
        events.put((4, key_bytes, 1))
    elif key.vk is not None:
        events.put((5, key.vk, 1))
    else:
        return
    

def on_release(key):
    if isinstance(key, keyboard.Key):
        key_bytes = str(key).encode('utf-8')
        events.put((4, key_bytes, 0))
    elif key.vk is not None:
        events.put((5, key.vk, 0))
    else:
        return

keyboard_listener = keyboard.Listener(
    on_press=on_press,
    on_release = on_release
)

s.settimeout(5.0)
password = getpass.getpass("Enter the password to connect with the server: ")
try:
    context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=CERT_FILE)
    s = context.wrap_socket(s, server_hostname = 'end')

    encoded_password = password.encode('utf-8')
    password_bytes_len = struct.pack('>I', len(encoded_password))
    s.connect(('172.20.10.10', port))
    s.sendall(password_bytes_len)
    s.sendall(encoded_password)
    password_status_bytes = recieve_data(4)
    password_status = struct.unpack('>I', password_status_bytes)[0]
    if password_status == STATUS_SUCCESS:
        print("The password is correct!")
    elif password_status == STATUS_FAILURE:
        print("The password is incorrect!")
        s.close()
        sys.exit(1)
    elif password_status == STATUS_BLOCKED:
        print("Too many failed attempts. You are blocked from this server.")
        s.close()
        sys.exit(1)
    else:
        print("Wrong password status!")
        s.close()
        sys.exit(1)
    mouse_listener.start()
    keyboard_listener.start()
    resolution_bytes = struct.pack('>II', client_width, client_height)
    resolution_bytes_len = struct.pack('>I', len(resolution_bytes))
    s.sendall(resolution_bytes_len)
    s.sendall(resolution_bytes)
    s.settimeout(10.0)
except OSError as e:
    print(f"Connection failed: {e}")
    s.close()
    keyboard_listener.stop()
    mouse_listener.stop()
    sys.exit(1)



while True:
    try:
        nbytes = recieve_data(4)
        no_bytes = struct.unpack('>I', nbytes)[0]
        if not (no_bytes>=MIN_FRAME_SIZE and no_bytes<=MAX_FRAME_SIZE):
            raise ValueError(f"Invalid frame length: {no_bytes}")
        image_byte = recieve_data(no_bytes)
        image_jpg = np.frombuffer(image_byte, dtype=np.uint8)
        image = cv2.imdecode(image_jpg, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("The frame is not a valid image")

        
        cv2.namedWindow('Server Display', cv2.WND_PROP_FULLSCREEN)
        cv2.setWindowProperty('Server Display', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

        cv2.imshow('Server Display', image)

        cv2.waitKey(1)

        
        if latest_mouse_position is not None:
            x, y = latest_mouse_position
            event_bytes = struct.pack('>Iii', 1, x, y)
            event_length = struct.pack('>I', len(event_bytes))
            s.sendall(event_length)
            s.sendall(event_bytes)
            latest_mouse_position = None

        if not events.empty():
            event = events.get()
            if event[0] == 2 or event[0] == 3:
                event_bytes = struct.pack('>Iiiii', event[0], event[1], event[2], event[3], event[4])
                # IIiii
                event_length = struct.pack('>I', len(event_bytes))
            elif event[0] == 4:
                event_bytes = (struct.pack('>II', event[0], event[2]) + event[1])
                event_length = struct.pack('>I', len(event_bytes)) 
            elif event[0] == 5:
                event_bytes = struct.pack('>III', event[0], event[2], event[1])
                event_length = struct.pack('>I', len(event_bytes))
            s.sendall(event_length)
            s.sendall(event_bytes)
            
    except (KeyboardInterrupt, ConnectionError, OSError, ValueError) as e:
        print(f"Session ended: {e!r}")
        s.close()
        mouse_listener.stop()
        keyboard_listener.stop()
        cv2.destroyAllWindows()
        break
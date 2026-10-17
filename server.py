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

server_width, server_height = pyautogui.size()
RESOLUTION_SIZE = struct.calcsize(">II")
MIN_EVENT_SIZE = struct.calcsize('>II') + 1
MAX_EVENT_SIZE = 64
MAX_RESOLUTION = 16384
ALLOWED_KEYS = {k.name : k for k in keyboard.Key}
HANDSHAKE_TIMEOUT = 5

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
        print('Failure')

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

        

def send_screen():
    while True:
        try:
            jpg_bytes, no_bytes = screen_capture()
        
            nbytes = struct.pack('>I', no_bytes)  

            conn.sendall(nbytes)
            conn.sendall(jpg_bytes)

            time.sleep(0.03)
        except Exception as e:
            print(f"The connection is closed: {e}")
            try:    
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()
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
            if event_type not in (1,2,3,4):
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
                    button = mouse.Button.middle
                else:
                    raise ValueError(f"This button doesnt exist: {button}")
                
                if pressed == 1:
                    mouse_controller.press(button)
                elif pressed == 0:
                    mouse_controller.release(button)    
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
                    if len(key_string) != 1:
                        raise ValueError(f"This key doesnt exist: {key_string}")
                    key = key_string

                if pressed == 1:
                    keyboard_controller.press(key)
                elif pressed == 0:
                    keyboard_controller.release(key)
                else:
                    raise ValueError(f"This function doesn't exist: {pressed}")
        except (ConnectionError, OSError, ValueError, struct.error) as e:
            print(f"The connection is closed: {e}")
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()
            break

# def receive_keyboard():
#     while True
# HOST = '127.0.0.1'
PORT = 12345

mouse_controller = mouse.Controller()
keyboard_controller = keyboard.Controller()


with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind(('', PORT))
    s.listen()
    s.settimeout(1.0) 
    print(f"Server listening on: {''}: {PORT}")

    context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile="server.crt", keyfile="server.key")

    while True:
        try:
            conn, addr = s.accept()
        except TimeoutError:
            continue
        except KeyboardInterrupt:
            print("Server shut down by user.")
            break
        deadline = time.monotonic() + HANDSHAKE_TIMEOUT
        print("CLIENT CONNECTED:", addr)

        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Handshake took too long")
            conn.settimeout(remaining)
            conn = context.wrap_socket(conn, server_side=True)
        except OSError as e:
            print(f"TLS Handshake failed with {addr}: {e}")
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
            print(f"Handshake failed: {e}")
            conn.close()
        else:
            conn.settimeout(600)
            print("Client resolution:", client_width, client_height)
            print("Server resolution:", server_width, server_height)
            
            print(f'The addres where the connection ocurred: {addr}')

            screen_thread = threading.Thread(target=send_screen)
            mouse_thread = threading.Thread(target=receive_mouse)

            screen_thread.start()
            mouse_thread.start()

            screen_thread.join()
            mouse_thread.join()
        
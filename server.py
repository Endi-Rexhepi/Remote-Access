import socket 
from PIL import ImageGrab, ImageDraw
import pyautogui
import cv2
import numpy as np
import struct
from pynput import mouse, keyboard
import threading

server_width, server_height = pyautogui.size()

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

def recieve_data(no_bytes):
    d = conn.recv(no_bytes)
    if not d:
        print("The server has closed the connection")
    while len(d) != no_bytes:
        try:
            a = conn.recv(no_bytes - len(d))
            if not a:
                print("The server has closed the connection")
                break
            d += a
        except Exception as e:
            print(f"The connection is closed: {e}")
            conn.close()
            break
    return d

def send_screen():
    while True:
        try:
            jpg_bytes, no_bytes = screen_capture()
        
            nbytes = struct.pack('>I', no_bytes)  

            conn.sendall(nbytes)
            conn.sendall(jpg_bytes)
        except Exception as e:
            print(f"The connection is closed: {e}")
            conn.close()
            break

def receive_mouse():
    while True:
        try:
            mouse_bytes_no = recieve_data(4)
            mouse_no = struct.unpack('>I', mouse_bytes_no)[0]
            mouse_bytes = recieve_data(mouse_no)
            event_type = struct.unpack('>I', mouse_bytes[:4])[0]
        

            if event_type == 1:
                event_type, x, y = struct.unpack('>Iii', mouse_bytes)
                scaled_x = int(x*server_width/client_width)
                scaled_y = int(y*server_height/client_height)
                mouse_controller.position = (scaled_x, scaled_y)
            elif event_type == 2:
                event_type, x, y, button, pressed = struct.unpack('>Iiiii', mouse_bytes)

                scaled_x = int(x*server_width/client_width)
                scaled_y = int(y*server_height/client_height)
                mouse_controller.position = (scaled_x, scaled_y)
                if button == 1:
                    button = mouse.Button.left
                elif button == 2:
                    button = mouse.Button.right
                elif button == 3:
                    button = mouse.Button.middle

                if pressed == 1:
                    mouse_controller.press(button)
                else:
                    mouse_controller.release(button)         
            elif event_type == 3:
                event_type, x, y, dx, dy = struct.unpack('>Iiiii', mouse_bytes)
                mouse_controller.scroll(dx,dy)
            elif event_type == 4:
                event_type, pressed = struct.unpack('>II', mouse_bytes[:8]) 
                key_bytes = mouse_bytes[8:]
                key_string = key_bytes.decode('utf-8')
                if key_string.startswith('Key.'):
                    key_name = key_string[4:]
                    key = getattr(keyboard.Key, key_name)
                else:
                    key = key_string
                if pressed == 1:
                    keyboard_controller.press(key)
                else:
                    keyboard_controller.release(key)
        except Exception as e:
            print(f"The connection is closed: {e}")
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
    print(f"Server listening on: {''}: {PORT}")

    conn, addr = s.accept()
    print("CLIENT CONNECTED:", addr)

    resolution_length = recieve_data(4)
    resolution_size = struct.unpack('>I', resolution_length)[0]
    resolution_bytes = recieve_data(resolution_size)
    client_width, client_height = struct.unpack('>II', resolution_bytes)
    print("Client resolution:", client_width, client_height)
    print("Server resolution:", server_width, server_height)
    
    print(f'The addres where the connection ocurred: {addr}')

    screen_thread = threading.Thread(target=send_screen)
    mouse_thread = threading.Thread(target=receive_mouse)

    screen_thread.start()
    mouse_thread.start()

    screen_thread.join()
    mouse_thread.join()
    
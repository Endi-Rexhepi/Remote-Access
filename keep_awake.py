import pyautogui
import time

start_time = time.time()
fifteen_days = 15*24*60*60

while time.time() - start_time<fifteen_days:
    mouse_position = pyautogui.position()
    time.sleep(20)
    new_mouse_position = pyautogui.position()
    if mouse_position == new_mouse_position:
        pyautogui.moveRel(1,0)
        time.sleep(2)
        pyautogui.moveRel(-1,0)
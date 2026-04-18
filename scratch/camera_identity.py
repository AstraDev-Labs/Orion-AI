import cv2
import os
import ctypes
from ctypes import wintypes

# This is a bit advanced, but we can try to guess the name by looking at the registry or using COM via pythoncom if available.
# Since we don't have pythoncom, we will use a simpler trick: 
# Open each camera and try to see if it matches the resolution we expect for a laptop cam vs a phone.

print("Starting Camera Identity Diagnostic...")

def get_camera_info(index):
    # Try multiple backends
    for backend in [cv2.CAP_DSHOW, cv2.CAP_MSMF]:
        cap = cv2.VideoCapture(index, backend)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                # Some virtual cams report weird properties
                print(f"Device {index} ({'DSHOW' if backend == cv2.CAP_DSHOW else 'MSMF'}): {int(w)}x{int(h)}")
            cap.release()

for i in range(5):
    get_camera_info(i)

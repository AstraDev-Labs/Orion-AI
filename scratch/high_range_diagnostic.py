import cv2
import os

print("Scanning high-range indices (5-20)...")
backends = [("DSHOW", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF), ("ANY", cv2.CAP_ANY)]

for index in range(5, 21):
    for name, const in backends:
        cap = cv2.VideoCapture(index, const)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                print(f"FOUND: Device {index} with {name} resolution {frame.shape}")
            cap.release()
print("Scan complete.")

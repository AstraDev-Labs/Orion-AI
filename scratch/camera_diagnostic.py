import cv2
import os

def test_camera(index, backend_name, backend_id):
    print(f"\n--- Testing Index {index} with backend {backend_name} ---")
    try:
        cap = cv2.VideoCapture(index, backend_id)
        if not cap.isOpened():
            print(f"FAILED: Could not open index {index} with {backend_name}")
            return False
        
        ret, frame = cap.read()
        if ret:
            print(f"SUCCESS: Captured frame from index {index} with {backend_name}")
            print(f"Frame shape: {frame.shape}")
            cap.release()
            return True
        else:
            print(f"FAILED: Opened index {index} with {backend_name} but could not read frame")
            cap.release()
            return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False

print(f"OS: {os.name}")
backends = [
    ("Default", cv2.CAP_ANY),
    ("DirectShow", cv2.CAP_DSHOW),
    ("MSMF", cv2.CAP_MSMF)
]

for i in range(3):
    for name, bid in backends:
        test_camera(i, name, bid)

print("\nCamera diagnostic complete.")

import cv2
import os

def test_camera(index, backend_name, backend_const):
    print(f"\n--- Testing Index {index} with backend {backend_name} ---")
    try:
        cap = cv2.VideoCapture(index, backend_const)
        if not cap.isOpened():
            print(f"FAILED: Could not open index {index} with {backend_name}")
            return False
        
        # Try to read a few frames to let auto-exposure settle
        for i in range(5):
            ret, frame = cap.read()
            if not ret:
                print(f"FAILED: Opened but could not read frame {i} from index {index} with {backend_name}")
                cap.release()
                return False
        
        print(f"SUCCESS: Captured {frame.shape} from index {index} with {backend_name}")
        cap.release()
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False

backends = [
    ("Default", cv2.CAP_ANY),
    ("DirectShow", cv2.CAP_DSHOW),
    ("MSMF", cv2.CAP_MSMF)
]

print("Starting deep camera diagnostic...")
for index in range(5):
    for name, const in backends:
        test_camera(index, name, const)

print("\nDiagnostic complete.")

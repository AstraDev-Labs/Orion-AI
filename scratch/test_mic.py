"""
Live mic RMS diagnostic - shows exactly what the mic is hearing.
Run this, speak into your mic, and see the RMS values printed.
Press Ctrl+C to stop.
"""
import pyaudio
import numpy as np

FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 512

p = pyaudio.PyAudio()

# Print all input devices
print("=== AVAILABLE INPUT DEVICES ===")
for i in range(p.get_device_count()):
    d = p.get_device_info_by_index(i)
    if d["maxInputChannels"] > 0:
        print(f"  [{i}] {d['name']}")

print()
print(f"Default input: [{p.get_default_input_device_info()['index']}] {p.get_default_input_device_info()['name']}")
print()
print("=== OPENING DEFAULT MIC — SPEAK NOW ===")
print("If RMS stays at 0 or near 0 when you speak, the wrong mic is selected.")
print("Press Ctrl+C to stop.\n")

stream = p.open(
    format=FORMAT,
    channels=CHANNELS,
    rate=RATE,
    input=True,
    frames_per_buffer=CHUNK
)

try:
    while True:
        data = stream.read(CHUNK, exception_on_overflow=False)
        rms = np.sqrt(np.mean(np.frombuffer(data, dtype=np.int16).astype(np.float64)**2))
        bar = "#" * int(rms / 10)
        print(f"RMS: {rms:6.1f}  |{bar[:60]}", end="\r")
except KeyboardInterrupt:
    pass

stream.stop_stream()
stream.close()
p.terminate()
print("\nDone.")

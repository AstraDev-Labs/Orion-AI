import pyaudio
p = pyaudio.PyAudio()

print("=== INPUT DEVICES ===")
for i in range(p.get_device_count()):
    d = p.get_device_info_by_index(i)
    if d["maxInputChannels"] > 0:
        print(f"  [{i}] {d['name']} (in:{d['maxInputChannels']})")

print()
print("=== OUTPUT DEVICES ===")
for i in range(p.get_device_count()):
    d = p.get_device_info_by_index(i)
    if d["maxOutputChannels"] > 0:
        print(f"  [{i}] {d['name']} (out:{d['maxOutputChannels']})")

print()
try:
    print("Default input:", p.get_default_input_device_info()["name"])
except:
    print("Default input: (none)")
try:
    print("Default output:", p.get_default_output_device_info()["name"])
except:
    print("Default output: (none)")

p.terminate()

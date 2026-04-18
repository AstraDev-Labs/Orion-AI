import asyncio
import edge_tts
import subprocess
import pyaudio

async def test_streaming():
    text = "Hello. I am JARVIS. I am currently testing the streaming audio pipeline to ensure near-zero latency. Each word should be spoken as it is received from the cloud."
    voice = "en-GB-RyanNeural"
    
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=24000, output=True)
    
    # Start ffmpeg as a pipe
    # -i pipe:0 means read from stdin
    cmd = ["ffmpeg", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", "24000", "pipe:1"]
    ffmpeg_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    
    communicate = edge_tts.Communicate(text, voice)
    
    async def feed_ffmpeg():
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                ffmpeg_proc.stdin.write(chunk["data"])
        ffmpeg_proc.stdin.close()

    async def read_ffmpeg():
        while True:
            # Read a small chunk from ffmpeg output
            data = ffmpeg_proc.stdout.read(4000)
            if not data:
                break
            stream.write(data)

    await asyncio.gather(feed_ffmpeg(), read_ffmpeg())
    
    stream.stop_stream()
    stream.close()
    p.terminate()
    ffmpeg_proc.wait()

if __name__ == "__main__":
    asyncio.run(test_streaming())

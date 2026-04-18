import asyncio
import edge_tts
import pyaudio

async def test():
    text = "Sir, I encountered a cloud processing error: Error code: 401 - {'error': {'message': 'Invalid API Key', 'type': 'invalid_request_error', 'code': 'invalid_api_key'}}"
    communicate = edge_tts.Communicate(text, "en-GB-RyanNeural")
    try:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                print("Got audio chunk")
    except Exception as e:
        print("ERROR:", e)

asyncio.run(test())

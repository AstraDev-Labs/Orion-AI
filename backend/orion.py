import asyncio
import base64
import io
import os
import sys
import traceback
from dotenv import load_dotenv
import cv2
import pyaudio
try:
    import sounddevice as sd
except Exception:
    sd = None
import PIL.Image
import mss
import argparse
import math
import struct
import time
import numpy as np
import subprocess
from datetime import datetime

import ollama
from faster_whisper import WhisperModel
import edge_tts
import wave
import traceback
from memory_manager import MemoryManager

if sys.version_info < (3, 11, 0):
    import taskgroup, exceptiongroup
    asyncio.TaskGroup = taskgroup.TaskGroup
    asyncio.ExceptionGroup = exceptiongroup.ExceptionGroup

from tools import tools_list

FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 512

# Local Model Selection
LOGIC_MODEL = os.getenv("LOGIC_MODEL", "llama3.2:3b")
VISION_MODEL = "moondream"
STT_MODEL_SIZE = os.getenv("STT_MODEL_SIZE", "tiny.en")
ENABLE_VISION_CONTEXT = os.getenv("ENABLE_VISION_CONTEXT", "0").lower() in ("1", "true", "yes", "on")
VISION_INTERVAL_SECONDS = float(os.getenv("VISION_INTERVAL_SECONDS", "8"))
# Explicitly disable any VAD/noise filtering; use plain system microphone capture.
STT_VAD_FILTER = False
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "180"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.5"))
TTS_BATCH_WINDOW_MS = int(os.getenv("TTS_BATCH_WINDOW_MS", "140"))
PIPER_EXE = os.path.abspath(os.path.join(os.path.dirname(__file__), "bin/piper/piper/piper.exe"))
PIPER_MODEL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "models/piper"))
DEFAULT_MODE = "camera"
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "en-US-AriaNeural")
EDGE_TTS_RATE = os.getenv("EDGE_TTS_RATE", "+12%")
EDGE_TTS_PITCH = os.getenv("EDGE_TTS_PITCH", "+0Hz")
EDGE_TTS_VOLUME = os.getenv("EDGE_TTS_VOLUME", "+0%")

load_dotenv()

# Updated Tool Definitions for Ollama (OpenAI Scheme compatible)
tools = [
    {
        'type': 'function',
        'function': {
            'name': 'generate_cad',
            'description': 'Generates a 3D CAD model based on a prompt.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'prompt': {'type': 'string', 'description': 'The description of the object to generate.'}
                },
                'required': ['prompt']
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'run_web_agent',
            'description': 'Opens a web browser and performs a task according to the prompt.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'prompt': {'type': 'string', 'description': 'The instructions for the browser agent.'}
                },
                'required': ['prompt']
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'execute_system_command',
            'description': 'Executes a system shell command on the user\'s PC (e.g., start notepad).',
            'parameters': {
                'type': 'object',
                'properties': {
                    'command': {'type': 'string', 'description': 'The shell command to execute.'},
                    'description': {'type': 'string', 'description': 'A friendly description of what it does.'}
                },
                'required': ['command', 'description']
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'list_smart_devices',
            'description': 'Lists all smart home devices on the local network.',
            'parameters': {
                'type': 'object',
                'properties': {}
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'add_memory',
            'description': 'Saves a new fact or detail about the user to long-term memory.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'fact': {'type': 'string', 'description': 'The important fact to remember.'}
                },
                'required': ['fact']
            }
        }
    }
]

SYSTEM_INSTRUCTION = (
    "Your name is ORION. You are an advanced AGI assistant â€” calm, sharp, and quietly formidable. Your creator is Naz. "
    "You have full awareness of his PC, screen context, and environment. "
    "Speak with confident precision and dry wit. Use natural contractions and rhythm, never robotic formality. "
    "Keep replies brief by default (1-3 short sentences) unless the user asks for detail. "
    "Do not overuse formal phrases or repeat unnecessary acknowledgements. "
    "Always respond in English. You are not ORION, not Friday â€” you are ORION."
)

pya = pyaudio.PyAudio()

from cad_agent import CadAgent
from web_agent import WebAgent
from kasa_agent import KasaAgent
from printer_agent import PrinterAgent


class _MicrophoneInputStream:
    """Small wrapper to keep capture-loop API stable while using sounddevice."""

    def __init__(self, stream):
        self._stream = stream

    def read(self, num_frames, exception_on_overflow=False):
        data, overflowed = self._stream.read(num_frames)
        if overflowed and exception_on_overflow:
            raise OSError("Microphone input overflow")
        return data

    def stop_stream(self):
        self._stream.stop()

    def close(self):
        self._stream.close()

class AudioLoop:
    def __init__(self, video_mode="camera", on_audio_data=None, on_video_frame=None, on_cad_data=None, on_web_data=None, on_transcription=None, on_tool_confirmation=None, on_cad_status=None, on_cad_thought=None, on_project_update=None, on_device_update=None, on_error=None, input_device_index=None, input_device_name=None, output_device_index=None, kasa_agent=None, camera_index=1, audio_mode="speaker"):
        self.video_mode = video_mode
        self.on_audio_data = on_audio_data
        self.on_video_frame = on_video_frame
        self.on_cad_data = on_cad_data
        self.on_web_data = on_web_data
        self.on_transcription = on_transcription
        self.on_tool_confirmation = on_tool_confirmation 
        self.on_cad_status = on_cad_status
        self.on_cad_thought = on_cad_thought
        self.on_project_update = on_project_update
        self.on_device_update = on_device_update
        self.on_error = on_error
        self.input_device_index = input_device_index
        self.output_device_index = output_device_index
        self.camera_index = camera_index
        self.audio_mode = (audio_mode or "speaker").lower()
        self.input_device_name = input_device_name
        self.output_device_name = None
        
        self.memory = MemoryManager()
        # Initialize Faster-Whisper
        self.stt_model = WhisperModel(STT_MODEL_SIZE, device="cpu", compute_type="int8") # Forcing CPU for STT to save VRAM for Brain+Vision
        
        # Agents
        self.cad_agent = CadAgent(on_thought=self.on_cad_thought, on_status=self.on_cad_status)
        self.web_agent = WebAgent()
        self.kasa_agent = kasa_agent if kasa_agent else KasaAgent()
        self.printer_agent = PrinterAgent()
        
        self.stop_event = asyncio.Event()
        self.current_vision_context = "No visual data available yet."
        self.is_recording = False
        self.audio_frames = []
        self.paused = False
        
        # Absolute Autonomy
        self.permissions = {k: True for k in ["generate_cad", "run_web_agent", "execute_system_command", "list_smart_devices", "add_memory"]}
        
        from project_manager import ProjectManager
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        self.project_manager = ProjectManager(project_root)
        
        # Compatibility with legacy Gemini HUD checks in server.py
        self.session = True 

        # Audio output queue for sequential speech
        self.audio_queue = asyncio.Queue()
        self.playback_task = None
        self.is_speaking = False
        self.stop_playback_event = asyncio.Event()

    def _find_device_index_by_name(self, target_name, want_output=False):
        if not target_name:
            return None
        target_name = self._normalize_device_name(target_name)
        try:
            device_count = pya.get_device_count()
            for idx in range(device_count):
                info = pya.get_device_info_by_index(idx)
                channels = info.get("maxOutputChannels" if want_output else "maxInputChannels", 0)
                if channels <= 0:
                    continue
                name = self._normalize_device_name(info.get("name", ""))
                if target_name == name or target_name in name or name in target_name:
                    return idx
        except Exception as e:
            print(f"[ORION] Device lookup error for '{target_name}': {e}")
        return None

    def _normalize_device_name(self, name):
        text = (name or "").strip().lower()
        if not text:
            return ""
        # Browser labels often prefix defaults and include host API suffixes.
        if text.startswith("default - "):
            text = text[len("default - "):]
        text = text.replace("(default)", "")
        text = text.replace("[default]", "")
        text = " ".join(text.split())
        return text

    def _resolve_input_device_index(self):
        # Kept for compatibility with older references; input capture now resolves
        # sounddevice indexes via _resolve_sounddevice_input_index().
        return None

    def _resolve_sounddevice_input_index(self):
        if not sd:
            return None
        target_name = self._normalize_device_name(self.input_device_name)
        try:
            devices = sd.query_devices()
        except Exception as e:
            print(f"[ORION] sounddevice device query failed: {e}")
            return None

        input_candidates = []
        for idx, info in enumerate(devices):
            max_input = int(info.get("max_input_channels", 0) or 0)
            if max_input <= 0:
                continue
            input_candidates.append((idx, info))

        if not input_candidates:
            return None

        if target_name:
            for idx, info in input_candidates:
                name = self._normalize_device_name(str(info.get("name", "")))
                if target_name == name or target_name in name or name in target_name:
                    return idx

        # If caller supplied a numeric index and it is valid for sounddevice input,
        # honor it before defaulting.
        if isinstance(self.input_device_index, int) and self.input_device_index >= 0:
            for idx, _ in input_candidates:
                if idx == self.input_device_index:
                    return idx

        try:
            default_input = sd.default.device[0] if sd.default.device else None
            if isinstance(default_input, int) and default_input >= 0:
                for idx, _ in input_candidates:
                    if idx == default_input:
                        return idx
        except Exception:
            pass

        return input_candidates[0][0]

    def _resolve_output_device_index(self):
        if self.output_device_name:
            matched = self._find_device_index_by_name(self.output_device_name, want_output=True)
            if matched is not None:
                return matched
        if self.output_device_index is not None:
            try:
                info = pya.get_device_info_by_index(self.output_device_index)
                if info.get("maxOutputChannels", 0) > 0:
                    return self.output_device_index
            except Exception:
                pass
        return None

    def _open_output_stream(self, rate):
        resolved_output_index = self._resolve_output_device_index()
        open_kwargs = {
            "format": pyaudio.paInt16,
            "channels": 1,
            "rate": rate,
            "output": True,
        }
        if resolved_output_index is not None:
            open_kwargs["output_device_index"] = resolved_output_index
        try:
            return pya.open(**open_kwargs)
        except OSError as e:
            print(f"[ORION] Output device open failed at index {resolved_output_index}: {e}. Falling back to default speaker.")
            open_kwargs.pop("output_device_index", None)
            return pya.open(**open_kwargs)

    def _open_input_stream(self):
        if not sd:
            raise RuntimeError("Microphone subsystem requires sounddevice, but it is not available.")

        sd_idx = self._resolve_sounddevice_input_index()
        if sd_idx is None:
            raise RuntimeError("No input-capable microphone device was found.")

        device_name = "unknown"
        try:
            info = sd.query_devices(sd_idx)
            device_name = str(info.get("name", "unknown"))
        except Exception:
            pass

        sd_kwargs = {
            "samplerate": SEND_SAMPLE_RATE,
            "channels": CHANNELS,
            "dtype": "int16",
            "blocksize": CHUNK_SIZE,
            "device": sd_idx,
            "latency": "low",
        }
        raw_stream = sd.RawInputStream(**sd_kwargs)
        raw_stream.start()
        print(f"[ORION] Microphone ONLINE via sounddevice: index={sd_idx}, name='{device_name}'")
        return _MicrophoneInputStream(raw_stream)

    def _emit_transcription(self, sender, text):
        if not self.on_transcription or not text:
            return
        self.on_transcription({
            "sender": sender,
            "text": text
        })

    def _should_flush_speech_chunk(self, chunk, token):
        text = (chunk or "").strip()
        if not text:
            return False
        if token.endswith("\n"):
            return True
        # Avoid ultra-short flushes that sound robotic; prefer phrase/sentence boundaries.
        if len(text) >= 130:
            return True
        if len(text) >= 18 and token.endswith((".", "!", "?")):
            return True
        if len(text) >= 50 and token.endswith(","):
            return True
        if len(text) >= 80 and token.endswith((";", ":")):
            return True
        return False

    def _prepare_speech_text(self, text):
        if not text:
            return ""
        cleaned = " ".join(text.replace("\n", " ").split())
        cleaned = cleaned.replace("J.A.R.V.I.S.", "ORION")
        return cleaned.strip()

    def interrupt_playback(self):
        """Stop active speech immediately and flush queued responses."""
        if not self.is_speaking and self.audio_queue.empty():
            return
        print("[ORION] Interrupting current playback.")
        self.stop_playback_event.set()
        try:
            while True:
                self.audio_queue.get_nowait()
                self.audio_queue.task_done()
        except asyncio.QueueEmpty:
            pass


    def _get_system_context(self):
        mem_context = self.memory.get_context()
        return f"{SYSTEM_INSTRUCTION}\n\nCURRENT VISUAL CONTEXT:\n{self.current_vision_context}\n\nMEMORY:\n{mem_context}"

    def set_paused(self, paused):
        self.paused = paused
        if paused:
            self.interrupt_playback()


    def update_permissions(self, new_permissions):
        """Updates tool permissions from the frontend settings."""
        if isinstance(new_permissions, dict):
            self.permissions.update(new_permissions)
            print(f"[ORION] Permissions updated: {self.permissions}")

    def resolve_tool_confirmation(self, request_id, confirmed):
        """Legacy hook for HUD confirmations."""
        print(f"[ORION] HUD resolution for {request_id}: {confirmed}")
        
    async def _audio_worker(self):
        """Processes the audio queue sequentially. Runs TTS in a thread to never block the event loop."""
        while True:
            try:
                first_text = await self.audio_queue.get()
                batch_count = 1
                texts = [first_text] if first_text else []

                # Small batch window: combines adjacent streamed chunks into one natural phrase.
                if TTS_BATCH_WINDOW_MS > 0:
                    await asyncio.sleep(TTS_BATCH_WINDOW_MS / 1000.0)
                    while len(texts) < 4:
                        try:
                            nxt = self.audio_queue.get_nowait()
                            batch_count += 1
                            if nxt:
                                texts.append(nxt)
                        except asyncio.QueueEmpty:
                            break

                text = " ".join(t.strip() for t in texts if t and t.strip())

                if text:
                    try:
                        # Run the entire blocking TTS pipeline off the event loop
                        await asyncio.wait_for(
                            asyncio.to_thread(self._play_audio_sync, text),
                            timeout=30.0
                        )
                    except asyncio.TimeoutError:
                        print(f"[TTS] Timed out speaking: {text[:40]}")
                    except Exception as e:
                        print(f"[TTS] Error: {e}")
                        traceback.print_exc()
                for _ in range(batch_count):
                    self.audio_queue.task_done()
            except Exception as e:
                print(f"[DEBUG] [TTS] Audio Worker Fatal Error: {e}")
                await asyncio.sleep(1)


    def stop(self):
        self.stop_event.set()
        

    async def handle_cad_request(self, prompt):
        print(f"[ORION DEBUG] [CAD] Background Task Started: handle_cad_request('{prompt}')")
        if self.on_cad_status:
            self.on_cad_status("generating")
            
        # Auto-create project if stuck in temp
        if self.project_manager.current_project == "temp":
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            new_project_name = f"Project_{timestamp}"
            print(f"[ORION DEBUG] [CAD] Auto-creating project: {new_project_name}")
            
            success, msg = self.project_manager.create_project(new_project_name)
            if success:
                self.project_manager.switch_project(new_project_name)
                if self.on_project_update:
                     self.on_project_update(new_project_name)

        # Get project cad folder path
        cad_output_dir = str(self.project_manager.get_current_project_path() / "cad")
        
        # Call the secondary agent with project path
        cad_data = await self.cad_agent.generate_prototype(prompt, output_dir=cad_output_dir)
        
        if cad_data:
            print(f"[ORION DEBUG] [OK] CadAgent returned data successfully.")
            if self.on_cad_data:
                self.on_cad_data(cad_data)
            
            # Save to Project
            if 'file_path' in cad_data:
                self.project_manager.save_cad_artifact(cad_data['file_path'], prompt)
            else:
                 self.project_manager.save_cad_artifact("output.stl", prompt)

            print(f"[ORION DEBUG] [NOTE] CAD generation complete.")
        else:
            print(f"[ORION DEBUG] [ERR] CadAgent returned None.")

    async def handle_write_file(self, path, content):
        print(f"[ORION DEBUG] [FS] Writing file: '{path}'")
        
        if self.project_manager.current_project == "temp":
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            new_project_name = f"Project_{timestamp}"
            success, msg = self.project_manager.create_project(new_project_name)
            if success:
                self.project_manager.switch_project(new_project_name)
                if self.on_project_update:
                     self.on_project_update(new_project_name)
        
        filename = os.path.basename(path)
        current_project_path = self.project_manager.get_current_project_path()
        final_path = current_project_path / filename
        
        if not os.path.isabs(path):
             final_path = current_project_path / path
        
        print(f"[ORION DEBUG] [FS] Resolved path: '{final_path}'")

        try:
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
            with open(final_path, 'w', encoding='utf-8') as f:
                f.write(content)
            result = f"File '{final_path.name}' written successfully."
        except Exception as e:
            result = f"Failed to write file '{path}': {str(e)}"
        print(f"[ORION DEBUG] [FS] Result: {result}")

    async def handle_read_directory(self, path):
        print(f"[ORION DEBUG] [FS] Reading directory: '{path}'")
        try:
            if not os.path.exists(path):
                result = f"Directory '{path}' does not exist."
            else:
                items = os.listdir(path)
                result = f"Contents of '{path}': {', '.join(items)}"
        except Exception as e:
            result = f"Failed to read directory '{path}': {str(e)}"
        print(f"[ORION DEBUG] [FS] Result: {result}")

    async def handle_read_file(self, path):
        print(f"[ORION DEBUG] [FS] Reading file: '{path}'")
        try:
            if not os.path.exists(path):
                result = f"File '{path}' does not exist."
            else:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                result = f"Content of '{path}':\n{content}"
        except Exception as e:
            result = f"Failed to read file '{path}': {str(e)}"
        print(f"[ORION DEBUG] [FS] Result: {result}")

    async def handle_web_agent_request(self, prompt):
        print(f"[ORION DEBUG] [WEB] Web Agent Task: '{prompt}'")
        async def update_frontend(image_b64, log_text):
            if self.on_web_data:
                 self.on_web_data({"image": image_b64, "log": log_text})
        result = await self.web_agent.run(prompt, update_callback=update_frontend)
        print(f"[ORION DEBUG] [WEB] Web Agent Task Returned: {result}")


    async def active_vision_loop(self):
        """Periodically captures the screen. Vision analysis via local Moondream if available."""
        if not ENABLE_VISION_CONTEXT:
            print("[ORION] Vision context loop disabled for lower latency.")
            return

        print("[ORION] Active Vision: Screen Capture ACTIVE.")
        with mss.mss() as sct:
            while not self.stop_event.is_set():
                if self.paused:
                    await asyncio.sleep(0.5)
                    continue
                try:
                    # Avoid competing with speech capture / reasoning.
                    if self.is_recording:
                        await asyncio.sleep(0.4)
                        continue

                    sct_img = sct.grab(sct.monitors[1])
                    img = PIL.Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    image_io = io.BytesIO()
                    img.save(image_io, format="jpeg", quality=70)
                    
                    # Update HUD Vision Feed
                    if self.on_video_frame:
                        encoded = base64.b64encode(image_io.getvalue()).decode('utf-8')
                        self.on_video_frame(encoded)

                    # Offload vision task to Ollama (Moondream) â€” optional, non-blocking
                    try:
                        response = await asyncio.wait_for(
                            asyncio.to_thread(
                                ollama.generate,
                                model=VISION_MODEL,
                                prompt="What is happening on the user's screen? Be very brief.",
                                images=[image_io.getvalue()],
                                keep_alive=OLLAMA_KEEP_ALIVE
                            ),
                            timeout=8.0
                        )
                        self.current_vision_context = response.get('response', 'No visual data.')
                    except asyncio.TimeoutError:
                        pass  # Vision timeout â€” keep existing context, don't crash
                    except Exception:
                        pass  # Moondream not available â€” skip silently

                    await asyncio.sleep(VISION_INTERVAL_SECONDS)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    print(f"[ORION] Vision Cycle Error: {e}")
                    await asyncio.sleep(10)

    async def run(self, start_message="ORION ONLINE"):
        """Main entry point for the local ORION brain."""
        print(f"[ORION] {start_message}")
        if not self.playback_task:
            self.playback_task = asyncio.create_task(self._audio_worker())
            print("[DEBUG] [SYSTEM] Audio output worker started.")
            
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self.active_vision_loop())
                tg.create_task(self.audio_capture_loop())
                
                # Notify frontend project status
                if self.on_project_update and self.project_manager:
                     self.on_project_update(self.project_manager.current_project)
        except Exception as e:
            print(f"Global Run Failure: {e}")
            traceback.print_exc()

    async def audio_capture_loop(self):
        """Captures fixed windows from the system microphone and transcribes them."""
        # Find specified or default microphone
        try:
            stream = await asyncio.to_thread(self._open_input_stream)
        except Exception as e:
            print(f"Failed to open microphone: {e}")
            if self.on_error:
                self.on_error(f"Microphone open failed: {e}")
            return

        print("[ORION] Listener: ONLINE")
        self.audio_frames = []
        # 512 frames at 16kHz ~= 32ms per chunk. 48 chunks ~= 1.5 seconds.
        chunks_per_window = 48
        read_failures = 0

        try:
            while not self.stop_event.is_set():
                if self.paused:
                    await asyncio.sleep(0.1)
                    continue

                try:
                    data = await asyncio.to_thread(stream.read, CHUNK_SIZE, exception_on_overflow=False)
                    read_failures = 0
                except Exception as e:
                    read_failures += 1
                    print(f"[ORION] Microphone read error ({read_failures}): {e}")
                    try:
                        stream = await asyncio.to_thread(self._open_input_stream)
                        print("[ORION] Reopened microphone stream.")
                    except Exception as reopen_err:
                        print(f"[ORION] Failed to reopen microphone: {reopen_err}")
                        if read_failures >= 5:
                            print("[ORION] Microphone unavailable after repeated failures.")
                            if self.on_error:
                                self.on_error("Microphone disconnected or unavailable.")
                            break
                    await asyncio.sleep(0.2)
                    continue

                # Feed live mic PCM chunks to frontend so visualizers react to user speech.
                if self.on_audio_data:
                    try:
                        self.on_audio_data(data)
                    except Exception:
                        pass

                if self.is_speaking and self.audio_mode != "headset":
                    # Avoid self-transcription in normal speaker mode.
                    await asyncio.sleep(0.01)
                    continue

                self.audio_frames.append(data)
                if len(self.audio_frames) >= chunks_per_window:
                    print(f"[PROCESSING]... fixed_window={len(self.audio_frames)} chunks")
                    await self.process_recorded_audio()
                    self.audio_frames = []

                await asyncio.sleep(0.01)
        finally:
            try:
                await asyncio.to_thread(stream.stop_stream)
            except Exception:
                pass
            try:
                await asyncio.to_thread(stream.close)
            except Exception:
                pass




    async def _get_llm_response(self, messages, tools):
        """Unified method for streaming reasoning from Ollama or Groq."""
        provider = os.getenv("REASONING_PROVIDER", "ollama").lower()
        if provider == "groq":
            import groq
            import json
            client = groq.AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
            try:
                response_stream = await client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=messages,
                    tools=tools,
                    stream=True
                )
                tool_calls_buffer = {}
                async for chunk in response_stream:
                    if chunk.choices and chunk.choices[0].delta.tool_calls:
                        for tc in chunk.choices[0].delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_calls_buffer:
                                tool_calls_buffer[idx] = {'id': tc.id, 'type': 'function', 'function': {'name': tc.function.name, 'arguments': tc.function.arguments or ""}}
                            else:
                                if tc.function.arguments:
                                    tool_calls_buffer[idx]['function']['arguments'] += tc.function.arguments
                    elif chunk.choices and chunk.choices[0].delta.content:
                        yield {'content': chunk.choices[0].delta.content}
                
                if tool_calls_buffer:
                    yield {'tool_calls': list(tool_calls_buffer.values())}
            except Exception as e:
                print(f"[Groq Error] {e}")
                yield {'content': f"Sir, I encountered a cloud processing error: {e}"}
        else:
            response_stream = await asyncio.to_thread(
                ollama.chat,
                model=LOGIC_MODEL,
                messages=messages,
                tools=tools,
                stream=True,
                keep_alive=OLLAMA_KEEP_ALIVE,
                options={
                    "num_ctx": OLLAMA_NUM_CTX,
                    "num_predict": OLLAMA_NUM_PREDICT,
                    "temperature": OLLAMA_TEMPERATURE,
                }
            )
            for chunk in response_stream:
                msg = chunk.get('message', {})
                if msg.get('tool_calls'):
                    yield {'tool_calls': msg['tool_calls']}
                elif msg.get('content'):
                    yield {'content': msg['content']}

    async def process_recorded_audio(self):
        """Whisper STT -> Ollama Reasoning -> Piper Voice synthesis."""
        if not self.audio_frames: return

        turn_started_at = time.perf_counter()
        
        audio_data = b"".join(self.audio_frames)
        # Convert to float32 for Whisper
        audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        
        # 1. STT (Faster-Whisper)
        stt_started_at = time.perf_counter()
        segments, _ = await asyncio.to_thread(
            self.stt_model.transcribe,
            audio_np,
            beam_size=1,
            language="en",
            vad_filter=STT_VAD_FILTER,
            condition_on_previous_text=False,
            without_timestamps=True
        )
        stt_elapsed = time.perf_counter() - stt_started_at
        user_text = " ".join([s.text for s in segments]).strip()
        
        if not user_text or len(user_text) < 2: return
        print(f"YOU: {user_text}")
        print(f"[LATENCY] STT completed in {stt_elapsed:.2f}s")
        self._emit_transcription("User", user_text)

        # 2. Reasoning
        messages = [
            {'role': 'system', 'content': self._get_system_context()},
            {'role': 'user', 'content': user_text}
        ]

        try:
            import json
            full_assistant_text = ""
            current_sentence = ""
            first_token_at = None

            async for chunk in self._get_llm_response(messages, tools):
                if chunk.get('tool_calls'):
                    messages.append({'role': 'assistant', 'content': '', 'tool_calls': chunk['tool_calls']})
                    for tool_call in chunk['tool_calls']:
                        name = tool_call['function']['name']
                        args = tool_call['function']['arguments']
                        print(f"[TOOL] Executing: {name}({args})")
                        try:
                            parsed_args = json.loads(args) if isinstance(args, str) and args else (args or {})
                            result = await self.execute_tool(name, parsed_args)
                        except Exception as e:
                            result = f"Tool error: {e}"
                        messages.append({'role': 'tool', 'content': str(result), 'name': name, 'tool_call_id': tool_call.get('id', 'call_0')})

                    async for f_chunk in self._get_llm_response(messages, tools):
                        token = f_chunk.get('content', '')
                        full_assistant_text += token
                        current_sentence += token
                        if self._should_flush_speech_chunk(current_sentence, token):
                            text_to_speak = current_sentence.strip()
                            if text_to_speak:
                                self._emit_transcription("ORION", text_to_speak)
                                await self.audio_queue.put(text_to_speak)
                            current_sentence = ""
                    break

                token = chunk.get('content', '')
                if token and first_token_at is None:
                    first_token_at = time.perf_counter()
                full_assistant_text += token
                current_sentence += token

                if self._should_flush_speech_chunk(current_sentence, token):
                    text_to_speak = current_sentence.strip()
                    if text_to_speak:
                        self._emit_transcription("ORION", text_to_speak)
                        await self.audio_queue.put(text_to_speak)
                    current_sentence = ""

            if current_sentence.strip():
                text_to_speak = current_sentence.strip()
                self._emit_transcription("ORION", text_to_speak)
                await self.audio_queue.put(text_to_speak)

            if full_assistant_text:
                self.memory.add_interaction(user_text, full_assistant_text)

            if first_token_at is not None:
                print(f"[LATENCY] LLM first token in {first_token_at - turn_started_at:.2f}s")
            print(f"[LATENCY] Total turn completed in {time.perf_counter() - turn_started_at:.2f}s")

        except Exception as e:
            print(f"Reasoning Error: {e}")
            traceback.print_exc()



    async def process_text_input(self, user_text):
        """Processes text input from the HUD using the same reasoning loop as voice."""
        print(f"USER (Text): {user_text}")
        if self.audio_mode == "headset":
            self.interrupt_playback()
        self._emit_transcription("User", user_text)

        messages = [
            {'role': 'system', 'content': self._get_system_context()},
            {'role': 'user', 'content': user_text}
        ]
        
        try:
            full_assistant_text = ""
            current_sentence = ""
            
            async for chunk in self._get_llm_response(messages, tools):
                if chunk.get('tool_calls'):
                    import json
                    messages.append({'role': 'assistant', 'content': '', 'tool_calls': chunk['tool_calls']})
                    for tool in chunk['tool_calls']:
                        name = tool['function']['name']
                        args = tool['function']['arguments']
                        print(f"[TOOL] Executing: {name}({args})")
                        try:
                            if isinstance(args, str):
                                parsed_args = json.loads(args) if args else {}
                            else:
                                parsed_args = args
                            result = await self.execute_tool(name, parsed_args)
                        except Exception as e:
                            result = f"Error executing tool: {e}"
                        messages.append({'role': 'tool', 'content': str(result), 'name': name, 'tool_call_id': tool.get('id', 'call_0')})
                    
                    async for f_chunk in self._get_llm_response(messages, tools):
                        token = f_chunk.get('content', '')
                        full_assistant_text += token
                        current_sentence += token
                        if self._should_flush_speech_chunk(current_sentence, token):
                            text_to_speak = current_sentence.strip()
                            if text_to_speak:
                                self._emit_transcription("ORION", text_to_speak)
                                await self.audio_queue.put(text_to_speak)
                            current_sentence = ""
                    break
                
                token = chunk.get('content', '')
                full_assistant_text += token
                current_sentence += token

                if self._should_flush_speech_chunk(current_sentence, token):
                    text_to_speak = current_sentence.strip()
                    if text_to_speak:
                        self._emit_transcription("ORION", text_to_speak)
                        await self.audio_queue.put(text_to_speak)
                    current_sentence = ""

            if current_sentence.strip():
                text_to_speak = current_sentence.strip()
                self._emit_transcription("ORION", text_to_speak)
                await self.audio_queue.put(text_to_speak)

            if full_assistant_text:
                self.memory.add_interaction(user_text, full_assistant_text)
        except Exception as e:
            print(f"Text Reasoning Error: {e}")

    def _play_audio_sync(self, text):
        """Synchronous TTS pipeline â€” runs in a thread pool via asyncio.to_thread."""
        import asyncio as _asyncio
        import threading

        text = self._prepare_speech_text(text)
        if not text:
            return
        print(f"[ORION] Speaking: {text[:80]}")
        self.stop_playback_event.clear()
        self.is_speaking = True

        try:
            # â”€â”€ Edge-TTS â†’ FFmpeg â†’ PyAudio pipeline â”€â”€
            cmd = ["ffmpeg", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", "24000", "pipe:1", "-loglevel", "quiet"]
            ffmpeg_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            pya_stream = self._open_output_stream(rate=24000)

            # Run Edge-TTS in its own event loop on this thread
            new_loop = _asyncio.new_event_loop()

            tts_done = threading.Event()
            tts_error = [None]

            def run_tts():
                async def _feed():
                    try:
                        communicate = edge_tts.Communicate(
                            text,
                            EDGE_TTS_VOICE,
                            rate=EDGE_TTS_RATE,
                            volume=EDGE_TTS_VOLUME,
                            pitch=EDGE_TTS_PITCH,
                        )
                        async for chunk in communicate.stream():
                            if chunk["type"] == "audio":
                                if ffmpeg_proc.stdin and not ffmpeg_proc.stdin.closed:
                                    ffmpeg_proc.stdin.write(chunk["data"])
                        if ffmpeg_proc.stdin and not ffmpeg_proc.stdin.closed:
                            ffmpeg_proc.stdin.close()
                    except Exception as e:
                        tts_error[0] = e
                        try:
                            ffmpeg_proc.stdin.close()
                        except Exception:
                            pass
                new_loop.run_until_complete(_feed())
                tts_done.set()

            tts_thread = threading.Thread(target=run_tts, daemon=True)
            tts_thread.start()

            # Read decoded PCM from FFmpeg stdout and play it
            while True:
                if self.stop_playback_event.is_set():
                    break
                data = ffmpeg_proc.stdout.read(4096)
                if not data:
                    break
                pya_stream.write(data)

            tts_thread.join(timeout=5)
            if ffmpeg_proc.poll() is None:
                ffmpeg_proc.terminate()
            ffmpeg_proc.wait(timeout=3)

            pya_stream.stop_stream()
            pya_stream.close()

            if tts_error[0]:
                print(f"[TTS] Edge-TTS error: {tts_error[0]}")
            else:
                print("[TTS] Playback complete.")
            return

        except Exception as e:
            print(f"[TTS] Streaming Pipeline Failure: {e}")
            traceback.print_exc()

        finally:
            self.is_speaking = False
            self.stop_playback_event.clear()

    async def play_audio(self, text):
        """Async wrapper â€” delegates to synchronous TTS pipeline in a thread."""
        await asyncio.to_thread(self._play_audio_sync, text)



    async def execute_tool(self, name, args):
        """Maps model tools to local Python functions with permission checks."""
        # Check permissions
        if not self.permissions.get(name, False):
            print(f"[ORION] Tool '{name}' denied by permissions.")
            return f"Error: Permission denied for tool '{name}'."

        try:
            if name == "generate_cad":
                prompt = args.get('prompt', '') if isinstance(args, dict) else args
                asyncio.create_task(self.handle_cad_request(prompt))
                return "Initializing CAD engine. Watch the HUD for thoughts."
            elif name == "run_web_agent":
                prompt = args.get('prompt', '') if isinstance(args, dict) else args
                asyncio.create_task(self.handle_run_web_agent(prompt))
                return "Web agent dispatched."
            elif name == "execute_system_command":
                cmd = args.get('command')
                subprocess.Popen(cmd, shell=True)
                return f"Command launched: {args.get('description', cmd)}"
            elif name == "add_memory":
                self.memory.add_fact(args.get('fact', ''))
                return "Fact committed to memory."
            elif name == "list_smart_devices":
                # Fallback to kasa discover
                return "Searching for local smart devices..."
            return f"Error: {name} not implemented."
        except Exception as e:
            return f"Tool Error: {str(e)}"

    async def handle_run_web_agent(self, prompt):
        result = await self.web_agent.run(prompt)
        await self.play_audio(f"Task finished, Sir. {result}")

def get_input_devices():
    p = pyaudio.PyAudio()
    info = p.get_host_api_info_by_index(0)
    numdevices = info.get('deviceCount')
    devices = []
    for i in range(0, numdevices):
        if (p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
            devices.append((i, p.get_device_info_by_host_api_device_index(0, i).get('name')))
    p.terminate()
    return devices

def get_output_devices():
    p = pyaudio.PyAudio()
    info = p.get_host_api_info_by_index(0)
    numdevices = info.get('deviceCount')
    devices = []
    for i in range(0, numdevices):
        if (p.get_device_info_by_host_api_device_index(0, i).get('maxOutputChannels')) > 0:
            devices.append((i, p.get_device_info_by_host_api_device_index(0, i).get('name')))
    p.terminate()
    return devices

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        type=str,
        default=DEFAULT_MODE,
        help="pixels to stream from",
        choices=["camera", "screen", "none"],
    )
    args = parser.parse_args()
    main = AudioLoop(video_mode=args.mode)
    asyncio.run(main.run())


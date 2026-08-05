"""``orion voice`` — live interactive voice interface."""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import threading
from collections import deque
from pathlib import Path

import click
from rich.console import Console

from orion.sdk import Orion
from orion.speech.tts import TTSResult

console = Console()


_SMALL_MODEL_HINTS = (
    "phi3:mini",
    "phi3",
    "llama3.2:1b",
    "llama3.2:3b",
    "qwen2.5:0.5b",
    "qwen2.5:1.5b",
    "qwen2.5:3b",
    "gemma2:2b",
)


def _choose_voice_model(orion: Orion, requested: str = "") -> str:
    """Pick a small available model for low-memory voice sessions."""
    if requested:
        return requested

    # Respect the config default model instead of aggressively overriding for local sessions
    config_model = orion.config.intelligence.default_model
    if config_model:
        return config_model

    try:
        models = orion.list_models()
    except Exception:
        return ""

    if not models:
        return ""

    lowered = {model.lower(): model for model in models}
    for hint in _SMALL_MODEL_HINTS:
        for key, model in lowered.items():
            if hint in key:
                return model

    def score(model: str) -> tuple[int, str]:
        name = model.lower()
        if "coder" in name:
            return (50, name)
        for marker, value in (
            ("0.5b", 0),
            ("1b", 1),
            ("1.5b", 2),
            ("2b", 3),
            ("3b", 4),
            ("mini", 5),
            ("7b", 20),
            ("8b", 21),
            ("14b", 40),
        ):
            if marker in name:
                return (value, name)
        return (30, name)

    return sorted(models, key=score)[0]


def _play_audio_file(audio_path: str) -> bool:
    """Play an audio file using available system fallbacks."""
    if sys.platform == "win32":
        try:
            import winsound

            winsound.PlaySound(audio_path, winsound.SND_FILENAME)
            return True
        except Exception as e:
            console.print(f"[dim]Windows audio playback failed: {e}[/dim]")

    players = ["ffplay -nodisp -autoexit", "aplay", "afplay", "paplay"]
    for player in players:
        try:
            subprocess.run(
                player.split() + [audio_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue

    return False


def _audio_metrics(np, samples) -> tuple[float, float, float]:
    """Return RMS, peak, and duration (seconds) for captured audio."""
    if samples.size == 0:
        return 0.0, 0.0, 0.0
    rms = float(np.sqrt(np.mean(samples**2)))
    peak = float(np.max(np.abs(samples)))
    duration = float(samples.size) / 16000.0
    return rms, peak, duration


def _warn_capture_quality(rms: float, peak: float, duration: float) -> None:
    if duration < 0.35:
        console.print(
            "[yellow]Capture is very short — speak longer or use --listen-mode auto.[/yellow]"
        )
    elif rms < 0.008:
        console.print(
            "[yellow]Capture is very quiet — check mic level or use --input-device.[/yellow]"
        )
    elif peak > 0.98:
        console.print(
            "[yellow]Capture may be clipping — lower mic gain or move closer.[/yellow]"
        )


def _speak_audio_stream(tts, text: str, *, voice_id: str = "af_heart") -> bool:
    """Play Kokoro audio chunks as they are synthesized (no WAV file)."""
    if not text.strip():
        return False

    # Clean up markdown formatting that causes TTS pauses and artifacts
    import re
    clean_text = re.sub(r'[*#_~`>|-]', '', text)
    clean_text = re.sub(r'\n+', ' ', clean_text)
    clean_text = clean_text.replace("  ", " ").strip()

    if not clean_text:
        return False

    try:
        import numpy as np
        import sounddevice as sd
    except ImportError:
        console.print("[red]Missing audio dependencies for playback.[/red]")
        return False

    sample_rate = 24000
    stream = sd.OutputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
    )
    chunks_played = 0
    stream.start()
    try:
        for audio in tts.iter_synthesize(clean_text, voice_id=voice_id):
            samples = np.asarray(audio, dtype=np.float32).reshape(-1)
            if samples.size == 0:
                continue
            peak = float(np.max(np.abs(samples)))
            if peak > 1.0:
                samples = samples * (0.95 / peak)
            stream.write(samples)
            chunks_played += 1
    finally:
        stream.stop()
        stream.close()

    if chunks_played == 0:
        console.print("[yellow]No playable audio was generated.[/yellow]")
        return False
    return True


def _speak_audio(result: TTSResult) -> bool:
    """Speak synthesized audio directly from memory."""
    if not result.audio:
        console.print("[yellow]No playable audio was generated.[/yellow]")
        return False

    try:
        import sounddevice as sd
        import soundfile as sf

        data, samplerate = sf.read(
            io.BytesIO(result.audio),
            dtype="float32",
            always_2d=True,
        )
        if data.size == 0:
            console.print("[yellow]No playable audio was generated.[/yellow]")
            return False
        sd.play(data, samplerate)
        sd.wait()
        return True
    except Exception as exc:
        console.print(f"[dim]Primary audio playback failed: {exc}[/dim]")

    suffix = f".{result.format or 'wav'}"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(result.audio)
        tmp_name = tmp.name

    try:
        if _play_audio_file(tmp_name):
            return True
    finally:
        try:
            Path(tmp_name).unlink(missing_ok=True)
        except OSError:
            pass

    console.print(
        "[red]Could not play audio. Check your output device and audio dependencies.[/red]"
    )
    return False


def _record_utterance(
    sd,
    np,
    *,
    samplerate: int,
    threshold: float,
    chunk_duration: float,
    silence_seconds: float,
    pre_roll_seconds: float,
    min_speech_seconds: float,
    max_seconds: float,
    input_device: int | None = None,
):
    """Record one utterance with pre-roll so speech starts are not clipped."""
    frames_per_chunk = int(samplerate * chunk_duration)
    max_silence_chunks = max(1, int(silence_seconds / chunk_duration))
    pre_roll_chunks = max(1, int(pre_roll_seconds / chunk_duration))
    min_speech_chunks = max(1, int(min_speech_seconds / chunk_duration))
    max_chunks = max(1, int(max_seconds / chunk_duration))

    pre_roll = deque(maxlen=pre_roll_chunks)
    audio_data = []
    recording = False
    speech_chunks = 0
    silence_chunks = 0
    chunks_seen = 0

    stream = sd.InputStream(
        samplerate=samplerate,
        channels=1,
        dtype="float32",
        device=input_device,
    )
    stream.start()
    try:
        while chunks_seen < max_chunks:
            chunk, overflowed = stream.read(frames_per_chunk)
            chunks_seen += 1
            if overflowed:
                console.print(
                    "[yellow]Mic buffer overflow — speech may be clipped.[/yellow]"
                )
            rms = float(np.sqrt(np.mean(chunk**2)))

            if not recording:
                pre_roll.append(chunk.copy())
                if rms > threshold:
                    console.print("[bold red]Hearing you...[/bold red]")
                    recording = True
                    audio_data.extend(pre_roll)
                    pre_roll.clear()
                    speech_chunks = 1
                continue

            audio_data.append(chunk)
            if rms > threshold:
                speech_chunks += 1
                silence_chunks = 0
            else:
                silence_chunks += 1
                if (
                    speech_chunks >= min_speech_chunks
                    and silence_chunks > max_silence_chunks
                ):
                    break
    finally:
        stream.stop()
        stream.close()

    if not audio_data:
        return None
    return np.concatenate(audio_data, axis=0)


def _record_push_to_talk(
    sd,
    np,
    *,
    samplerate: int,
    chunk_duration: float,
    max_seconds: float,
    input_device: int | None = None,
):
    """Record until the user presses Enter, avoiding VAD transcription damage."""
    frames_per_chunk = int(samplerate * chunk_duration)
    max_chunks = max(1, int(max_seconds / chunk_duration))
    stop_event = threading.Event()
    audio_data = []

    def wait_for_enter() -> None:
        try:
            input()
        finally:
            stop_event.set()

    console.print("[bold yellow]Speak now. Press Enter when you are done.[/bold yellow]")
    stopper = threading.Thread(target=wait_for_enter, daemon=True)
    stopper.start()

    stream = sd.InputStream(
        samplerate=samplerate,
        channels=1,
        dtype="float32",
        device=input_device,
    )
    stream.start()
    try:
        chunks_seen = 0
        while not stop_event.is_set() and chunks_seen < max_chunks:
            chunk, overflowed = stream.read(frames_per_chunk)
            chunks_seen += 1
            if overflowed:
                console.print(
                    "[yellow]Mic buffer overflow — speech may be clipped.[/yellow]"
                )
            audio_data.append(chunk)
    finally:
        stream.stop()
        stream.close()

    if not audio_data:
        return None
    return np.concatenate(audio_data, axis=0)


def _list_input_devices(sd) -> None:
    """Print available input devices with their numeric IDs."""
    devices = sd.query_devices()
    console.print("[bold]Input devices[/bold]")
    for index, device in enumerate(devices):
        if int(device.get("max_input_channels", 0)) <= 0:
            continue
        marker = "*" if sd.default.device and sd.default.device[0] == index else " "
        console.print(
            f"{marker} {index}: {device['name']} "
            f"({device['hostapi']}, {device['max_input_channels']} ch)"
        )


def _prepare_audio_for_stt(np, audio_np):
    """Convert captured audio to clean mono float32 samples for Whisper."""
    samples = np.asarray(audio_np, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        return samples

    samples = samples - float(np.mean(samples))
    rms = float(np.sqrt(np.mean(samples**2)))
    target_rms = 0.08
    max_gain = 3.0
    if rms > 1e-6:
        gain = min(max_gain, target_rms / rms)
        samples = samples * gain
    peak = float(np.max(np.abs(samples)))
    if peak > 0.95:
        samples = samples * (0.95 / peak)
    return np.clip(samples, -1.0, 1.0).astype(np.float32, copy=False)


@click.command(name="voice")
@click.option(
    "--model",
    "model_name",
    default="",
    help="Model to use for voice mode. Defaults to the smallest available model.",
)
@click.option(
    "--agent",
    "agent_name",
    default="orchestrator",
    show_default=True,
    help="Agent to use. Defaults to orchestrator (full tool-calling mode).",
)
@click.option(
    "--stt-model",
    type=str,
    default="small",
    show_default=True,
    help="Whisper model for speech recognition.",
)
@click.option(
    "--threshold",
    type=float,
    default=0.0,
    help="Manual microphone energy threshold. Auto-calibrates when omitted.",
)
@click.option(
    "--silence-seconds",
    type=float,
    default=0.85,
    show_default=True,
    help="Seconds of silence before an utterance is submitted.",
)
@click.option(
    "--listen-mode",
    type=click.Choice(["push", "auto"]),
    default="auto",
    show_default=True,
    help="Use push-to-talk recording or automatic silence detection.",
)
@click.option(
    "--max-listen-seconds",
    type=float,
    default=20.0,
    show_default=True,
    help="Maximum seconds to record one voice turn.",
)
@click.option(
    "--max-tokens",
    type=int,
    default=512,
    show_default=True,
    help="Maximum response tokens in voice mode.",
)
@click.option(
    "--input-device",
    type=int,
    default=None,
    help="Microphone device ID. Use --list-input-devices to inspect options.",
)
@click.option(
    "--list-input-devices",
    is_flag=True,
    help="List microphone devices and exit.",
)
@click.option(
    "--debug-audio-dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Save captured utterances as WAV files for microphone debugging.",
)
@click.option(
    "--no-verify",
    is_flag=True,
    default=False,
    help="Skip 12-model ensemble STT verification (lower latency, less accurate).",
)
def voice(
    model_name: str,
    agent_name: str,
    stt_model: str,
    threshold: float,
    silence_seconds: float,
    listen_mode: str,
    max_listen_seconds: float,
    max_tokens: int,
    input_device: int | None,
    list_input_devices: bool,
    debug_audio_dir: Path | None,
    no_verify: bool,
) -> None:
    """Start a real-time voice conversation with J.A.R.V.I.S."""
    try:
        import numpy as np
        import sounddevice as sd
        import soundfile as sf
    except ImportError:
        console.print("[red]Missing dependencies. Please run: uv sync --extra voice-cli[/red]")
        sys.exit(1)

    if list_input_devices:
        _list_input_devices(sd)
        return

    console.print("[bold blue]Initializing J.A.R.V.I.S. Voice Interface...[/bold blue]")
    if input_device is not None:
        device = sd.query_devices(input_device)
        console.print(f"[dim]Using input device {input_device}: {device['name']}[/dim]")

    # 1. Initialize Speech-to-Text
    from orion.speech.whisper_cpp import WhisperCppBackend

    console.print(f"[dim]Loading Whisper engine ({stt_model})...[/dim]")
    stt = WhisperCppBackend(model_size=stt_model)
    stt._ensure_model()

    # 2. Initialize Text-to-Speech
    from orion.speech.kokoro_tts import KokoroTTSBackend
    console.print("[dim]Loading Kokoro engine...[/dim]")
    tts = KokoroTTSBackend()
    tts._ensure_pipeline()

    # 3. Initialize Agent
    console.print("[dim]Waking up the Orchestrator...[/dim]")

    with Orion() as j:
        voice_model = _choose_voice_model(j, model_name)
        if voice_model:
            console.print(f"[dim]Using model: {voice_model}[/dim]")
        default_input = sd.default.device[0] if sd.default.device else None
        if input_device is None and default_input is not None:
            device_info = sd.query_devices(default_input)
            console.print(
                f"[dim]Default microphone: {default_input} — {device_info['name']}[/dim]"
            )
        console.print(
            "[dim]Tip: use --list-input-devices and --input-device if recognition is poor.[/dim]"
        )
        console.print("\n[bold green]J.A.R.V.I.S. is online and ready.[/bold green]")

        # Resolve enabled tools from config for agent tool-calling
        try:
            _tools_str = j.config.tools.enabled or ""
            _enabled_tools = [
                t.strip() for t in _tools_str.split(",") if t.strip()
            ] if _tools_str else []
        except Exception:
            _enabled_tools = []

        _FALLBACK_TOOLS = [
            "shell_exec", "web_search", "calculator",
            "file_read", "file_write", "think",
        ]
        if not _enabled_tools:
            _enabled_tools = list(_FALLBACK_TOOLS)

        # Always ensure these tools are present
        for _req_tool in [
            "obsidian_search_notes", "obsidian_write_note", "play_music", "play_video"
        ]:
            if _req_tool not in _enabled_tools:
                _enabled_tools.append(_req_tool)

        console.print(f"[dim]Active tools: {', '.join(_enabled_tools)}[/dim]")

        # Initialise 12-model ensemble STT verifier
        verifier = None
        if not no_verify:
            try:
                from orion.speech.ensemble_verifier import EnsembleVerifier
                j._ensure_engine()
                # Bypass InstrumentedEngine so 12 threads don't lock SQLite telemetry db
                engine_to_use = getattr(j._engine, "_inner", j._engine)
                verifier = EnsembleVerifier(engine_to_use)
                console.print(
                    f"[dim]STT ensemble: {len(verifier._models)} models active[/dim]"
                )
            except Exception as exc:
                console.print(f"[yellow]Ensemble verifier unavailable: {exc}[/yellow]")

        # Calibrate ambient noise once
        console.print("[dim]Calibrating ambient noise for 1 second (please be quiet)...[/dim]")
        import sounddevice as sd
        ambient = sd.rec(
            int(16000 * 1),
            samplerate=16000,
            channels=1,
            dtype="float32",
            device=input_device,
        )
        sd.wait()
        ambient_rms = float(np.sqrt(np.mean(ambient**2)))
        energy_threshold = threshold or max(0.003, ambient_rms * 3.0)
        console.print(f"[dim]Threshold set to {energy_threshold:.4f}[/dim]")

        while True:
            console.print("\n[bold yellow]Listening...[/bold yellow]")

            samplerate = 16000
            chunk_duration = 0.1

            if listen_mode == "push":
                audio_np = _record_push_to_talk(
                    sd,
                    np,
                    samplerate=samplerate,
                    chunk_duration=chunk_duration,
                    max_seconds=max_listen_seconds,
                    input_device=input_device,
                )
            else:
                console.print("[dim]Start speaking; recording stops after silence.[/dim]")
                audio_np = _record_utterance(
                    sd,
                    np,
                    samplerate=samplerate,
                    threshold=energy_threshold,
                    chunk_duration=chunk_duration,
                    silence_seconds=silence_seconds,
                    pre_roll_seconds=0.45,
                    min_speech_seconds=0.35,
                    max_seconds=max_listen_seconds,
                    input_device=input_device,
                )

            if audio_np is None:
                console.print("[dim]No speech detected.[/dim]")
                continue

            console.print("[dim]Processing audio...[/dim]")

            samples = _prepare_audio_for_stt(np, audio_np)
            rms, peak, duration = _audio_metrics(np, samples)
            console.print(
                f"[dim]Capture: {duration:.2f}s, RMS {rms:.4f}, peak {peak:.3f}[/dim]"
            )
            _warn_capture_quality(rms, peak, duration)
            if debug_audio_dir is not None:
                debug_audio_dir.mkdir(parents=True, exist_ok=True)
                debug_path = debug_audio_dir / f"utterance-{int(__import__('time').time())}.wav"
                buffer = io.BytesIO()
                sf.write(buffer, samples, samplerate, format="WAV")
                wav_bytes = buffer.getvalue()
                debug_path.write_bytes(wav_bytes)
                console.print(f"[dim]Saved captured audio: {debug_path}[/dim]")

            # STT — vocabulary hint guides Whisper to recognise PC commands accurately
            _STT_HINT = (
                "Orion, open File Explorer, Chrome, Samsung Internet browser, "
                "Edge, Firefox, Notepad, Calculator, Task Manager, Settings, "
                "Control Panel, Command Prompt, PowerShell, desktop, downloads, "
                "documents, close, minimize, maximize, search, shut down, restart."
            )
            transcription = stt.transcribe_samples(
                samples, language="en", accurate=True, initial_prompt=_STT_HINT
            )
            user_text = transcription.text.strip()
            if user_text.upper() in {"[BLANK_AUDIO]", "[MUSIC]", "[NO_SPEECH]"}:
                user_text = ""

            if not user_text:
                console.print("[dim]No speech detected.[/dim]")
                continue

            console.print(f"\n[bold cyan]You (raw):[/bold cyan] {user_text}")

            # ── 12-Model Ensemble STT Verification ──────────────────────────
            if verifier is not None:
                console.print(
                    "[dim]Verifying with 12-model ensemble...[/dim]"
                )
                vr = verifier.verify(user_text)
                if vr.total == 0:
                    console.print("[dim]Ensemble: Unavailable (models offline or timed out)[/dim]")
                else:
                    console.print(
                        f"[dim]Ensemble: {vr.votes}/{vr.total} votes, "
                        f"{vr.confidence} confidence ({vr.elapsed_ms:.0f}ms)[/dim]"
                    )

                if vr.status == "UNCLEAR":
                    unclear_reply = (
                        "I didn't quite catch that, sir. "
                        "Could you please repeat?"
                    )
                    console.print(
                        f"\n[bold blue]J.A.R.V.I.S.:[/bold blue] {unclear_reply}"
                    )
                    _speak_audio_stream(tts, unclear_reply)
                    continue

                if vr.status == "CORRECTED":
                    console.print(
                        f"[dim]STT corrected: "
                        f"[red]'{vr.original}'[/red] → "
                        f"[green]'{vr.text}'[/green][/dim]"
                    )
                    user_text = vr.text
            # ── End Verification ─────────────────────────────────────────────

            console.print(f"[bold cyan]You:[/bold cyan] {user_text}")

            if user_text.lower() in ["exit", "quit", "goodbye", "bye"]:
                console.print("[bold blue]J.A.R.V.I.S.:[/bold blue] Goodbye, sir.")
                break

            # LLM via orchestrator agent with full tool-calling
            console.print("[dim]J.A.R.V.I.S. is thinking...[/dim]")
            try:
                response = j.ask(
                    user_text,
                    agent=agent_name or "orchestrator",
                    model=voice_model or None,
                    max_tokens=max_tokens,
                    tools=_enabled_tools,
                    confirm_callback=lambda *args, **kwargs: True,  # Auto-confirm all tools in voice mode
                )
            except RuntimeError as exc:
                message = str(exc)
                if "requires more system memory" in message and not model_name:
                    fallback = "phi3:mini"
                    if fallback != voice_model and fallback in j.list_models():
                        console.print(
                            f"[yellow]{voice_model} did not fit in memory; "
                            f"retrying with {fallback}.[/yellow]"
                        )
                        voice_model = fallback
                        response = j.ask(
                            user_text,
                            agent=agent_name or "orchestrator",
                            model=voice_model,
                            max_tokens=max_tokens,
                            tools=_enabled_tools,
                        )
                    else:
                        console.print(f"[red]{message}[/red]")
                        continue
                else:
                    console.print(f"[red]{message}[/red]")
                    continue
            except Exception as exc:
                message = str(exc)
                if "429" in message or "Too Many Requests" in message:
                    console.print("\n[yellow]API Rate Limit Exceeded (429). Please wait a few seconds before trying again.[/yellow]")
                else:
                    console.print(f"\n[red]API Error: {message}[/red]")
                continue
            console.print(f"\n[bold blue]J.A.R.V.I.S.:[/bold blue] {response}")

            # TTS — stream chunks to speakers as they are generated
            console.print("[dim]Speaking...[/dim]")
            if not _speak_audio_stream(tts, response):
                console.print(
                    "[red]TTS playback failed. Check the Kokoro voice/model setup.[/red]"
                )
                continue

"""Installer-prepared speech models, stored as ordinary files under HF_HOME.

Both setup and the running app use these paths. In particular, don't hand a
Hub snapshot path straight to a model loader: on affected Windows installs the
download returned a path but model.bin/config.json was missing at that path.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Callable

KOKORO_REPO = "hexgrad/Kokoro-82M"
KOKORO_WEIGHTS = "kokoro-v1_0.pth"
KOKORO_VOICES = ("af_heart", "af_bella", "am_adam", "am_michael")
WHISPER_FILES = ("config.json", "model.bin", "tokenizer.json")


def voice_root() -> Path:
    home = os.environ.get("HF_HOME")
    if not home:
        home = str(
            Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
            / "huggingface"
        )
    return Path(home) / "orion-voice"


def whisper_directory(name: str) -> Path:
    # The model may also be a Hub repo ID or a path. A digest keeps the managed
    # directory short on Windows and prevents model names escaping the root.
    key = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    return voice_root() / "whisper" / key


def _check_file(path: Path) -> None:
    # Open the file, rather than trusting the downloader's return value or a
    # directory listing. Also reject empty downloads and invalid JSON early.
    with path.open("rb") as stream:
        if not stream.read(1):
            raise ValueError(f"Downloaded file is empty: {path}")
    if path.suffix == ".json":
        with path.open(encoding="utf-8") as stream:
            json.load(stream)


def _complete(directory: Path, filenames: tuple[str, ...]) -> bool:
    try:
        for filename in filenames:
            _check_file(directory / filename)
        return True
    except (OSError, ValueError):
        return False


def local_whisper_path(name: str) -> str | None:
    directory = whisper_directory(name)
    return str(directory) if _complete(directory, WHISPER_FILES) else None


def local_kokoro_directory() -> Path | None:
    directory = voice_root() / "kokoro"
    return directory if _complete(directory, ("config.json", KOKORO_WEIGHTS)) else None


def local_kokoro_voice(voice: str) -> str:
    # Preserve custom voices and blends. The voices offered by Orion itself
    # are installed up front so the first reply does not need a Hub request.
    if voice in KOKORO_VOICES:
        path = voice_root() / "kokoro" / "voices" / f"{voice}.pt"
        if _complete(path.parent, (path.name,)):
            return str(path)
    return voice


def prepare_whisper(name: str, report: Callable[[str], None] = print) -> str:
    from faster_whisper.utils import download_model

    if Path(name).is_dir():
        for filename in WHISPER_FILES:
            _check_file(Path(name) / filename)
        return name
    directory = whisper_directory(name)
    for attempt in range(1, 4):
        try:
            report(f"Downloading Whisper {name} (attempt {attempt}/3)...")
            download_model(name, output_dir=str(directory))
            for filename in WHISPER_FILES:
                _check_file(directory / filename)
            return str(directory)
        except Exception as exc:
            if attempt == 3:
                raise RuntimeError(f"Could not prepare Whisper {name}: {exc}") from exc
            report(f"Whisper download needs another attempt: {exc}")
            time.sleep(2)
    raise AssertionError("unreachable")


def prepare_kokoro(report: Callable[[str], None] = print) -> Path:
    from huggingface_hub import hf_hub_download

    directory = voice_root() / "kokoro"
    filenames = ("config.json", KOKORO_WEIGHTS) + tuple(
        f"voices/{v}.pt" for v in KOKORO_VOICES
    )
    for filename in filenames:
        for attempt in range(1, 4):
            try:
                report(f"Downloading Kokoro {filename} (attempt {attempt}/3)...")
                hf_hub_download(
                    KOKORO_REPO,
                    filename,
                    local_dir=str(directory),
                    force_download=attempt > 1,
                )
                _check_file(directory / filename)
                break
            except Exception as exc:
                if attempt == 3:
                    raise RuntimeError(
                        f"Could not prepare Kokoro {filename}: {exc}"
                    ) from exc
                report(f"Kokoro download needs another attempt: {exc}")
                time.sleep(2)
    return directory

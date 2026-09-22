"""Speech setup must verify files and the app must reuse them without the Hub."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from orion.speech import _model_files as models


@pytest.fixture(autouse=True)
def isolated_models(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    monkeypatch.setattr(models.time, "sleep", lambda _: None)


def _write(directory, names):
    for name in names:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"{}" if path.suffix == ".json" else b"model data")


def test_whisper_retries_a_download_that_returns_a_missing_snapshot(monkeypatch):
    import faster_whisper.utils

    calls = []

    def download(name, output_dir):
        calls.append(output_dir)
        if len(calls) == 2:
            _write(Path(output_dir), models.WHISPER_FILES)
        return "missing/snapshot"

    monkeypatch.setattr(faster_whisper.utils, "download_model", download)
    directory = models.prepare_whisper("base", lambda _: None)
    assert len(calls) == 2
    assert models.local_whisper_path("base") == directory
    assert models.local_whisper_path("base.en") is None


def test_kokoro_forces_retry_when_downloader_returns_a_missing_file(monkeypatch):
    import huggingface_hub

    calls = []

    def download(repo, filename, *, local_dir, force_download):
        calls.append((filename, force_download))
        if len(calls) > 1:
            _write(Path(local_dir), (filename,))
        return "missing/snapshot/config.json"

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", download)
    directory = models.prepare_kokoro(lambda _: None)
    assert calls[:2] == [("config.json", False), ("config.json", True)]
    assert models.local_kokoro_directory() == directory
    for voice in models.KOKORO_VOICES:
        assert Path(models.local_kokoro_voice(voice)).is_file()


def test_missing_kokoro_files_never_report_success(monkeypatch):
    import huggingface_hub

    download = MagicMock(return_value="missing/snapshot/config.json")
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", download)
    with pytest.raises(RuntimeError, match="Could not prepare Kokoro config.json"):
        models.prepare_kokoro(lambda _: None)
    assert download.call_count == 3
    assert models.local_kokoro_directory() is None


def test_incomplete_or_invalid_model_directory_is_not_ready():
    directory = models.whisper_directory("base")
    _write(directory, models.WHISPER_FILES)
    (directory / "model.bin").write_bytes(b"")
    assert models.local_whisper_path("base") is None
    (directory / "model.bin").write_bytes(b"model data")
    (directory / "config.json").write_text("incomplete JSON")
    assert models.local_whisper_path("base") is None


def test_whisper_backend_loads_prepared_files(monkeypatch):
    from orion.speech import faster_whisper

    directory = models.whisper_directory("base")
    _write(directory, models.WHISPER_FILES)
    model_cls = MagicMock()
    monkeypatch.setattr(faster_whisper, "WhisperModel", model_cls)
    faster_whisper.FasterWhisperBackend(model_size="base", device="cpu")._ensure_model()
    model_cls.assert_called_once_with(str(directory), device="cpu", compute_type="int8")


def test_kokoro_backend_loads_prepared_config_weights_and_voice(monkeypatch):
    import sys

    from orion.speech.kokoro_tts import KokoroTTSBackend

    directory = models.voice_root() / "kokoro"
    _write(directory, ("config.json", models.KOKORO_WEIGHTS, "voices/af_heart.pt"))
    model_cls, pipeline_cls = MagicMock(), MagicMock()
    pipeline_cls.return_value.return_value = [("Ready", "phonemes", b"audio")]
    monkeypatch.setitem(
        sys.modules, "kokoro", SimpleNamespace(KModel=model_cls, KPipeline=pipeline_cls)
    )
    result = list(KokoroTTSBackend().iter_synthesize("Ready"))
    assert result == [b"audio"]
    model_cls.assert_called_once_with(
        repo_id=models.KOKORO_REPO,
        config=str(directory / "config.json"),
        model=str(directory / models.KOKORO_WEIGHTS),
    )
    pipeline_cls.return_value.assert_called_once_with(
        "Ready",
        voice=str(directory / "voices/af_heart.pt"),
        speed=1.0,
    )

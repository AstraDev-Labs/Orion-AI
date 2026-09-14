"""Shared fixtures — clear all registries and the event bus between tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orion.core.config import GpuInfo, HardwareInfo
from orion.core.events import EventBus, reset_event_bus
from orion.core.registry import (
    AgentRegistry,
    BenchmarkRegistry,
    ChannelRegistry,
    CompressionRegistry,
    ConnectorRegistry,
    EngineRegistry,
    MemoryRegistry,
    MinerRegistry,
    ModelRegistry,
    RouterPolicyRegistry,
    SkillRegistry,
    SpeechRegistry,
    ToolRegistry,
    TTSRegistry,
)

# ---------------------------------------------------------------------------
# Credential isolation
# ---------------------------------------------------------------------------

# Environment variables that carry real secrets. Unit tests must not see these:
# a test asserting a default of "" picks up the developer's live token instead,
# fails, and prints the secret into the failure output -- which then lands in
# CI logs, terminal scrollback and pasted bug reports.
_CREDENTIAL_ENV_VARS = (
    "TELEGRAM_BOT_TOKEN",
    "DISCORD_BOT_TOKEN",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_ACCOUNT_SID",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "DEEPGRAM_API_KEY",
    "ELEVENLABS_API_KEY",
    "CARTESIA_API_KEY",
    "STEAM_API_KEY",
    "OPENORION_API_KEY",
    "HF_TOKEN",
    # Not secrets, but ambient endpoint overrides that change which URL the
    # code calls -- the Ollama installer sets OLLAMA_HOST=127.0.0.1:11434,
    # which silently defeats respx mocks written against the documented
    # localhost default.
    "OLLAMA_HOST",
    "OPENORION_CONFIG",
)

# Markers whose tests deliberately need the real credentials.
_LIVE_MARKERS = frozenset({"live", "cloud", "live_channel", "live_external"})


@pytest.fixture(autouse=True)
def _isolate_environment(request, monkeypatch, tmp_path_factory) -> None:
    """Hide real secrets and the real config file from unit tests.

    Two separate leaks, same shape. Secrets: a test asserting a default of ""
    picked up the developer's live token and printed it on failure. Config:
    load_config() falls back to ~/.orion/config.toml, so a test asserting the
    dataclass default of temperature=0.7 read the developer's 0.0 instead.
    Pointing OPENORION_CONFIG at a path that does not exist makes load_config()
    return pristine defaults.

    Tests carrying a live/cloud marker are exempt: those exist precisely to
    exercise the real service and are skipped elsewhere when it is absent.
    """
    if _LIVE_MARKERS & {m.name for m in request.node.iter_markers()}:
        return
    from orion.core.credentials import TOOL_CREDENTIALS

    # Every key the Connections screen can save is a secret too; saving one in
    # a test also sets os.environ, which otherwise leaks into later tests.
    saved_keys = {key for keys in TOOL_CREDENTIALS.values() for key in keys}
    for name in (*_CREDENTIAL_ENV_VARS, *sorted(saved_keys)):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(
        "OPENORION_CONFIG",
        str(tmp_path_factory.mktemp("orion-cfg") / "config.toml"),
    )
    # Saved credentials (~/.orion/credentials.toml) are the third leak: a
    # connector that reuses the Email login read the developer's real Gmail
    # app password and reported itself connected in a "no credentials" test.
    from orion.core import credentials as _credentials

    monkeypatch.setattr(
        _credentials,
        "_DEFAULT_PATH",
        tmp_path_factory.mktemp("orion-creds") / "credentials.toml",
    )
    _isolate_connector_files(monkeypatch, tmp_path_factory.mktemp("orion-connectors"))
    # The away flag decides whether Orion auto-replies to real contacts; a
    # test must never read or change the developer's.
    from orion.core import activity as _activity

    monkeypatch.setattr(_activity, "_STATE_PATH", tmp_path_factory.mktemp("orion-away") / "away_state.json")
    # Keep test bridge lifecycles out of the real WhatsApp bridge log.
    try:
        from orion.channels import whatsapp_baileys as _wa

        monkeypatch.setattr(_wa, "_BRIDGE_LOG_PATH", tmp_path_factory.mktemp("orion-wa-log") / "bridge.log")
    except Exception:
        pass


def _isolate_connector_files(monkeypatch, isolated_dir: Path) -> None:
    """Point every connector's token/credential file at an empty temp dir.

    Connector modules compute default paths under ~/.orion/connectors at
    import time. Once a developer actually connects Google, GitHub or Notion,
    "not connected without credentials" tests read those real files and fail.
    """
    import sys

    try:
        import orion.connectors  # noqa: F401  (loads every connector module)
        import orion.server.connections  # noqa: F401
    except Exception:
        return
    for name, module in list(sys.modules.items()):
        if module is None or not (name.startswith("orion.connectors") or name == "orion.server.connections"):
            continue
        for attr, value in list(vars(module).items()):
            if attr == "_CONNECTORS_DIR" and isinstance(value, Path):
                monkeypatch.setattr(module, attr, isolated_dir)
            elif attr.startswith("_") and attr.endswith("_PATH") and isinstance(value, (str, Path)):
                if ".orion" in str(value):
                    replacement = isolated_dir / Path(value).name
                    monkeypatch.setattr(module, attr, replacement if isinstance(value, Path) else str(replacement))


def pytest_collection_modifyitems(config, items):
    """Skip tests whose prerequisites are genuinely absent.

    These are marked as requiring a GPU, a running engine, a Docker daemon or
    real credentials. Without this they *fail* on a machine that simply does
    not have the thing, which buries real regressions in expected noise. A
    skip states the same fact honestly.
    """
    import platform as _platform
    import shutil as _shutil

    def _has_engine() -> bool:
        import urllib.request

        try:
            urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2)
            return True
        except Exception:
            return False

    def _has_gpu(vendor: str) -> bool:
        try:
            from orion.core.config import detect_hardware

            return any(g.vendor == vendor for g in (detect_hardware().gpus or []))
        except Exception:
            return False

    engine_ok: bool | None = None
    checks = {
        "cloud": lambda: any(
            os.environ.get(k)
            for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")
        ),
        "live_channel": lambda: any(os.environ.get(k) for k in _CREDENTIAL_ENV_VARS),
        "live_external": lambda: bool(
            os.environ.get("HERMES_AGENT_PATH") and os.environ.get("OPENCLAW_PATH")
        ),
        "docker": lambda: _shutil.which("docker") is not None,
        "nvidia": lambda: _has_gpu("nvidia"),
        "amd": lambda: _has_gpu("amd"),
        "apple": lambda: _platform.machine() in ("arm64", "aarch64")
        and _platform.system() == "Darwin",
        "macos15": lambda: _platform.system() == "Darwin"
        and int((_platform.mac_ver()[0] or "0").split(".")[0] or 0) >= 15,
    }

    for item in items:
        names = {m.name for m in item.iter_markers()}
        for marker, available in checks.items():
            if marker in names and not available():
                item.add_marker(
                    pytest.mark.skip(reason=f"requires {marker}: not available here")
                )
                break
        else:
            if "live" in names:
                if engine_ok is None:
                    engine_ok = _has_engine()
                if not engine_ok:
                    item.add_marker(
                        pytest.mark.skip(reason="requires a running inference engine")
                    )


_ALL_REGISTRIES = (
    ModelRegistry,
    EngineRegistry,
    MemoryRegistry,
    MinerRegistry,
    AgentRegistry,
    ToolRegistry,
    RouterPolicyRegistry,
    BenchmarkRegistry,
    ChannelRegistry,
    SpeechRegistry,
    CompressionRegistry,
    ConnectorRegistry,
    TTSRegistry,
    SkillRegistry,
)


@pytest.fixture(scope="session", autouse=True)
def _registry_snapshot():
    """The registry contents as imports left them, captured once per session.

    autouse so it is built before the first test runs. Created lazily it
    would snapshot whatever _clean_registries had already emptied.

    Registries populate as an import side effect -- importing orion.engine runs
    the @EngineRegistry.register decorators. Those decorators never run again,
    so once a unit test wipes a registry it stays empty for the rest of the
    session. Live integration tests are restored from this snapshot rather than
    merely skipping the wipe, which would still leave them with whatever an
    earlier test had already cleared.
    """
    import orion.agents  # noqa: F401
    import orion.engine  # noqa: F401
    import orion.tools  # noqa: F401

    return {reg: dict(reg._entries()) for reg in _ALL_REGISTRIES}


@pytest.fixture
def real_registries(request):
    """Restore the real, import-populated registries for this test.

    _clean_registries empties them for isolation, and the @register decorators
    only run once at import, so a test that needs the actual tool catalogue
    (routing behaviour, "is this tool wired up at all") otherwise sees nothing.
    Request this fixture instead of marking such a test `live`.
    """
    snapshot = request.getfixturevalue("_registry_snapshot")
    for reg, entries in snapshot.items():
        reg.clear()
        for key, value in entries.items():
            reg.register_value(key, value)
    return snapshot


@pytest.fixture(autouse=True)
def _clean_registries(request) -> None:
    """Give each unit test empty registries and a fresh event bus.

    Live integration tests instead get the real, fully populated registries --
    they build a whole system and would otherwise hit "No inference engine
    available" or "Unknown agent: orchestrator" with everything truly running.
    """
    if _LIVE_MARKERS & {m.name for m in request.node.iter_markers()}:
        snapshot = request.getfixturevalue("_registry_snapshot")
        for reg, entries in snapshot.items():
            reg.clear()
            for key, value in entries.items():
                reg.register_value(key, value)
        reset_event_bus()
        return
    ModelRegistry.clear()
    EngineRegistry.clear()
    MemoryRegistry.clear()
    MinerRegistry.clear()
    AgentRegistry.clear()
    ToolRegistry.clear()
    RouterPolicyRegistry.clear()
    BenchmarkRegistry.clear()
    ChannelRegistry.clear()
    SpeechRegistry.clear()
    CompressionRegistry.clear()
    ConnectorRegistry.clear()
    TTSRegistry.clear()
    SkillRegistry.clear()
    reset_event_bus()


# ---------------------------------------------------------------------------
# Hardware fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def nvidia_gpu() -> GpuInfo:
    """NVIDIA A100 GPU fixture."""
    return GpuInfo(vendor="nvidia", name="NVIDIA A100-SXM4-80GB", vram_gb=80.0, count=1)


@pytest.fixture
def nvidia_consumer_gpu() -> GpuInfo:
    """NVIDIA consumer GPU fixture."""
    return GpuInfo(
        vendor="nvidia",
        name="NVIDIA GeForce RTX 4090",
        vram_gb=24.0,
        count=1,
    )


@pytest.fixture
def nvidia_multi_gpu() -> GpuInfo:
    """NVIDIA multi-GPU fixture."""
    return GpuInfo(vendor="nvidia", name="NVIDIA H100", vram_gb=80.0, count=4)


@pytest.fixture
def amd_gpu() -> GpuInfo:
    """AMD MI300X GPU fixture."""
    return GpuInfo(vendor="amd", name="AMD Instinct MI300X", vram_gb=192.0, count=1)


@pytest.fixture
def apple_gpu() -> GpuInfo:
    """Apple Silicon GPU fixture."""
    return GpuInfo(vendor="apple", name="Apple M4 Max", vram_gb=128.0, count=1)


@pytest.fixture
def hardware_nvidia(nvidia_gpu: GpuInfo) -> HardwareInfo:
    """Full NVIDIA hardware profile."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="AMD EPYC 7763",
        cpu_count=64,
        ram_gb=512.0,
        gpu=nvidia_gpu,
    )


@pytest.fixture
def hardware_nvidia_consumer(nvidia_consumer_gpu: GpuInfo) -> HardwareInfo:
    """Consumer NVIDIA hardware profile."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="Intel Core i9-14900K",
        cpu_count=24,
        ram_gb=64.0,
        gpu=nvidia_consumer_gpu,
    )


@pytest.fixture
def hardware_amd(amd_gpu: GpuInfo) -> HardwareInfo:
    """Full AMD hardware profile."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="AMD EPYC 9654",
        cpu_count=96,
        ram_gb=768.0,
        gpu=amd_gpu,
    )


@pytest.fixture
def hardware_apple(apple_gpu: GpuInfo) -> HardwareInfo:
    """Apple Silicon hardware profile."""
    return HardwareInfo(
        platform="darwin",
        cpu_brand="Apple M4 Max",
        cpu_count=16,
        ram_gb=128.0,
        gpu=apple_gpu,
    )


@pytest.fixture
def hardware_cpu_only() -> HardwareInfo:
    """CPU-only hardware profile (no GPU)."""
    return HardwareInfo(
        platform="linux",
        cpu_brand="Intel Xeon E5-2686 v4",
        cpu_count=8,
        ram_gb=32.0,
        gpu=None,
    )


# ---------------------------------------------------------------------------
# Engine availability fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def has_ollama() -> bool:
    """Check if Ollama is running locally."""
    try:
        import httpx

        resp = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.fixture
def has_vllm() -> bool:
    """Check if vLLM is running locally."""
    try:
        import httpx

        resp = httpx.get("http://localhost:8000/v1/models", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.fixture
def has_llamacpp() -> bool:
    """Check if llama.cpp server is running locally."""
    try:
        import httpx

        resp = httpx.get("http://localhost:8080/v1/models", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Cloud API key fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def has_openai_key() -> bool:
    """Check if OPENAI_API_KEY is set."""
    return bool(os.environ.get("OPENAI_API_KEY"))


@pytest.fixture
def has_anthropic_key() -> bool:
    """Check if ANTHROPIC_API_KEY is set."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@pytest.fixture
def has_gemini_key() -> bool:
    """Check if GEMINI_API_KEY or GOOGLE_API_KEY is set."""
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


# ---------------------------------------------------------------------------
# Mock engine factory
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_engine():
    """Factory for mock InferenceEngine instances."""

    def _factory(
        engine_id: str = "mock",
        model_response: str = "Hello!",
        tool_calls: list | None = None,
        models: list[str] | None = None,
    ) -> MagicMock:
        engine = MagicMock()
        engine.engine_id = engine_id
        engine.health.return_value = True
        engine.list_models.return_value = models or ["test-model"]

        result = {
            "content": model_response,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "test-model",
            "finish_reason": "stop",
        }
        if tool_calls:
            result["tool_calls"] = tool_calls
            result["finish_reason"] = "tool_calls"
        engine.generate.return_value = result
        return engine

    return _factory


@pytest.fixture
def event_bus() -> EventBus:
    """Fresh EventBus with history recording enabled."""
    return EventBus(record_history=True)


# ---------------------------------------------------------------------------
# Mining sidecar fixtures (shared across tests/mining/ and tests/engine/)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_sidecar_payload() -> dict:
    """A valid vllm-pearl sidecar payload with all expected fields."""
    return {
        "provider": "vllm-pearl",
        "vllm_endpoint": "http://127.0.0.1:8000/v1",
        "model": "pearl-ai/Llama-3.3-70B-Instruct-pearl",
        "gateway_url": "http://127.0.0.1:8337",
        "gateway_metrics_url": "http://127.0.0.1:8339",
        "container_id": "abc123def456",
        "wallet_address": "prl1qexampleaddress",
        "started_at": 1714867200,
    }


@pytest.fixture
def sidecar_path(tmp_path: Path) -> Path:
    """Path to a (not-yet-written) mining sidecar JSON file."""
    return tmp_path / "mining.json"


@pytest.fixture
def written_sidecar(sidecar_path: Path, sample_sidecar_payload: dict) -> Path:
    """A written mining sidecar JSON file; returns the path."""
    sidecar_path.write_text(json.dumps(sample_sidecar_payload))
    return sidecar_path

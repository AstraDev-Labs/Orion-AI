"""NVIDIA NIM (NVIDIA Inference Microservice) inference engine backend."""

from __future__ import annotations

import logging
import os
from typing import List

import httpx

from orion.core.registry import EngineRegistry
from orion.engine._openai_compat import _OpenAICompatibleEngine

logger = logging.getLogger(__name__)


@EngineRegistry.register("nvidia")
class NvidiaNimEngine(_OpenAICompatibleEngine):
    """Inference engine for NVIDIA NIM (cloud-hosted and self-hosted)."""

    engine_id = "nvidia"
    _default_host = "https://integrate.api.nvidia.com"
    _api_prefix = "/v1"

    def __init__(
        self,
        host: str | None = None,
        *,
        api_key: str | None = None,
        timeout: float = 600.0,
    ) -> None:
        # Resolve target host priority: arg -> environment -> cloud default
        self._host = (
            host
            or os.environ.get("NVIDIA_NIM_HOST")
            or os.environ.get("NVIDIA_API_HOST")
            or self._default_host
        ).rstrip("/")

        # Resolve API key priority: arg -> environment variables
        key = (
            api_key
            or os.environ.get("NVIDIA_API_KEY")
            or os.environ.get("NVIDIA_NIM_API_KEY")
        )

        headers = {}
        if key:
            headers["Authorization"] = f"Bearer {key}"

        self._client = httpx.Client(
            base_url=self._host,
            headers=headers,
            timeout=timeout,
        )

    def health(self) -> bool:
        """Probe NIM integration connectivity.

        If we are using the public cloud integrate endpoint but no API key is
        present, we return False immediately to avoid useless requests.
        Otherwise, attempt a quick request to /models and accept both 200 (OK)
        and 401 (requires key but reachable) as healthy responses.
        """
        is_cloud_default = "integrate.api.nvidia.com" in self._host
        has_auth = "Authorization" in self._client.headers
        if is_cloud_default and not has_auth:
            return False

        try:
            resp = self._client.get(f"{self._api_prefix}/models", timeout=2.0)
            return resp.status_code in (200, 401)
        except Exception as exc:
            logger.debug(
                "NVIDIA NIM health check failed at %s: %s",
                self._host,
                exc,
            )
            return False

    def list_models(self) -> List[str]:
        """Fetch available NIM models.

        Falls back to a curated list of standard NVIDIA API Catalog models if
        the network request fails or requires authentication.
        """
        models = super().list_models()
        if not models:
            return [
                "meta/llama-3.3-70b-instruct",
                "nvidia/llama-3.1-nemotron-70b-instruct",
                "meta/llama-3.1-405b-instruct",
                "meta/llama-3.1-70b-instruct",
                "meta/llama-3.1-8b-instruct",
                "microsoft/phi-3-medium-128k-instruct",
                "mistralai/mistral-large-2-instruct",
            ]
        return models


__all__ = ["NvidiaNimEngine"]

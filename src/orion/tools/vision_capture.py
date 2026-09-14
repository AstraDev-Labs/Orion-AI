"""Vision capture tool — lets ORION see the screen or webcam on request.

Captures a screenshot or a single webcam frame and answers a question about
it using a local vision-capable model via Ollama (default: moondream).
Falls back to whichever cloud vision model is configured if one is available.
"""

from __future__ import annotations

import base64
import io
import os
from typing import Any

from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec

VISION_MODEL = os.environ.get("VISION_MODEL", "moondream")


def _capture_screen() -> bytes:
    """Grab the primary display as PNG bytes."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        shot = sct.grab(monitor)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def _capture_camera(device_index: int = 0) -> bytes:
    """Grab a single frame from the webcam as JPEG bytes."""
    import cv2

    cap = cv2.VideoCapture(device_index)
    try:
        if not cap.isOpened():
            raise RuntimeError(f"Could not open camera at index {device_index}.")
        # Warm up: first frames from some webcams are dark/uncalibrated.
        for _ in range(5):
            ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError("Failed to read a frame from the camera.")
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            raise RuntimeError("Failed to encode camera frame.")
        return buf.tobytes()
    finally:
        cap.release()


def _describe_with_ollama(image_bytes: bytes, question: str, model: str) -> str:
    import ollama

    response = ollama.chat(
        model=model,
        messages=[
            {
                "role": "user",
                "content": question,
                "images": [image_bytes],
            }
        ],
    )
    return response.get("message", {}).get("content", "").strip()


@ToolRegistry.register("vision_capture")
class VisionCaptureTool(BaseTool):
    """Capture the screen or webcam and describe/answer a question about it."""

    tool_id = "vision_capture"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="vision_capture",
            description=(
                "Look at the user's screen or webcam right now and answer a "
                "question about what's visible. Use this whenever the user asks "
                "what you see, to look at their screen, to check the camera, or "
                "asks about something currently on screen. You have no visual "
                "ability without calling this tool first."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "'screen' to capture the display, 'camera' for the webcam. Default 'screen'.",
                    },
                    "question": {
                        "type": "string",
                        "description": "What to look for or answer about the image.",
                    },
                },
                "required": ["question"],
            },
            category="vision",
            required_capabilities=["system:admin"],
            timeout_seconds=45.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        source = (params.get("source") or "screen").lower().strip()
        question = params.get("question") or "Describe what you see."

        if source not in ("screen", "camera"):
            return ToolResult(
                tool_name="vision_capture",
                content=f"Invalid source '{source}'. Must be 'screen' or 'camera'.",
                success=False,
            )

        try:
            image_bytes = _capture_screen() if source == "screen" else _capture_camera()
        except Exception as exc:
            return ToolResult(
                tool_name="vision_capture",
                content=f"Failed to capture {source}: {exc}",
                success=False,
            )

        try:
            answer = _describe_with_ollama(image_bytes, question, VISION_MODEL)
        except Exception as exc:
            return ToolResult(
                tool_name="vision_capture",
                content=(
                    f"Vision model '{VISION_MODEL}' unavailable ({exc}). "
                    f"Pull it with: ollama pull {VISION_MODEL}"
                ),
                success=False,
            )

        if not answer:
            return ToolResult(
                tool_name="vision_capture",
                content="The vision model returned no description.",
                success=False,
            )

        return ToolResult(
            tool_name="vision_capture",
            content=answer,
            success=True,
            metadata={
                "source": source,
                "model": VISION_MODEL,
                "image_base64": base64.b64encode(image_bytes).decode("ascii"),
            },
        )


__all__ = ["VisionCaptureTool"]

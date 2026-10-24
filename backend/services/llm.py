"""Pick the model that reads, splits and judges: any OpenAI-compatible endpoint (Toklens DeepSeek/GLM…) or Gemini.

LLM_API_KEY + LLM_BASE_URL selects the OpenAI-compatible endpoint; LLM_MODEL names the model, or the first
DeepSeek/GLM model the endpoint lists is used. Screenshots go to Gemini when GEMINI_API_KEY is set (it reads
images well), otherwise to LLM_VISION_MODEL on the same endpoint.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

from . import gemini

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("LLM_BASE_URL", "https://hkg.toklens.ai/v1").rstrip("/")
# v4.1-flash supports both fast mode (thinking disabled) and reasoning mode, plus multimodal vision.
PREFER = ("deepseek-v4.1-flash", "deepseek-v4-flash", "deepseek", "glm")
FALLBACK_MODEL = "deepseek-v4.1-flash"
CALL_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))

_client: httpx.AsyncClient | None = None
_model: str | None = os.getenv("LLM_MODEL") or None
_models: list[str] = []


class NoVision(RuntimeError):
    pass


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=120.0)
    return _client


def _key() -> str:
    return os.getenv("LLM_API_KEY", "")


def _vision_model() -> str:
    return os.getenv("LLM_VISION_MODEL") or (FALLBACK_MODEL if _key() else "")


def provider() -> str:
    return "openai" if _key() else "gemini" if os.getenv("GEMINI_API_KEY") else "none"


def can_read_images() -> bool:
    return bool(os.getenv("GEMINI_API_KEY") or _vision_model())


async def list_models() -> list[str]:
    global _models
    if not _models and _key():
        resp = await _http().get(f"{BASE_URL}/models", headers={"Authorization": f"Bearer {_key()}"})
        resp.raise_for_status()
        _models = sorted(m["id"] for m in resp.json().get("data", []) if m.get("id"))
        logger.info("models at %s: %s", BASE_URL, _models)
    return _models


async def _text_model() -> str:
    global _model
    if _model:
        return _model
    models = await list_models()
    for want in PREFER:
        hit = next((m for m in models if want in m.lower()), None)
        if hit:
            _model = hit
            break
    else:
        if not models:
            raise RuntimeError("LLM_MODEL is not set and the endpoint lists no models")
        _model = models[0]
    logger.info("using model %s", _model)
    return _model


def _parse_json(text: str) -> dict[str, Any]:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        return json.loads(fence.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError(f"model did not return JSON: {text[:200]}")


async def _chat(model: str, content: Any, thinking: str = "low") -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你只输出一个 JSON 对象，不要输出任何其他文字。"},
            {"role": "user", "content": content},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    if thinking == "minimal":
        body["thinking"] = {"type": "disabled"}
    headers = {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"}

    async def post() -> httpx.Response:
        # The upstream sometimes stalls or 503s; on retry, fall back to FALLBACK_MODEL with thinking disabled for speed.
        for attempt in range(2):
            if attempt:
                if body["model"] != FALLBACK_MODEL:
                    logger.warning("Falling back from %s to %s", body["model"], FALLBACK_MODEL)
                    body["model"] = FALLBACK_MODEL
                body["thinking"] = {"type": "disabled"}
            try:
                resp = await _http().post(f"{BASE_URL}/chat/completions", headers=headers, json=body,
                                          timeout=CALL_TIMEOUT)
            except httpx.TimeoutException:
                if attempt:
                    raise RuntimeError(f"LLM {body['model']} timed out twice ({CALL_TIMEOUT:.0f}s each)")
                logger.warning("LLM %s timed out after %.0fs, retrying with thinking disabled", body["model"], CALL_TIMEOUT)
                continue
            if resp.status_code < 500 or attempt:
                return resp
            logger.warning("LLM %s %s, retrying", body["model"], resp.status_code)
        return resp

    resp = await post()
    if resp.status_code == 400 and ("response_format" in resp.text or "thinking" in resp.text):
        body.pop("response_format", None)
        body.pop("thinking", None)
        resp = await post()
    if resp.status_code != 200:
        raise RuntimeError(f"LLM {body['model']} {resp.status_code}: {resp.text[:300]}")
    return _parse_json(resp.json()["choices"][0]["message"].get("content") or "")


async def generate_json(prompt: str, image_b64: str | None = None, mime: str = "image/jpeg",
                        thinking: str = "low") -> dict[str, Any]:
    if not _key():
        return await gemini.generate_json(prompt, image_b64, mime, thinking)
    if not image_b64:
        return await _chat(await _text_model(), prompt, thinking=thinking)
    if os.getenv("GEMINI_API_KEY"):
        return await gemini.generate_json(prompt, image_b64, mime, thinking)
    vision = _vision_model()
    if not vision:
        raise NoVision("还没有配置能看图的模型，请把截图里的文字粘贴进来")
    return await _chat(vision, [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
        {"type": "text", "text": prompt},
    ], thinking=thinking)

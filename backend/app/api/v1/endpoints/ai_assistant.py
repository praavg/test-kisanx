"""Bring-your-own-key chat proxy. User keys are request-scoped and never persisted."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["optional AI assistant"])


class ChatRequest(BaseModel):
    provider: str = Field(pattern="^(gemini|openai|anthropic|openai-compatible)$")
    model: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=8000)
    base_url: str | None = Field(default=None, max_length=500)


def _public_https_url(raw: str) -> str:
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="Custom provider URL must be an HTTPS URL without embedded credentials.")
    if parsed.port not in (None, 443) or parsed.query or parsed.fragment:
        raise HTTPException(status_code=422, detail="Custom provider URL must use standard HTTPS without query or fragment values.")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal")):
        raise HTTPException(status_code=422, detail="Local or private-network provider URLs are not allowed.")
    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise HTTPException(status_code=422, detail="Could not resolve the custom provider host.") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise HTTPException(status_code=422, detail="Custom provider host must resolve only to public IP addresses.")
    return raw.rstrip("/")


@router.post("/ai/chat")
async def optional_ai_chat(payload: ChatRequest, x_provider_api_key: str | None = Header(default=None, alias="X-Provider-API-Key")) -> dict:
    if not x_provider_api_key or len(x_provider_api_key) > 4096:
        raise HTTPException(status_code=400, detail="Enter your provider API key in Settings. It is used only for this request.")
    if payload.provider == "gemini":
        url = "https://generativelanguage.googleapis.com/v1beta/interactions"
        headers = {"x-goog-api-key": x_provider_api_key}
        body = {"model": payload.model, "input": payload.message, "store": False}
    elif payload.provider == "openai":
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {x_provider_api_key}"}
        body = {"model": payload.model, "messages": [{"role": "user", "content": payload.message}]}
    elif payload.provider == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        headers = {"x-api-key": x_provider_api_key, "anthropic-version": "2023-06-01"}
        body = {"model": payload.model, "max_tokens": 1200, "messages": [{"role": "user", "content": payload.message}]}
    else:
        if not payload.base_url:
            raise HTTPException(status_code=422, detail="Enter an OpenAI-compatible HTTPS base URL in Settings.")
        base = _public_https_url(payload.base_url)
        url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        headers = {"Authorization": f"Bearer {x_provider_api_key}"}
        body = {"model": payload.model, "messages": [{"role": "user", "content": payload.message}]}
    try:
        async with httpx.AsyncClient(timeout=35, follow_redirects=False) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
        if payload.provider == "gemini":
            answer = "".join(part.get("text", "") for step in data["steps"] if step.get("type") == "model_output" for part in step.get("content", []) if part.get("type") == "text")
        elif payload.provider == "anthropic":
            answer = "".join(block.get("text", "") for block in data["content"] if block.get("type") == "text")
        else:
            answer = data["choices"][0]["message"]["content"]
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Empty model response")
    except httpx.HTTPStatusError as exc:
        # Avoid echoing provider error bodies which may contain sensitive request data.
        raise HTTPException(status_code=502, detail=f"{payload.provider} rejected the request (HTTP {exc.response.status_code}); check the key, model and provider account.") from exc
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail=f"{payload.provider} is unavailable or returned an unexpected response.") from exc
    return {"provider": payload.provider, "model": payload.model, "answer": answer, "key_storage": "request_only"}

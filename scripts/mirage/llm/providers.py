"""
MIRAGE — Somut LLM sağlayıcıları (OpenAI, Anthropic).

Her sağlayıcı `LLMProvider` arayüzünü uygular. HTTP katmanı enjekte
edilebilir (`client`), böylece testler ağa çıkmadan gerçek kod yolunu
doğrular (mock yerine sahte HTTP taşıyıcısı).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .provider import LLMConfigError, LLMError, LLMMessage, LLMProvider, LLMResponse

if TYPE_CHECKING:  # httpx yalnızca sağlayıcı kullanıldığında gerekir (opsiyonel bağımlılık).
    import httpx

OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
ANTHROPIC_DEFAULT_MODEL = "claude-3-5-haiku-latest"


class _HTTPProvider(LLMProvider):
    """Ortak HTTP taşıyıcı yönetimi."""

    def __init__(self, *, client: Optional[httpx.AsyncClient] = None, timeout: float = 30.0):
        self._client = client
        self._timeout = timeout

    async def _post(self, url: str, *, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        import httpx  # opsiyonel bağımlılık: yalnızca gerçek çağrıda gerekir.

        owns = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            resp = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:  # ağ hataları
            raise LLMError(f"{self.name}: HTTP error: {exc}") from exc
        finally:
            if owns:
                await client.aclose()
        if resp.status_code >= 400:
            raise LLMError(
                f"{self.name}: provider returned {resp.status_code}: {resp.text[:300]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise LLMError(f"{self.name}: invalid JSON response") from exc


class OpenAIProvider(_HTTPProvider):
    name = "openai"
    ENDPOINT = "https://api.openai.com/v1/chat/completions"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = OPENAI_DEFAULT_MODEL,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 30.0,
    ):
        super().__init__(client=client, timeout=timeout)
        if not api_key:
            raise LLMConfigError("openai: api_key is required")
        self._api_key = api_key
        self._model = model

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        body = await self._post(
            self.ENDPOINT,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "content-type": "application/json",
            },
            payload=payload,
        )
        try:
            text = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"openai: unexpected response shape: {str(body)[:200]}") from exc
        return LLMResponse(text=text, provider=self.name, model=self._model, raw=body)


class AnthropicProvider(_HTTPProvider):
    name = "anthropic"
    ENDPOINT = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = ANTHROPIC_DEFAULT_MODEL,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 30.0,
    ):
        super().__init__(client=client, timeout=timeout)
        if not api_key:
            raise LLMConfigError("anthropic: api_key is required")
        self._api_key = api_key
        self._model = model

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> LLMResponse:
        # Anthropic system prompt'u ayrı bir alanda bekler.
        system_parts = [m.content for m in messages if m.role == "system"]
        convo = [m for m in messages if m.role != "system"]
        if json_mode:
            system_parts.append("Respond with a single valid JSON object and nothing else.")
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": m.role, "content": m.content} for m in convo],
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        body = await self._post(
            self.ENDPOINT,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": self.API_VERSION,
                "content-type": "application/json",
            },
            payload=payload,
        )
        try:
            blocks = body["content"]
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (KeyError, TypeError) as exc:
            raise LLMError(f"anthropic: unexpected response shape: {str(body)[:200]}") from exc
        return LLMResponse(text=text, provider=self.name, model=self._model, raw=body)

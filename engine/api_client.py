import json
import requests


class ApiError(Exception):
    def __init__(self, code: int, body: str, retry_after: int | None = None):
        self.code = code
        self.body = body
        self.retry_after = retry_after
        super().__init__(f"API Error {code}: {body}")


class ApiClient:
    """LLM API client supporting OpenAI-compatible and Anthropic formats."""

    SYSTEM_PROMPT = "你是一个专业的聊天分析助手。你的输出必须是严格的JSON格式。"

    def __init__(
        self,
        api_url: str,
        api_key: str,
        model: str = "deepseek-chat",
        temperature: float = 0.3,
        api_format: str = "openai",
    ):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.api_format = api_format
        self._session = requests.Session()

    def chat_completion(self, prompt: str, timeout: int = 120,
                        system_prompt: str | None = None,
                        model: str | None = None) -> dict:
        """Send a chat completion request and return parsed JSON response."""
        sp = system_prompt if system_prompt is not None else self.SYSTEM_PROMPT
        m = model if model else self.model
        if self.api_format == "anthropic":
            return self._anthropic_chat(prompt, timeout, sp, m)
        return self._openai_chat(prompt, timeout, sp, m)

    # ---- OpenAI-compatible path ----

    def _openai_chat(self, prompt: str, timeout: int,
                     system_prompt: str, model: str) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
        }
        chat_url = self.api_url + "/chat/completions"
        try:
            resp = self._session.post(
                chat_url, headers=headers, json=payload, timeout=timeout,
            )
        except requests.Timeout:
            raise ApiError(0, "timeout", None)
        except requests.ConnectionError:
            raise ApiError(0, "connection_error", None)

        return self._handle_response(resp)

    # ---- Anthropic Messages API path ----

    def _anthropic_chat(self, prompt: str, timeout: int,
                        system_prompt: str, model: str) -> dict:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 4096,
            "temperature": self.temperature,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": prompt},
            ],
        }
        chat_url = self.api_url + "/messages"
        try:
            resp = self._session.post(
                chat_url, headers=headers, json=payload, timeout=timeout,
            )
        except requests.Timeout:
            raise ApiError(0, "timeout", None)
        except requests.ConnectionError:
            raise ApiError(0, "connection_error", None)

        return self._handle_response(resp)

    # ---- Response handling (shared) ----

    def _handle_response(self, resp: requests.Response) -> dict:
        if resp.status_code == 401 or resp.status_code == 403:
            raise ApiError(resp.status_code, resp.text, None)
        if resp.status_code == 429:
            retry_after = None
            try:
                retry_after = int(resp.headers.get("Retry-After", 0))
            except (ValueError, TypeError):
                pass
            raise ApiError(429, resp.text, retry_after)
        if resp.status_code != 200:
            raise ApiError(resp.status_code, resp.text, None)

        try:
            data = resp.json()
        except json.JSONDecodeError:
            snippet = resp.text[:200]
            raise ApiError(resp.status_code, snippet, None)

        return data

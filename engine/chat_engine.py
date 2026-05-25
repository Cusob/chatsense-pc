from models.chat_message import ChatMessage
from models.analysis_result import AnalysisResult, DimensionScores


class ChatEngine:
    """LLM chat engine: builds prompt with context, calls API."""

    def __init__(self, api_client):
        self._client = api_client

    def chat(self, user_input: str, contact_name: str,
             messages: list[ChatMessage],
             analysis_result: AnalysisResult | None,
             history: list[dict],
             config: dict,
             ) -> dict:
        deep_think = config.get("deep_think", False)
        web_search = config.get("web_search", False)

        # ---- Build prompt ----
        parts = []

        parts.append(
            f"你是聊天顾问，正在帮助用户分析与\"{contact_name}\"的对话。"
            f"请基于聊天记录给出具体、可操作的建议。回答简洁直接，不要客套。"
        )

        if config.get("include_analysis") and analysis_result:
            parts.append(self._format_analysis(analysis_result))

        if config.get("include_messages") and messages:
            parts.append(f"以下是与\"{contact_name}\"的聊天记录：")
            for m in messages:
                role = "我" if m.is_from_me else "对方"
                parts.append(f"[{role}] {m.display_text}")

        # ---- Web search (injected between messages and history) ----
        sources = None
        if web_search:
            search_text, sources = self._web_search(user_input)
            if search_text:
                parts.append(search_text)

        if history:
            parts.append("---")
            for h in history:
                role = "用户" if h["role"] == "user" else "助手"
                parts.append(f"{role}: {h['content']}")

        parts.append(f"---\n用户问题: {user_input}")

        prompt = "\n".join(parts)

        # ---- API call with deep-think model override and retry ----
        model = "deepseek-reasoner" if deep_think else None

        try:
            response = self._client.chat_completion(
                prompt,
                system_prompt="你是聊天顾问。用简洁直接的中文回答用户问题。",
                model=model,
            )
        except Exception:
            if deep_think:
                # Retry with default model when reasoning model fails
                response = self._client.chat_completion(
                    prompt,
                    system_prompt="你是聊天顾问。用简洁直接的中文回答用户问题。",
                    model=None,
                )
            else:
                raise

        # ---- Extract answer and reasoning from response ----
        answer = ""
        reasoning = None

        if isinstance(response, dict):
            choices = response.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                answer = message.get("content", "")
                reasoning = message.get("reasoning_content", None)
            else:
                content_list = response.get("content", [])
                if content_list:
                    answer = content_list[0].get("text", "")

        if not answer:
            answer = str(response)

        return {"answer": answer, "reasoning": reasoning, "sources": sources}

    # ---- Web search helper ----

    @staticmethod
    def _web_search(query: str) -> tuple[str | None, list | None]:
        """Call web search and return (formatted_text, sources_list).

        Returns (None, None) on any failure -- fault tolerant by design.
        """
        try:
            import requests
            resp = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1,
                        "t": "ChatSense"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("RelatedTopics", [])[:5]
                if results:
                    lines = ["[网络搜索结果]"]
                    sources = []
                    for r in results:
                        text = r.get("Text", "")
                        url = r.get("FirstURL", "")
                        if text:
                            lines.append(f"- {text}")
                            sources.append({
                                "title": text[:100],
                                "url": url,
                                "snippet": text,
                            })
                    return "\n".join(lines), sources
        except Exception:
            pass
        return None, None

    @staticmethod
    def _format_analysis(result: AnalysisResult) -> str:
        lines = [f"当前分析: 阶段={result.stage or '未知'}"]
        scores_parts = []
        for key, name in DimensionScores().dimension_names():
            scores_parts.append(f"{name}({getattr(result.scores, key, 0)})")
        lines.append("评分: " + " ".join(scores_parts))
        if result.strengths:
            lines.append("优势: " + "; ".join(result.strengths[:3]))
        if result.warnings:
            lines.append("警告: " + "; ".join(result.warnings[:3]))
        return "\n".join(lines)

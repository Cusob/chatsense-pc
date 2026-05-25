import json
import sqlite3
import time

from models.chat_message import ChatMessage
from models.analysis_result import AnalysisResult, DimensionScores
from engine.api_client import ApiClient, ApiError
from config.settings import CACHE_DB_PATH, ensure_config_dir


ANNOTATION_PROMPT = (
    "## 角色\n"
    "你是一个专业的聊天对话标注助手。你的任务是对以下男女聊天记录进行精确的结构化标注。\n\n"
    "## 标注规则\n"
    "逐条处理消息。对每条\"我\"（男性）的消息标注以下字段，不需要时省略为null或false：\n\n"
    "**基础字段：**\n"
    "- content_length: 消息内容字符数\n"
    "- emotion_signal: 我表达的情绪（null/\"开心\"/\"难过\"/\"疲惫\"/\"焦虑\"/\"撒娇\"/\"调侃\"/\"抱怨\"/\"分享\"）\n"
    "- question_type: 提问类型（null/\"open\"开放/\"closed\"封闭）\n"
    "- ends_with_question: 是否以问句结尾（true/false）\n\n"
    "**行为特征字段：**\n"
    "- is_self_centered: 该消息主要内容是夸耀自己（成就、收入、能力）→true\n"
    "- is_praise: 该消息是对对方的赞美但无实质内容（\"你好漂亮\"）→true\n"
    "- is_excessive_praise: 赞美脱离上下文（对方未做相关展示就被过度恭维），或该对话中赞美频率异常高→true\n"
    "- is_template: 疑似话术模板（生硬的冷读、套用公式的表达、不自然的开场白）→true\n"
    "- is_empathizing: 对对方最近一条情绪信号做出了共情回应（认可感受、表示理解），而非说教/解决问题/忽视→true\n"
    "- politely_disagree: 礼貌表达不同意见（\"我觉得不一定\"\"也有另一种可能\"），而非一味附和→true\n"
    "- is_private_question: 私人问题（年龄、收入、住处、感情经历、家庭背景等）→true\n"
    "- is_confirmation: 确认类消息（\"在吗\"\"睡了吗\"\"起了吗\"\"吃了吗\"）→true\n"
    "- is_sensitive_topic: 敏感话题（前任、政治、宗教、收入攀比）→true\n"
    "- self_contradictory: 同一话题前后立场不一致→true\n\n"
    "**对话结构字段：**\n"
    "- topic_id: 从1开始递增的整数，同一话题用相同id。自然延伸不算新话题，明显转折才算\n"
    "- is_new_topic: 开启了一个明显的新话题→true\n"
    "- has_invitation: 包含邀约（一起做某事、见面、打电话、\"有空一起\"）→true\n"
    "- topic_transition_natural: 话题过渡自然，是在对方话题基础上的延伸→true\n"
    "- escalation_natural: 自然升级关系（适度暧昧、深度情感分享、拉近距离）→true\n"
    "- escalation_forced: 强行升级（不合适时机告白、过早亲密称呼、对方明显回避时硬推进）→true\n\n"
    "---\n"
    "对每条\"对方\"（女性）的消息标注：\n"
    "- emotion_signal: 同上（null/\"开心\"/\"难过\"/\"疲惫\"/\"焦虑\"/\"撒娇\"/\"调侃\"/\"抱怨\"/\"分享\"）\n"
    "- is_short_response: 是否极短回应（\"嗯\"\"哦\"\"好\"\"行\"\"哈哈\"\"😂\"等，不超过3字）→true\n"
    "- content_length: 消息内容字符数\n\n"
    "## 对话结构标注\n"
    "1. rounds: 将对话按自然轮次分割，每轮标注initiator（\"我\"或\"对方\"）。一轮指围绕一个主题的来回对话\n"
    "2. unanswered_segments: 对方最后一条消息后，我继续发消息但对方无回应的片段。间隔<60秒的多条算同一段\n"
    "   每段需包含：start_index, end_index, message_count, avg_interval_s\n"
    "3. stage: 对话所处阶段——\"初识期\"|\"熟悉期\"|\"暧昧期\"|\"亲密期\"。\n"
    "   初识期=刚加好友/matched，对话以基本信息交换为主\n"
    "   熟悉期=有过多次对话，话题扩展到生活/兴趣/观点\n"
    "   暧昧期=有明显情感信号、互相试探、亲密称呼\n"
    "   亲密期=确认关系后\n\n"
    "## 输出格式\n"
    "返回严格JSON，不要有任何额外文字。Schema: "
    "{{\"messages\":[{{\"index\":0,\"timestamp\":1700,\"role\":\"我\",\"content\":\"...\",\"annotations\":{{...}}}}],"
    "\"rounds\":[{{\"start_index\":0,\"end_index\":5,\"initiator\":\"我\"}}],"
    "\"unanswered_segments\":[],\"stage\":\"熟悉期\"}}\n\n"
    "## 聊天记录\n{chat_history}\n"
)

FEEDBACK_PROMPT = """## 角色
你是一个专业的异性沟通分析顾问，面向男性用户提供具体、可操作的聊天改进建议。

## 任务
分析以下已标注的聊天对话和8维评分结果。
**必须为全部8个维度生成详细分析**（每个维度一条），无论分数高低都要有具体分析和证据。

## 核心原则
1. 分数只是参考——你的分析必须基于具体聊天内容，引用实际对话片段作为证据
2. 每个维度的分析需要：描述具体表现 + 引用对话证据 + 给出可操作建议
3. 高分维度同样需要分析——说明是什么具体行为让这个维度做得不错
4. 语气客观分析而非评判——你是分析者，不是打分者

## 8维定义
- boundary(分寸感): 是否尊重对方的个人空间和边界，避免过度追问/侵犯隐私
- empathy(共情力): 对方表达情绪时，是否先理解感受而非直接给建议或忽视
- interaction(你来我往): 双方发言的平衡度，是否存在一方主导或回应过短
- self_disclosure(自我展示): 展示自己的程度——太少对方不了解你，太多显得自我中心
- naturalness(自然度): 对话是否自然流畅，有无模板感或生硬感
- initiative(主动性): 发起话题和分享的程度——太少太被动，太多给对方压力
- authenticity(真诚感): 表达是否真实自然，有无明显话术、套路或过度恭维
- escalation(升温力): 关系推进的自然程度——是否在合适的时机表达好感和推进关系

## 输出格式
返回严格JSON（不要markdown包裹），dimension_analysis数组必须恰好8个元素：
{{
  "dimension_analysis": [
    {{
      "dimension": "boundary",
      "score": 75,
      "analysis": "2-3句话描述该维度的具体表现。要求：引用对话作为证据（如第X轮对方说...你回复...），结合分数但不依赖分数，分析实际行为模式，即使分数高也要说明什么做对了"
    }},
    ... 共8个，涵盖全部维度 ...
  ],
  "strengths": ["一句话点出最亮眼的3-5个具体表现，不超过30字"],
  "warnings": ["严重问题的警告，需紧急关注，不超过30字"],
  "sample_reply": "仅在有明确需要时提供(5-30字)"
}}

## 数据
标注对话：
{annotated_messages}

评分明细：
{scores_summary}

对话阶段：{stage}
"""


FALLBACK_PROMPT = (
    "你是一个聊天分析助手。分析以下聊天对话，从8个维度评分(0-100)，"
    "并给出strengths、improvements、warnings和可选的sample_reply。\n\n"
    "聊天记录：\n{chat_history}\n\n"
    "维度：分寸感(boundary)、共情力(empathy)、你来我往(interaction)、自我展示(self_disclosure)、"
    "自然度(naturalness)、主动性(initiative)、真诚感(authenticity)、升温力(escalation)。\n"
    "返回严格JSON格式。"
)


class AnalysisEngine:
    """LLM-based analysis engine running in a QThread."""

    def __init__(self, api_client: ApiClient):
        self.api_client = api_client
        self._init_cache_db()

    def _init_cache_db(self):
        ensure_config_dir()
        conn = sqlite3.connect(CACHE_DB_PATH)
        conn.execute("PRAGMA busy_timeout = 3000")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS analyses (
                contact_wxid TEXT,
                timestamp INTEGER,
                json_result TEXT
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_analyses_lookup ON analyses(contact_wxid, timestamp DESC)"
        )
        conn.commit()
        conn.close()

    def get_cached_result(self, contact_wxid: str) -> AnalysisResult | None:
        try:
            conn = sqlite3.connect(CACHE_DB_PATH)
            conn.execute("PRAGMA busy_timeout = 3000")
            cur = conn.execute(
                "SELECT json_result FROM analyses WHERE contact_wxid = ? ORDER BY timestamp DESC LIMIT 1",
                (contact_wxid,),
            )
            row = cur.fetchone()
            conn.close()
            if row:
                return AnalysisResult.from_dict(json.loads(row[0]))
        except (sqlite3.Error, json.JSONDecodeError):
            pass
        return None

    def _save_to_cache(self, contact_wxid: str, result: AnalysisResult):
        try:
            conn = sqlite3.connect(CACHE_DB_PATH)
            conn.execute("PRAGMA busy_timeout = 3000")
            conn.execute(
                "INSERT INTO analyses (contact_wxid, timestamp, json_result) VALUES (?, ?, ?)",
                (
                    contact_wxid,
                    int(time.time()),
                    json.dumps(
                        {
                            "scores": result.scores.to_dict(),
                            "strengths": result.strengths,
                            "improvements": result.improvements,
                            "warnings": result.warnings,
                            "sample_reply": result.sample_reply,
                            "stage": result.stage,
                            "debug_log": result.debug_log,
                            "dimension_advice": result.dimension_advice,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            conn.commit()
            conn.close()
        except sqlite3.Error:
            pass

    def analyze(
        self, messages: list[ChatMessage], contact_wxid: str = ""
    ) -> AnalysisResult:
        text_messages = [m for m in messages if m.is_text]
        debug = []
        debug.append(f"[1/3] 文本消息数: {len(text_messages)} (需要 ≥5)")

        if len(text_messages) < 5:
            debug.append("[结果] 消息不足，返回空结果")
            return AnalysisResult.empty()

        # Build chat history
        lines = []
        for m in text_messages:
            role = "我" if m.is_from_me else "对方"
            lines.append(f"[{role}] {m.display_text}")
        chat_history = "\n".join(lines)
        debug.append(f"  聊天记录 {len(lines)} 行, {len(chat_history)} 字符")

        # Stage 1: Annotation
        debug.append(f"[2/3] 标注阶段: 调用 LLM...")
        annotation_prompt = ANNOTATION_PROMPT.format(chat_history=chat_history)
        try:
            response = self.api_client.chat_completion(annotation_prompt)
            debug.append(f"  API 响应成功")
            annotated = self._parse_annotation(response)
        except ApiError as e:
            debug.append(f"  [失败] 标注 API 错误: code={e.code} body={e.body[:100]}")
            return self._fallback_analyze(chat_history, debug)

        if annotated is None:
            content = self._extract_content(response)
            debug.append(f"  [失败] 标注 JSON 解析失败。raw (前200字符): {content[:200]}")
            return self._fallback_analyze(chat_history, debug)

        debug.append(f"  标注完成: {len(annotated.get('messages',[]))} 条消息, stage={annotated.get('stage','?')}")

        # Stage 2: Scoring
        debug.append(f"[3/3] 评分阶段: Python 计算 8 维分数...")
        from engine.scoring import calculate_scores
        try:
            scores = calculate_scores(annotated)
            for k, v in scores.items():
                debug.append(f"  {k}: {v}")
        except Exception as e:
            debug.append(f"  [失败] 评分计算异常: {e}")
            return self._fallback_analyze(chat_history, debug)

        scores_summary = {k: {"score": v} for k, v in scores.items()}
        num_msgs = len(annotated.get("messages", []))

        # Stage 3: Feedback
        debug.append(f"  反馈阶段: 调用 LLM ({num_msgs} 条标注消息)...")
        feedback_prompt = FEEDBACK_PROMPT.format(
            annotated_messages=json.dumps(annotated["messages"], ensure_ascii=False),
            scores_summary=json.dumps(scores_summary, ensure_ascii=False),
            stage=annotated.get("stage", "熟悉期"),
        )
        try:
            response2 = self.api_client.chat_completion(feedback_prompt)
            feedback = self._parse_feedback(response2)
            dim_count = len(feedback.get('dimension_analysis', []))
            imp_count = len(feedback.get('improvements', []))
            debug.append(f"  反馈完成: dimension_analysis={dim_count}, improvements={imp_count}, "
                         f"strengths={len(feedback.get('strengths',[]))}")
        except ApiError as e:
            debug.append(f"  [警告] 反馈 API 错误: code={e.code}")
            feedback = {}

        result_scores = DimensionScores.from_dict(scores) if scores else DimensionScores()
        dimension_analysis = feedback.get("dimension_analysis", [])
        # Fallback: if LLM didn't return dimension_analysis, use old improvements format
        if not dimension_analysis:
            dimension_analysis = feedback.get("improvements", [])
        result = AnalysisResult(
            scores=result_scores,
            strengths=feedback.get("strengths", []),
            improvements=dimension_analysis,
            warnings=feedback.get("warnings", []),
            sample_reply=feedback.get("sample_reply", ""),
            stage=annotated.get("stage", ""),
            debug_log="\n".join(debug),
            dimension_advice=[],
        )

        if contact_wxid:
            self._save_to_cache(contact_wxid, result)
        return result

    def _fallback_analyze(self, chat_history: str,
                          debug: list | None = None) -> AnalysisResult:
        if debug is None:
            debug = []
        debug.append("[回退] 标注失败，尝试单阶段分析...")
        prompt = FALLBACK_PROMPT.format(chat_history=chat_history)
        try:
            response = self.api_client.chat_completion(prompt)
            data = self._parse_feedback(response)
        except ApiError as e:
            debug.append(f"[失败] 回退 API 错误: code={e.code}")
            raise
        if data:
            scores = data.get("scores", {})
            if not scores:
                # LLM may return flat scores without 'scores' wrapper
                dim_keys = {"boundary", "empathy", "interaction", "self_disclosure",
                           "naturalness", "initiative", "authenticity", "escalation"}
                flat = {k: v for k, v in data.items() if k in dim_keys}
                if flat:
                    scores = flat
            debug.append(f"[回退] 完成: {len(scores)} 维评分")
            debug.append(f"  分数: {scores}")
            result_scores = DimensionScores.from_dict(scores)
            return AnalysisResult(
                scores=result_scores,
                strengths=data.get("strengths", []),
                improvements=data.get("improvements", []),
                warnings=data.get("warnings", []),
                sample_reply=data.get("sample_reply", ""),
                stage="简化评估",
                debug_log="\n".join(debug),
                dimension_advice=[],
            )
        debug.append("[失败] 回退 LLM 返回无效 JSON")
        raise ApiError(0, "all_stages_failed", None)

    def _parse_annotation(self, response: dict) -> dict | None:
        content = self._extract_content(response)
        if not content:
            return None
        try:
            data = json.loads(content)
            if "messages" not in data:
                return None
            return data
        except (json.JSONDecodeError, KeyError):
            import re
            m = re.search(r'```(?:json)?\s*\n?(.{5,}?)\n?```', content, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1).strip())
                    if "messages" in data:
                        return data
                except (json.JSONDecodeError, KeyError):
                    pass
            return None

    def _parse_feedback(self, response: dict) -> dict:
        content = self._extract_content(response)
        if not content:
            return {}
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # LLM may wrap JSON in markdown ``` blocks
            import re
            m = re.search(r'```(?:json)?\s*\n?(.{5,}?)\n?```', content, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(1).strip())
                except json.JSONDecodeError:
                    pass
            return {}

    def _extract_content(self, response: dict) -> str:
        choices = response.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        anthropic_content = response.get("content", [])
        if anthropic_content:
            return anthropic_content[0].get("text", "")
        return ""

    def check_one_way(self, messages: list[ChatMessage]) -> bool:
        """Check if the conversation is one-way (only one side sends messages)."""
        text_messages = [m for m in messages if m.is_text]
        if not text_messages:
            return False
        from_me = any(m.is_from_me for m in text_messages)
        from_other = any(not m.is_from_me for m in text_messages)
        return not (from_me and from_other)

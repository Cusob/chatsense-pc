from dataclasses import dataclass, field


@dataclass
class ChatMessage:
    msg_svr_id: int
    msg_type: int
    is_send: int  # 0=received, 1=sent
    create_time: int  # Unix timestamp
    talker: str  # wxid of the contact
    content: str
    transcript: str | None = None

    @property
    def display_text(self) -> str:
        """显示/分析用文字：transcript 优先。非文本消息回退到 type_label。"""
        if self.transcript:
            return self.transcript
        if self.msg_type == 1:
            return self.content
        return self.get_type_label()

    @property
    def is_text(self) -> bool:
        if self.msg_type == 1:
            return True
        if self.msg_type in (34, 47) and self.transcript:
            return True
        return False

    @property
    def is_from_me(self) -> bool:
        return self.is_send == 1

    @property
    def sender_label(self) -> str:
        return "我" if self.is_from_me else "对方"

    def get_type_label(self) -> str:
        if self.msg_type == 1:
            return ""
        if self.msg_type == 3:
            return "[图片]"
        if self.msg_type == 34:
            return "[语音]"
        if self.msg_type == 43:
            return "[视频]"
        if self.msg_type == 47:
            return "[表情]"
        if self.msg_type == 49:
            return "[链接/文件]"
        return f"[类型:{self.msg_type}]"

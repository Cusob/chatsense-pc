from models.chat_message import ChatMessage


class TestChatMessageIsText:
    def test_text_message_is_text(self):
        msg = ChatMessage(1, 1, 1, 100, "wx", "hello")
        assert msg.is_text is True

    def test_voice_with_transcript_is_text(self):
        msg = ChatMessage(2, 34, 0, 100, "wx", "<xml>...</xml>", transcript="ni hao")
        assert msg.is_text is True

    def test_voice_without_transcript_not_text(self):
        msg = ChatMessage(3, 34, 0, 100, "wx", "<xml>...</xml>")
        assert msg.is_text is False

    def test_emoji_with_transcript_is_text(self):
        msg = ChatMessage(4, 47, 0, 100, "wx", "<xml>...</xml>", transcript="[\u5fae\u7b11]")
        assert msg.is_text is True

    def test_emoji_without_transcript_not_text(self):
        msg = ChatMessage(5, 47, 0, 100, "wx", "<xml>...</xml>")
        assert msg.is_text is False

    def test_image_not_text(self):
        msg = ChatMessage(6, 3, 0, 100, "wx", "")
        assert msg.is_text is False

    def test_display_text_transcript_priority(self):
        msg = ChatMessage(7, 1, 0, 100, "wx", "yuan wen", transcript="transcript")
        assert msg.display_text == "transcript"

    def test_display_text_text_fallback(self):
        msg = ChatMessage(8, 1, 0, 100, "wx", "ni hao")
        assert msg.display_text == "ni hao"

    def test_display_text_voice_fallback(self):
        """No transcript voice falls back to get_type_label()"""
        msg = ChatMessage(9, 34, 0, 100, "wx", "<xml>...</xml>")
        assert msg.display_text == "[\u8bed\u97f3]"

    def test_display_text_emoji_fallback(self):
        msg = ChatMessage(10, 47, 0, 100, "wx", "<xml>...</xml>")
        assert msg.display_text == "[\u8868\u60c5]"

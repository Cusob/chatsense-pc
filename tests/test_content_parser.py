import os

import pytest
from engine.content_parser import ContentParser


class TestParseVoice:
    def test_valid_voice_xml(self):
        xml = '<msg><voicemsg endflag="1" voicelength="5000" bufid="3057020100abcd" /></msg>'
        file_path, duration = ContentParser.parse_voice(xml, "/wechat/wxid/Msg")
        assert file_path == os.path.normpath("/wechat/wxid/Msg/3057020100abcd.amr")
        assert duration == 5000

    def test_voice_xml_no_bufid(self):
        xml = '<msg><voicemsg endflag="1" voicelength="3000" /></msg>'
        file_path, duration = ContentParser.parse_voice(xml, "/wechat/Msg")
        assert file_path is None
        assert duration == 3000  # preserves duration for fallback label

    def test_voice_xml_parse_failure(self):
        file_path, duration = ContentParser.parse_voice("not xml", "/wechat/Msg")
        assert file_path is None
        assert duration == 0

    def test_voice_xml_empty_string(self):
        file_path, duration = ContentParser.parse_voice("", "/wechat/Msg")
        assert file_path is None
        assert duration == 0

    def test_voice_xml_missing_attrs(self):
        xml = '<msg><voicemsg endflag="1" bufid="abc123" /></msg>'
        file_path, duration = ContentParser.parse_voice(xml, "/wechat/Msg")
        assert file_path == os.path.normpath("/wechat/Msg/abc123.amr")
        assert duration == 0

    def test_voice_xml_bufid_no_suffix_amr(self, tmp_path):
        xml = '<msg><voicemsg bufid="abc" voicelength="2000" /></msg>'
        msg_dir = str(tmp_path)
        (tmp_path / "abc.silk").touch()
        file_path, duration = ContentParser.parse_voice(xml, msg_dir)
        assert file_path is not None
        assert "abc.silk" in file_path


class TestParseEmoji:
    def test_emoji_with_text(self):
        xml = '<msg><emoji type="1">[微笑]</emoji></msg>'
        assert ContentParser.parse_emoji(xml) == "[微笑]"

    def test_emoji_custom_no_text(self):
        xml = '<msg><emoji type="1" md5="abc123" /></msg>'
        assert ContentParser.parse_emoji(xml) is None

    def test_emoji_parse_failure(self):
        assert ContentParser.parse_emoji("not xml") is None

    def test_emoji_empty_string(self):
        assert ContentParser.parse_emoji("") is None


import os
import tempfile
from xml.etree import ElementTree


class ContentParser:
    """Parse WeChat MSG.db voice/emoji content XML fields.

    WeChat versions and voice storage:
      - v2 (plaintext MSG.db):  Msg/<bufid>.amr or .silk
      - v3+ (encrypted MSG*.db): voiceurl (hex, AES-encrypted SILK) in XML
    """

    # AMR file magic bytes
    _AMR_MAGIC = b"#!AMR"

    @staticmethod
    def parse_voice(content: str, msg_dir: str) -> tuple[str | None, int]:
        """Return (audio_file_path, duration_ms).

        WeChat v2: bufid points to .amr/.silk in Msg/ directory.
        WeChat v3+: bufid=\"0\", audio embedded as AES-encrypted voiceurl hex.

        Returns (file_path, duration) where file_path is a temp decrypted
        audio file.  Returns (None, duration) on failure — caller uses
        duration for the fallback label.
        """
        if not content or not content.strip():
            return None, 0
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError:
            return None, 0

        voice = root.find("voicemsg")
        if voice is None:
            return None, 0

        bufid = voice.get("bufid", "")
        duration_str = voice.get("voicelength", "0")
        try:
            duration = int(duration_str)
        except (ValueError, TypeError):
            duration = 0

        if not bufid:
            # No bufid at all — can't resolve
            return None, duration

        # --- WeChat 3.x: bufid="0", audio in MediaMSG*.db ---
        if bufid == "0":
            voiceurl = voice.get("voiceurl", "")
            if voiceurl:
                return "media_msg", duration
            return None, duration

        # --- WeChat v2: plain .amr/.silk in Msg/ ---
        for ext in (".amr", ".silk"):
            candidate = os.path.join(msg_dir, bufid + ext)
            if os.path.isfile(candidate):
                return os.path.normpath(candidate), duration

        # --- V3 .dat fallback (some v3 installs keep bufid as hash) ---
        wxid_dir = os.path.dirname(msg_dir)
        dat_dir = os.path.join(wxid_dir, "FileStorage", "MsgAttach", bufid)
        if os.path.isdir(dat_dir):
            for root_dir, _, files in os.walk(dat_dir):
                for f in files:
                    if f.lower().endswith(".dat"):
                        decrypted = ContentParser._decode_dat(os.path.join(root_dir, f))
                        if decrypted:
                            return os.path.normpath(decrypted), duration

        # Nothing found — return the .amr path; caller checks os.path.isfile()
        return os.path.normpath(os.path.join(msg_dir, bufid + ".amr")), duration

    @staticmethod
    def _decode_dat(dat_path: str) -> str | None:
        """Attempt XOR-decrypt a WeChat .dat file. Returns path to temp AMR, or None."""
        try:
            with open(dat_path, "rb") as f:
                data = f.read()
        except OSError:
            return None

        if not data:
            return None

        # Determine XOR key: assume first byte of plaintext is 0x23 (AMR magic '#')
        key = data[0] ^ 0x23
        decoded = bytes(b ^ key for b in data)

        # Verify the decoded data looks like AMR
        if not decoded.startswith(ContentParser._AMR_MAGIC):
            # Try common alternative keys
            for alt_key in (0x00, 0x01, 0xFF):
                if key == alt_key:
                    continue  # already tried
                decoded = bytes(b ^ alt_key for b in data)
                if decoded.startswith(ContentParser._AMR_MAGIC):
                    break
            else:
                # If it's a SILK file instead of AMR
                if data[0] ^ 0x02 == ord('#'):
                    decoded = bytes(b ^ 0x02 for b in data)
                elif len(data) >= 5 and all(0x20 <= data[i] ^ 0xFF <= 0x7E for i in range(min(5, len(data)))):
                    decoded = bytes(b ^ 0xFF for b in data)
                else:
                    return None

        if not decoded.startswith(ContentParser._AMR_MAGIC):
            return None

        # Write to temp file
        tmp = tempfile.NamedTemporaryFile(suffix=".amr", delete=False)
        try:
            tmp.write(decoded)
            return tmp.name
        finally:
            tmp.close()

    @staticmethod
    def parse_emoji(content: str) -> str | None:
        """Return emoji text description (e.g. '[微笑]'), or None for custom emoji.

        Handles multiple WeChat emoji XML formats:
          - <msg><emoji type="1">[微笑]</emoji></msg> — text in element
          - <msg><emoji cdnurl="..." /> — custom emoji/sticker
          - Non-XML plain text (e.g. bare emoji code)
        """
        if not content or not content.strip():
            return None
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError:
            # Not XML — might be plain emoji text like "[微笑]" or "😊"
            stripped = content.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                return stripped
            return None

        emoji = root.find("emoji")
        if emoji is None:
            # Check if content itself is emoji text
            tag = root.tag if hasattr(root, 'tag') else ""
            if tag == "emoji":
                text = (root.text or "").strip()
                if text:
                    return text
            return None

        # Strategy 1: text content of <emoji> element
        text = (emoji.text or "").strip()
        if text:
            return text

        # Strategy 2: custom sticker (has md5/cdnurl, no text) — explicitly None
        if emoji.get("md5") or emoji.get("cdnurl"):
            return None

        # Strategy 3: check type attribute against known WeChat emoji map
        emoji_type = emoji.get("type", "")
        if emoji_type:
            # Common WeChat emoji types have known descriptions
            emoji_map = {
                "1": "[微笑]", "2": "[撇嘴]", "3": "[色]", "4": "[发呆]",
                "5": "[得意]", "6": "[流泪]", "7": "[害羞]", "8": "[闭嘴]",
                "9": "[睡]", "10": "[大哭]", "11": "[尴尬]", "12": "[发怒]",
                "13": "[调皮]", "14": "[呲牙]", "15": "[惊讶]", "16": "[难过]",
                "17": "[酷]", "18": "[冷汗]", "19": "[抓狂]", "20": "[吐]",
                "21": "[偷笑]", "22": "[可爱]", "23": "[白眼]", "24": "[傲慢]",
                "25": "[饥饿]", "26": "[困]", "27": "[惊恐]", "28": "[流汗]",
                "29": "[憨笑]", "30": "[悠闲]", "31": "[奋斗]", "32": "[咒骂]",
                "33": "[疑问]", "34": "[嘘]", "35": "[晕]", "36": "[疯了]",
                "37": "[衰]", "38": "[骷髅]", "39": "[敲打]", "40": "[再见]",
                "41": "[擦汗]", "42": "[抠鼻]", "43": "[鼓掌]", "44": "[糗大了]",
                "45": "[坏笑]", "46": "[左哼哼]", "47": "[右哼哼]", "48": "[哈欠]",
                "49": "[鄙视]", "50": "[委屈]", "51": "[快哭了]", "52": "[阴险]",
                "53": "[亲亲]", "54": "[吓]", "55": "[可怜]", "56": "[菜刀]",
                "57": "[西瓜]", "58": "[啤酒]", "59": "[篮球]", "60": "[乒乓]",
                "61": "[咖啡]", "62": "[饭]", "63": "[猪头]", "64": "[玫瑰]",
                "65": "[凋谢]", "66": "[嘴唇]", "67": "[爱心]", "68": "[心碎]",
                "69": "[蛋糕]", "70": "[闪电]", "71": "[炸弹]", "72": "[刀]",
                "73": "[足球]", "74": "[瓢虫]", "75": "[便便]", "76": "[月亮]",
                "77": "[太阳]", "78": "[礼物]", "79": "[拥抱]", "80": "[强]",
                "81": "[弱]", "82": "[握手]", "83": "[胜利]", "84": "[抱拳]",
                "85": "[勾引]", "86": "[拳头]", "87": "[差劲]", "88": "[爱你]",
                "89": "[NO]", "90": "[OK]", "91": "[爱情]", "92": "[飞吻]",
                "93": "[跳跳]", "94": "[发抖]", "95": "[怄火]", "96": "[转圈]",
                "97": "[磕头]", "98": "[回头]", "99": "[跳绳]", "100": "[投降]",
                "101": "[激动]", "102": "[乱舞]", "103": "[献吻]", "104": "[左太极]",
                "105": "[右太极]", "106": "[晚安]", "107": "[嘴唇]", "108": "[手掌]",
            }
            if emoji_type in emoji_map:
                return emoji_map[emoji_type]

        # Strategy 4: check <gameext> sub-element content
        gameext = emoji.find("gameext")
        if gameext is not None:
            txt = (gameext.get("content", "") or "").strip()
            if txt:
                return txt

        return None

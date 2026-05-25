import os
from models.wechat_account import WeChatAccount


def test_wechat_account_v2_plaintext():
    """2.x account: single MSG.db, is_encrypted=False, version=2."""
    acc = WeChatAccount(
        wxid="wxid_test123",
        data_dir="/fake/Documents/WeChat Files/wxid_test123",
        msg_dir="/fake/Documents/WeChat Files/wxid_test123/Msg",
        version=2,
        shard_paths=[
            "/fake/Documents/WeChat Files/wxid_test123/Msg/MSG.db"
        ],
        micro_msg_db="/fake/Documents/WeChat Files/wxid_test123/Msg/MicroMsg.db",
    )
    assert acc.wxid == "wxid_test123"
    assert acc.version == 2
    assert acc.is_encrypted is False
    assert len(acc.shard_paths) == 1
    assert "MSG.db" in acc.shard_paths[0]


def test_wechat_account_v3_encrypted():
    """3.x account: multi-shard encrypted, is_encrypted=True, version=3."""
    acc = WeChatAccount(
        wxid="wxid_v3demo",
        data_dir="/fake/WeChat Files/wxid_v3demo",
        msg_dir="/fake/WeChat Files/wxid_v3demo/Msg",
        version=3,
        shard_paths=[
            "/fake/WeChat Files/wxid_v3demo/Msg/Multi/MSG0.db",
            "/fake/WeChat Files/wxid_v3demo/Msg/Multi/MSG1.db",
            "/fake/WeChat Files/wxid_v3demo/Msg/Multi/MSG2.db",
        ],
        micro_msg_db="/fake/WeChat Files/wxid_v3demo/Msg/MicroMsg.db",
    )
    assert acc.version == 3
    assert acc.is_encrypted is True
    assert len(acc.shard_paths) == 3

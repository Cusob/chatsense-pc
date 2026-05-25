from dataclasses import dataclass, field


@dataclass
class WeChatAccount:
    wxid: str
    data_dir: str
    msg_dir: str
    version: int
    shard_paths: list[str] = field(default_factory=list)
    micro_msg_db: str = ""

    @property
    def is_encrypted(self) -> bool:
        return self.version >= 3

from dataclasses import dataclass, field


@dataclass
class DimensionScores:
    boundary: int = 50           # 分寸感
    empathy: int = 55            # 共情力
    interaction: int = 50        # 你来我往
    self_disclosure: int = 50    # 自我展示
    naturalness: int = 50        # 自然度
    initiative: int = 50         # 主动性
    authenticity: int = 50       # 真诚感
    escalation: int = 50         # 升温力

    def to_dict(self) -> dict:
        return {
            "boundary": self.boundary,
            "empathy": self.empathy,
            "interaction": self.interaction,
            "self_disclosure": self.self_disclosure,
            "naturalness": self.naturalness,
            "initiative": self.initiative,
            "authenticity": self.authenticity,
            "escalation": self.escalation,
        }

    @staticmethod
    def from_dict(d: dict) -> "DimensionScores":
        return DimensionScores(
            boundary=d.get("boundary", 50),
            empathy=d.get("empathy", 55),
            interaction=d.get("interaction", 50),
            self_disclosure=d.get("self_disclosure", 50),
            naturalness=d.get("naturalness", 50),
            initiative=d.get("initiative", 50),
            authenticity=d.get("authenticity", 50),
            escalation=d.get("escalation", 50),
        )

    def dimension_names(self) -> list[tuple[str, str]]:
        return [
            ("boundary", "分寸感"),
            ("empathy", "共情力"),
            ("interaction", "你来我往"),
            ("self_disclosure", "自我展示"),
            ("naturalness", "自然度"),
            ("initiative", "主动性"),
            ("authenticity", "真诚感"),
            ("escalation", "升温力"),
        ]


@dataclass
class AnalysisResult:
    scores: DimensionScores
    strengths: list[str] = field(default_factory=list)
    improvements: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sample_reply: str = ""
    stage: str = ""
    debug_log: str = ""
    dimension_advice: list[dict] = field(default_factory=list)  # per-dimension suggestions

    @staticmethod
    def from_dict(d: dict) -> "AnalysisResult":
        scores = d.get("scores", {})
        return AnalysisResult(
            scores=DimensionScores.from_dict(scores),
            strengths=d.get("strengths", []),
            improvements=d.get("improvements", []),
            warnings=d.get("warnings", []),
            sample_reply=d.get("sample_reply", ""),
            stage=d.get("stage", ""),
            debug_log=d.get("debug_log", ""),
            dimension_advice=d.get("dimension_advice", []),
        )

    def to_dict(self) -> dict:
        return {
            "scores": self.scores.to_dict(),
            "strengths": self.strengths,
            "improvements": self.improvements,
            "warnings": self.warnings,
            "sample_reply": self.sample_reply,
            "stage": self.stage,
            "dimension_advice": self.dimension_advice,
        }

    @staticmethod
    def empty() -> "AnalysisResult":
        return AnalysisResult(scores=DimensionScores())

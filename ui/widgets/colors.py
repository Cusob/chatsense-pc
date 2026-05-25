"""Shared score color mapping — 4-tier scheme for V2 analysis."""


def score_color(score: int) -> str:
    """Return CSS hex for a 0-100 score using 4-tier scheme."""
    if score <= 30:
        return "#C62828"   # deep red – needs improvement
    if score <= 50:
        return "#D32F2F"   # light red – has room to grow
    if score <= 75:
        return "#2E7D32"   # green – healthy
    return "#1B5E20"       # deep green – excellent

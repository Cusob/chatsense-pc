def calculate_scores(annotated: dict) -> dict:
    for m in annotated.get("messages", []):
        if "annotations" not in m:
            m["annotations"] = {}
        if "timestamp" not in m:
            m["timestamp"] = m.get("index", 0) * 10  # fallback
    msgs = annotated["messages"]
    rounds = annotated["rounds"]
    segments = annotated.get("unanswered_segments", [])
    stage = annotated.get("stage", "熟悉期")
    my_msgs = [m for m in msgs if m["role"] == "我"]
    other_msgs = [m for m in msgs if m["role"] == "对方"]
    total = len(my_msgs)

    return {
        "boundary": _score_boundary(my_msgs, total, segments),
        "empathy": _score_empathy(my_msgs, other_msgs),
        "interaction": _score_interaction(msgs, my_msgs, other_msgs, total),
        "self_disclosure": _score_self_disclosure(my_msgs, total),
        "naturalness": _score_naturalness(my_msgs, total),
        "initiative": _score_initiative(my_msgs, other_msgs, rounds, total, segments),
        "authenticity": _score_authenticity(my_msgs),
        "escalation": _score_escalation(my_msgs, stage),
    }


def _clamp(score: int) -> int:
    return max(0, min(100, score))


# ---------------------------------------------------------------------------
# boundary — 分寸感
# ---------------------------------------------------------------------------
def _score_boundary(my_msgs: list, total: int, segments: list) -> int:
    score = 75

    # Long unanswered segments
    for seg in segments:
        if seg.get("avg_interval_s", 0) >= 60 and seg.get("message_count", 0) >= 2:
            score -= 20

    # Private questions
    private_count = sum(1 for m in my_msgs if m.get("annotations", {}).get("is_private_question"))
    excess = max(0, private_count - total // 10)
    score -= min(excess * 5, 15)

    return _clamp(score)


# ---------------------------------------------------------------------------
# empathy — 共情力
# ---------------------------------------------------------------------------
def _score_empathy(my_msgs: list, other_msgs: list) -> int:
    score = 55

    emotion_count = sum(
        1 for m in other_msgs if m.get("annotations", {}).get("emotion_signal")
    )
    if emotion_count == 0:
        return score

    emp_count = sum(1 for m in my_msgs if m.get("annotations", {}).get("is_empathizing"))
    ratio = emp_count / emotion_count

    if ratio >= 0.8:
        score += 20
    elif ratio >= 0.6:
        score += 10
    elif ratio >= 0.4:
        pass  # 0 change
    elif ratio >= 0.2:
        score -= 15
    else:
        score -= 25

    return _clamp(score)


# ---------------------------------------------------------------------------
# interaction — 你来我往
# ---------------------------------------------------------------------------
def _score_interaction(msgs: list, my_msgs: list, other_msgs: list, total: int) -> int:
    score = 75
    my_count = len(my_msgs)
    other_count = len(other_msgs)

    # Message ratio
    if other_count > 0:
        ratio = my_count / other_count
        if ratio < 0.4:
            score -= 20
        elif ratio > 2.5:
            score -= 25

    # Topic control
    my_new_topics = sum(1 for m in my_msgs if m.get("annotations", {}).get("is_new_topic"))
    all_new_topics = sum(1 for m in msgs if m.get("annotations", {}).get("is_new_topic"))
    if all_new_topics > 0 and my_new_topics / all_new_topics > 0.7:
        score -= 15

    # Short-to-long: partner sends long message, I reply with <=2 chars
    short_to_long_count = 0
    for i in range(len(msgs) - 1):
        curr = msgs[i]
        nxt = msgs[i + 1]
        if (
            curr["role"] == "对方"
            and curr.get("annotations", {}).get("content_length", 0) > 30
            and nxt["role"] == "我"
            and nxt.get("annotations", {}).get("content_length", 0) <= 2
        ):
            short_to_long_count += 1
    if short_to_long_count >= 3:
        score -= 20

    return _clamp(score)


# ---------------------------------------------------------------------------
# self_disclosure — 自我展示
# ---------------------------------------------------------------------------
def _score_self_disclosure(my_msgs: list, total: int) -> int:
    score = 65

    self_centered_count = sum(
        1 for m in my_msgs if m.get("annotations", {}).get("is_self_centered")
    )
    if total > 0:
        ratio = self_centered_count / total
        if 0.2 <= ratio <= 0.35:
            score += 10
        elif ratio < 0.1:
            score -= 20
        elif ratio > 0.5:
            score -= 25

    # Per-message penalty (capped)
    score -= min(self_centered_count * 10, 20)

    # Encourages ending with questions
    ends_q_count = sum(
        1 for m in my_msgs if m.get("annotations", {}).get("ends_with_question")
    )
    if total > 0 and ends_q_count / total >= 0.3:
        score += 10

    return _clamp(score)


# ---------------------------------------------------------------------------
# naturalness — 自然度
# ---------------------------------------------------------------------------
def _score_naturalness(my_msgs: list, total: int) -> int:
    score = 65

    open_q = sum(
        1 for m in my_msgs if m.get("annotations", {}).get("question_type") == "open"
    )
    closed_q = sum(
        1 for m in my_msgs if m.get("annotations", {}).get("question_type") == "closed"
    )
    total_q = open_q + closed_q

    if total_q > 0:
        open_ratio = open_q / total_q
        if open_ratio > 0.6:
            score += 15
        elif open_ratio < 0.4:
            score -= 20

    # Natural topic transitions
    transition_count = sum(
        1 for m in my_msgs if m.get("annotations", {}).get("topic_transition_natural")
    )
    if transition_count > 0:
        score += 10

    # Confirmation messages
    confirmation_count = sum(
        1 for m in my_msgs if m.get("annotations", {}).get("is_confirmation")
    )
    score -= (confirmation_count // 2) * 5

    return _clamp(score)


# ---------------------------------------------------------------------------
# initiative — 主动性
# ---------------------------------------------------------------------------
def _score_initiative(
    my_msgs: list, other_msgs: list, rounds: list, total: int, segments: list
) -> int:
    score = 70

    if rounds:
        total_rounds = len(rounds)
        my_rounds = sum(1 for r in rounds if r.get("initiator") == "我")
        ratio = my_rounds / total_rounds

        if 0.3 <= ratio <= 0.6:
            score += 10
        elif 0.6 < ratio <= 0.8:
            score -= 10
        elif ratio > 0.8:
            score -= 25
        elif ratio < 0.3:
            score -= 20

    # Qualifying segments
    qualifying = sum(
        1
        for seg in segments
        if seg.get("avg_interval_s", 0) >= 60 and seg.get("message_count", 0) >= 2
    )
    if qualifying >= 2:
        score -= 30

    # 1-hour density check: >5 mine + <=1 partner in any 60-min window -> -20
    my_ts = [m.get("timestamp") for m in my_msgs]
    if all(t is not None for t in my_ts) and len(other_msgs) > 0:
        other_ts = [m.get("timestamp") for m in other_msgs]
        if all(t is not None for t in other_ts):
            for t0 in my_ts:
                t1 = t0 + 3600
                my_in_window = sum(1 for t in my_ts if t0 <= t <= t1)
                other_in_window = sum(1 for t in other_ts if t0 <= t <= t1)
                if my_in_window > 5 and other_in_window <= 1:
                    score -= 20
                    break  # apply once

    return _clamp(score)


# ---------------------------------------------------------------------------
# authenticity — 真诚感
# ---------------------------------------------------------------------------
def _score_authenticity(my_msgs: list) -> int:
    score = 70

    template_count = sum(1 for m in my_msgs if m.get("annotations", {}).get("is_template"))
    score -= min(template_count * 10, 30)

    excessive_praise_count = sum(
        1 for m in my_msgs if m.get("annotations", {}).get("is_excessive_praise")
    )
    score -= min(excessive_praise_count * 8, 24)

    if sum(1 for m in my_msgs if m.get("annotations", {}).get("self_contradictory")) >= 1:
        score -= 15

    if sum(1 for m in my_msgs if m.get("annotations", {}).get("politely_disagree")) >= 1:
        score += 5

    return _clamp(score)


# ---------------------------------------------------------------------------
# escalation — 升温力
# ---------------------------------------------------------------------------
def _score_escalation(my_msgs: list, stage: str) -> int:
    score = 55

    invitations = sum(1 for m in my_msgs if m.get("annotations", {}).get("has_invitation"))
    escalation_natural_count = sum(
        1 for m in my_msgs if m.get("annotations", {}).get("escalation_natural")
    )
    escalation_forced_count = sum(
        1 for m in my_msgs if m.get("annotations", {}).get("escalation_forced")
    )

    if invitations > 0:
        score += 20
    if escalation_natural_count > 0:
        score += 10
    if escalation_forced_count > 0:
        score -= 15

    # Stagnation penalty
    if invitations == 0 and escalation_natural_count == 0 and escalation_forced_count == 0:
        score -= 25

    # Early stage + sensitive topics
    sensitive_count = sum(
        1 for m in my_msgs if m.get("annotations", {}).get("is_sensitive_topic")
    )
    if stage == "初识期" and sensitive_count > 0:
        score -= 25

    return _clamp(score)

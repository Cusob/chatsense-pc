import copy

from engine.scoring import calculate_scores


def _deep_copy(obj):
    return copy.deepcopy(obj)


DEFAULT_MY_ANN = {
    "emotion_signal": None,
    "question_type": None,
    "is_self_centered": False,
    "is_praise": False,
    "is_excessive_praise": False,
    "is_template": False,
    "is_empathizing": False,
    "politely_disagree": False,
    "ends_with_question": False,
    "topic_id": 1,
    "is_new_topic": False,
    "has_invitation": False,
    "is_private_question": False,
    "is_confirmation": False,
    "is_sensitive_topic": False,
    "self_contradictory": False,
    "topic_transition_natural": False,
    "escalation_natural": False,
    "escalation_forced": False,
    "content_length": 4,
}

SAMPLE_ANNOTATED = {
    "messages": [
        {
            "index": 0,
            "timestamp": 1000,
            "role": "我",
            "content": "今天好累",
            "annotations": dict(DEFAULT_MY_ANN),
        },
        {
            "index": 1,
            "timestamp": 1010,
            "role": "对方",
            "content": "怎么了",
            "annotations": {
                "emotion_signal": None,
                "is_short_response": False,
                "content_length": 3,
            },
        },
    ],
    "rounds": [{"start_index": 0, "end_index": 1, "initiator": "我"}],
    "unanswered_segments": [],
    "stage": "熟悉期",
}


class TestScoring:
    def test_basic_conversation(self):
        """A normal, short conversation should score reasonably well."""
        annotated = _deep_copy(SAMPLE_ANNOTATED)
        scores = calculate_scores(annotated)
        assert scores["boundary"] >= 50
        assert scores["interaction"] >= 50

    def test_boundary_private_questions(self):
        """Private questions should lower the boundary score."""
        annotated = _deep_copy(SAMPLE_ANNOTATED)
        for i in range(3):
            ann = dict(DEFAULT_MY_ANN)
            ann["is_private_question"] = True
            annotated["messages"].append({
                "index": 2 + i,
                "timestamp": 1100 + i * 100,
                "role": "我",
                "content": f"私人问题{i}",
                "annotations": ann,
            })
        scores = calculate_scores(annotated)
        assert scores["boundary"] <= 60

    def test_empathy_missing(self):
        """Failing to empathize when the partner shows emotion should lower empathy."""
        annotated = _deep_copy(SAMPLE_ANNOTATED)
        # Give the partner an emotion signal
        annotated["messages"][1]["annotations"]["emotion_signal"] = "伤心"
        # Add a non-empathizing response from me
        ann = dict(DEFAULT_MY_ANN)
        ann["is_empathizing"] = False
        annotated["messages"].append({
            "index": 2,
            "timestamp": 1020,
            "role": "我",
            "content": "没什么",
            "annotations": ann,
        })
        scores = calculate_scores(annotated)
        assert scores["empathy"] < 55

    def test_self_disclosure_excess(self):
        """Too much self-centered talk should reduce the self_disclosure score."""
        annotated = _deep_copy(SAMPLE_ANNOTATED)
        for i in range(4):
            ann = dict(DEFAULT_MY_ANN)
            ann["is_self_centered"] = True
            annotated["messages"].append({
                "index": 2 + i,
                "timestamp": 1020 + i * 100,
                "role": "我",
                "content": f"我怎样怎样{i}",
                "annotations": ann,
            })
        scores = calculate_scores(annotated)
        assert scores["self_disclosure"] < 60

    def test_naturalness_closed_questions(self):
        """Too many closed questions should hurt naturalness."""
        annotated = _deep_copy(SAMPLE_ANNOTATED)
        for i in range(4):
            ann = dict(DEFAULT_MY_ANN)
            ann["question_type"] = "closed"
            annotated["messages"].append({
                "index": 2 + i,
                "timestamp": 1020 + i * 100,
                "role": "我",
                "content": f"是吗?{i}",
                "annotations": ann,
            })
        scores = calculate_scores(annotated)
        assert scores["naturalness"] < 55

    def test_initiative_excessive(self):
        """Initiating every round should lower the initiative score."""
        annotated = _deep_copy(SAMPLE_ANNOTATED)
        annotated["rounds"] = [
            {"start_index": 0, "end_index": 1, "initiator": "我"},
            {"start_index": 2, "end_index": 3, "initiator": "我"},
            {"start_index": 4, "end_index": 5, "initiator": "我"},
        ]
        scores = calculate_scores(annotated)
        assert scores["initiative"] < 50

    def test_authenticity_templates(self):
        """Template-style messages reduce authenticity."""
        annotated = _deep_copy(SAMPLE_ANNOTATED)
        annotated["messages"][0]["annotations"]["is_template"] = True
        scores = calculate_scores(annotated)
        assert scores["authenticity"] < 65

    def test_escalation_invitation(self):
        """Invitation signals boost the escalation score."""
        annotated = _deep_copy(SAMPLE_ANNOTATED)
        annotated["messages"][0]["annotations"]["has_invitation"] = True
        scores = calculate_scores(annotated)
        assert scores["escalation"] >= 70

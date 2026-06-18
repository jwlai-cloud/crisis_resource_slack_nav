import logging
from unittest.mock import Mock

from listeners.events.assistant_thread_started import (
    SUGGESTED_PROMPTS,
    handle_assistant_thread_started,
)

test_logger = logging.getLogger(__name__)


class TestSuggestedPromptsContent:
    """The suggested prompts must teach the crisis-domain value in one glance."""

    def test_generic_template_prompts_are_gone(self):
        # Arrange / Act
        titles = [p["title"] for p in SUGGESTED_PROMPTS]

        # Assert — the starter-template trio must not survive.
        assert "Write a Message" not in titles
        assert "Summarize" not in titles
        assert "Brainstorm" not in titles

    def test_has_at_least_three_prompts(self):
        # A resident need, a volunteer offer, a road/info question (4th optional).
        assert 3 <= len(SUGGESTED_PROMPTS) <= 4

    def test_every_prompt_has_title_and_message(self):
        for prompt in SUGGESTED_PROMPTS:
            assert prompt["title"].strip()
            assert prompt["message"].strip()

    def test_covers_a_resident_need(self):
        messages = " ".join(p["message"].lower() for p in SUGGESTED_PROMPTS)
        # A realistic resident need names a resource want.
        assert "need" in messages

    def test_covers_a_volunteer_offer(self):
        messages = " ".join(p["message"].lower() for p in SUGGESTED_PROMPTS)
        assert "offer" in messages or "can offer" in messages

    def test_covers_a_road_or_info_question(self):
        messages = " ".join(p["message"].lower() for p in SUGGESTED_PROMPTS)
        assert "road" in messages or "open" in messages

    def test_prompts_are_scenario_grounded(self):
        # The demo scenario is Exmouth WA — the prompts should be locally grounded.
        messages = " ".join(p["message"] for p in SUGGESTED_PROMPTS)
        assert "Exmouth" in messages


class TestHandleAssistantThreadStarted:
    def setup_method(self):
        self.set_suggested_prompts = Mock()

    def test_sets_the_crisis_prompts_and_a_calm_title(self):
        # Act
        handle_assistant_thread_started(
            set_suggested_prompts=self.set_suggested_prompts,
            logger=test_logger,
        )

        # Assert
        self.set_suggested_prompts.assert_called_once()
        kwargs = self.set_suggested_prompts.call_args.kwargs
        assert kwargs["prompts"] is SUGGESTED_PROMPTS
        # A calm, plain-language invitation — not the generic "How can I help".
        assert kwargs["title"]
        assert kwargs["title"] != "How can I help you today?"

    def test_swallows_failures(self, caplog):
        self.set_suggested_prompts.side_effect = Exception("boom")

        # Act — must not raise (the try/except is kept).
        handle_assistant_thread_started(
            set_suggested_prompts=self.set_suggested_prompts,
            logger=test_logger,
        )

        # Assert
        assert "boom" in caplog.text

"""Unit tests for listeners.channel_gate — the single-channel passive-listening gate.

The gate is read from ``CRISIS_CHANNEL`` at call time (cheap, hot-reloadable). An
empty or unset value means the feature is off — no channel is designated, so passive
listening never engages. Tests monkeypatch the env var directly; no real Slack.
"""

import pytest

from listeners import channel_gate


def test_unset_env_means_feature_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """No CRISIS_CHANNEL configured -> no channel is the crisis channel (feature off)."""
    monkeypatch.delenv(channel_gate.CRISIS_CHANNEL_ENV, raising=False)

    assert channel_gate.is_crisis_channel("C_ANY") is False


def test_empty_env_means_feature_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty CRISIS_CHANNEL (whitespace included) is treated as off, never a match."""
    monkeypatch.setenv(channel_gate.CRISIS_CHANNEL_ENV, "   ")

    assert channel_gate.is_crisis_channel("C_ANY") is False
    assert channel_gate.is_crisis_channel("") is False


def test_matching_channel_id_is_the_crisis_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    """The configured channel id (whitespace-trimmed) is the one designated channel."""
    monkeypatch.setenv(channel_gate.CRISIS_CHANNEL_ENV, "  C_CRISIS  ")

    assert channel_gate.is_crisis_channel("C_CRISIS") is True


def test_other_channel_id_is_not_the_crisis_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    """A different channel id is never the crisis channel — everywhere else stays gated."""
    monkeypatch.setenv(channel_gate.CRISIS_CHANNEL_ENV, "C_CRISIS")

    assert channel_gate.is_crisis_channel("C_OTHER") is False


def test_none_channel_id_is_never_a_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing channel id (None) never matches, even with the feature on."""
    monkeypatch.setenv(channel_gate.CRISIS_CHANNEL_ENV, "C_CRISIS")

    assert channel_gate.is_crisis_channel(None) is False

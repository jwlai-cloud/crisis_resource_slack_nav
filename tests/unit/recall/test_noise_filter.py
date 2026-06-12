from datetime import UTC, datetime, timedelta

from recall.client import _drop_agent_noise
from recall.models import RecallMatch


def _m(text, author_id="U1", ts_offset=0):
    return RecallMatch(
        text=text,
        author="user",
        author_id=author_id,
        channel="general",
        channel_id="C1",
        ts=datetime(2026, 6, 12, tzinfo=UTC) + timedelta(minutes=ts_offset),
        permalink="https://x/p1",
    )


def test_bot_mentions_dropped():
    ms = [_m("<@UBOT> we need formula"), _m("Offering: water")]
    out = _drop_agent_noise(ms, "UBOT")
    assert [m.text for m in out] == ["Offering: water"]


def test_duplicates_collapse_to_newest():
    ms = [_m("Offering: water", ts_offset=0), _m("offering:  water", ts_offset=5)]
    out = _drop_agent_noise(ms, None)
    assert len(out) == 1 and out[0].ts.minute == 5


def test_no_bot_id_keeps_all_unique():
    ms = [_m("<@UBOT> need x"), _m("Offering: water")]
    assert len(_drop_agent_noise(ms, None)) == 2


def test_bot_authored_messages_dropped():
    ms = [_m("We understand you need formula", author_id="UBOT"), _m("Offering: water")]
    out = _drop_agent_noise(ms, "UBOT")
    assert [m.text for m in out] == ["Offering: water"]

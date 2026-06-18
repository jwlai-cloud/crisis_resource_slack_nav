"""Unit tests for recall.client — RTS query with the WebClient mocked.

No live network: the ``WebClient`` is a ``pytest-mock`` mock. We assert the query
build, the user-token auth header, the happy-path mapping, and that every
degraded path (no token, SlackApiError, generic failure) returns a typed
RecallError rather than raising or returning None. Builders come from the
``make_need`` fixture in conftest.
"""

from collections.abc import Callable

from pytest_mock import MockerFixture
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from entities import Need
from recall.client import build_query, recall_offers
from recall.models import RecallError, RecallMatch

USER_TOKEN = "xoxp-test-user-token"


def _ok_response(messages: list[dict]) -> dict:
    """A minimal ok assistant.search.context response body."""
    return {"ok": True, "results": {"messages": messages}}


def test_build_query_joins_need_type_and_location(make_need: Callable[..., Need]) -> None:
    """The search string is keyword need_type + location, no question phrasing."""
    need = make_need(need_type="drinking water", location="North Exmouth")

    assert build_query(need) == "drinking water North Exmouth"


async def test_recall_returns_no_token_error_without_user_token(
    make_need: Callable[..., Need],
    mocker: MockerFixture,
) -> None:
    """No user token -> typed RecallError (degraded, never silent), no API call."""
    need = make_need()
    client = mocker.Mock(spec=WebClient)

    result = await recall_offers(need, client, user_token=None)

    assert isinstance(result, RecallError)
    assert result.reason == "no_user_token"
    client.api_call.assert_not_called()


async def test_recall_maps_messages_to_typed_matches(
    make_need: Callable[..., Need],
    mocker: MockerFixture,
) -> None:
    """Happy path: results.messages[] map to RecallMatch with source + ts."""
    need = make_need()
    client = mocker.Mock(spec=WebClient)
    client.api_call.return_value = _ok_response(
        [
            {
                "content": "spare generator in Exmouth",
                "author_name": "Jordan",
                "author_user_id": "U1",
                "channel_name": "offers",
                "channel_id": "C1",
                "message_ts": "1742550600.000200",
                "permalink": "https://x/p1",
            }
        ]
    )

    result = await recall_offers(need, client, user_token=USER_TOKEN)

    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], RecallMatch)
    assert result[0].author == "Jordan"
    assert result[0].channel == "offers"


async def test_recall_calls_rts_method_with_user_token_header(
    make_need: Callable[..., Need],
    mocker: MockerFixture,
) -> None:
    """The call targets assistant.search.context and authenticates with the user token."""
    need = make_need(need_type="generator", location="Exmouth")
    client = mocker.Mock(spec=WebClient)
    client.api_call.return_value = _ok_response([])

    await recall_offers(need, client, user_token=USER_TOKEN)

    client.api_call.assert_called_once()
    args, kwargs = client.api_call.call_args
    assert args[0] == "assistant.search.context"
    assert kwargs["params"]["query"] == "generator Exmouth"
    assert kwargs["headers"]["Authorization"] == f"Bearer {USER_TOKEN}"


async def test_recall_returns_empty_list_for_no_results(
    make_need: Callable[..., Need],
    mocker: MockerFixture,
) -> None:
    """Zero hits is a valid (non-degraded) empty list, distinct from RecallError."""
    need = make_need()
    client = mocker.Mock(spec=WebClient)
    client.api_call.return_value = _ok_response([])

    result = await recall_offers(need, client, user_token=USER_TOKEN)

    assert result == []


async def test_recall_returns_error_on_slack_api_error(
    make_need: Callable[..., Need],
    mocker: MockerFixture,
) -> None:
    """A SlackApiError (ok: false) becomes a typed RecallError carrying the code."""
    need = make_need()
    client = mocker.Mock(spec=WebClient)
    api_error = SlackApiError(
        message="search failed",
        response={"ok": False, "error": "assistant_search_context_disabled"},
    )
    client.api_call.side_effect = api_error

    result = await recall_offers(need, client, user_token=USER_TOKEN)

    assert isinstance(result, RecallError)
    assert result.reason == "assistant_search_context_disabled"


async def test_recall_returns_error_on_unexpected_failure(
    make_need: Callable[..., Need],
    mocker: MockerFixture,
) -> None:
    """Any other failure also degrades explicitly to a RecallError, never raises."""
    need = make_need()
    client = mocker.Mock(spec=WebClient)
    client.api_call.side_effect = TimeoutError("network down")

    result = await recall_offers(need, client, user_token=USER_TOKEN)

    assert isinstance(result, RecallError)
    assert result.reason == "request_failed"


async def test_recall_drops_need_echo_when_request_text_passed(
    make_need: Callable[..., Need],
    mocker: MockerFixture,
) -> None:
    """The requester's own need echoed back from RTS is filtered when request_text is given (014)."""
    need = make_need(need_type="generator", location="Exmouth")
    client = mocker.Mock(spec=WebClient)
    request_text = "Family of 4 in Exmouth, no power, need a generator"
    client.api_call.return_value = _ok_response(
        [
            {
                "content": "Family of 4 in Exmouth, no power, need a generator",
                "author_name": "Requester",
                "author_user_id": "U_REQ",
                "channel_name": "general",
                "channel_id": "C1",
                "message_ts": "1742550600.000200",
                "permalink": "https://x/echo",
            },
            {
                "content": "I have a spare generator to lend, collect from town",
                "author_name": "Jordan",
                "author_user_id": "U_OFFERER",
                "channel_name": "offers",
                "channel_id": "C2",
                "message_ts": "1742550700.000200",
                "permalink": "https://x/offer",
            },
        ]
    )

    result = await recall_offers(need, client, user_token=USER_TOKEN, request_text=request_text)

    assert isinstance(result, list)
    texts = [m.text for m in result]
    assert "I have a spare generator to lend, collect from town" in texts
    assert all("need a generator" not in t for t in texts)  # the echo is gone


async def test_recall_logs_observability_line(
    make_need: Callable[..., Need],
    mocker: MockerFixture,
) -> None:
    """recall_offers emits one INFO line with query + latency + raw/post-filter counts (012)."""
    need = make_need(need_type="generator", location="Exmouth")
    client = mocker.Mock(spec=WebClient)
    client.api_call.return_value = _ok_response(
        [
            {
                "content": "spare generator in Exmouth",
                "author_name": "Jordan",
                "author_user_id": "U_OFFERER",
                "channel_name": "offers",
                "channel_id": "C1",
                "message_ts": "1742550600.000200",
                "permalink": "https://x/p1",
            }
        ]
    )
    info = mocker.patch("recall.client.logger.info")

    await recall_offers(need, client, user_token=USER_TOKEN)

    observ = [c for c in info.call_args_list if "RTS recall:" in str(c.args[0])]
    assert len(observ) == 1
    fmt, *args = observ[0].args
    assert "query=" in fmt and "latency=" in fmt and "raw=" in fmt and "post_filter=" in fmt
    assert args[0] == "generator Exmouth"  # query
    assert args[2] == 1  # raw count
    assert args[3] == 1  # post-filter count

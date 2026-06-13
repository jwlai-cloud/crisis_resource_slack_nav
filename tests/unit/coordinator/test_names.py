"""Unit tests for coordinator.names — best-effort user-id -> display-name lookup.

The canvas markdown does NOT resolve ``<@id>`` mention syntax (live W4 finding),
so the board has to substitute real display names. This helper is the impure
boundary that fetches them via ``users.info`` on the user token; the board
composer stays pure and just receives the resulting ``{id: name}`` dict.

No live API: the ``WebClient`` is a mock so ``users_info`` calls are asserted by
argument. These tests pin: one call per distinct id (caching), the display-name
field precedence, the user-token ``token=`` override, and the best-effort
guarantee that a per-id failure degrades to *omitting* that id (caller falls back
to the bare id) and the helper never raises.
"""

from pytest_mock import MockerFixture

from coordinator.names import resolve_display_names

USER_TOKEN = "xoxp-user-token"


def _user_response(user_id: str, *, display_name: str = "", real_name: str = "", name: str = ""):
    """A users.info success payload with the given profile fields."""
    return {
        "ok": True,
        "user": {
            "id": user_id,
            "name": name,
            "real_name": real_name,
            "profile": {"display_name": display_name, "real_name": real_name},
        },
    }


def test_resolves_ids_to_display_names(mocker: MockerFixture) -> None:
    """Each id maps to its profile display name."""
    client = mocker.Mock()
    client.users_info.return_value = _user_response("U_ROSARIO", display_name="Rosario Bennet")

    names = resolve_display_names(client, USER_TOKEN, {"U_ROSARIO"})

    assert names == {"U_ROSARIO": "Rosario Bennet"}


def test_uses_user_token_via_token_override(mocker: MockerFixture) -> None:
    """The lookup authenticates as the user via the per-call token= override."""
    client = mocker.Mock()
    client.users_info.return_value = _user_response("U_X", display_name="Pat")

    resolve_display_names(client, USER_TOKEN, {"U_X"})

    assert client.users_info.call_args.kwargs["token"] == USER_TOKEN
    assert client.users_info.call_args.kwargs["user"] == "U_X"


def test_one_lookup_per_distinct_id(mocker: MockerFixture) -> None:
    """A repeated id is fetched only once — cached within the call."""
    client = mocker.Mock()
    client.users_info.return_value = _user_response("U_DUP", display_name="Dup")

    # The same id appears once in the set, but the set dedupes upstream callers;
    # here we assert the helper itself issues exactly one call per distinct id.
    names = resolve_display_names(client, USER_TOKEN, {"U_DUP"})

    assert names == {"U_DUP": "Dup"}
    client.users_info.assert_called_once()


def test_distinct_ids_each_fetched_once(mocker: MockerFixture) -> None:
    """Two distinct ids produce two lookups, each returning its own name.

    Keyed on the requested ``user`` rather than call order — the helper iterates a
    set, so the lookup order is not guaranteed.
    """
    client = mocker.Mock()
    profiles = {"U_A": "Alice", "U_B": "Bob"}

    def _by_user(*, user: str, token: str):
        return _user_response(user, display_name=profiles[user])

    client.users_info.side_effect = _by_user

    names = resolve_display_names(client, USER_TOKEN, {"U_A", "U_B"})

    assert names == {"U_A": "Alice", "U_B": "Bob"}
    assert client.users_info.call_count == 2


def test_falls_back_to_real_name_when_display_name_blank(mocker: MockerFixture) -> None:
    """An empty display_name falls back to the profile real name."""
    client = mocker.Mock()
    client.users_info.return_value = _user_response("U_R", display_name="", real_name="Real Name")

    names = resolve_display_names(client, USER_TOKEN, {"U_R"})

    assert names == {"U_R": "Real Name"}


def test_falls_back_to_username_when_names_blank(mocker: MockerFixture) -> None:
    """With no display_name or real_name, the username is used."""
    client = mocker.Mock()
    client.users_info.return_value = _user_response("U_N", name="janedoe")

    names = resolve_display_names(client, USER_TOKEN, {"U_N"})

    assert names == {"U_N": "janedoe"}


def test_failed_lookup_omits_that_id(mocker: MockerFixture) -> None:
    """A users.info error for one id degrades to omitting it — never raises."""
    client = mocker.Mock()
    client.users_info.side_effect = RuntimeError("user_not_found")

    names = resolve_display_names(client, USER_TOKEN, {"U_GONE"})

    assert names == {}


def test_one_failure_does_not_block_other_ids(mocker: MockerFixture) -> None:
    """A failure on one id still resolves the others — per-id isolation.

    Keyed on the requested ``user`` (not call order) since the helper iterates a
    set, whose iteration order is not guaranteed.
    """
    client = mocker.Mock()

    def _by_user(*, user: str, token: str):
        if user == "U_BAD":
            raise RuntimeError("user_not_found")
        return _user_response("U_OK", display_name="Okay")

    client.users_info.side_effect = _by_user

    names = resolve_display_names(client, USER_TOKEN, {"U_BAD", "U_OK"})

    assert names == {"U_OK": "Okay"}


def test_response_without_user_omits_that_id(mocker: MockerFixture) -> None:
    """A malformed response (no user object) omits the id rather than raising."""
    client = mocker.Mock()
    client.users_info.return_value = {"ok": True}

    names = resolve_display_names(client, USER_TOKEN, {"U_WEIRD"})

    assert names == {}


def test_empty_id_set_makes_no_calls(mocker: MockerFixture) -> None:
    """With no ids to resolve, no API call is made and the map is empty."""
    client = mocker.Mock()

    names = resolve_display_names(client, USER_TOKEN, set())

    assert names == {}
    client.users_info.assert_not_called()


def test_no_user_token_makes_no_calls(mocker: MockerFixture) -> None:
    """Without a user token, the lookup is skipped (caller falls back to bare ids)."""
    client = mocker.Mock()

    names = resolve_display_names(client, None, {"U_A"})

    assert names == {}
    client.users_info.assert_not_called()

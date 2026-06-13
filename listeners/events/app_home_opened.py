from logging import Logger

from slack_bolt import BoltContext
from slack_sdk import WebClient

from coordinator.announce import canvas_link
from coordinator.canvas_store import load_canvas_id
from coordinator.situation import SituationSnapshot, read_situation
from listeners.views.app_home_builder import build_app_home_view


def _read_situation_best_effort(logger: Logger) -> SituationSnapshot | None:
    """Read the official situation for the Home tab, degrading to ``None`` on failure.

    :func:`coordinator.situation.read_situation` is already best-effort per feed,
    but the Home render must never crash (first impression), so an *unexpected*
    failure of the whole read degrades to ``None`` — the builder then omits the
    Current-situation section cleanly rather than showing a broken one.
    """
    try:
        return read_situation()
    except Exception as exc:
        logger.warning("App Home situation read failed; omitting the section: %s", exc)
        return None


def _board_url_best_effort(client: WebClient, context: BoltContext, logger: Logger) -> str | None:
    """Build a deep link to the coordinator board canvas, or ``None`` when unavailable.

    Best-effort throughout: a missing canvas id, an unknown team, or any read/auth
    failure degrades to ``None`` so the builder omits the board link cleanly. The
    team domain (for an in-app deep link) is resolved via ``auth.test`` when
    possible; if that fails we still build the slack.com-form link from the team id
    (:func:`coordinator.announce.canvas_link`).
    """
    try:
        canvas_id = load_canvas_id()
    except Exception as exc:
        logger.warning("App Home canvas-id read failed; omitting board link: %s", exc)
        return None
    if not canvas_id:
        return None

    team_url: str | None = None
    try:
        resp = client.auth_test()
        team_url = resp.get("url") or None
    except Exception as exc:
        logger.info("Could not resolve team url for the board link (will use fallback): %s", exc)

    return canvas_link(canvas_id=canvas_id, team_id=context.team_id, team_url=team_url)


def handle_app_home_opened(client: WebClient, context: BoltContext, logger: Logger):
    """Publish the branded App Home view when a user opens the app's Home tab.

    Does the impure reads here (situation feeds + board canvas id), each wrapped so
    a failure degrades/omits rather than crashing, then hands the results to the
    pure :func:`~listeners.views.app_home_builder.build_app_home_view` composer. A
    Home render must never crash — it is the first impression — so the whole body
    is additionally guarded.
    """
    try:
        situation = _read_situation_best_effort(logger)
        board_url = _board_url_best_effort(client, context, logger)
        view = build_app_home_view(situation=situation, board_url=board_url)
        client.views_publish(user_id=context.user_id, view=view)
    except Exception as e:
        logger.exception(f"Failed to publish App Home: {e}")

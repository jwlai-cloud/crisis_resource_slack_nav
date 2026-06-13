# 023 — Persistent quick link to the coordinator board

UX problem (user-observed): the board link is only in a channel message that scrolls
away, and the slack.com/docs/... URL unfurls into an ugly generic "Slack Login"
card. Coordinators need an always-visible quick link.

## Direction
1. **Channel bookmark** (the persistent quick link): on board create/recreate, add or
   update a bookmark in CRISIS_CHANNEL pointing at the board canvas — the bookmark
   bar sits at the top of the channel, one click, never scrolls. Use bookmarks_add /
   bookmarks_edit (slack_sdk has them); add `bookmarks:write` to the manifest (note
   the re-install). Idempotent: update the existing "Community Cases board" bookmark
   rather than adding duplicates (bookmarks_list to find it). Best-effort — a
   bookmark failure never breaks the board create (mirror the announce posture).
2. **Suppress the announce unfurl**: the announce chat_postMessage should pass
   unfurl_links=False, unfurl_media=False so it stops rendering the login card.
3. **Verify the canvas URL form** for this enterprise org: the slack.com/docs/{team}/
   {canvas} link unfurled to a login card — confirm the URL that actually opens the
   canvas for a member (canvases_create response may carry a URL; or construct from
   the team domain crisis-resource-nav.enterprise.slack.com). Use the working URL for
   both the bookmark and the announce link.
4. (App Home board link is task 022 — complementary, also persistent.)

## Acceptance criteria
1. bookmarks:write scope added; on board create/recreate a single "Community Cases
   board" channel bookmark is added/updated (no duplicates on re-run), best-effort.
2. Announce no longer unfurls (no login card); the link form is the one that opens
   the canvas for members.
3. Tests: bookmark add-vs-update logic (mocked bookmarks_list/add/edit), unfurl flags
   on the announce call, URL construction. Zero warnings.
4. [HUMAN] live: after make board, #exmouth-mutual-aid shows a top-bar bookmark that
   opens the board; the announce message has no login-card unfurl.

## Out of scope
Making the board a channel-tab canvas (a larger redesign of 017's standalone-canvas
approach; revisit only if bookmarks prove insufficient).

## Log

# Lists

A list is something the account keeps: a to-do list with things to tick
off, or a general list such as shopping, packing, ideas, names. The agent
reads and edits lists from chat; the lists page edits them by hand and
hands out a link other apps can read. Both write to the same rows, so there
is one list and never two copies of it.

## Where a list lives

Two tables in the portal database (`packages/infrastructure/portal_db.py`):
`account_lists` (name, kind, share token, archived) and `account_list_items`
(text, done, position). Everything else the agent keeps durably lives in the
same file, on the Render disk, so lists need nothing connected.

Limits: 200 lists per account, 500 items per list, 120 characters for a
name, 300 for an item. Adding something already on the list, spelled the
same, is skipped and reported rather than duplicated.

## From chat

Three tools in `packages/infrastructure/agent_loop.py`:

- `create_list(name, kind, items)` starts one.
- `update_list(list_name, action, items, new_name)` changes one: add, remove,
  check, uncheck, rename, clear_done, delete. Delete archives; the page can
  restore.
- `show_lists(list_name)` reads one list with its items, or the names and
  counts of all of them.

The model names the list in the person's words; `find_account_lists` resolves
that to a row (exact name, then contained words). More than one candidate
comes back as `choice_required` with the names as options; none comes back
as `nothing_found` naming the lists that do exist.

Every turn's context carries `listsPage`, the account's lists page, so a reply about lists or todos can point at it even when no tool ran. Every list result also carries `link`: that list on the page. The link is
added to `links_offered`, so the reply guard lets it through. From the
browser it is `/lists#/list/<id>`; from WhatsApp, where the phone has no
session, it is `/lists/open/<code>`: a twelve-character one-time code kept
in `list_open_codes` with the account, the list, and a 48-hour expiry. The
server marks it used, sets a normal session cookie, and redirects to the
list; a second tap lands on `/lists?expired=1`. The code replaced a signed
session token in the URL, which made the link too long to read in a chat
message. Redemption is rate limited per IP so a guessed code stays slow.
On WhatsApp the address is not shown at all: the loop reports the links the
reply carries (`links`, each with a button label such as "Open Packing"),
and the chat lifts each one out of the text and sends it as a call-to-action
button under the message. If the button message fails, the plain text with
the address goes instead.

## Due dates and the morning nudge

A to-do item may carry `dueOn` (YYYY-MM-DD); a general list never does.
From chat, `update_list` takes `due` on `add` and on the `set_due` action
(null clears it); the model works the date out from `CONTEXT.today` and
`todayWeekday`. On the page, the deadline sits under the item and opens the
phone's own date picker. Reminders and the share output say the date too.

`packages/infrastructure/list_due_nudges.py` runs beside the scheduler.
Once a day, after 08:00 where the person is (`PORTAL_LIST_NUDGE_HOUR`; the
timezone comes from their WhatsApp number, else the last message they
scheduled, else UTC), every account with an unticked dated item that is due
today, due tomorrow, or overdue gets one message listing them. It is queued
as a scheduled `send_message`, so it reaches WhatsApp when that is set up
and the in-app feed otherwise. `account_list_nudges` records the day so a
second poll never sends it twice. `PORTAL_LIST_NUDGES_ENABLED=0` turns it off.

A reminder about a list is `schedule_message` with `list_name`. The payload
carries `listId`, never the items: `ScheduledActionScheduler` reads the list
when the message goes out and appends what is still on it.

The web chat is still on the older turn flow, so today the list tools are
reachable over WhatsApp. The page itself works from either.

## The page

`/lists` serves `portal/lists.html` (`lists.js`, `lists.css`), a small
mobile-first app: all lists and a create form, one list with tap-to-edit
items, tick boxes on to-do lists, add bar pinned to the bottom, rename,
archive, restore, delete for good, and sharing. It uses the session cookie
and the `/api/lists` endpoints:

| Method | Path | Does |
| --- | --- | --- |
| GET | `/api/lists?archived=1` | all lists with counts |
| POST | `/api/lists` | `{name, kind, items}` |
| GET | `/api/lists/<id>` | one list with items |
| POST | `/api/lists/<id>` | `{name}`, `{kind}`, `{archived}` |
| DELETE | `/api/lists/<id>` | delete for good |
| POST | `/api/lists/<id>/items` | `{items: [...]}`; returns added and skipped |
| POST | `/api/lists/<id>/items/<itemId>` | `{text}`, `{done}`, `{position}` |
| DELETE | `/api/lists/<id>/items/<itemId>` | remove |
| POST | `/api/lists/<id>/items/clear-done` | drop ticked items |
| POST | `/api/lists/<id>/share` | `{enabled}`; on mints a new token |

The portal's account menu has a Lists entry that opens the page.

## Sharing

Turning sharing on mints a random token and the list becomes readable,
without a sign-in, at:

- `/l/<token>`: a read-only page (`portal/list-share.html`)
- `/api/public/lists/<token>`: JSON `{name, kind, items, updatedAt}`
- `/api/public/lists/<token>.csv`: CSV for a spreadsheet

Only the words on the list go out; nothing names the owner. Turning sharing
off, or archiving the list, makes the token answer 404. Turning it on again
mints a different token, so the old link stays dead.

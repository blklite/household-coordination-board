# Household Coordination Board

A weekly board for a busy, blended household. Each Sunday it builds 3 pages:

- **Whiteboard**: every calendar for the week in 1 view, Monday to Sunday.
  Each day shows where each kid sleeps, from your custody calendars, and marks
  events that overlap. A short "coming up" section covers the next week.
- **Dinner plan**: 7 dinners that fit the week. Each night shows who is at the
  table and when. Practice nights, late arrivals, and diet rules are part of
  the plan.
- **Grocery list**: the shop for that dinner plan, with your staples, the
  items to check before you leave, and what goes into the freezer.

The pages are static HTML files that link to each other through a row of
pill buttons. Open them from the disk, or put the folder on any web host. From
mid-September to February, each page gets the seasonal drawings of the week
(fall, Halloween, Thanksgiving, Christmas, winter).

## How it works

1. The board reads your calendars from their iCal addresses (or a Google
   service account, or the MLB schedule of a team).
2. Code, not a model, decides every event, time, and kid location. The rules
   come from `household.toml`.
3. The whiteboard job makes 1 call to Claude for the week's notes and flags.
   The menu job makes 1 call to Claude for the dinner plan and the grocery
   list. Code checks each reply against a fixed schema before it uses it.
4. The jobs write the pages to a folder.

The dinner plan lists the 7 days first, then the snack shelf, the
assumptions and the open questions, and last the rules of the week and the
diet box. The grocery list's diet box holds only the swap nights and the
labels to read.

### The kitchen rules, the plan history and the retry

Code checks the dinner plan against the kitchen rules before it builds a
page:

- each of your staples is on the list once, for `staples` alone, marked
  "check first", and no other item names a staple;
- at least 1 item is for the snack shelf;
- a dinner cooked double carries to a night at most 2 days later;
- meat whose first night is Wednesday or later goes into the freezer at
  put-away;
- no 2 dinners of the week have the same title, and no dinner repeats a
  title of the week before.

Each good menu run saves its plan in `state/history/plan-<monday>.json`; the
12 newest weeks stay. The next run sends the dinners of the week before to
the model, so that it does not repeat them. With no history file for that
week, the last good plan stands in.

When code rejects a reply (no JSON, the schema, or a rule above), the menu job
asks the same model 1 more time, with the failure texts of code (never the
model's own text) in a `<failed-checks>` part of the prompt. That second call
has its own run folder (`retry/`) and its own dollar cap. When it fails too,
the run fails, and the line says `after 1 retry`. A runner error or a reply
cut short gets no retry.

Calendar text goes to the model only as data. A reply that holds a web
address fails the check, so a hostile calendar event cannot put a link on a
page.

## Requirements

- Python 3.11 or later.
- The [Claude Code](https://claude.com/claude-code) program (`claude`),
  signed in. Without it, the whiteboard still renders with no notes. The menu
  job needs it.
- The iCal address of each calendar. In Google Calendar, open
  **Settings → your calendar → Integrate calendar → Secret address in iCal
  format**. Team and school sites often give a `webcal://` address; that works
  too. An MLB team's games need no address: set `source = "mlb"` and the
  team's `team_id` (see the example).

## Setup

```bash
git clone https://github.com/blklite/household-coordination-board.git
cd household-coordination-board
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e .
cp household.example.toml household.toml
cp kitchen-notes.example.md kitchen-notes.md
cp whiteboard-notes.example.md whiteboard-notes.md
```

1. Edit `household.toml`: your time zone, your people, custody rules,
   calendars, and kitchen settings. The comments in the example explain each
   key. Set `timezone` in `[household]` to your own zone (such as
   `Europe/London`): the days of the board run midnight to midnight in it.
   With no `timezone`, the board uses UTC.
2. Create `household.env` with the address of each calendar. The key names
   match the `env` keys in `household.toml`:

   ```
   HCB_ICAL_FAMILY=https://calendar.google.com/calendar/ical/.../basic.ics
   HCB_ICAL_CUSTODY=https://calendar.google.com/calendar/ical/.../basic.ics
   ```

   On Linux and macOS, run `chmod 600 household.env`. The jobs refuse the file
   when other users can read it.
3. Edit `kitchen-notes.md` (dinners you like, staples) and
   `whiteboard-notes.md` (standing notes, custody overrides).
4. Check the setup. The check reads each calendar and prints 1 line for each,
   then where each kid is and the table line of each night. It writes no page
   and makes no model call.

   ```bash
   hcb check
   ```

To read Google calendars through a service account instead of iCal
addresses, run `pip install -e ".[google]"` and see the `[google]` table in
the example.

## Run

```bash
hcb whiteboard
hcb menu
```

The pages go to `out/`. Each run on a Sunday builds the next Monday to
Sunday. To rebuild the week that is on the board now, add `--this-week`.

A run exits 0 when it is good. It exits 1 when it fails, and also when the
pages are written but a record is not: the line of `state/cost.log`, the last
good plan or the history file. A `household.env` that can not be read fails
the run at its step `config`, with 1 line that names the file and the type
of the error. A config error is exit 2.

### Reading the calendars

Each calendar read has a limit of 30 seconds for the name lookup, the
connect and every read together. The job waits 1 second more for the read to
give its own reason, so a read that hangs ends after 31 seconds at most.
When a host has both IPv6 and IPv4 addresses, the connect tries
them in turn, starting with the family of the first address. Each try but
the last gets a fair share of the time left (the time left divided by the
tries left, at least 5 seconds), so a dead IPv6 route does not use the whole
30 seconds before IPv4 gets a try. A calendar that fails gets a fixed reason,
such as `HTTP 404`, `no reply in 30 s`, or `no reply in 30 s (2 of 8
addresses got no try)` when the time ran out before every address had a try.

To run the jobs each Sunday, see [docs/scheduling.md](docs/scheduling.md).

## Custody rules

Each kid with a custody rule follows the all-day events of 1 calendar. The
title of the event says where the kid sleeps that night, such as "Sam" or
"Chris Weekend". A day with no label, or with labels that disagree, shows as
"unsure" and is listed as an open point. You can also:

- correct 1 day in `whiteboard-notes.md` (Overrides);
- take a kid off the board, or keep a kid home, for a period (`[[bypass]]`);
- mark a trade day with a title prefix such as `TRADE`;
- tag any event with `custody:<word>` in its description.

## Files and privacy

| File | What it holds | In git? |
|---|---|---|
| `household.toml` | Names and rules | No |
| `household.env` | Calendar addresses | No |
| `kitchen-notes.md`, `whiteboard-notes.md` | Your notes | No |
| `out/` | The pages | No |
| `state/` | Run folders, the last good plan, the plan history, `cost.log` | No |

A calendar address is a secret: anyone with it can read the calendar. The
addresses stay in `household.env`. They never reach a printed line, a page,
or the model step. `state/cost.log` records the tokens, seconds, and dollars
of each model call: a call that is followed by a retry has `status=retry`.
The files of a run folder (`reply.txt`, `notes.json`) are written whole or not
at all, and a paid call keeps its counters when its reply can not be written.

## Development

```bash
pip install -e ".[dev,google]"
pytest
```

The tests use a made-up family and synthetic calendars. They make no network
call and no model call.

## License

MIT. See [LICENSE](LICENSE).

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

The pages are static HTML files that link to each other. Open them from the
disk, or put the folder on any web host.

## How it works

1. The board reads your calendars from their iCal addresses.
2. Code, not a model, decides every event, time, and kid location. The rules
   come from `household.toml`.
3. The whiteboard job makes 1 call to Claude for the week's notes and flags.
   The menu job makes 1 call to Claude for the dinner plan and the grocery
   list. Code checks each reply against a fixed schema before it uses it.
4. The jobs write the pages to a folder.

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
  too.

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

1. Edit `household.toml`: your people, custody rules, calendars, and kitchen
   settings. The comments in the example explain each key.
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
| `state/` | Run folders, the last good plan, `cost.log` | No |

A calendar address is a secret: anyone with it can read the calendar. The
addresses stay in `household.env`. They never reach a printed line, a page,
or the model step. `state/cost.log` records the tokens, seconds, and dollars
of each run.

## Development

```bash
pip install -e ".[dev,google]"
pytest
```

The tests use a made-up family and synthetic calendars. They make no network
call and no model call.

## License

MIT. See [LICENSE](LICENSE).

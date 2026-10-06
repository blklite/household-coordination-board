# Household Coordination Board

A weekly board for a busy, blended household. Each Sunday it builds 3 pages:

- **Whiteboard**: every calendar for the week in 1 view, Monday to Sunday.
  Each day shows where each kid sleeps, from your custody calendars.
- **Dinner plan**: 7 dinners that fit the week. Each night shows who is at the
  table and when. Practice nights, late arrivals, and diet rules are part of
  the plan.
- **Grocery list**: the shop for that dinner plan, with your staples.

> **Status: in progress.** This repo is new. The code moves here from a
> private household setup in steps. The commands below describe the target.

## How it works

1. The board reads your calendars from their iCal addresses.
2. Code, not a model, resolves the custody state of each kid for each day.
   The rules come from `household.toml`.
3. The whiteboard job makes 1 call to Claude for the week's notes. The menu
   job makes 1 call to Claude for the dinner plan and the grocery list.
4. The jobs write static HTML pages to a folder. Open them, or host them
   anywhere.

## Requirements

- Python 3.11 or later.
- The [Claude Code](https://claude.com/claude-code) program (`claude`) for the
  model step. Without it, the whiteboard still renders with no notes. The menu
  job needs it.
- The iCal address of each calendar. In Google Calendar, use
  **Settings → your calendar → Secret address in iCal format**.

## Setup

```bash
git clone https://github.com/blklite/household-coordination-board.git
cd household-coordination-board
python -m venv .venv
. .venv/bin/activate
pip install -e .
cp household.example.toml household.toml
```

1. Edit `household.toml`: your people, custody rules, calendars, and kitchen
   settings.
2. Put each calendar address in an environment file, `household.env`. The
   names match the `env` keys in `household.toml`:

   ```
   HCB_ICAL_FAMILY=https://calendar.google.com/calendar/ical/.../basic.ics
   ```

3. Check the setup. The check reads each calendar and prints 1 line for each.
   The check writes no page and makes no model call.

   ```bash
   hcb check
   ```

## Run

```bash
hcb whiteboard
hcb menu
```

The pages go to `out/`. To run each Sunday, use cron, launchd, or the Windows
Task Scheduler. See `docs/scheduling.md`.

## Privacy

`household.toml`, `household.env`, `kitchen-notes.md`, and `out/` are in
`.gitignore`. Never commit them. Calendar addresses never reach a log line,
a page, or the model step.

## License

MIT. See [LICENSE](LICENSE).

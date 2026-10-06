"""The ``hcb`` command: ``hcb check``, ``hcb whiteboard``, ``hcb menu``."""
import argparse
import datetime as dt
import sys

from . import __version__, config, jobs


def main(argv=None, now=lambda: dt.datetime.now(dt.timezone.utc), out=None, **hooks):
    parser = argparse.ArgumentParser(
        prog="hcb", description="Build the household whiteboard, dinner plan and grocery list.")
    parser.add_argument("--version", action="version", version=f"hcb {__version__}")
    parser.add_argument("-c", "--config", help="the household file (default: household.toml, "
                                               "or the HCB_CONFIG environment variable)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="read each calendar and print the coming week; "
                                      "write no page, call no model")
    commands.add_parser("whiteboard", help="build whiteboard.html")
    commands.add_parser("menu", help="build menu.html and groceries.html")
    for sub in commands.choices.values():
        sub.add_argument("--this-week", action="store_true",
                         help="build the current week (Monday to Saturday), not the next week")
    args = parser.parse_args(argv)
    out = out or (lambda line: print(line, flush=True))
    try:
        household = config.load(jobs.resolve_paths(args.config))
    except config.ConfigError as err:
        for error in err.errors:
            out(f"config: {error}")
        return 2
    run = {"check": jobs.check, "whiteboard": jobs.whiteboard, "menu": jobs.menu}[args.command]
    return run(household, now, out, this_week=args.this_week, **hooks)


if __name__ == "__main__":
    sys.exit(main())

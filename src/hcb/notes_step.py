"""The notes step: 1 model call through a runner adapter.

The adapter's contract:

- input: a folder, a prompt file, a time limit and the runner's name;
- output: a fixed last line, files in the folder, and counters for tokens,
  seconds and dollars (``RunResult``).

The runner is ``ClaudeRunner``: the Claude Code program (``claude -p``), run
with no tools, ``--strict-mcp-config`` and no MCP servers, in the run folder,
with a fixed model, a time limit, a dollar cap, and only the environment
variables it needs to find its sign-in (``ENV_KEYS``). No calendar address
reaches it: the addresses live in a dict, never in ``os.environ``.

``run_notes_step`` writes the prompt file (the prompt plus the week as JSON)
into the folder, runs the runner, reads its reply and checks it against the
schema: exactly 4 fields, plain text, with length limits, no web address
(``http://``, ``https://``, ``www.``) as written or as the page shows it, and
no other key. A failed run or a failed check is not a failed job: the caller
renders the grid with 1 line that says the notes are missing.
"""
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .week import plain

LAST_LINE = "END-OF-NOTES"
TIME_LIMIT_SECONDS = 600
# The environment of the model step: what the claude program needs to run and to
# find its sign-in on Linux, macOS and Windows. Nothing else is passed.
ENV_KEYS = ("HOME", "PATH", "LANG", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SYSTEMROOT",
            "TEMP", "TMP", "XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR", "ANTHROPIC_API_KEY",
            "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
            "AWS_PROFILE", "AWS_REGION", "ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION")

# field: (kind, max items for a list, max characters for each string)
SCHEMA = {
    "standing_note": ("text", None, 700),
    "headline": ("text", None, 60),
    "flags": ("list", 6, 300),
    "open_points": ("list", 5, 160),
}
# Event text and the notes file reach the model; a field with a web address
# is how a hostile event would steer the family to a link. It fails the check.
URL = re.compile(r"https?://|www\.", re.I)


def holds_web_address(text):
    """True when ``text`` holds a web address, as written or as it is shown.

    The page shows a text after ``week.plain``, which decodes HTML entities:
    ``h&#116;tps://`` and ``www&period;`` are shown as ``https://`` and ``www.``.
    """
    return bool(URL.search(text) or URL.search(plain(text)))


@dataclass
class RunResult:
    last_line: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    usd: float = 0.0
    error: str = ""         # a fixed reason when the runner itself failed


@dataclass
class NotesOutcome:
    notes: object           # the checked dict, or None
    reason: str             # why there are no notes; "" when there are
    result: RunResult


class ClaudeRunner:
    """The adapter for the Claude Code program (``claude -p``)."""

    name = "claude"

    def __init__(self, binary="claude", model="claude-opus-5-5", budget_usd=0.50,
                 run=subprocess.run, environ=None):
        self.binary, self.model, self.budget = binary, model, budget_usd
        self._run = run
        self._environ = os.environ if environ is None else environ

    def resolved(self):
        """The full path of the program, or None when it is not found."""
        return shutil.which(self.binary, path=self._environ.get("PATH"))

    def argv(self):
        return [self.resolved() or self.binary, "-p", "--model", self.model,
                "--tools", "",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--disable-slash-commands", "--no-session-persistence",
                "--output-format", "json",
                "--max-budget-usd", f"{self.budget:.2f}"]

    def env(self):
        """The whole environment of the model step: no calendar address is in it."""
        found = {key: self._environ[key] for key in ENV_KEYS if self._environ.get(key)}
        found.setdefault("LANG", "C.UTF-8")
        return found

    def run(self, folder, prompt_file, time_limit):
        started = time.monotonic()
        if self.resolved() is None:
            return RunResult(error=f"the program {self.binary} is not found")
        try:
            with open(prompt_file, encoding="utf-8") as stdin:
                proc = self._run(self.argv(), stdin=stdin, capture_output=True,
                                 text=True, encoding="utf-8", timeout=time_limit,
                                 cwd=str(folder), env=self.env())
        except subprocess.TimeoutExpired:
            return RunResult(seconds=round(time.monotonic() - started, 1),
                             error=f"no reply in {time_limit} s")
        except OSError as err:
            return RunResult(error=f"runner did not start ({type(err).__name__})")
        seconds = round(time.monotonic() - started, 1)
        try:
            envelope = json.loads(proc.stdout)
        except (ValueError, TypeError):
            return RunResult(seconds=seconds, error=f"runner exit {proc.returncode}, no JSON")
        usage = envelope.get("usage") or {}
        result = RunResult(
            tokens_in=int(usage.get("input_tokens", 0))
            + int(usage.get("cache_creation_input_tokens", 0))
            + int(usage.get("cache_read_input_tokens", 0)),
            tokens_out=int(usage.get("output_tokens", 0)),
            seconds=round(envelope.get("duration_ms", seconds * 1000) / 1000, 1),
            usd=float(envelope.get("total_cost_usd", 0.0)))
        if proc.returncode != 0 or envelope.get("is_error"):
            result.error = f"runner exit {proc.returncode}"
            return result
        reply = envelope.get("result") or ""
        (Path(folder) / "reply.txt").write_text(reply, encoding="utf-8")
        lines = [line.strip() for line in reply.splitlines() if line.strip()]
        result.last_line = lines[-1] if lines else ""
        return result


def runner_for(household, budget):
    """The runner of a job, from the ``[model]`` table of the household."""
    return ClaudeRunner(binary=household.claude, model=household.model, budget_usd=budget)


def check(obj):
    """``(notes, "")`` when ``obj`` fits the schema, else ``(None, reason)``."""
    if not isinstance(obj, dict):
        return None, "the reply is not a JSON object"
    if set(obj) != set(SCHEMA):
        extra, missing = set(obj) - set(SCHEMA), set(SCHEMA) - set(obj)
        return None, f"wrong fields ({len(extra)} extra, missing {sorted(missing)})"
    notes = {}
    for key, (kind, max_items, max_chars) in SCHEMA.items():
        value = obj[key]
        items = value if kind == "list" else [value]
        if kind == "list" and (not isinstance(value, list) or len(value) > max_items):
            return None, f"{key} is not a list of at most {max_items}"
        clean = []
        for item in items:
            if not isinstance(item, str):
                return None, f"{key} holds a value that is not text"
            text = " ".join(item.split())
            if not text or len(text) > max_chars:
                return None, f"{key} is empty or longer than {max_chars} characters"
            if holds_web_address(text):
                return None, f"{key} holds a web address"
            clean.append(text)
        notes[key] = clean if kind == "list" else clean[0]
    return notes, ""


def json_in(reply, last_line):
    """The JSON object in the reply: from its first ``{`` to its last ``}``."""
    body = reply.rsplit(last_line, 1)[0]
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object")
    return json.loads(body[start:end + 1])


def prompt_text(template, household_text):
    """The prompt with the household's description in place of ``{{HOUSEHOLD}}``."""
    return template.replace("{{HOUSEHOLD}}", household_text)


def run_notes_step(runner, folder, prompt, week_json, time_limit=TIME_LIMIT_SECONDS):
    """Run the notes step in ``folder``. Never raises."""
    folder = Path(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "week.json").write_text(
            json.dumps(week_json, indent=1, ensure_ascii=False), encoding="utf-8")
        prompt_file = folder / "prompt.md"
        prompt_file.write_text(
            f"{prompt.rstrip()}\n\n<week>\n"
            f"{json.dumps(week_json, ensure_ascii=False)}\n</week>\n", encoding="utf-8")
    except OSError as err:
        return NotesOutcome(None, f"run folder not written ({type(err).__name__})", RunResult())
    try:
        result = runner.run(folder, prompt_file, time_limit)
    except Exception as err:  # noqa: BLE001 - a broken runner is a missing note, not a failed job
        return NotesOutcome(None, f"runner failed ({type(err).__name__})", RunResult())
    if result.error:
        return NotesOutcome(None, result.error, result)
    if result.last_line != LAST_LINE:
        return NotesOutcome(None, "the reply has no fixed last line", result)
    try:
        obj = json_in((folder / "reply.txt").read_text(encoding="utf-8"), LAST_LINE)
    except (OSError, ValueError):
        return NotesOutcome(None, "the reply holds no JSON object", result)
    notes, reason = check(obj)
    if notes is None:
        return NotesOutcome(None, f"the reply failed the check: {reason}", result)
    (folder / "notes.json").write_text(json.dumps(notes, indent=1, ensure_ascii=False),
                                       encoding="utf-8")
    return NotesOutcome(notes, "", result)

"""The notes step: text that is not valid Unicode, atomic writes, and the counters of a
paid call."""
import json
import os
import stat
import subprocess
import tempfile

import pytest
from conftest import NOTES, FakeRunner

from hcb import notes_step, output

ENVELOPE = {"is_error": False, "duration_ms": 1000, "total_cost_usd": 0.0812,
            "usage": {"input_tokens": 12000, "output_tokens": 640}}
COUNTERS = {"tokens_in": 12000, "tokens_out": 640, "seconds": 1.0, "usd": 0.0812}


def claude(result, tmp_path):
    """A ``ClaudeRunner`` whose program answers with ``result`` in its JSON envelope."""
    envelope = dict(ENVELOPE, result=result)

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(envelope), stderr="")
    runner = notes_step.ClaudeRunner(run=run, environ={})
    runner.resolved = lambda: "claude"          # no program is looked up or started
    return runner


def step(tmp_path, runner, week=None):
    return notes_step.run_notes_step(runner, tmp_path / "run", "prompt", week or {"days": []})


def counters(result):
    return {key: getattr(result, key) for key in COUNTERS}


# --- text that is not valid Unicode --------------------------------------------------------------

def test_a_note_with_a_lone_surrogate_is_a_missing_note(tmp_path):
    reply = json.dumps(dict(NOTES, headline="Busy \ud800 week"))       # escaped: \ud800
    outcome = step(tmp_path, FakeRunner(reply, notes_step.LAST_LINE))
    assert outcome.notes is None
    assert outcome.reason == ("the reply failed the check: headline holds text that is not "
                              "valid Unicode")
    assert not (tmp_path / "run" / "notes.json").exists()


def test_a_week_with_a_lone_surrogate_is_a_missing_note_at_no_cost(tmp_path):
    runner = FakeRunner(NOTES, notes_step.LAST_LINE)
    outcome = step(tmp_path, runner, {"days": ["\ud800"]})
    assert outcome.notes is None
    assert outcome.reason.startswith("run folder not written (Unicode")
    assert runner.prompts == []


def test_a_claude_reply_with_a_lone_surrogate_keeps_the_counters_of_the_call(tmp_path):
    folder = tmp_path / "run"
    folder.mkdir()
    result = claude("x \ud800\n" + notes_step.LAST_LINE, tmp_path).run(folder, _prompt(folder),
                                                                       60)
    assert result.error == notes_step.NOT_UNICODE_REPLY
    assert counters(result) == COUNTERS
    assert list(folder.iterdir()) == [folder / "prompt.md"]        # no reply.txt, no temp file


def _prompt(folder):
    path = folder / "prompt.md"
    path.write_text("prompt", encoding="utf-8")
    return path


# --- the counters of a paid call -----------------------------------------------------------------

def test_a_reply_txt_that_can_not_be_written_keeps_the_counters_of_the_call(tmp_path):
    folder = tmp_path / "run"
    (folder / "reply.txt").mkdir(parents=True)
    result = claude("x\n" + notes_step.LAST_LINE, tmp_path).run(folder, _prompt(folder), 60)
    assert result.error.startswith("reply.txt not written (")
    assert counters(result) == COUNTERS


@pytest.mark.parametrize("value", [0, [], {"text": "x"}, 12, False])
def test_a_result_that_is_not_text_keeps_the_counters_of_the_call(tmp_path, value):
    folder = tmp_path / "run"
    folder.mkdir()
    result = claude(value, tmp_path).run(folder, _prompt(folder), 60)
    assert result.error == "the Claude reply has no result text"
    assert counters(result) == COUNTERS
    assert not (folder / "reply.txt").exists()


def test_a_good_claude_reply_is_written_whole(tmp_path):
    folder = tmp_path / "run"
    folder.mkdir()
    text = json.dumps(NOTES) + "\n" + notes_step.LAST_LINE
    result = claude(text, tmp_path).run(folder, _prompt(folder), 60)
    assert result.error == "" and result.last_line == notes_step.LAST_LINE
    assert (folder / "reply.txt").read_text(encoding="utf-8") == text


# --- the atomic writes ---------------------------------------------------------------------------

def test_a_notes_json_that_can_not_be_written_is_a_missing_note_with_no_temp_file(tmp_path):
    (tmp_path / "run" / "notes.json").mkdir(parents=True)
    outcome = step(tmp_path, FakeRunner(NOTES, notes_step.LAST_LINE))
    assert outcome.notes is None
    assert outcome.reason.startswith("notes.json could not be written (")
    assert outcome.result.usd == 0.01
    assert [p.name for p in (tmp_path / "run").iterdir() if p.name.startswith(".")] == []


def test_a_write_that_fails_before_the_rename_leaves_the_old_file_and_no_temp_file(
        tmp_path, monkeypatch):
    path = tmp_path / "notes.json"
    path.write_text("old", encoding="utf-8")

    def full(fd):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(output.os, "fsync", full)
    with pytest.raises(OSError):
        output.write_file(path, "new")
    assert path.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["notes.json"]


def test_write_file_writes_through_a_temp_file_in_the_same_folder(tmp_path, monkeypatch):
    made = []
    real = tempfile.mkstemp

    def spy(*args, **kwargs):
        made.append(kwargs.get("dir"))
        return real(*args, **kwargs)
    monkeypatch.setattr(output.tempfile, "mkstemp", spy)
    output.write_file(tmp_path / "reply.txt", "the reply")
    assert made == [tmp_path]
    assert (tmp_path / "reply.txt").read_text(encoding="utf-8") == "the reply"


@pytest.mark.skipif(not hasattr(os, "O_DIRECTORY"), reason="no folder fsync on this system")
def test_notes_written_with_their_folder_not_synced_stand(tmp_path, monkeypatch):
    real = os.fsync

    def no_folder_sync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(5, "I/O error")
        return real(fd)
    monkeypatch.setattr(output.os, "fsync", no_folder_sync)
    with pytest.raises(output.FolderSyncError):
        output.write_file(tmp_path / "x.txt", "x")
    assert (tmp_path / "x.txt").read_text(encoding="utf-8") == "x"
    outcome = step(tmp_path, FakeRunner(NOTES, notes_step.LAST_LINE))
    assert outcome.notes is not None and outcome.reason == ""
    assert json.loads((tmp_path / "run" / "notes.json").read_text(encoding="utf-8")) == \
        outcome.notes

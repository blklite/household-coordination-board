"""The menu job: the kitchen rules in code, the plan history, the retry, and the edges of a run."""
import copy
import datetime as dt
import json
import os
from pathlib import Path

import pytest
from conftest import MONDAY, NOTES, NOW, STAPLES, FakeRunner, plan_for

from hcb import cli, jobs, notes_step, plan_step

STAPLE_ITEMS = range(4, 4 + len(STAPLES))      # the list items of the staples in plan_for


def good():
    return plan_for(MONDAY, STAPLES)


def errors(plan, earlier=()):
    checked = plan_step.validate(plan, plan_step.SCHEMA)
    return plan_step.check_plan(checked, MONDAY, STAPLES, earlier)[1]


def test_the_plan_of_the_tests_passes_every_rule():
    assert errors(good()) == []


# --- the kitchen rules in code ---------------------------------------------------------------

def test_a_staple_on_2_list_items_fails():
    plan = good()
    plan["shopping"].append(copy.deepcopy(plan["shopping"][STAPLE_ITEMS[0]]))
    assert errors(plan) == ["the staple Milk (2 gal) is on the list 2 times"]


@pytest.mark.parametrize("change", [{"days": ["staples", "Mon"]}, {"days": ["Mon"]},
                                    {"check_first": False}])
def test_a_staple_item_is_days_staples_alone_with_check_first(change):
    plan = good()
    plan["shopping"][STAPLE_ITEMS[1]].update(change)
    assert errors(plan) == ["the list item of the staple Eggs (2 dozen) is not days staples "
                            "with check first"]


def test_no_other_item_names_a_staple():
    plan = good()
    plan["shopping"][0]["staple"] = "Broccoli"
    assert errors(plan) == ["shopping[0].staple is not a staple of the kitchen notes"]


def test_the_staples_match_in_any_case_and_spacing():
    plan = good()
    plan["shopping"][STAPLE_ITEMS[0]]["staple"] = "milk  (2 GAL)"
    assert errors(plan) == []


def test_at_least_1_list_item_is_for_the_snack_shelf():
    plan = good()
    plan["shopping"] = [i for i in plan["shopping"] if i["days"] != ["snack shelf"]]
    assert errors(plan) == ["no list item is for the snack shelf"]


def test_a_carry_over_goes_at_most_2_days_later():
    plan = good()
    plan["dinners"][0]["carries"] = [{"to": "2026-10-14", "what": "Half the chicken"}]
    assert errors(plan) == []
    plan["dinners"][0]["carries"] = [{"to": "2026-10-15", "what": "Half the chicken"}]
    assert errors(plan) == ["the carry-over of 2026-10-12 goes more than 2 days later"]


@pytest.mark.parametrize("days, freeze, ok", [
    (["Wed"], False, False), (["Sun"], False, False), (["Tue", "Wed"], False, True),
    (["Wed", "Fri"], True, True), (["staples"], False, True)])
def test_meat_whose_first_night_is_wed_or_later_is_marked_freeze(days, freeze, ok):
    plan = good()
    plan["shopping"][1].update(days=days, freeze=freeze)
    assert errors(plan) == ([] if ok else
                            ["shopping[1] is meat for Wed or later and is not marked freeze"])


def test_no_2_dinners_of_the_week_have_the_same_title():
    plan = good()
    plan["dinners"][5]["title"] = "dinner  2"
    assert errors(plan) == ["the dinners of 2026-10-13 and 2026-10-17 have the same title"]


def test_no_dinner_repeats_a_title_of_the_earlier_dinners():
    earlier = [{"date": "2026-10-07", "title": "Dinner 3"}]
    assert errors(good(), earlier) == [
        "the dinner of 2026-10-14 repeats a dinner of the week of 2026-10-05"]


def test_the_rules_box_may_hold_0_rules_and_no_more_than_5():
    plan = good()
    plan["week_rules"] = []
    assert errors(plan) == []
    plan["week_rules"] = [{"lead": "A rule", "text": ""}] * 6
    with pytest.raises(plan_step.PlanError):
        plan_step.validate(plan, plan_step.SCHEMA)


def test_the_prompt_states_the_rules_and_the_retry_part():
    prompt = " ".join(jobs._asset("plan_prompt.md").split())
    for words in ("earlier_dinners", "at most 2 days after", "`Wed` or later has `freeze` true",
                  "at least 1 list item is for the snack shelf", "<failed-checks>",
                  "Every other item has `staple` `\"\"`", "0 to 5 objects"):
        assert words in prompt


# --- the runs ---------------------------------------------------------------------------------

class SeqRunner:
    """A runner that answers each call with the next reply of ``replies``."""

    name = "seq"

    def __init__(self, *replies):
        self.replies, self.prompts, self.folders = list(replies), [], []

    def run(self, folder, prompt_file, time_limit):
        self.prompts.append(Path(prompt_file).read_text(encoding="utf-8"))
        self.folders.append(Path(folder))
        reply = self.replies.pop(0)
        text = reply if isinstance(reply, str) else json.dumps(reply)
        (Path(folder) / "reply.txt").write_text(f"{text}\n{plan_step.LAST_LINE}\n",
                                                encoding="utf-8")
        return notes_step.RunResult(last_line=plan_step.LAST_LINE, tokens_in=10,
                                    tokens_out=20, seconds=1.0, usd=0.25)


def run(command, home, fetch, runner, now=NOW, **hooks):
    lines = []
    if command != "check":
        hooks["runner"] = runner
    code = cli.main(["-c", str(home / "household.toml"), command], now=lambda: now,
                    out=lines.append, fetch=fetch, **hooks)
    return code, lines


def cost_lines(home):
    return (home / "state" / "cost.log").read_text(encoding="utf-8").splitlines()


def no_snack(plan):
    plan["shopping"] = [i for i in plan["shopping"] if i["days"] != ["snack shelf"]]
    return plan


def test_a_rejected_reply_gets_1_retry_with_the_failure_texts(home, fetch):
    runner = SeqRunner(no_snack(good()), good())
    code, lines = run("menu", home, fetch, runner)
    assert code == 0, lines
    assert len(runner.prompts) == 2 and runner.folders[1].name == "retry"
    assert "\n<failed-checks>\n" not in runner.prompts[0]
    retry = runner.prompts[1]
    assert retry.startswith(runner.prompts[0])
    assert ("<failed-checks>\n- no list item is for the snack shelf\n</failed-checks>\n"
            + plan_step.RETRY_ASK) in retry
    assert [line.split(" status=")[1] for line in cost_lines(home)] == ["retry", "ok"]


def test_a_reply_with_no_json_gets_1_retry(home, fetch):
    runner = SeqRunner("sorry", good())
    code, lines = run("menu", home, fetch, runner)
    assert code == 0, lines
    assert "- the reply holds no JSON object\n" in runner.prompts[1]


def test_a_retry_that_fails_fails_the_run_and_says_after_1_retry(home, fetch):
    runner = SeqRunner(no_snack(good()), no_snack(good()))
    code, lines = run("menu", home, fetch, runner)
    assert code == 1
    assert ("menu failed at the step plan: the plan failed a check: no list item is for the "
            "snack shelf, after 1 retry") in lines
    assert [line.split(" status=")[1] for line in cost_lines(home)] == ["retry", "failed:plan"]
    assert not (home / "out" / "menu.html").exists()


def test_a_runner_error_gets_no_retry(home, fetch):
    class Broken:
        calls = 0

        def run(self, folder, prompt_file, time_limit):
            Broken.calls += 1
            return notes_step.RunResult(error="runner exit 1", usd=0.1)
    code, lines = run("menu", home, fetch, Broken())
    assert code == 1 and Broken.calls == 1
    assert "menu failed at the step plan: runner exit 1" in lines


def test_the_retry_prompt_holds_at_most_20_failure_texts(tmp_path):
    plan = good()
    plan["shopping"] = [dict(plan["shopping"][1], days=["Thu"], freeze=False)
                        for _ in range(25)] + plan["shopping"]
    runner = SeqRunner(plan, good())
    plan_step.run_plan_step(runner, tmp_path, "prompt", {"earlier_dinners": []}, MONDAY,
                            STAPLES)
    part = runner.prompts[1].split("<failed-checks>\n")[1].split("</failed-checks>")[0]
    assert len(part.splitlines()) == 20


def test_a_plan_json_that_can_not_be_written_gives_no_plan_and_no_retry(tmp_path):
    (tmp_path / "plan.json").mkdir()
    runner = SeqRunner(good())
    outcome = plan_step.run_plan_step(runner, tmp_path, "prompt", {}, MONDAY, STAPLES)
    assert outcome.plan is None and outcome.reason.startswith("plan.json not written (")
    assert outcome.result.usd == 0.25 and len(runner.prompts) == 1


def test_a_plan_json_write_that_fails_fails_the_run_under_step_plan(home, fetch, monkeypatch):
    real = Path.write_text

    def refuse(path, *args, **kwargs):
        if path.name == "plan.json":
            raise PermissionError("no")
        return real(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", refuse)
    code, lines = run("menu", home, fetch, SeqRunner(good()))
    assert code == 1
    assert "menu failed at the step plan: plan.json not written (PermissionError)" in lines


# --- the plan history -------------------------------------------------------------------------

def test_a_good_run_saves_the_plan_in_the_history(home, fetch):
    assert run("menu", home, fetch, SeqRunner(good()))[0] == 0
    saved = json.loads((home / "state" / "history" / "plan-2026-10-12.json").read_text(
        encoding="utf-8"))
    assert saved["monday"] == "2026-10-12" and len(saved["plan"]["dinners"]) == 7


def test_the_history_keeps_the_12_newest_weeks(home, household):
    folder = home / "state" / "history"
    folder.mkdir(parents=True)
    for week in range(14):
        (folder / f"plan-{MONDAY - dt.timedelta(weeks=week + 1)}.json").write_text("{}")
    jobs.save_history(household, MONDAY, good())
    kept = sorted(p.name for p in folder.iterdir())
    assert len(kept) == 12 and kept[-1] == "plan-2026-10-12.json"
    assert kept[0] == f"plan-{MONDAY - dt.timedelta(weeks=11)}.json"


def test_the_earlier_dinners_are_the_week_before_from_its_history_file(home, fetch):
    last = plan_for(MONDAY - dt.timedelta(weeks=1), STAPLES)
    folder = home / "state" / "history"
    folder.mkdir(parents=True)
    (folder / "plan-2026-10-05.json").write_text(json.dumps(
        {"monday": "2026-10-05", "plan": last}), encoding="utf-8")
    runner = SeqRunner(good(), good())
    code, lines = run("menu", home, fetch, runner)
    sent = json.loads(runner.prompts[0].split("<input>\n")[1].split("\n</input>")[0])
    assert sent["earlier_dinners"][0] == {"date": "2026-10-05", "title": "Dinner 1"}
    assert len(sent["earlier_dinners"]) == 7
    # Each title of the plan of the tests is a title of the week before: both calls fail.
    assert code == 1 and "repeats a dinner of the week of 2026-10-05" in lines[0]


def test_the_last_good_plan_stands_in_for_a_week_with_no_history_file(home, household):
    saved = {"monday": "2026-10-05", "plan": plan_for(dt.date(2026, 10, 5), STAPLES)}
    assert len(jobs.earlier_dinners(household, MONDAY, saved)) == 7
    # A plan of this same Monday is never an earlier week.
    assert jobs.earlier_dinners(household, MONDAY, {"monday": "2026-10-12",
                                                    "plan": good()}) == []
    assert jobs.earlier_dinners(household, MONDAY, None) == []


# --- the edges of a run -----------------------------------------------------------------------

@pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX only")
@pytest.mark.parametrize("command", ["whiteboard", "menu", "check"])
def test_an_env_file_that_can_not_be_read_fails_the_step_config(home, fetch, command):
    env = home / "household.env"
    env.write_bytes(b"HCB_ICAL_FAMILY=\xff\xfe\n")
    env.chmod(0o600)
    runner = FakeRunner(NOTES, notes_step.LAST_LINE)
    code, lines = run(command, home, fetch, runner)
    assert code == 1
    expected = ("config: failed, household.env not read (UnicodeDecodeError)" if command == "check"
                else f"{command} failed at the step config: household.env not read "
                     "(UnicodeDecodeError)")
    assert expected in lines
    assert not any("Traceback" in line or "unexpected" in line for line in lines)


@pytest.mark.parametrize("command", ["whiteboard", "menu"])
def test_a_good_run_whose_cost_line_is_not_written_exits_1(home, fetch, command):
    (home / "state" / "cost.log").mkdir(parents=True)
    runner = (FakeRunner(NOTES, notes_step.LAST_LINE) if command == "whiteboard"
              else SeqRunner(good()))
    code, lines = run(command, home, fetch, runner)
    assert code == 1
    assert any(line.startswith("cost.log not written (") for line in lines)
    assert (home / "out" / f"{'whiteboard' if command == 'whiteboard' else 'menu'}.html").exists()

"""Background tasks: every run recorded, failures kept with their error, and
the few-second sweep not flooding the history."""

import asyncio

from tests.test_auth import claim


def _task(key, fn, every=60, store=True):
    from app import tasks

    tasks.register(tasks.Task(key, key.title(), "A test task.", fn, lambda: every, store_every_run=store))


def _runs(client, key):
    return client.get(f"/api/tasks/{key}/runs").json()


def test_runs_are_recorded_with_errors_and_skips(client):
    from app import tasks

    claim(client)

    async def ok():
        return {"history": 12, "ips": 0}

    async def boom():
        raise RuntimeError("Tautulli said no to http://x/api?apikey=secret123")

    async def nothing():
        raise tasks.Skipped("Not set up yet")

    _task("t_ok", ok)
    _task("t_boom", boom)
    _task("t_skip", nothing)
    for key in ("t_ok", "t_boom", "t_skip"):
        asyncio.run(tasks.run(key))

    listed = {t["key"]: t for t in client.get("/api/tasks").json()}
    assert listed["t_ok"]["last"]["status"] == "ok" and listed["t_ok"]["last"]["message"] == "history 12"
    assert listed["t_boom"]["failures"] == 1 and listed["t_boom"]["every_seconds"] == 60
    failure = _runs(client, "t_boom")[0]
    # The sentence somebody wrote to be read, not four thousand characters of
    # stack with it buried in the middle. The stack goes to the log.
    assert failure["status"] == "failed"
    assert failure["message"].startswith("Tautulli said no")
    assert "Traceback" not in failure["message"]
    assert "secret123" not in failure["message"]
    assert _runs(client, "t_skip")[0]["status"] == "skipped"
    # The real tasks are all listed.
    assert {"sync", "slow_sync", "enforce", "capabilities", "replacements"} <= set(listed)


def test_the_sweep_stores_only_failures_and_runs_by_hand_are_logged(client):
    from app import tasks

    claim(client)
    calls = {"n": 0}

    async def sweep():
        calls["n"] += 1
        if calls["n"] == 3:
            raise ValueError("bad poll")
        return {"checked": 2}

    _task("t_sweep", sweep, every=5, store=False)
    for _ in range(4):
        asyncio.run(tasks.run("t_sweep"))
    assert [r["status"] for r in _runs(client, "t_sweep")] == ["failed"]
    assert tasks.TASKS["t_sweep"].runs == 4

    assert client.post("/api/tasks/t_sweep/run").status_code == 200
    assert client.post("/api/tasks/nope/run").status_code == 404
    actions = [e["action"] for e in client.get("/api/log?kind=changes").json()]
    assert "task.run" in actions


def test_old_runs_are_pruned(client):
    from app import tasks

    claim(client)

    async def ok():
        return "fine"

    _task("t_many", ok)
    for _ in range(tasks.KEEP_RUNS + 5):
        asyncio.run(tasks.run("t_many"))
    assert len(client.get("/api/tasks/t_many/runs?limit=500").json()) == tasks.KEEP_RUNS


def test_every_task_is_scheduled_and_none_paused(client):
    """A job added with next_run_time=None is paused. The rule sweep once was."""
    from app import tasks

    assert tasks.scheduler is not None
    for key in ("sync", "slow_sync", "enforce", "capabilities", "replacements"):
        job = tasks.scheduler.get_job(key)
        assert job is not None and job.next_run_time is not None, key

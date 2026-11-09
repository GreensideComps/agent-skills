"""End-to-end test of hostctl against a local bare repo with a fake agent (no broker, no network)."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOSTCTL = HERE / "hostctl.py"

FAKE_AGENT = r'''
import json, os, signal, sys, time
from pathlib import Path
st = Path(os.environ["MARKET_AGENT_STATE"])
stop = False
def term(*_):
    global stop; stop = True
signal.signal(signal.SIGTERM, term)
n = 0
while not stop:
    n += 1
    (st / "heartbeat.json").write_text(json.dumps({"t": time.time(), "version": "fake", "loops": n}))
    with open(st / "events" / time.strftime("%Y-%m-%d.jsonl", time.gmtime()), "a") as f:
        f.write(json.dumps({"kind": "heartbeat", "ctl": json.loads((st / "control.json").read_text())}) + "\n")
    time.sleep(0.2)
'''


def sh(*a, cwd=None, env=None, check=True):
    r = subprocess.run(a, cwd=cwd, env=env, capture_output=True, text=True)
    if check and r.returncode:
        raise AssertionError(f"{a}: {r.stdout}{r.stderr}")
    return r


def setup(tmp: Path):
    bare = tmp / "remote.git"
    sh("git", "init", "-q", "--bare", str(bare))
    work = tmp / "work"
    sh("git", "clone", "-q", str(bare), str(work))
    agent = work / "agent"
    agent.mkdir()
    (agent / "fake_agent.py").write_text(FAKE_AGENT)
    sh("git", "-C", str(work), "add", ".")
    sh("git", "-C", str(work), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "agent v1")
    sh("git", "-C", str(work), "push", "-q", "origin", "HEAD:refs/heads/agent-branch")
    # session-side project root
    proj = tmp / "proj"
    st = proj / "market-agent/state"
    (st / "events").mkdir(parents=True)
    (st / "intents").mkdir()
    (st / "control.json").write_text(json.dumps({"trading_enabled": True, "reason": "test"}))
    (st / "intents/intents.jsonl").write_text('{"id": "x", "status": "filled"}\n')
    (st / "events/2020-01-01.jsonl").write_text("old\n")  # outside the kept window
    (st / "lease.json").write_text(json.dumps({"instance": "old", "t": 0}))
    (st / "sec_user_agent.txt").write_text("secret-ua\n")
    fwd = proj / "research/always-on/forward"
    fwd.mkdir(parents=True)
    (fwd / "Q206_picks_2026-11.csv").write_text("a,b\n")
    (fwd / "Q205.csv").write_text("h\n")
    return bare, work, proj


def run_test(tmp: Path):
    env = {**os.environ, "T212_API_KEY": "k", "T212_API_SECRET": "s3cret", "GITHUB_RUN_ID": "r1"}
    bare, work, proj = setup(tmp)
    hc = [sys.executable, str(HOSTCTL), "--repo", str(work)]
    # seed refuses while a local lease is live
    (proj / "market-agent/state/lease.json").write_text(json.dumps({"instance": "live", "t": time.time()}))
    assert sh(*hc, "seed", "--root", str(proj), env=env, check=False).returncode == 1
    (proj / "market-agent/state/lease.json").write_text(json.dumps({"instance": None, "t": 0}))
    sh(*hc, "seed", "--root", str(proj), env=env)
    # secret material never appears in the public branch
    sh("git", "-C", str(work), "fetch", "-q", "origin", "market-agent-state")
    tree = sh("git", "-C", str(work), "ls-tree", "-r", "FETCH_HEAD").stdout
    for name in ("snapshot.tar.gz.enc", "owner.json", "control.json", "inputs.tar.gz.enc"):
        assert name in tree, tree
    raw = subprocess.run(["git", "-C", str(work), "cat-file", "blob", "FETCH_HEAD:snapshot.tar.gz.enc"],
                         capture_output=True, check=True).stdout
    assert b"secret-ua" not in raw
    # hosted run on a fresh root
    host = tmp / "hostroot"
    host.mkdir()
    # the runner has a DIFFERENT secret: it registers its key and waits for a reseal
    renv = {**env, "T212_API_SECRET": "runner-secret"}
    r = sh(*hc, "run", "--root", str(host), "--agent-ref", "agent-branch", "--code-dir", str(tmp / "code0"),
           "--budget-min", "1", env=renv)
    assert "registered this host's key" in r.stdout and "hostctl reseal" in r.stdout, r.stdout
    sh(*hc, "reseal", env=env)
    runner = subprocess.Popen(hc + ["run", "--root", str(host), "--agent-ref", "agent-branch",
                                    "--code-dir", str(tmp / "code"), "--budget-min", "0.4", "--tick-s", "0.5", "--sync-s", "3",
                                    "--agent-cmd", f"{sys.executable} fake_agent.py"],
                              env=renv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(8)
    assert (host / "market-agent/state/sec_user_agent.txt").read_text() == "secret-ua\n"
    assert (host / "research/always-on/forward/Q206_picks_2026-11.csv").exists()
    assert not (host / "market-agent/state/events/2020-01-01.jsonl").exists()
    st = json.loads(sh(*hc, "status", env=env).stdout)
    assert st["hosted_live"] and st["hosted"]["run_id"] == "r1", st
    # a session must not mirror over a live local agent, but can mirror otherwise
    sh(*hc, "halt", "test halt", env=env)
    out, _ = runner.communicate(timeout=120)
    assert runner.returncode == 0, out
    assert "agent started" in out and "final snapshot pushed" in out, out
    st = json.loads(sh(*hc, "status", env=env, check=False).stdout)
    assert st["hosted"]["restarts"] == 0, (st, out)
    assert st["hosted"]["phase"] == "stopped" and not st["hosted_live"], st
    mirror = tmp / "mirror"
    sh(*hc, "mirror", "--root", str(mirror), env=env)
    ev = (mirror / "market-agent/state/events" / time.strftime("%Y-%m-%d.jsonl", time.gmtime())).read_text()
    assert '"trading_enabled": false' in ev.replace('"trading_enabled":false', '"trading_enabled": false'), ev[-300:]
    lease = mirror / "market-agent/state/lease.json"
    assert not lease.exists() or json.loads(lease.read_text())["instance"] is None
    # handover to session: the next run stands by
    sh(*hc, "handover", "--to", "session", "--reason", "test", "--wait-s", "5", env=env)
    r = sh(*hc, "run", "--root", str(host), "--agent-ref", "agent-branch", "--code-dir", str(tmp / "code"),
           "--budget-min", "1", env={**renv, "GITHUB_RUN_ID": "r2"})
    assert "standby" in r.stdout, r.stdout
    # wrong secret cannot decrypt
    bad = sh(*hc, "mirror", "--root", str(tmp / "m2"), env={**env, "T212_API_SECRET": "nope"}, check=False)
    assert bad.returncode != 0
    print("ok")


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        run_test(Path(d))

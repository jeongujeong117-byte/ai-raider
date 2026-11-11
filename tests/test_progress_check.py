import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import progress_check as pc  # noqa: E402

GIT = shutil.which("git")

BOARD_TMPL = """# 작업 현황

| ID | 제목 | 담당 | 상태 | 브랜치 | 반려 횟수 |
|---|---|---|---|---|---|
{rows}

## 역사
| ID | 제목 | 담당 | 상태 | 브랜치 | 반려 횟수 |
|---|---|---|---|---|---|
| T-009 | 과거 | S1 | 진행 중 | x | 5 |
"""


def board(*rows):
    return BOARD_TMPL.format(rows="\n".join(rows))


A, B, C = "aaaaaaa1", "bbbbbbb2", "ccccccc3"
FULL = {A: "a" * 39 + "1", B: "b" * 39 + "2", C: "c" * 39 + "3", "develop": "d" * 40,
        "master": "0be384f" + "0" * 33, "0be384f": "0be384f" + "0" * 33}


class FakeEnv:
    """run_command 를 대체하는 주입 가능한 가짜 git/orca."""

    def __init__(self, board_text, ancestors=(), unresolved=(), dirty=(), tasks=None,
                 workers=None, worktrees=None, orca_status="ok", orca_rc=0,
                 orca_stdout=None, git_fail=False):
        self.board_text = board_text
        self.ancestors, self.unresolved, self.dirty = set(ancestors), set(unresolved), set(dirty)
        self.tasks = tasks if tasks is not None else []
        self.workers = workers if workers is not None else []
        self.worktrees = worktrees or ["/r/main::refs/heads/develop", "/r/t-005-dev::refs/heads/x/t-005-dev"]
        self.orca_status, self.orca_rc, self.orca_stdout = orca_status, orca_rc, orca_stdout
        self.git_fail = git_fail
        self.calls = []

    def __call__(self, argv, timeout=15.0, max_bytes=0):
        self.calls.append(list(argv))
        exe = Path(argv[0]).stem
        if exe != "git":
            return self._orca(argv)
        if self.git_fail:
            return pc.CmdResult("missing")
        a = argv[1:]
        if a[0] == "--no-optional-locks":
            a = a[1:]
        path, a = a[1], a[2:]
        if a[0] == "rev-parse" and a[1] == "--git-dir":
            return pc.CmdResult("ok", 0, ".git")
        if a[0] == "worktree":
            out = ""
            for w in self.worktrees:
                p, b = w.split("::")
                out += f"worktree {p}\nHEAD {'e'*40}\nbranch {b}\n\n"
            return pc.CmdResult("ok", 0, out)
        if a[0] == "status":
            return pc.CmdResult("ok", 0, " M f.py\n?? g.py\n" if path in self.dirty else "")
        if a[0] == "rev-parse":
            name = a[3].replace("^{commit}", "")
            if name in self.unresolved or name not in FULL and name not in FULL.values():
                return pc.CmdResult("ok", 1, "")
            return pc.CmdResult("ok", 0, FULL.get(name, name) + "\n")
        if a[0] == "merge-base":
            full = a[2]
            return pc.CmdResult("ok", 0 if full in {FULL[x] for x in self.ancestors} else 1, "")
        raise AssertionError(a)

    def _orca(self, argv):
        if self.orca_status != "ok":
            return pc.CmdResult(self.orca_status)
        if self.orca_stdout is not None:
            return pc.CmdResult("ok", self.orca_rc, self.orca_stdout)
        key = "tasks" if argv[2] == "task-list" else "workers"
        items = self.tasks if key == "tasks" else self.workers
        return pc.CmdResult("ok", self.orca_rc, json.dumps({"ok": True, "result": {key: items}}))


def run_main(env, repo_dir, extra=()):
    """FakeEnv 로 main 을 실행하고 (rc, stdout) 반환."""
    (Path(repo_dir) / "handoff").mkdir(exist_ok=True)
    (Path(repo_dir) / "handoff" / "BOARD.md").write_text(env.board_text, encoding="utf-8")
    out = io.StringIO()
    with mock.patch.object(pc, "run_command", env), \
            mock.patch.object(pc.shutil, "which", return_value="/usr/bin/git"), \
            mock.patch.object(pc, "resolve_executable", return_value="/usr/bin/orca"), \
            contextlib.redirect_stdout(out):
        rc = pc.main(["--repo", str(repo_dir), "--run", "run_x", "--json", *extra])
    return rc, out.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.dir = self._td.name

    def run_json(self, env, extra=()):
        rc, out = run_main(env, self.dir, extra)
        return rc, json.loads(out)

    def codes(self, data):
        return [f["code"] for f in data["findings"]]

    def check(self, data, name):
        return next(c for c in data["checks"] if c["name"] == name)


class BoardParsingTests(unittest.TestCase):
    def test_only_main_table_and_malformed(self):
        rows = pc.parse_board(board("| T-001 | a | S1 | 병합 완료 | develop (aaaaaaa1) | 0 |"))
        self.assertEqual([r["id"] for r in rows], ["T-001"])  # 역사 절 T-009 제외
        with self.assertRaises(pc.BoardError):
            pc.parse_board("no table here")
        with self.assertRaises(pc.BoardError):
            pc.parse_board("| ID | 제목 | 담당 | 상태 | 브랜치 | 반려 횟수 |\n|---|---|---|---|---|---|\n| T-001 | x |\n")

    def test_task_tid_exact_boundary(self):
        self.assertEqual(pc.task_tid("T-001 수집기"), "T-001")
        self.assertIsNone(pc.task_tid("T-0010 x"))
        self.assertIsNone(pc.task_tid("XT-001 x"))
        self.assertIsNone(pc.task_tid("T-001 T-003 학습"))  # 복수 → 모호
        self.assertIsNone(pc.task_tid("New messages"))

    def test_commit_tokens_ignore_words(self):
        self.assertEqual(pc.commit_tokens("개발 c4783ac, develop, 2026-11-12, 1234567"), ["c4783ac"])


class MergeAndIntegrationTests(Base):
    def test_merged_ancestor_ok(self):
        env = FakeEnv(board("| T-001 | a | S1 | 병합 완료 | develop (개발 aaaaaaa1, QA bbbbbbb2) | 0 |"),
                      ancestors=[A, B])
        rc, d = self.run_json(env)
        self.assertEqual(rc, 0, d["findings"])
        self.assertEqual(self.check(d, "merged_ancestry:T-001")["status"], "ok")

    def test_merged_not_ancestor_error(self):
        env = FakeEnv(board("| T-001 | a | S1 | 병합 완료 | develop (aaaaaaa1) | 0 |"))
        rc, d = self.run_json(env)
        self.assertEqual(rc, 1)
        self.assertIn("MERGED_NOT_ANCESTOR", self.codes(d))
        self.assertEqual(d["findings"][0]["severity"], "error")

    def test_merged_partial_is_warning(self):
        env = FakeEnv(board("| T-001 | a | S1 | 병합 완료 | aaaaaaa1 bbbbbbb2 | 0 |"), ancestors=[A])
        rc, d = self.run_json(env)
        self.assertEqual(rc, 1)
        self.assertEqual(self.codes(d), ["MERGED_PARTIAL_ANCESTOR"])

    def test_merged_unresolvable_is_unknown_no_false_error(self):
        env = FakeEnv(board("| T-001 | a | S1 | 병합 완료 | aaaaaaa1 | 0 |"), unresolved=[A])
        rc, d = self.run_json(env)
        self.assertEqual(rc, 0)
        self.assertNotIn("MERGED_NOT_ANCESTOR", self.codes(d))
        self.assertEqual(self.check(d, "merged_ancestry:T-001")["status"], "unknown")

    def test_merged_without_commit_unknown(self):
        env = FakeEnv(board("| T-001 | a | S1 | 병합 완료 | develop | 0 |"))
        rc, d = self.run_json(env)
        self.assertEqual(self.check(d, "merged_ancestry:T-001")["status"], "unknown")
        self.assertEqual(rc, 0)

    def test_open_but_fully_integrated(self):
        env = FakeEnv(board("| T-004 | a | S1 → S2 QA | 진행 중 개발 aaaaaaa1 | QA bbbbbbb2 | 0 |"),
                      ancestors=[A, B])
        rc, d = self.run_json(env)
        self.assertEqual(rc, 1)
        self.assertIn("OPEN_BUT_INTEGRATED", self.codes(d))

    def test_open_with_unintegrated_or_single_evidence_unknown(self):
        env = FakeEnv(board("| T-004 | a | S1 → S2 QA | 진행 중 개발 aaaaaaa1 | QA bbbbbbb2 | 0 |"),
                      ancestors=[A])
        rc, d = self.run_json(env)
        self.assertEqual(rc, 0)
        self.assertEqual(self.check(d, "open_integration:T-004")["status"], "unknown")
        env = FakeEnv(board("| T-004 | a | S1 QA | 진행 중 aaaaaaa1 | x | 0 |"), ancestors=[A])
        rc, d = self.run_json(env)
        self.assertNotIn("OPEN_BUT_INTEGRATED", self.codes(d))  # 증거 1건만

    def test_branch_name_alone_not_evidence(self):
        env = FakeEnv(board("| T-005 | a | S1 | 배정 준비 | 예정 t-005-dev | 0 |"))
        rc, d = self.run_json(env)
        self.assertEqual(rc, 0)
        self.assertNotIn("OPEN_BUT_INTEGRATED", self.codes(d))

    def test_history_section_not_current(self):
        env = FakeEnv(board("| T-001 | a | S1 | 병합 완료 | aaaaaaa1 | 0 |"), ancestors=[A])
        rc, d = self.run_json(env)
        self.assertEqual(rc, 0)
        self.assertFalse(any(c["name"].endswith("T-009") for c in d["checks"]))

    def test_rejections(self):
        env = FakeEnv(board("| T-001 | a | S1 | 병합 완료 | aaaaaaa1 | 2 |",
                            "| T-002 | a | S1 | 병합 완료 | aaaaaaa1 | 1 |",
                            "| 학습 | a | S3 | 완료 | x | 해당 없음 |"), ancestors=[A])
        rc, d = self.run_json(env)
        self.assertEqual(rc, 1)
        warn = [f for f in d["findings"] if f["code"] == "REJECTION_COUNT_HIGH"]
        self.assertEqual([f["task_id"] for f in warn], ["T-001"])

    def test_unparseable_rejection_unknown(self):
        env = FakeEnv(board("| T-001 | a | S1 | 병합 완료 | aaaaaaa1 | ? |"), ancestors=[A])
        _, d = self.run_json(env)
        self.assertEqual(self.check(d, "rejection_count:T-001")["status"], "unknown")


class WorktreeTests(Base):
    def test_clean_and_dirty(self):
        text = board("| T-001 | a | S1 | 병합 완료 | aaaaaaa1 | 0 |")
        rc, d = self.run_json(FakeEnv(text, ancestors=[A]))
        self.assertEqual(rc, 0)
        rc, d = self.run_json(FakeEnv(text, ancestors=[A], dirty=["/r/t-005-dev"]))
        self.assertEqual(rc, 1)
        f = next(f for f in d["findings"] if f["code"] == "WORKTREE_DIRTY")
        self.assertEqual(f["task_id"], "T-005")
        self.assertEqual(f["evidence"]["entries"], 2)
        self.assertNotIn("f.py", json.dumps(d))  # 파일명/본문 미노출


class OrcaTests(Base):
    TEXT = board("| T-002 | a | S1 | 병합 완료 | aaaaaaa1 | 0 |")

    def env(self, **kw):
        return FakeEnv(self.TEXT, ancestors=[A], **kw)

    def test_retained_completed_warns_and_unverifiable_unknown(self):
        tasks = [{"id": "task_1", "status": "completed", "title": "T-002 QA"}]
        workers = [
            {"dispatchId": "ctx_1", "taskId": "task_1", "state": "succeeded",
             "liveness": "unverifiable", "terminalState": "retained"},
            {"dispatchId": "ctx_2", "taskId": "task_1", "state": "ready", "outcome": "in_progress",
             "liveness": "unverifiable", "terminalState": "active"},
        ]
        rc, d = self.run_json(self.env(tasks=tasks, workers=workers))
        self.assertEqual(rc, 1)
        ret = [f for f in d["findings"] if f["code"] == "WORKER_RETAINED_AFTER_COMPLETION"]
        self.assertEqual(len(ret), 1)
        self.assertEqual(ret[0]["task_id"], "T-002")
        self.assertEqual(self.check(d, "worker_liveness:ctx_1")["status"], "unknown")
        text = json.dumps(d, ensure_ascii=False)
        self.assertNotIn("dead", text)
        self.assertNotIn("재시도 필요", text)

    def test_unverifiable_alone_is_not_a_warning(self):
        tasks = [{"id": "task_1", "status": "completed", "title": "T-002 QA"}]
        workers = [{"dispatchId": "ctx_1", "taskId": "task_1", "state": "succeeded",
                    "liveness": "unverifiable", "terminalState": "released"}]
        rc, d = self.run_json(self.env(tasks=tasks, workers=workers))
        self.assertEqual(rc, 0)

    def test_failed_history_with_and_without_correction(self):
        tasks = [{"id": "t_f", "status": "failed", "title": "T-002 PASS 미수락 정정"},
                 {"id": "t_ok", "status": "completed", "title": "T-002 재검증"},
                 {"id": "t_g", "status": "failed", "title": "New messages"}]
        rc, d = self.run_json(self.env(tasks=tasks))
        self.assertEqual(rc, 0)  # failed 이력만으로 경고/재시도 권고 없음
        self.assertEqual(self.check(d, "failed_task:t_f")["status"], "ok")
        self.assertEqual(self.check(d, "failed_task:t_g")["status"], "unknown")
        self.assertTrue(all(f["severity"] == "info" for f in d["findings"]
                            if f["code"] == "TASK_FAILED_HISTORY"))

    def test_wrong_types_fail_safely_exit2(self):
        """S0 재현 포함: 잘못된 타입은 traceback 없이 고정 오류/exit 2."""
        good_t = {"ok": True, "result": {"tasks": [{"id": "t1", "status": "completed", "title": "T-005"}]}}
        good_w = {"ok": True, "result": {"workers": []}}
        bad_tasks = [
            {"ok": True, "result": {"tasks": [{"id": [], "title": "T-005"}]}},
            {"ok": True, "result": {"tasks": [{"id": {"a": 1}, "title": "x"}]}},
            {"ok": True, "result": {"tasks": [{"title": "x"}]}},
            {"ok": True, "result": {"tasks": [{"id": "t", "title": 5}]}},
            {"ok": True, "result": {"tasks": [{"id": "t", "status": []}]}},
            {"ok": True, "result": {"tasks": ["x"]}},
            {"ok": True, "result": {"tasks": {}}},
            {"ok": True, "result": []},
            {"ok": True, "result": "s"},
            {"ok": False, "result": {"tasks": []}},
            [], "scalar", 5, None,
        ]
        bad_workers = [
            {"ok": True, "result": {"workers": [{"dispatchId": []}]}},
            {"ok": True, "result": {"workers": [{"dispatchId": "d", "taskId": []}]}},
            {"ok": True, "result": {"workers": [{"dispatchId": "d", "state": 1}]}},
            {"ok": True, "result": {"workers": [{"dispatchId": "d", "liveness": {}}]}},
            {"ok": True, "result": {"workers": [{"dispatchId": "d", "terminalState": 3}]}},
            {"ok": True, "result": {"workers": [{"taskId": "t"}]}},
            {"ok": True, "result": {"workers": [], "nextCursor": 5}},
            {"ok": True, "result": {"workers": [[]]}},
        ]
        cases = [(t, good_w) for t in bad_tasks] + [(good_t, w) for w in bad_workers]
        for tdata, wdata in cases:
            env = self.env()
            base = env._orca

            def orca(argv, _t=tdata, _w=wdata):
                return pc.CmdResult("ok", 0, json.dumps(_t if argv[2] == "task-list" else _w))
            env._orca = orca
            rc, out = run_main(env, self.dir)
            d = json.loads(out)  # traceback였다면 예외
            self.assertEqual(rc, 2, (tdata, wdata))
            self.assertTrue(any(c["status"] == "error" and "파싱 실패" in c["detail"] for c in d["checks"]))
        # 정상 입력은 영향 없음
        env = self.env()
        env._orca = lambda argv: pc.CmdResult("ok", 0, json.dumps(good_t if argv[2] == "task-list" else good_w))
        self.assertEqual(run_main(env, self.dir)[0], 0)

    def test_unexpected_exception_is_contained(self):
        env = self.env()
        err = io.StringIO()
        with mock.patch.object(pc, "check_orca", side_effect=RuntimeError("secret-token")),                 contextlib.redirect_stderr(err):
            rc, out = run_main(env, self.dir)
        self.assertEqual(rc, 2)
        self.assertNotIn("secret", out + err.getvalue())

    def test_malformed_json_exit2(self):
        rc, d = self.run_json(self.env(orca_stdout="{not json"))
        self.assertEqual(rc, 2)
        self.assertEqual(self.check(d, "orca_task_list")["status"], "error")
        self.assertNotIn("not json", json.dumps(d))
        rc, d = self.run_json(self.env(orca_stdout=json.dumps({"ok": True, "result": {}})))
        self.assertEqual(rc, 2)

    def test_timeout_nonzero_and_missing_cli_exit2(self):
        for kw in ({"orca_status": "timeout"}, {"orca_rc": 3}, {"orca_status": "missing"}):
            rc, d = self.run_json(self.env(**kw))
            self.assertEqual(rc, 2, kw)
            self.assertEqual(self.check(d, "orca_task_list")["status"], "error")

    def test_cli_not_found(self):
        env = self.env()
        (Path(self.dir) / "handoff").mkdir(exist_ok=True)
        (Path(self.dir) / "handoff" / "BOARD.md").write_text(env.board_text, encoding="utf-8")
        out = io.StringIO()
        with mock.patch.object(pc, "run_command", env), \
                mock.patch.object(pc, "resolve_executable", return_value=None), \
                contextlib.redirect_stdout(out):
            rc = pc.main(["--repo", self.dir, "--run", "run_x", "--json"])
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(out.getvalue())["checks"][-1]["status"], "error")

    def test_git_unavailable_exit2(self):
        rc, d = self.run_json(self.env(git_fail=True))
        self.assertEqual(rc, 2)


class OutputAndArgsTests(Base):
    TEXT = board("| T-001 | a | S1 | 병합 완료 | aaaaaaa1 | 0 |")

    def test_json_schema_and_text_mode(self):
        rc, d = self.run_json(FakeEnv(self.TEXT, ancestors=[A]))
        self.assertEqual(set(d), {"schema_version", "observed_at", "repo", "run_id", "findings", "checks"})
        self.assertEqual(d["schema_version"], 1)
        self.assertTrue(d["observed_at"].endswith("+00:00"))
        self.assertEqual(d["run_id"], "run_x")
        for c in d["checks"]:
            self.assertIn(c["status"], ("ok", "unknown", "error"))
        env = FakeEnv(self.TEXT, dirty=["/r/t-005-dev"])
        out = io.StringIO()
        (Path(self.dir) / "handoff").mkdir(exist_ok=True)
        (Path(self.dir) / "handoff" / "BOARD.md").write_text(self.TEXT, encoding="utf-8")
        with mock.patch.object(pc, "run_command", env), \
                mock.patch.object(pc, "resolve_executable", return_value="/o"), \
                contextlib.redirect_stdout(out):
            rc = pc.main(["--repo", self.dir, "--run", "run_x"])
        self.assertEqual(rc, 1)
        self.assertIn("WORKTREE_DIRTY", out.getvalue())
        self.assertIn("MERGED_NOT_ANCESTOR", out.getvalue())
        with self.assertRaises(ValueError):
            json.loads(out.getvalue())

    def test_bad_args_exit2_no_stdout(self):
        for argv in ([], ["--run", "bad id!"], ["--run", "r", "--repo", os.path.join(self.dir, "nope")],
                     ["--run", "r", "--timeout", "0"]):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    rc = pc.main(argv)
                except SystemExit as e:
                    rc = e.code
            self.assertEqual(rc, 2, argv)
            self.assertEqual(out.getvalue(), "")

    def test_board_missing_or_malformed_exit2(self):
        env = FakeEnv("garbage")
        rc, d = self.run_json(env)
        self.assertEqual(rc, 2)
        self.assertEqual(self.check(d, "board_table")["status"], "error")
        os.remove(Path(self.dir) / "handoff" / "BOARD.md")
        out = io.StringIO()
        with mock.patch.object(pc, "run_command", env), \
                mock.patch.object(pc, "resolve_executable", return_value="/o"), \
                contextlib.redirect_stdout(out):
            self.assertEqual(pc.main(["--repo", self.dir, "--run", "r", "--json"]), 2)

    def test_master_baseline(self):
        _, d = self.run_json(FakeEnv(self.TEXT, ancestors=[A]))
        self.assertEqual(self.check(d, "master_baseline")["status"], "ok")
        for name in ("stall_detection", "test_count_regression", "master_push"):
            self.assertEqual(self.check(d, name)["status"], "unknown")

    def test_default_orca_command(self):
        with mock.patch.dict(os.environ, {"ORCA_CLI_COMMAND": "my-orca"}):
            self.assertEqual(pc.default_orca_command(), "my-orca")
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(pc.os, "name", "posix"):
            self.assertEqual(pc.default_orca_command(), "orca-ide")
            os.environ["ORCA_DEV_REPO_ROOT"] = "/x"
            self.assertEqual(pc.default_orca_command(), "orca-dev")
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(pc.os, "name", "nt"):
            self.assertEqual(pc.default_orca_command(), "orca")

    def test_resolve_executable_rejects_shell_strings(self):
        for bad in ("orca; rm -rf x", "orca && x", "", "--help", "a|b", "$(x)"):
            self.assertIsNone(pc.resolve_executable(bad))


class SafetyTests(unittest.TestCase):
    def test_subprocess_shell_false_and_no_stderr_leak(self):
        proc = subprocess.CompletedProcess([], 0, stdout=b"ok", stderr=b"")
        with mock.patch.object(pc.subprocess, "run", return_value=proc) as m:
            res = pc.run_command(["/usr/bin/git", "-C", "/r", "status", "--porcelain"])
        self.assertEqual(res.stdout, "ok")
        kw = m.call_args.kwargs
        self.assertIs(kw["shell"], False)
        self.assertIsInstance(m.call_args.args[0], list)
        self.assertEqual(kw["stderr"], subprocess.DEVNULL)
        self.assertIn("timeout", kw)

    def test_run_command_error_mapping(self):
        argv = ["git", "-C", "/r", "status", "--porcelain"]
        for exc, status in ((subprocess.TimeoutExpired("g", 1), "timeout"),
                            (FileNotFoundError(), "missing"), (OSError("secret-token"), "error")):
            with mock.patch.object(pc.subprocess, "run", side_effect=exc):
                res = pc.run_command(argv)
            self.assertEqual(res.status, status)
            self.assertNotIn("secret", repr(res))
        big = subprocess.CompletedProcess([], 0, stdout=b"x" * 100, stderr=b"")
        with mock.patch.object(pc.subprocess, "run", return_value=big):
            self.assertEqual(pc.run_command(argv, max_bytes=10).status, "toolarge")

    def test_allowlist_allows_only_read_only(self):
        ok = [
            ["git", "-C", "/r", "worktree", "list", "--porcelain"],
            ["git", "--no-optional-locks", "-C", "/r", "status", "--porcelain"],
            ["git", "-C", "/r", "rev-parse", "--verify", "--quiet", "abcdef1^{commit}"],
            ["git", "-C", "/r", "merge-base", "--is-ancestor", "abcdef1", "develop"],
            ["git", "-C", "/r", "for-each-ref", "--format=%(refname)", "refs/heads"],
            ["orca", "orchestration", "task-list", "--run", "run_1", "--json"],
            ["orca", "orchestration", "worker-list", "--run", "run_1", "--json", "--limit", "100"],
        ]
        denied = [
            ["git", "-C", "/r", "push", "origin", "master"],
            ["git", "-C", "/r", "commit", "-m", "x"],
            ["git", "-C", "/r", "checkout", "master"],
            ["git", "-C", "/r", "merge", "develop"],
            ["git", "-C", "/r", "reset", "--hard"],
            ["git", "-C", "/r", "status"],
            ["git", "-C", "/r", "merge-base", "--is-ancestor", "--all", "develop"],
            ["git", "-C", "/r", "rev-parse", "--verify", "--quiet", "--output=x"],
            ["git", "-C", "/r", "fetch"],
            ["git", "status", "--porcelain"],
            ["orca", "orchestration", "worker-stop", "--run", "run_1", "--json"],
            ["orca", "orchestration", "task-update", "--run", "run_1", "--json"],
            ["orca", "orchestration", "task-list", "--run", "run 1;x", "--json"],
            ["orca", "orchestration", "dispatch", "--run", "run_1", "--json"],
        ]
        with mock.patch.object(pc.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, b"", b"")) as m:
            for argv in ok:
                self.assertEqual(pc.run_command(argv).status, "ok", argv)
            called = m.call_count
            for argv in denied:
                self.assertEqual(pc.run_command(argv).status, "denied", argv)
            self.assertEqual(m.call_count, called)  # 거부된 명령은 실행되지 않음

    def test_every_command_in_fake_run_is_allowlisted(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        env = FakeEnv(board("| T-001 | a | S1 | 병합 완료 | aaaaaaa1 | 0 |"), ancestors=[A],
                      tasks=[], workers=[])
        run_main(env, td.name)
        self.assertTrue(env.calls)
        for argv in env.calls:
            exe = Path(argv[0]).stem
            (pc.validate_git_args if exe == "git" else pc.validate_orca_args)(argv[1:])


@unittest.skipUnless(GIT, "git 필요")
class RealGitFixtureTests(Base):
    def git(self, *args):
        subprocess.run([GIT, "-C", self.dir, "-c", "user.name=t", "-c", "user.email=t@e.x",
                        "-c", "commit.gpgsign=false", *args],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def head(self):
        return subprocess.run([GIT, "-C", self.dir, "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_real_ancestry(self):
        self.git("init", "-q", "-b", "develop")
        Path(self.dir, "a.txt").write_text("a")
        self.git("add", "a.txt")
        self.git("commit", "-q", "-m", "a")
        merged = self.head()
        self.git("checkout", "-q", "-b", "feature")
        Path(self.dir, "b.txt").write_text("b")
        self.git("add", "b.txt")
        self.git("commit", "-q", "-m", "b")
        unmerged = self.head()
        self.git("checkout", "-q", "develop")
        Path(self.dir, "handoff").mkdir()
        Path(self.dir, "handoff", "BOARD.md").write_text(board(
            f"| T-001 | a | S1 | 병합 완료 | develop ({merged[:10]}) | 0 |",
            f"| T-002 | a | S1 | 병합 완료 | develop ({unmerged[:10]}) | 0 |"), encoding="utf-8")
        git = pc.Git(GIT, self.dir, 15)
        self.assertTrue(git.is_ancestor(merged, "develop"))
        self.assertFalse(git.is_ancestor(unmerged, "develop"))
        self.assertIsNone(git.resolve("deadbeef12"))
        rep = pc.Report(self.dir, "r")
        pc.check_board_vs_git(rep, git, pc.parse_board(Path(self.dir, "handoff", "BOARD.md").read_text("utf-8")))
        err = [f for f in rep.findings if f["code"] == "MERGED_NOT_ANCESTOR"]
        self.assertEqual([f["task_id"] for f in err], ["T-002"])
        self.assertEqual(next(c for c in rep.checks if c["name"] == "merged_ancestry:T-001")["status"], "ok")
        # 실제 git status 로 dirty 감지
        Path(self.dir, "new.txt").write_text("x")
        rep = pc.Report(self.dir, "r")
        pc.check_worktrees(rep, git)
        self.assertIn("WORKTREE_DIRTY", [f["code"] for f in rep.findings])


if __name__ == "__main__":
    unittest.main()

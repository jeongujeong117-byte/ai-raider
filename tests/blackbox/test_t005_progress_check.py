"""Blackbox integration and security tests for T-005 read-only progress_check CLI.

Verifies:
- Public CLI contract: args, options, exit codes (0, 1, 2), safe fixed error messages.
- JSON schema version 1 conformance and text output parity.
- BOARD parsing isolation: first table only, history tables ignored, malformed formats handled.
- Task ID boundary regex and multi-T-ID ambiguity resolution.
- Git ancestry checks: merged all ancestor, not ancestor, partial ancestor, unresolvable, open integrated.
- Worktree clean vs dirty checking without file path / content leaks.
- Orca task/worker state classification: retained worker, unverifiable liveness, failed history.
- Unobservable checks: stall detection, test count regression, master push, master baseline.
- Orca failure and corruption robustness: bad JSON, schema corruption, nonzero rc, timeout, large output.
- Security allowlist enforcement: shell=False, shell metacharacter rejection, disallowed commands rejected.
- Real repository smoke execution ensuring read-only non-destructive behavior.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = ROOT / "tools" / "progress_check.py"
CSC_PATH = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import progress_check as pc  # noqa: E402


def build_csharp_mock(out_exe: str) -> None:
    """Compiles a standalone Mock Orca executable using Windows csc.exe."""
    src = """
using System;
using System.IO;
using System.Threading;

class MockOrca {
    static int Main(string[] args) {
        string sub = args.Length > 1 ? args[1] : "";
        string dir = Environment.GetEnvironmentVariable("MOCK_ORCA_DIR");
        if (string.IsNullOrEmpty(dir)) dir = AppDomain.CurrentDomain.BaseDirectory;

        string rcPath = Path.Combine(dir, "mock_rc.txt");
        if (File.Exists(rcPath)) {
            return int.Parse(File.ReadAllText(rcPath).Trim());
        }

        string sleepPath = Path.Combine(dir, "mock_sleep.txt");
        if (File.Exists(sleepPath)) {
            Thread.Sleep(int.Parse(File.ReadAllText(sleepPath).Trim()));
        }

        string largePath = Path.Combine(dir, "mock_large.txt");
        if (File.Exists(largePath)) {
            byte[] bytes = new byte[5 * 1024 * 1024];
            using (Stream s = Console.OpenStandardOutput()) {
                s.Write(bytes, 0, bytes.Length);
            }
            return 0;
        }

        string specific = Path.Combine(dir, "mock_" + sub.Replace("-", "_") + ".json");
        if (File.Exists(specific)) {
            Console.Write(File.ReadAllText(specific));
            return 0;
        }

        if (sub == "task-list") {
            Console.Write("{\\"ok\\": true, \\"result\\": {\\"tasks\\": []}}");
        } else if (sub == "worker-list") {
            Console.Write("{\\"ok\\": true, \\"result\\": {\\"workers\\": []}}");
        } else {
            Console.Write("{\\"ok\\": true, \\"result\\": {}}");
        }
        return 0;
    }
}
"""
    tmp_cs = out_exe + ".cs"
    Path(tmp_cs).write_text(src, encoding="utf-8")
    try:
        subprocess.run([CSC_PATH, "/nologo", f"/out:{out_exe}", tmp_cs], check=True, stdout=subprocess.DEVNULL)
    finally:
        if os.path.exists(tmp_cs):
            os.remove(tmp_cs)


class BlackboxProgressCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared_temp = tempfile.mkdtemp(prefix="t005_bb_shared_")
        cls.mock_orca_exe = os.path.join(cls.shared_temp, "mock_orca.exe")
        if os.name == "nt" and os.path.exists(CSC_PATH):
            build_csharp_mock(cls.mock_orca_exe)
        else:
            cls.mock_orca_exe = None

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.shared_temp):
            shutil.rmtree(cls.shared_temp, ignore_errors=True)

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="t005_bb_case_")
        self.mock_dir = os.path.join(self.test_dir, "mock_config")
        os.makedirs(self.mock_dir, exist_ok=True)
        self.env = dict(os.environ)
        self.env["MOCK_ORCA_DIR"] = self.mock_dir

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _run_cli(self, args: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
        cmd = [sys.executable, str(CLI_PATH)] + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=self.env,
        )

    def _init_git_repo(self, path: str, branch: str = "develop") -> str:
        """Initializes a git repository with a base commit."""
        subprocess.run(["git", "-C", path, "init", "-b", branch], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-C", path, "config", "user.name", "QA Tester"], check=True)
        subprocess.run(["git", "-C", path, "config", "user.email", "qa@example.com"], check=True)
        init_file = Path(path) / "README.md"
        init_file.write_text("# Repo\n", encoding="utf-8")
        subprocess.run(["git", "-C", path, "add", "."], check=True)
        subprocess.run(["git", "-C", path, "commit", "-m", "Initial commit"], check=True, stdout=subprocess.DEVNULL)
        return subprocess.check_output(["git", "-C", path, "rev-parse", "HEAD"], text=True).strip()

    def _commit(self, repo_path: str, message: str, filename: str = "data.txt", content: str = "data") -> str:
        p = Path(repo_path) / filename
        p.write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", repo_path, "add", "."], check=True)
        subprocess.run(["git", "-C", repo_path, "commit", "-m", message], check=True, stdout=subprocess.DEVNULL)
        return subprocess.check_output(["git", "-C", repo_path, "rev-parse", "HEAD"], text=True).strip()

    def _write_board(self, repo_path: str, rows: list[str], extra_sections: str = "", commit: bool = True) -> None:
        handoff = Path(repo_path) / "handoff"
        handoff.mkdir(parents=True, exist_ok=True)
        board = handoff / "BOARD.md"
        header = [
            "# 작업 현황",
            "",
            "| ID | 제목 | 담당 | 상태 | 브랜치 | 반려 횟수 |",
            "|---|---|---|---|---|---|",
        ]
        text = "\n".join(header + rows + [""] + ([extra_sections] if extra_sections else []))
        board.write_text(text, encoding="utf-8")
        if commit:
            subprocess.run(["git", "-C", repo_path, "add", "."], check=True)
            subprocess.run(["git", "-C", repo_path, "commit", "-m", "chore: add BOARD.md"], check=True, stdout=subprocess.DEVNULL)

    # --------------------------------------------------------------------------
    # 1. CLI Arguments & Safe Fixed Errors
    # --------------------------------------------------------------------------

    def test_01_cli_arg_validation_and_safe_errors(self):
        """CLI validates mandatory args, bounds, and outputs safe errors without tracebacks."""
        # Missing --run
        res = self._run_cli([])
        self.assertEqual(res.returncode, 2)
        self.assertIn("잘못된 인자 (returncode=2)", res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(res.stdout.strip(), "")

        # Invalid run_id with spaces or punctuation
        res = self._run_cli(["--run", "bad run id; rm -rf"])
        self.assertEqual(res.returncode, 2)
        self.assertIn("잘못된 인자 (returncode=2)", res.stderr)
        self.assertNotIn("Traceback", res.stderr)

        # Nonexistent repo path
        fake_repo = os.path.join(self.test_dir, "nonexistent_dir_9999")
        res = self._run_cli(["--run", "run_12345", "--repo", fake_repo])
        self.assertEqual(res.returncode, 2)
        self.assertIn("repo 경로 검증 실패 (returncode=2)", res.stderr)
        self.assertNotIn("Traceback", res.stderr)

        # File path instead of directory for repo
        file_repo = os.path.join(self.test_dir, "file_as_repo.txt")
        Path(file_repo).write_text("not a dir", encoding="utf-8")
        res = self._run_cli(["--run", "run_12345", "--repo", file_repo])
        self.assertEqual(res.returncode, 2)
        self.assertIn("repo 경로 검증 실패 (returncode=2)", res.stderr)

        # Option injection in repo argument
        res = self._run_cli(["--run", "run_12345", "--repo", "-v"])
        self.assertEqual(res.returncode, 2)
        self.assertIn("progress_check:", res.stderr)

        # Invalid timeout (negative, zero, too large)
        for bad_to in ["0", "-5", "305"]:
            res = self._run_cli(["--run", "run_12345", "--timeout", bad_to])
            self.assertEqual(res.returncode, 2)
            self.assertIn("잘못된 인자 (returncode=2)", res.stderr)

    def test_02_cli_spaces_in_path_and_relative_repo_path(self):
        """CLI resolves paths containing spaces and relative paths accurately."""
        if not self.mock_orca_exe:
            self.skipTest("C# compiler required for standalone mock orca")
        space_repo = os.path.join(self.test_dir, "repo with spaces in name")
        os.makedirs(space_repo, exist_ok=True)
        c1 = self._init_git_repo(space_repo, branch="develop")
        self._write_board(space_repo, [f"| T-001 | Init | S1 | 병합 완료 ({c1[:7]}) | develop | 0 |"])

        # Run with absolute path containing spaces
        res = self._run_cli([
            "--repo", space_repo,
            "--run", "run_space_test",
            "--orca-command", self.mock_orca_exe,
            "--json",
        ])
        self.assertIn(res.returncode, (0, 1))
        data = json.loads(res.stdout)
        self.assertEqual(data["run_id"], "run_space_test")

        # Run with relative path from current directory
        rel_path = os.path.relpath(space_repo, start=os.getcwd())
        res_rel = self._run_cli([
            "--repo", rel_path,
            "--run", "run_space_rel",
            "--orca-command", self.mock_orca_exe,
            "--json",
        ])
        self.assertIn(res_rel.returncode, (0, 1))
        data_rel = json.loads(res_rel.stdout)
        self.assertEqual(data_rel["run_id"], "run_space_rel")

    # --------------------------------------------------------------------------
    # 2. JSON Schema & Text Output
    # --------------------------------------------------------------------------

    def test_03_json_schema_conformance_and_text_parity(self):
        """JSON output strictly complies with schema version 1; text output reflects identical checks."""
        if not self.mock_orca_exe:
            self.skipTest("C# compiler required")
        repo = os.path.join(self.test_dir, "schema_repo")
        os.makedirs(repo)
        c1 = self._init_git_repo(repo, branch="develop")
        self._write_board(repo, [f"| T-001 | Task One | S1 | 병합 완료 ({c1[:7]}) | develop | 0 |"])

        # JSON mode
        res_json = self._run_cli([
            "--repo", repo,
            "--run", "run_schema_01",
            "--orca-command", self.mock_orca_exe,
            "--json",
        ])
        self.assertEqual(res_json.returncode, 0)
        data = json.loads(res_json.stdout)

        # Top-level keys
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["repo"], str(Path(repo).resolve()))
        self.assertEqual(data["run_id"], "run_schema_01")
        self.assertIsInstance(data["findings"], list)
        self.assertIsInstance(data["checks"], list)

        # Datetime validity
        obs = datetime.fromisoformat(data["observed_at"])
        self.assertIsNotNone(obs)

        # Findings schema
        for f in data["findings"]:
            self.assertIn("code", f)
            self.assertIn(f["severity"], ("info", "warning", "error"))
            self.assertTrue(f["task_id"] is None or f["task_id"].startswith("T-"))
            self.assertIn("summary", f)
            self.assertIn("evidence", f)

        # Checks schema
        check_names = set()
        for c in data["checks"]:
            self.assertIn("name", c)
            self.assertIn(c["status"], ("ok", "unknown", "error"))
            self.assertIn("detail", c)
            check_names.add(c["name"])

        self.assertIn("git", check_names)
        self.assertIn("board_table", check_names)
        self.assertIn("worktrees", check_names)
        self.assertIn("develop_ref", check_names)
        self.assertIn("merged_ancestry:T-001", check_names)

        # Text mode
        res_text = self._run_cli([
            "--repo", repo,
            "--run", "run_schema_01",
            "--orca-command", self.mock_orca_exe,
        ])
        self.assertEqual(res_text.returncode, 0)
        self.assertIn("progress_check run=run_schema_01", res_text.stdout)
        self.assertIn("checks:", res_text.stdout)
        self.assertIn("[ok] merged_ancestry:T-001", res_text.stdout)

    # --------------------------------------------------------------------------
    # 3. BOARD Parsing & Boundary Attacks
    # --------------------------------------------------------------------------

    def test_04_board_parsing_current_table_only_and_history_ignored(self):
        """Only the first main table is parsed; subsequent tables in history are ignored."""
        if not self.mock_orca_exe:
            self.skipTest("C# compiler required")
        repo = os.path.join(self.test_dir, "board_repo")
        os.makedirs(repo)
        c1 = self._init_git_repo(repo, branch="develop")

        # Table 1: T-001 clean
        # Table 2 (History): T-099 with "진행 중" and rejections=99
        history_table = """
## 작업 역사
| ID | 제목 | 담당 | 상태 | 브랜치 | 반려 횟수 |
|---|---|---|---|---|---|
| T-099 | 과거 작업 | S1 | 진행 중 | dev | 99 |
"""
        self._write_board(repo, [f"| T-001 | Active | S1 | 병합 완료 ({c1[:7]}) | develop | 0 |"], extra_sections=history_table)

        res = self._run_cli([
            "--repo", repo,
            "--run", "run_board_01",
            "--orca-command", self.mock_orca_exe,
            "--json",
        ])
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)

        # Verify T-099 is never evaluated or present in checks/findings
        check_names = [c["name"] for c in data["checks"]]
        self.assertIn("merged_ancestry:T-001", check_names)
        self.assertNotIn("rejection_count:T-099", check_names)
        self.assertNotIn("open_integration:T-099", check_names)
        finding_codes = [f["code"] for f in data["findings"]]
        self.assertNotIn("REJECTION_COUNT_HIGH", finding_codes)

    def test_05_board_malformed_handling_clean_error(self):
        """Corrupted BOARD table produces board_table error (exit 2) without unhandled exception."""
        if not self.mock_orca_exe:
            self.skipTest("C# compiler required")
        repo = os.path.join(self.test_dir, "bad_board_repo")
        os.makedirs(repo)
        self._init_git_repo(repo, branch="develop")

        handoff = Path(repo) / "handoff"
        handoff.mkdir(parents=True, exist_ok=True)
        # Missing column separator / wrong columns
        (handoff / "BOARD.md").write_text("# Board\n| ID | 제목 |\n|---|---|\n| T-001 | 제목1 |\n", encoding="utf-8")

        res = self._run_cli([
            "--repo", repo,
            "--run", "run_bad_board",
            "--orca-command", self.mock_orca_exe,
            "--json",
        ])
        self.assertEqual(res.returncode, 2)
        data = json.loads(res.stdout)
        bad_check = next((c for c in data["checks"] if c["name"] == "board_table"), None)
        self.assertIsNotNone(bad_check)
        self.assertEqual(bad_check["status"], "error")
        self.assertIn("파싱 실패", bad_check["detail"])
        self.assertNotIn("Traceback", res.stderr)

    def test_06_tid_boundary_regex_and_multi_id_ambiguity(self):
        """Task title T-ID extraction honors boundaries and handles ambiguous multi-IDs safely."""
        # Unit-level contract test on task_tid
        self.assertEqual(pc.task_tid("T-001 feature"), "T-001")
        self.assertEqual(pc.task_tid("Prefix T-005 suffix"), "T-005")
        self.assertEqual(pc.task_tid("Duplicate T-003 and T-003"), "T-003")

        # Ambiguous multiple distinct IDs must resolve to None
        self.assertIsNone(pc.task_tid("T-001 and T-002 review"))
        self.assertIsNone(pc.task_tid("Merge T-003 with T-004"))

        # Boundary negatives
        self.assertIsNone(pc.task_tid("POST-001"))
        self.assertIsNone(pc.task_tid("T-0010"))
        self.assertIsNone(pc.task_tid("AT-001"))
        self.assertIsNone(pc.task_tid("T-01"))
        self.assertIsNone(pc.task_tid("No task id here"))

    # --------------------------------------------------------------------------
    # 4. Git Ancestry & Integration Verifications
    # --------------------------------------------------------------------------

    def test_07_ancestry_all_ancestor_not_ancestor_partial_unresolved(self):
        """Ancestry verifies: all ancestor (ok), none ancestor (error), partial (warning), unresolved (unknown)."""
        if not self.mock_orca_exe:
            self.skipTest("C# compiler required")
        repo = os.path.join(self.test_dir, "ancestry_repo")
        os.makedirs(repo)
        c_init = self._init_git_repo(repo, branch="develop")

        # Commit 1 on develop
        c1 = self._commit(repo, "feat: commit 1 on develop", "f1.txt", "1")

        # Commit 2 on unmerged branch
        subprocess.run(["git", "-C", repo, "checkout", "-b", "feature-unmerged"], check=True, stdout=subprocess.DEVNULL)
        c2 = self._commit(repo, "feat: commit 2 on feature", "f2.txt", "2")

        # Back to develop
        subprocess.run(["git", "-C", repo, "checkout", "develop"], check=True, stdout=subprocess.DEVNULL)

        rows = [
            f"| T-001 | Clean Merged | S1 | 병합 완료 ({c1[:12]}) | develop | 0 |",
            f"| T-002 | False Merged | S1 | 병합 완료 ({c2[:12]}) | feature | 0 |",
            f"| T-003 | Partial Merged | S1 | 병합 완료 ({c1[:12]}, {c2[:12]}) | mixed | 0 |",
            "| T-004 | Ambiguous Hash | S1 | 병합 완료 (deadbee1dead) | dev | 0 |",
            "| T-005 | No Commit Hash | S1 | 병합 완료 | dev | 0 |",
        ]
        self._write_board(repo, rows)

        res = self._run_cli([
            "--repo", repo,
            "--run", "run_ancestry_01",
            "--orca-command", self.mock_orca_exe,
            "--json",
        ])
        # Exit 1 because of MERGED_NOT_ANCESTOR (error) and MERGED_PARTIAL_ANCESTOR (warning)
        self.assertEqual(res.returncode, 1)
        data = json.loads(res.stdout)

        finding_map = {f["task_id"]: f for f in data["findings"]}

        # T-001: All ancestor -> no finding
        self.assertNotIn("T-001", finding_map)
        check_t1 = next(c for c in data["checks"] if c["name"] == "merged_ancestry:T-001")
        self.assertEqual(check_t1["status"], "ok")

        # T-002: Not ancestor -> MERGED_NOT_ANCESTOR error
        self.assertIn("T-002", finding_map)
        self.assertEqual(finding_map["T-002"]["code"], "MERGED_NOT_ANCESTOR")
        self.assertEqual(finding_map["T-002"]["severity"], "error")

        # T-003: Partial ancestor -> MERGED_PARTIAL_ANCESTOR warning
        self.assertIn("T-003", finding_map)
        self.assertEqual(finding_map["T-003"]["code"], "MERGED_PARTIAL_ANCESTOR")
        self.assertEqual(finding_map["T-003"]["severity"], "warning")

        # T-004: Unresolved hash -> check unknown, no finding
        self.assertNotIn("T-004", finding_map)
        check_t4 = next(c for c in data["checks"] if c["name"] == "merged_ancestry:T-004")
        self.assertEqual(check_t4["status"], "unknown")

        # T-005: No hash -> check unknown, no finding
        self.assertNotIn("T-005", finding_map)
        check_t5 = next(c for c in data["checks"] if c["name"] == "merged_ancestry:T-005")
        self.assertEqual(check_t5["status"], "unknown")

    def test_08_open_task_integration_vs_branch_name_only(self):
        """Open tasks require >=2 commits (dev+QA) to flag OPEN_BUT_INTEGRATED; branch names alone are unknown."""
        if not self.mock_orca_exe:
            self.skipTest("C# compiler required")
        repo = os.path.join(self.test_dir, "open_task_repo")
        os.makedirs(repo)
        c_init = self._init_git_repo(repo, branch="develop")
        c_dev = self._commit(repo, "feat: dev commit", "dev.txt", "dev")
        c_qa = self._commit(repo, "test: qa commit", "qa.txt", "qa")

        rows = [
            # Branch name only: must remain unknown
            "| T-001 | In Progress Branch Only | S1 | 진행 중 | refs/heads/develop | 0 |",
            # Integrated with dev + qa commits and QA in owner: OPEN_BUT_INTEGRATED warning
            f"| T-002 | Integrated Open | S2 QA | 진행 중 ({c_dev[:12]}, {c_qa[:12]}) | dev | 0 |",
            # Single commit only: unknown
            f"| T-003 | Single Commit Open | S1 | 진행 중 ({c_dev[:12]}) | dev | 0 |",
        ]
        self._write_board(repo, rows)

        res = self._run_cli([
            "--repo", repo,
            "--run", "run_open_01",
            "--orca-command", self.mock_orca_exe,
            "--json",
        ])
        self.assertEqual(res.returncode, 1)
        data = json.loads(res.stdout)

        finding_map = {f["task_id"]: f for f in data["findings"]}

        # T-001: Branch name alone must not be assumed integrated
        self.assertNotIn("T-001", finding_map)
        check_t1 = next(c for c in data["checks"] if c["name"] == "open_integration:T-001")
        self.assertEqual(check_t1["status"], "unknown")

        # T-002: Marked open but both dev+QA commits are ancestors -> OPEN_BUT_INTEGRATED
        self.assertIn("T-002", finding_map)
        self.assertEqual(finding_map["T-002"]["code"], "OPEN_BUT_INTEGRATED")
        self.assertEqual(finding_map["T-002"]["severity"], "warning")

        # T-003: Single commit only -> unknown
        self.assertNotIn("T-003", finding_map)
        check_t3 = next(c for c in data["checks"] if c["name"] == "open_integration:T-003")
        self.assertEqual(check_t3["status"], "unknown")

    def test_09_rejection_count_threshold(self):
        """Rejections >= 2 triggers warning; < 2 is ok; non-numeric is unknown."""
        if not self.mock_orca_exe:
            self.skipTest("C# compiler required")
        repo = os.path.join(self.test_dir, "rejection_repo")
        os.makedirs(repo)
        c1 = self._init_git_repo(repo, branch="develop")

        rows = [
            f"| T-001 | Zero Rejections | S1 | 병합 완료 ({c1[:7]}) | develop | 0 |",
            f"| T-002 | One Rejection | S1 | 병합 완료 ({c1[:7]}) | develop | 1 |",
            f"| T-003 | Two Rejections | S1 | 병합 완료 ({c1[:7]}) | develop | 2 |",
            f"| T-004 | Five Rejections | S1 | 병합 완료 ({c1[:7]}) | develop | 5 |",
            f"| T-005 | Non-numeric | S1 | 병합 완료 ({c1[:7]}) | develop | - |",
        ]
        self._write_board(repo, rows)

        res = self._run_cli([
            "--repo", repo,
            "--run", "run_rej_01",
            "--orca-command", self.mock_orca_exe,
            "--json",
        ])
        self.assertEqual(res.returncode, 1)  # Warnings present
        data = json.loads(res.stdout)

        rejection_findings = {f["task_id"]: f for f in data["findings"] if f["code"] == "REJECTION_COUNT_HIGH"}
        self.assertNotIn("T-001", rejection_findings)
        self.assertNotIn("T-002", rejection_findings)
        self.assertIn("T-003", rejection_findings)
        self.assertIn("T-004", rejection_findings)
        self.assertNotIn("T-005", rejection_findings)

        check_t5 = next(c for c in data["checks"] if c["name"] == "rejection_count:T-005")
        self.assertEqual(check_t5["status"], "unknown")

    # --------------------------------------------------------------------------
    # 5. Worktrees & Cleanliness
    # --------------------------------------------------------------------------

    def test_10_worktree_clean_vs_dirty_no_content_leak(self):
        """Dirty worktrees produce WORKTREE_DIRTY without exposing file paths or file content."""
        if not self.mock_orca_exe:
            self.skipTest("C# compiler required")
        repo = os.path.join(self.test_dir, "worktree_repo")
        os.makedirs(repo)
        c1 = self._init_git_repo(repo, branch="develop")
        self._write_board(repo, [f"| T-001 | Main | S1 | 병합 완료 ({c1[:7]}) | develop | 0 |"])

        # Create a linked worktree
        wt_path = os.path.join(self.test_dir, "t-002-dev")
        subprocess.run(["git", "-C", repo, "worktree", "add", "-b", "t-002-dev", wt_path], check=True, stdout=subprocess.DEVNULL)

        # Make the linked worktree dirty with sensitive content
        secret_file = Path(wt_path) / "secret_file.txt"
        secret_file.write_text("SUPER_CONFIDENTIAL_TOKEN_XYZ", encoding="utf-8")

        res = self._run_cli([
            "--repo", repo,
            "--run", "run_wt_01",
            "--orca-command", self.mock_orca_exe,
            "--json",
        ])
        self.assertEqual(res.returncode, 1)
        data = json.loads(res.stdout)

        dirty_findings = [f for f in data["findings"] if f["code"] == "WORKTREE_DIRTY"]
        self.assertEqual(len(dirty_findings), 1)
        f_dirty = dirty_findings[0]
        self.assertEqual(f_dirty["task_id"], "T-002")
        self.assertEqual(f_dirty["evidence"]["entries"], 1)

        # Ensure raw filenames and sensitive content are not leaked
        evidence_str = json.dumps(f_dirty["evidence"])
        self.assertNotIn("secret_file.txt", evidence_str)
        self.assertNotIn("SUPER_CONFIDENTIAL_TOKEN_XYZ", res.stdout)
        self.assertNotIn("SUPER_CONFIDENTIAL_TOKEN_XYZ", res.stderr)

    # --------------------------------------------------------------------------
    # 6. Orca State & Unobservable Checks
    # --------------------------------------------------------------------------

    def test_11_orca_states_retained_unverifiable_and_failed_history(self):
        """Worker and task states: retained after completion, unverifiable liveness, and failed history."""
        if not self.mock_orca_exe:
            self.skipTest("C# compiler required")
        repo = os.path.join(self.test_dir, "orca_state_repo")
        os.makedirs(repo)
        c1 = self._init_git_repo(repo, branch="develop")
        self._write_board(repo, [f"| T-001 | Task | S1 | 병합 완료 ({c1[:7]}) | develop | 0 |"])

        # Mock Orca responses
        mock_tasks = [
            {"id": "task_fail_1", "title": "T-001 implement", "status": "failed"},
            {"id": "task_succ_1", "title": "T-001 retry", "status": "completed"},
            {"id": "task_fail_2", "title": "T-002 unrecovered", "status": "failed"},
        ]
        mock_workers = [
            # Retained worker after completion -> warning
            {"dispatchId": "ctx_01", "taskId": "task_succ_1", "state": "completed", "terminalState": "retained", "liveness": "live"},
            # Unverifiable liveness -> info finding, check unknown
            {"dispatchId": "ctx_02", "taskId": "task_fail_2", "state": "running", "terminalState": "active", "liveness": "unverifiable"},
            # Failed worker history -> info finding
            {"dispatchId": "ctx_03", "taskId": "task_fail_2", "state": "failed", "terminalState": "exited", "liveness": "dead"},
        ]
        Path(os.path.join(self.mock_dir, "mock_task_list.json")).write_text(
            json.dumps({"ok": True, "result": {"tasks": mock_tasks}}), encoding="utf-8"
        )
        Path(os.path.join(self.mock_dir, "mock_worker_list.json")).write_text(
            json.dumps({"ok": True, "result": {"workers": mock_workers, "nextCursor": "page2"}}), encoding="utf-8"
        )

        res = self._run_cli([
            "--repo", repo,
            "--run", "run_orca_state_01",
            "--orca-command", self.mock_orca_exe,
            "--json",
        ])
        self.assertEqual(res.returncode, 1)  # Retained worker warning triggers exit 1
        data = json.loads(res.stdout)

        finding_codes = {f["code"]: f for f in data["findings"]}
        self.assertIn("WORKER_RETAINED_AFTER_COMPLETION", finding_codes)
        self.assertIn("WORKER_LIVENESS_UNVERIFIABLE", finding_codes)
        self.assertIn("WORKER_FAILED_HISTORY", finding_codes)
        self.assertIn("TASK_FAILED_HISTORY", finding_codes)

        # Check pagination unknown
        self.assertTrue(any(c["name"] == "orca_worker_list_pages" and c["status"] == "unknown" for c in data["checks"]))

        # Failed task with later completed task of same T-ID: check status ok ("정정 이력으로 추정, 단정 아님")
        check_fail_1 = next(c for c in data["checks"] if c["name"] == "failed_task:task_fail_1")
        self.assertEqual(check_fail_1["status"], "ok")
        self.assertIn("정정 이력", check_fail_1["detail"])

        # Failed task without later completed task: check status unknown
        check_fail_2 = next(c for c in data["checks"] if c["name"] == "failed_task:task_fail_2")
        self.assertEqual(check_fail_2["status"], "unknown")

    def test_12_unobservable_checks_remain_unknown(self):
        """Unobservable properties (stall detection, test count regression, push, master change) report unknown."""
        if not self.mock_orca_exe:
            self.skipTest("C# compiler required")
        repo = os.path.join(self.test_dir, "unobservable_repo")
        os.makedirs(repo)
        c1 = self._init_git_repo(repo, branch="develop")
        self._write_board(repo, [f"| T-001 | Task | S1 | 병합 완료 ({c1[:7]}) | develop | 0 |"])

        # Create master branch with non-baseline commit
        subprocess.run(["git", "-C", repo, "checkout", "-b", "master"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-C", repo, "checkout", "develop"], check=True, stdout=subprocess.DEVNULL)

        # 1. Unobservable checks in CLI execution
        res = self._run_cli([
            "--repo", repo,
            "--run", "run_unobs_01",
            "--orca-command", self.mock_orca_exe,
            "--json",
        ])
        data = json.loads(res.stdout)

        unobs_names = {"stall_detection", "test_count_regression", "master_push"}
        for name in unobs_names:
            c = next(x for x in data["checks"] if x["name"] == name)
            self.assertEqual(c["status"], "unknown")

        # In repo without 0be384f baseline commit, master_baseline is unknown
        master_check = next(x for x in data["checks"] if x["name"] == "master_baseline")
        self.assertEqual(master_check["status"], "unknown")

        # 2. Unit test check_unobservable when master differs from baseline
        rep = pc.Report(repo, "run_unit")
        fake_git = mock.MagicMock()
        fake_git.resolve.side_effect = lambda ref: "1111111" if ref == "master" else "0be384f"
        pc.check_unobservable(rep, fake_git)
        self.assertTrue(any(f["code"] == "MASTER_DIFFERS_FROM_BASELINE" and f["severity"] == "info" for f in rep.findings))
        c_diff = next(c for c in rep.checks if c["name"] == "master_baseline")
        self.assertEqual(c_diff["status"], "unknown")
        self.assertIn("master 변경 감지", c_diff["detail"])

        # 3. Unit test check_unobservable when master matches baseline
        rep_ok = pc.Report(repo, "run_unit_ok")
        fake_git_ok = mock.MagicMock()
        fake_git_ok.resolve.side_effect = lambda ref: "0be384f"
        pc.check_unobservable(rep_ok, fake_git_ok)
        c_ok = next(c for c in rep_ok.checks if c["name"] == "master_baseline")
        self.assertEqual(c_ok["status"], "ok")
        self.assertIn("동일", c_ok["detail"])

    # --------------------------------------------------------------------------
    # 7. Robustness, Corrupted JSON, Timeouts & Output Limits
    # --------------------------------------------------------------------------

    def test_13_orca_corruption_and_timeouts_exit_2(self):
        """Corrupted JSON, bad schema, non-zero rc, or timeout from Orca produces exit code 2."""
        if not self.mock_orca_exe:
            self.skipTest("C# compiler required")
        repo = os.path.join(self.test_dir, "orca_fail_repo")
        os.makedirs(repo)
        c1 = self._init_git_repo(repo, branch="develop")
        self._write_board(repo, [f"| T-001 | Task | S1 | 병합 완료 ({c1[:7]}) | develop | 0 |"])

        # 1. Non-zero exit code
        Path(os.path.join(self.mock_dir, "mock_rc.txt")).write_text("1", encoding="utf-8")
        res = self._run_cli(["--repo", repo, "--run", "run_err_01", "--orca-command", self.mock_orca_exe, "--json"])
        self.assertEqual(res.returncode, 2)
        os.remove(os.path.join(self.mock_dir, "mock_rc.txt"))

        # 2. Corrupted JSON syntax
        Path(os.path.join(self.mock_dir, "mock_task_list.json")).write_text("{bad json syntax", encoding="utf-8")
        res = self._run_cli(["--repo", repo, "--run", "run_err_02", "--orca-command", self.mock_orca_exe, "--json"])
        self.assertEqual(res.returncode, 2)

        # 3. Schema pollution (ok: false or missing key)
        Path(os.path.join(self.mock_dir, "mock_task_list.json")).write_text(
            json.dumps({"ok": False, "error": "internal crash"}), encoding="utf-8"
        )
        res = self._run_cli(["--repo", repo, "--run", "run_err_03", "--orca-command", self.mock_orca_exe, "--json"])
        self.assertEqual(res.returncode, 2)
        os.remove(os.path.join(self.mock_dir, "mock_task_list.json"))

        # 4. Timeout
        Path(os.path.join(self.mock_dir, "mock_sleep.txt")).write_text("1200", encoding="utf-8")
        res = self._run_cli([
            "--repo", repo,
            "--run", "run_err_04",
            "--orca-command", self.mock_orca_exe,
            "--timeout", "0.5",
            "--json",
        ])
        self.assertEqual(res.returncode, 2)
        os.remove(os.path.join(self.mock_dir, "mock_sleep.txt"))

    def test_14_large_output_limit_handled_safely(self):
        """Orca output exceeding 4MiB is flagged as toolarge and triggers exit code 2."""
        if not self.mock_orca_exe:
            self.skipTest("C# compiler required")
        repo = os.path.join(self.test_dir, "large_out_repo")
        os.makedirs(repo)
        c1 = self._init_git_repo(repo, branch="develop")
        self._write_board(repo, [f"| T-001 | Task | S1 | 병합 완료 ({c1[:7]}) | develop | 0 |"])

        # Configure mock orca to output 5MiB
        Path(os.path.join(self.mock_dir, "mock_large.txt")).write_text("1", encoding="utf-8")
        res = self._run_cli([
            "--repo", repo,
            "--run", "run_large_01",
            "--orca-command", self.mock_orca_exe,
            "--json",
        ])
        self.assertEqual(res.returncode, 2)
        data = json.loads(res.stdout)
        task_check = next(c for c in data["checks"] if c["name"] == "orca_task_list")
        self.assertEqual(task_check["status"], "error")
        self.assertIn("toolarge", task_check["detail"])

    # --------------------------------------------------------------------------
    # 8. Security Allowlist & Injection Defenses
    # --------------------------------------------------------------------------

    def test_15_security_command_allowlist_and_shell_meta_rejection(self):
        """Shell metacharacters and disallowed subcommands are rejected before execution."""
        # Unit allowlist validation
        with self.assertRaises(pc.DisallowedCommand):
            pc.validate_git_args(["-C", "repo", "push", "origin", "master"])

        with self.assertRaises(pc.DisallowedCommand):
            pc.validate_git_args(["-C", "repo", "commit", "-m", "foo"])

        with self.assertRaises(pc.DisallowedCommand):
            pc.validate_git_args(["-C", "repo", "checkout", "master"])

        with self.assertRaises(pc.DisallowedCommand):
            pc.validate_orca_args(["orchestration", "worker-stop", "--run", "run_1"])

        with self.assertRaises(pc.DisallowedCommand):
            pc.validate_orca_args(["orchestration", "send", "--body", "x"])

        # Shell metacharacter rejection in resolve_executable
        for evil in ["orca; echo pwned", "orca && dir", "orca | type", "orca `whoami`", "orca $VAR"]:
            self.assertIsNone(pc.resolve_executable(evil))

        # CLI execution with shell metacharacter in --orca-command produces exit 2
        repo = os.path.join(self.test_dir, "sec_repo")
        os.makedirs(repo)
        c1 = self._init_git_repo(repo, branch="develop")
        self._write_board(repo, [f"| T-001 | Task | S1 | 병합 완료 ({c1[:7]}) | develop | 0 |"])

        res = self._run_cli([
            "--repo", repo,
            "--run", "run_sec_01",
            "--orca-command", "orca; whoami",
            "--json",
        ])
        self.assertEqual(res.returncode, 2)
        data = json.loads(res.stdout)
        orca_check = next(c for c in data["checks"] if c["name"] == "orca_task_list")
        self.assertEqual(orca_check["status"], "error")
        self.assertIn("실행파일을 찾을 수 없음", orca_check["detail"])

    # --------------------------------------------------------------------------
    # 9. Real Repository & Run Smoke Execution
    # --------------------------------------------------------------------------

    def test_16_real_repo_smoke_read_only_invariance(self):
        """Smoke test against the real repository and active run confirms read-only behavior."""
        real_repo = str(ROOT)
        real_run = "run_548a284d59da"

        # Check git status before execution
        status_before = subprocess.check_output(
            ["git", "-C", real_repo, "status", "--porcelain"], text=True
        )

        res = self._run_cli([
            "--repo", real_repo,
            "--run", real_run,
            "--json",
        ])

        # Check git status after execution
        status_after = subprocess.check_output(
            ["git", "-C", real_repo, "status", "--porcelain"], text=True
        )

        # Working directory must be identical (strictly read-only)
        self.assertEqual(status_before, status_after)

        # Exit code must be 0 or 1 (expected findings: dirty worktree or retained worker)
        self.assertIn(res.returncode, (0, 1))

        data = json.loads(res.stdout)
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["run_id"], real_run)

        # Verify key baseline checks ran
        check_names = {c["name"] for c in data["checks"]}
        self.assertIn("git", check_names)
        self.assertIn("board_table", check_names)
        self.assertIn("develop_ref", check_names)
        self.assertIn("master_baseline", check_names)
        self.assertIn("orca_task_list", check_names)
        self.assertIn("orca_worker_list", check_names)


if __name__ == "__main__":
    unittest.main()

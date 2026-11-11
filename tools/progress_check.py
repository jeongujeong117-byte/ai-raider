#!/usr/bin/env python3
"""읽기 전용 진행감독 CLI (T-005).

handoff/BOARD.md 의 현재 주 작업표와 실제 Git/Orca 상태의 불일치를 보고한다.
자동 수정·중지·재시작·병합·배정·네트워크 호출은 하지 않는다. stdlib 전용이다.

사용법:
    python tools/progress_check.py --run <run_id> [--repo <path>]
        [--orca-command <executable>] [--json] [--timeout 15]

종료 코드: 0 점검 완료·경고 없음 / 1 불일치·경고 발견 / 2 필수 소스 사용 불가·
잘못된 인자·파싱 실패.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_TIMEOUT = 15.0
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MASTER_BASELINE = "0be384f"
DEVELOP_REF = "develop"
MASTER_REF = "master"

EXIT_OK, EXIT_FINDINGS, EXIT_UNAVAILABLE = 0, 1, 2

_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_HEX_TOKEN_RE = re.compile(r"(?<![0-9A-Za-z_])[0-9a-f]{7,40}(?![0-9A-Za-z_])")
_TID_RE = re.compile(r"(?<![0-9A-Za-z-])T-(\d{3})(?![0-9A-Za-z])")
_BOARD_ID_RE = re.compile(r"^T-\d{3}$")
_SHELL_META = set(';&|<>`$"\'\n\r\x00%^')


# --------------------------------------------------------------------------
# 안전한 명령 실행 (shell=False + 읽기 전용 허용목록)
# --------------------------------------------------------------------------


@dataclass
class CmdResult:
    status: str  # ok | timeout | missing | toolarge | error | denied
    returncode: int | None = None
    stdout: str = ""


class DisallowedCommand(Exception):
    pass


def _safe_ref(value: str) -> bool:
    return bool(_REF_RE.match(value)) and ".." not in value and not value.endswith(".lock")


def _commit_operand(value: str) -> bool:
    if value.endswith("^{commit}"):
        value = value[: -len("^{commit}")]
    return bool(_COMMIT_RE.match(value)) or _safe_ref(value)


def validate_git_args(args: list[str]) -> None:
    """git 하위 인자(실행파일 제외)가 읽기 전용 허용목록인지 검증한다."""
    a = list(args)
    if a[:1] == ["--no-optional-locks"]:
        a = a[1:]
    if len(a) < 2 or a[0] != "-C" or not a[1] or a[1].startswith("-"):
        raise DisallowedCommand("git: -C <path> required")
    a = a[2:]
    ok = False
    if a == ["worktree", "list", "--porcelain"]:
        ok = True
    elif a == ["status", "--porcelain"]:
        ok = True
    elif a == ["rev-parse", "--git-dir"]:
        ok = True
    elif len(a) == 4 and a[:3] == ["rev-parse", "--verify", "--quiet"]:
        ok = _commit_operand(a[3])
    elif len(a) == 4 and a[:2] == ["merge-base", "--is-ancestor"]:
        ok = _commit_operand(a[2]) and _commit_operand(a[3])
    elif a == ["for-each-ref", "--format=%(refname)", "refs/heads"]:
        ok = True
    if not ok:
        raise DisallowedCommand("git: subcommand not allowed")


def validate_orca_args(args: list[str]) -> None:
    a = list(args)
    if len(a) >= 5 and a[0] == "orchestration" and a[1] in ("task-list", "worker-list"):
        if a[2] == "--run" and _RUN_ID_RE.match(a[3]) and a[4] == "--json":
            rest = a[5:]
            if a[1] == "worker-list" and rest == ["--limit", "100"]:
                return
            if not rest:
                return
    raise DisallowedCommand("orca: subcommand not allowed")


def run_command(argv: list[str], timeout: float = DEFAULT_TIMEOUT,
                max_bytes: int = MAX_OUTPUT_BYTES) -> CmdResult:
    """allowlist 통과 후 shell=False 로 실행. 원시 stderr 는 폐기한다."""
    if not argv:
        return CmdResult("denied")
    exe_name = Path(argv[0]).stem.lower()
    try:
        if exe_name == "git":
            validate_git_args(argv[1:])
        else:
            validate_orca_args(argv[1:])
    except DisallowedCommand:
        return CmdResult("denied")
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        proc = subprocess.run(
            argv, shell=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=timeout, env=env, check=False,
        )
    except subprocess.TimeoutExpired:
        return CmdResult("timeout")
    except (FileNotFoundError, PermissionError):
        return CmdResult("missing")
    except OSError:
        return CmdResult("error")
    if len(proc.stdout) > max_bytes:
        return CmdResult("toolarge", proc.returncode)
    return CmdResult("ok", proc.returncode, proc.stdout.decode("utf-8", errors="replace"))


# --------------------------------------------------------------------------
# 실행파일 해석
# --------------------------------------------------------------------------


def default_orca_command() -> str:
    env = os.environ.get("ORCA_CLI_COMMAND")
    if env:
        return env
    if os.name == "nt":
        return "orca"
    return "orca-dev" if os.environ.get("ORCA_DEV_REPO_ROOT") else "orca-ide"


def resolve_executable(command: str) -> str | None:
    """실행파일 하나로 해석한다. 셸 문자열/메타문자는 거부한다."""
    if not command or any(ch in _SHELL_META for ch in command) or command.startswith("-"):
        return None
    found = shutil.which(command)
    if not found:
        return None
    if os.name == "nt" and Path(found).suffix.lower() in (".cmd", ".bat"):
        sibling = Path(found).with_suffix(".exe")
        if sibling.is_file():
            return str(sibling)
        return None  # .cmd/.bat 를 셸 없이 안전하게 실행할 수 없다
    return found


# --------------------------------------------------------------------------
# 결과 모델
# --------------------------------------------------------------------------


class Report:
    def __init__(self, repo: str, run_id: str):
        self.repo, self.run_id = repo, run_id
        self.findings: list[dict] = []
        self.checks: list[dict] = []
        self.source_failure = False

    def finding(self, code, severity, task_id, summary, evidence):
        self.findings.append({"code": code, "severity": severity, "task_id": task_id,
                              "summary": summary, "evidence": evidence})

    def check(self, name, status, detail):
        self.checks.append({"name": name, "status": status, "detail": detail})
        if status == "error":
            self.source_failure = True

    def exit_code(self) -> int:
        if self.source_failure:
            return EXIT_UNAVAILABLE
        if any(f["severity"] in ("warning", "error") for f in self.findings):
            return EXIT_FINDINGS
        return EXIT_OK

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "repo": self.repo,
            "run_id": self.run_id,
            "findings": self.findings,
            "checks": self.checks,
        }


def _fail_detail(label: str, res: CmdResult) -> str:
    rc = f", returncode={res.returncode}" if res.returncode is not None else ""
    return f"{label} 실행 실패 ({res.status}{rc})"


# --------------------------------------------------------------------------
# BOARD 파싱
# --------------------------------------------------------------------------


class BoardError(Exception):
    pass


def parse_board(text: str) -> list[dict]:
    """첫 번째 `| ID |` 헤더 표(현재 주 작업표)만 읽는다. 이후 절/표는 무시."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*\|\s*ID\s*\|", line):
            start = i
            break
    if start is None:
        raise BoardError("작업표 헤더 없음")
    header = _cells(lines[start])
    if len(header) < 6 or start + 1 >= len(lines) or not re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[start + 1]):
        raise BoardError("작업표 형식 불일치")
    rows = []
    for line in lines[start + 2:]:
        if not line.strip().startswith("|"):
            break
        cells = _cells(line)
        if len(cells) != len(header):
            raise BoardError("작업표 열 수 불일치")
        rows.append({"id": cells[0], "title": cells[1], "owner": cells[2],
                     "status": cells[3], "branch": cells[4], "rejections": cells[5]})
    if not rows:
        raise BoardError("작업표 행 없음")
    return rows


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def commit_tokens(*texts: str) -> list[str]:
    seen: list[str] = []
    for text in texts:
        for tok in _HEX_TOKEN_RE.findall(text):
            if re.search(r"\d", tok) and re.search(r"[a-f]", tok) and tok not in seen:
                seen.append(tok)
    return seen


def task_tid(title: str) -> str | None:
    """Task 제목에서 정확히 하나의 T-xxx 가 있을 때만 매핑한다."""
    ids = {f"T-{m}" for m in _TID_RE.findall(title or "")}
    return ids.pop() if len(ids) == 1 else None


# --------------------------------------------------------------------------
# Git 질의
# --------------------------------------------------------------------------


class Git:
    def __init__(self, exe: str, repo: str, timeout: float):
        self.exe, self.repo, self.timeout = exe, repo, timeout

    def _run(self, *args: str, path: str | None = None, lock_free: bool = False) -> CmdResult:
        argv = [self.exe]
        if lock_free:
            argv.append("--no-optional-locks")
        argv += ["-C", path or self.repo, *args]
        return run_command(argv, self.timeout)

    def worktrees(self) -> CmdResult:
        return self._run("worktree", "list", "--porcelain")

    def status(self, path: str) -> CmdResult:
        return self._run("status", "--porcelain", path=path, lock_free=True)

    def resolve(self, name: str) -> str | None:
        """커밋으로 해석되면 True 해시 대신 입력 그대로 사용 가능 여부를 돌려준다."""
        if not _commit_operand(name):
            return None
        res = self._run("rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")
        if res.status == "ok" and res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
        return None

    def is_ancestor(self, commit: str, ref: str) -> bool | None:
        res = self._run("merge-base", "--is-ancestor", commit, ref)
        if res.status != "ok":
            return None
        if res.returncode == 0:
            return True
        if res.returncode == 1:
            return False
        return None

    def branches(self) -> CmdResult:
        return self._run("for-each-ref", "--format=%(refname)", "refs/heads")

    def git_dir(self) -> CmdResult:
        return self._run("rev-parse", "--git-dir")


def parse_worktrees(text: str) -> list[dict]:
    result, cur = [], {}
    for line in text.splitlines() + [""]:
        if not line.strip():
            if cur.get("path"):
                result.append(cur)
            cur = {}
            continue
        key, _, val = line.partition(" ")
        if key == "worktree":
            cur["path"] = val
        elif key == "branch":
            cur["branch"] = val
        elif key in ("bare", "detached", "prunable", "locked"):
            cur[key] = True
        elif key == "HEAD":
            cur["head"] = val
    if not result:
        raise ValueError("worktree 없음")
    return result


_WT_TID_RE = re.compile(r"(?:^|[/\\])t-(\d{3})-(?:dev|qa|learn)$", re.IGNORECASE)


def worktree_tid(wt: dict) -> str | None:
    for src in (wt.get("branch", ""), wt.get("path", "")):
        m = _WT_TID_RE.search(src.rstrip("/\\"))
        if m:
            return f"T-{m.group(1)}"
    return None


# --------------------------------------------------------------------------
# 점검
# --------------------------------------------------------------------------


def check_board_vs_git(rep: Report, git: Git, rows: list[dict]) -> None:
    develop = git.resolve(DEVELOP_REF)
    if develop is None:
        rep.check("develop_ref", "unknown", "develop 브랜치를 커밋으로 해석할 수 없어 통합 점검 불가")
    else:
        rep.check("develop_ref", "ok", "develop 해석됨")

    for row in rows:
        tid = row["id"]
        if not _BOARD_ID_RE.match(tid):
            continue  # 학습/S4/별도 행은 T-ID 작업이 아님
        status = row["status"]
        merged = "병합 완료" in status and "미병합" not in status
        tokens = commit_tokens(row["status"], row["branch"])

        # 반려 횟수
        m = re.match(r"^\s*(\d+)\s*$", row["rejections"])
        if m:
            n = int(m.group(1))
            if n >= 2:
                rep.finding("REJECTION_COUNT_HIGH", "warning", tid,
                            f"반려 횟수 {n}회 (2회 이상)", {"rejections": n})
            rep.check(f"rejection_count:{tid}", "ok", f"반려 {n}회")
        else:
            rep.check(f"rejection_count:{tid}", "unknown", "반려 횟수를 숫자로 해석할 수 없음")

        # 커밋별 develop 조상 여부
        results: dict[str, bool | None] = {}
        for tok in tokens:
            if develop is None:
                results[tok] = None
                continue
            full = git.resolve(tok)
            results[tok] = git.is_ancestor(full, DEVELOP_REF) if full else None

        if merged:
            name = f"merged_ancestry:{tid}"
            if not tokens:
                rep.check(name, "unknown", "병합 완료 표기에 근거 커밋이 없음")
                continue
            anc = [t for t, v in results.items() if v is True]
            non = [t for t, v in results.items() if v is False]
            unk = [t for t, v in results.items() if v is None]
            if non and not anc:
                rep.finding("MERGED_NOT_ANCESTOR", "error", tid,
                            "BOARD는 병합 완료이나 근거 커밋이 develop 조상이 아님",
                            {"not_ancestor": non, "unresolved": unk})
                rep.check(name, "ok", "점검 완료(불일치 보고)")
            elif non:
                rep.finding("MERGED_PARTIAL_ANCESTOR", "warning", tid,
                            "일부 근거 커밋이 develop 조상이 아님(대체/squash 가능성 미판정)",
                            {"ancestor": anc, "not_ancestor": non, "unresolved": unk})
                rep.check(name, "ok", "점검 완료(부분 불일치 보고)")
            elif unk:
                rep.check(name, "unknown", f"일부 커밋 해석 불가: {len(unk)}건, 확인된 조상 {len(anc)}건")
            else:
                rep.check(name, "ok", f"근거 커밋 {len(anc)}건 모두 develop 조상")
            continue

        # 현재 진행/대기 계열 행
        if re.search(r"진행|대기|준비|예정|QA|배정", status):
            name = f"open_integration:{tid}"
            qa_mentioned = "QA" in (row["owner"] + status + row["branch"])
            if len(tokens) >= 2 and qa_mentioned and all(v is True for v in results.values()):
                rep.finding("OPEN_BUT_INTEGRATED", "warning", tid,
                            "BOARD는 진행/대기이나 기록된 개발/QA 커밋이 모두 develop에 통합됨(기록 불일치)",
                            {"commits": tokens, "board_status": status})
                rep.check(name, "ok", "점검 완료(기록 불일치 보고)")
            else:
                rep.check(name, "unknown", "통합 완료를 단정할 명확한 증거 없음")


def check_worktrees(rep: Report, git: Git) -> None:
    res = git.worktrees()
    if res.status != "ok" or res.returncode != 0:
        rep.check("worktrees", "error", _fail_detail("git worktree list", res))
        return
    try:
        wts = parse_worktrees(res.stdout)
    except ValueError:
        rep.check("worktrees", "error", "git worktree list 출력 파싱 실패")
        return
    rep.check("worktrees", "ok", f"worktree {len(wts)}개 확인")
    for wt in wts:
        label = wt.get("branch", "").replace("refs/heads/", "") or Path(wt["path"]).name
        tid = worktree_tid(wt)
        name = f"worktree_clean:{Path(wt['path']).name}"
        if wt.get("bare"):
            continue
        if wt.get("prunable"):
            rep.check(name, "unknown", "prunable worktree 라 status 점검 불가")
            continue
        st = git.status(wt["path"])
        if st.status != "ok" or st.returncode != 0:
            rep.check(name, "unknown", _fail_detail("git status", st))
            continue
        entries = [ln for ln in st.stdout.splitlines() if ln.strip()]
        if entries:
            rep.finding("WORKTREE_DIRTY", "warning", tid,
                        f"worktree {Path(wt['path']).name} 에 미커밋 변경 {len(entries)}건",
                        {"worktree": Path(wt["path"]).name, "branch": label, "entries": len(entries)})
        rep.check(name, "ok", "clean" if not entries else f"dirty({len(entries)}건, 본문 미조회)")


def _orca_json(rep: Report, orca: str, timeout: float, sub: str, run_id: str,
               key: str, extra: list[str]) -> tuple[list[dict] | None, dict]:
    res = run_command([orca, "orchestration", sub, "--run", run_id, "--json", *extra], timeout)
    name = f"orca_{sub.replace('-', '_')}"
    if res.status != "ok" or res.returncode != 0:
        rep.check(name, "error", _fail_detail(f"orca {sub}", res))
        return None, {}
    try:
        data = json.loads(res.stdout)
        result = data["result"]
        items = result[key]
        if data.get("ok") is not True or not isinstance(items, list) or \
                not all(isinstance(i, dict) for i in items):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        rep.check(name, "error", f"orca {sub} JSON 파싱 실패")
        return None, {}
    rep.check(name, "ok", f"{len(items)}건 확인")
    return items, result


def check_orca(rep: Report, orca: str | None, timeout: float, run_id: str) -> None:
    if orca is None:
        rep.check("orca_task_list", "error", "Orca CLI 실행파일을 찾을 수 없음")
        rep.check("orca_worker_list", "error", "Orca CLI 실행파일을 찾을 수 없음")
        return
    tasks, _ = _orca_json(rep, orca, timeout, "task-list", run_id, "tasks", [])
    workers, wres = _orca_json(rep, orca, timeout, "worker-list", run_id, "workers", ["--limit", "100"])
    if tasks is None or workers is None:
        return
    if wres.get("nextCursor"):
        rep.check("orca_worker_list_pages", "unknown", "추가 페이지가 있으나 첫 100건만 확인")

    title_by_id = {t.get("id"): str(t.get("title", "")) for t in tasks}
    tid_by_task = {i: task_tid(t) for i, t in title_by_id.items()}

    # failed 이력
    for t in tasks:
        if t.get("status") != "failed":
            continue
        tid = tid_by_task.get(t.get("id"))
        name = f"failed_task:{t.get('id')}"
        later_ok = [o.get("id") for o in tasks
                    if o is not t and o.get("status") == "completed" and tid and tid_by_task.get(o.get("id")) == tid]
        rep.finding("TASK_FAILED_HISTORY", "info", tid,
                    "failed Task 이력(재시도 권고 아님; 최종 작업 실패와 구분)",
                    {"task": t.get("id"), "same_tid_completed": later_ok})
        if later_ok:
            rep.check(name, "ok", f"동일 T-ID의 completed Task {len(later_ok)}건 존재(정정 이력으로 추정, 단정 아님)")
        else:
            rep.check(name, "unknown", "failed 이력이 최종 실패인지 정정 이력인지 근거 부족")

    # 워커 상태
    live_in_progress = 0
    for w in workers:
        did = str(w.get("dispatchId", "?"))
        tid = tid_by_task.get(w.get("taskId"))
        state = w.get("state")
        if w.get("liveness") == "unverifiable":
            rep.check(f"worker_liveness:{did}", "unknown", "liveness unverifiable: 멈춤/사망 판정 불가")
            rep.finding("WORKER_LIVENESS_UNVERIFIABLE", "info", tid,
                        "워커 liveness 검증 불가(멈춤/사망으로 판정하지 않음)",
                        {"dispatch": did, "state": state})
        if state in ("succeeded", "completed") and w.get("terminalState") == "retained":
            rep.finding("WORKER_RETAINED_AFTER_COMPLETION", "warning", tid,
                        "완료된 워커의 화면(terminal)이 retained 로 남아 있음",
                        {"dispatch": did, "task": w.get("taskId"), "state": state,
                         "terminalState": "retained"})
        if state == "failed":
            rep.finding("WORKER_FAILED_HISTORY", "info", tid,
                        "failed 워커 이력(재시도 권고 아님)", {"dispatch": did})
        if w.get("outcome") == "in_progress" and w.get("liveness") == "live":
            live_in_progress += 1
    rep.check("workers", "ok", f"워커 {len(workers)}건 (진행 중 live {live_in_progress}건)")


def check_unobservable(rep: Report, git: Git) -> None:
    rep.check("stall_detection", "unknown", "시작 후 응답 없음/오래 멈춤은 허용 자료에 직접 증거가 없어 판정 불가")
    rep.check("test_count_regression", "unknown", "테스트 수 감소는 허용 자료만으로 판정 불가(S4/QA 확인 필요)")
    rep.check("master_push", "unknown", "원격 네트워크 호출 금지로 push 여부 확인 불가")
    master = git.resolve(MASTER_REF)
    base = git.resolve(MASTER_BASELINE)
    if master is None or base is None:
        rep.check("master_baseline", "unknown", "master 또는 기준 커밋을 해석할 수 없음")
    elif master == base:
        rep.check("master_baseline", "ok", f"master 가 기준 {MASTER_BASELINE} 과 동일")
    else:
        rep.finding("MASTER_DIFFERS_FROM_BASELINE", "info", None,
                    f"master 가 기준 {MASTER_BASELINE} 과 다름(승인 여부는 판정 불가)",
                    {"baseline": MASTER_BASELINE})
        rep.check("master_baseline", "unknown", "master 변경 감지, 승인 여부는 허용 자료로 판정 불가")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # 원시 인자를 에코하지 않는 고정 오류
        sys.stderr.write("progress_check: 잘못된 인자 (returncode=2)\n")
        raise SystemExit(EXIT_UNAVAILABLE)


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="progress_check.py", description="읽기 전용 진행감독 점검")
    p.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
    p.add_argument("--run", required=True)
    p.add_argument("--orca-command", default=None)
    p.add_argument("--json", action="store_true")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    return p


def render_text(data: dict) -> str:
    out = [f"progress_check run={data['run_id']} repo={data['repo']} observed_at={data['observed_at']}",
           f"findings: {len(data['findings'])}"]
    for f in data["findings"]:
        out.append(f"  [{f['severity']}] {f['code']} task={f['task_id']}: {f['summary']} "
                   f"evidence={json.dumps(f['evidence'], ensure_ascii=False, sort_keys=True)}")
    out.append(f"checks: {len(data['checks'])}")
    for c in data["checks"]:
        out.append(f"  [{c['status']}] {c['name']}: {c['detail']}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not _RUN_ID_RE.match(args.run) or not (0 < args.timeout <= 300):
        sys.stderr.write("progress_check: 잘못된 인자 (returncode=2)\n")
        return EXIT_UNAVAILABLE
    repo_path = Path(args.repo).expanduser()
    try:
        repo_path = repo_path.resolve(strict=True)
    except (OSError, RuntimeError):
        sys.stderr.write("progress_check: repo 경로 검증 실패 (returncode=2)\n")
        return EXIT_UNAVAILABLE
    if not repo_path.is_dir():
        sys.stderr.write("progress_check: repo 경로 검증 실패 (returncode=2)\n")
        return EXIT_UNAVAILABLE

    repo = str(repo_path)
    rep = Report(repo, args.run)
    git_exe = shutil.which("git")
    if not git_exe:
        rep.check("git", "error", "git 실행파일을 찾을 수 없음")
    else:
        git = Git(git_exe, repo, args.timeout)
        gd = git.git_dir()
        if gd.status != "ok" or gd.returncode != 0:
            rep.check("git", "error", _fail_detail("git rev-parse", gd))
        else:
            rep.check("git", "ok", "git 저장소 확인")
            board_path = repo_path / "handoff" / "BOARD.md"
            rows = None
            try:
                rows = parse_board(board_path.read_text(encoding="utf-8"))
                rep.check("board_table", "ok", f"작업표 {len(rows)}행 파싱")
            except (OSError, UnicodeDecodeError):
                rep.check("board_table", "error", "BOARD.md 를 읽을 수 없음")
            except BoardError:
                rep.check("board_table", "error", "BOARD.md 작업표 파싱 실패")
            check_worktrees(rep, git)
            if rows is not None:
                check_board_vs_git(rep, git, rows)
            check_unobservable(rep, git)

    orca = resolve_executable(args.orca_command or default_orca_command())
    check_orca(rep, orca, args.timeout, args.run)

    data = rep.to_dict()
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else render_text(data))
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""winbox — 일회용 Windows 샌드박스를 SSH 너머에서 쓰는 MCP 서버 (stdlib only, Python 3.9+).

Windows 호스트에서 실행된다. MCP 클라이언트는 보통 이렇게 붙는다:
    ssh -T user@host py -3 C:\\Users\\user\\winbox-mcp\\winbox.py

호스트↔샌드박스 통신은 공유 폴더 우편함(mail\\req → mail\\res) 하나뿐이라
네트워크를 끈 샌드박스(network=off)에서도 똑같이 동작한다.
WINBOX_LOCAL=1 이면 샌드박스 대신 호스트에서 에이전트를 직접 띄운다(배선 시험용).
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from xml.sax.saxutils import escape

VERSION = "0.2.1"
HERE = Path(__file__).resolve().parent
GUEST_TOOLS = HERE / "guest"
RUNS = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "winbox" / "runs"
TASK = "winbox-launch"
LOCK = RUNS.parent / "lock.json"  # 호스트 전역: 샌드박스는 한 대뿐이라 SSH 접속(=winbox 프로세스)끼리 줄을 선다


class BoxError(Exception):
    pass


def wsb_xml(tools, mail, inbox, network="on", memory_mb=4096):
    """Windows Sandbox 설정(.wsb). 클립보드·마이크·카메라·프린터 차단이 기본."""
    def mf(host, guest, ro):
        return ("<MappedFolder><HostFolder>%s</HostFolder><SandboxFolder>%s</SandboxFolder>"
                "<ReadOnly>%s</ReadOnly></MappedFolder>" % (escape(str(host)), guest, "true" if ro else "false"))
    return (
        "<Configuration>"
        "<Networking>%s</Networking>" % ("Disable" if network == "off" else "Default")
        + "<MemoryInMB>%d</MemoryInMB>" % int(memory_mb)
        + "<ClipboardRedirection>Disable</ClipboardRedirection><AudioInput>Disable</AudioInput>"
        "<VideoInput>Disable</VideoInput><PrinterRedirection>Disable</PrinterRedirection>"
        "<MappedFolders>"
        + mf(tools, r"C:\winbox\tools", True) + mf(mail, r"C:\winbox\mail", False) + mf(inbox, r"C:\winbox\in", True)
        + "</MappedFolders>"
        "<LogonCommand><Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden "
        r"-File C:\winbox\tools\agent.ps1</Command></LogonCommand>"
        "</Configuration>"
    )


def diff(a, b):
    """스냅샷 두 개(섹션 → {키: 값})를 섹션별 added/removed/changed로 비교."""
    out = {}
    for sec in sorted(set(a) | set(b)):
        x, y = a.get(sec) or {}, b.get(sec) or {}
        out[sec] = {
            "added": sorted(k for k in y if k not in x),
            "removed": sorted(k for k in x if k not in y),
            "changed": sorted(k for k in y if k in x and x[k] != y[k]),
        }
    return out


def diff_summary(d, cap=40):
    lines = []
    for sec, kinds in d.items():
        n = {k: len(v) for k, v in kinds.items()}
        if not any(n.values()):
            continue
        lines.append("[%s] +%d -%d ~%d" % (sec, n["added"], n["removed"], n["changed"]))
        for kind, sign in (("added", "+"), ("removed", "-"), ("changed", "~")):
            for k in kinds[kind][:cap]:
                lines.append("  %s %s" % (sign, k))
            if n[kind] > cap:
                lines.append("  %s … %d개 더" % (sign, n[kind] - cap))
    return "\n".join(lines) or "변화 없음"


def _alive(pid):
    if os.name == "nt":  # os.kill(pid, 0)은 Windows에서 프로세스를 죽인다 → tasklist로 확인
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH", "/FO", "CSV"],
                             capture_output=True, text=True, errors="replace").stdout
        return '"%d"' % pid in out
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def holder():
    """잠금을 쥔 살아 있는 winbox 정보, 없으면 None(빈 잠금·주인 죽은 잠금 포함)."""
    try:
        h = json.loads(LOCK.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):  # 방금 만들어져 아직 쓰는 중일 수 있다
        try:
            return {"owner": "?", "pid": -1} if time.time() - LOCK.stat().st_mtime < 10 else None
        except OSError:
            return None
    return h if _alive(int(h.get("pid", -1))) else None


def acquire(owner, wait_s=0):
    """잠금 획득. 주인이 죽은 잠금은 넘겨받고 True(=남은 샌드박스 치워야 함)를 돌려준다."""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    t0, stale = time.time(), False
    while True:
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            h = holder()
            if h is None:  # ponytail: 주인 없는 잠금 회수에 아주 짧은 경합 창이 있음, 필요하면 OS 뮤텍스로
                stale = True
                try:
                    LOCK.unlink()
                except OSError:
                    pass
                continue
            if time.time() - t0 >= wait_s:
                raise BoxError("다른 에이전트가 사용 중: %s (pid %s, %s부터). wait_s를 주면 줄을 선다"
                               % (h.get("owner"), h.get("pid"), h.get("since", "?")))
            time.sleep(2)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"owner": owner, "pid": os.getpid(), "since": time.strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False)
        return stale


def release():
    try:
        if json.loads(LOCK.read_text(encoding="utf-8")).get("pid") == os.getpid():
            LOCK.unlink()
    except (OSError, ValueError):
        pass


def _sandbox_running():
    out = subprocess.run(["tasklist", "/NH", "/FO", "CSV"], capture_output=True, text=True, errors="replace").stdout
    return any(l.lower().startswith('"windowssandbox') for l in out.splitlines())  # 이름 앞부분만(다른 *-sandbox-service 오탐 방지)


def _kill_sandbox():
    subprocess.run(["taskkill", "/F", "/IM", "WindowsSandbox*"], capture_output=True)
    subprocess.run(["schtasks", "/Delete", "/TN", TASK, "/F"], capture_output=True)


class Box:
    def __init__(self):
        self.run = None
        self.local = bool(os.environ.get("WINBOX_LOCAL"))
        self.owner = os.environ.get("WINBOX_OWNER") or "pid %d" % os.getpid()

    # -- 상태 ---------------------------------------------------------------
    def _need(self):
        if not self.run:
            raise BoxError("실행 중인 샌드박스가 없음 — box_start 먼저")

    def status(self):
        if not self.run:
            h = holder()
            return "꺼짐" + (" — 다른 에이전트 사용 중: %s (pid %s, %s부터)" % (h.get("owner"), h.get("pid"), h.get("since", "?")) if h else "")
        return "실행 중: %s (network=%s, local=%s)" % (self.run, self.network, self.local)

    # -- 기동/종료 -----------------------------------------------------------
    def start(self, network="on", memory_mb=4096, owner=None, wait_s=0, timeout_s=240, _locked=False):
        if self.run:
            raise BoxError("이미 실행 중 (Windows Sandbox는 한 번에 하나): %s" % self.run)
        if network not in ("on", "off"):
            raise BoxError("network는 on|off")
        self.local = bool(os.environ.get("WINBOX_LOCAL"))
        if owner:
            self.owner = owner
        if not _locked:
            if acquire(self.owner, wait_s) and not self.local:
                _kill_sandbox()  # 죽은 winbox가 남긴 샌드박스
        if not self.local and _sandbox_running():
            release()
            raise BoxError("winbox 밖에서 띄운 Windows 샌드박스가 이미 떠 있음 — 그 창을 닫고 다시")
        run = RUNS / time.strftime("%Y%m%d-%H%M%S")
        while run.exists():  # 리셋을 1초 안에 반복해도 폴더가 겹치지 않게
            time.sleep(1)
            run = RUNS / time.strftime("%Y%m%d-%H%M%S")
        self.run, self.network, self.memory_mb = run, network, memory_mb
        try:
            if self.local:  # ponytail: 로컬 모드는 배선 시험용 — 격리 없음, 신뢰하는 명령만
                self.groot = run / "local"
                shutil.copytree(str(GUEST_TOOLS), str(self.groot / "tools"))
                self.mail, self.inbox = self.groot / "mail", self.groot / "in"
            else:
                self.groot = Path(r"C:\winbox")
                self.mail, self.inbox = run / "mail", run / "in"
            for d in (self.mail / "res", self.mail / "out", self.inbox):
                d.mkdir(parents=True, exist_ok=True)
            (self.mail / "req.json").write_text("{}", encoding="utf-8")  # 부팅 전에 있어야 게스트가 내용 변경을 바로 본다
            self.proc = None
            if self.local:
                self.proc = subprocess.Popen(
                    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                     str(self.groot / "tools" / "agent.ps1"), "-Root", str(self.groot), "-Local"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                wsb = run / "box.wsb"
                wsb.write_text(wsb_xml(GUEST_TOOLS, self.mail, self.inbox, network, memory_mb), encoding="utf-8")
                self._launch_interactive(wsb)
            t0 = time.time()
            while not (self.mail / "ready").exists():
                if time.time() - t0 > timeout_s:
                    raise BoxError("에이전트 준비 신호 없음 (%ds). Windows 샌드박스 기능이 켜져 있고 콘솔에 로그인돼 있는지 확인" % timeout_s)
                time.sleep(1)
        except Exception:
            self.stop(force=True)
            raise
        return "준비 완료 %.0fs: %s" % (time.time() - t0, run)

    @staticmethod
    def _launch_interactive(wsb):
        # SSH 세션엔 데스크톱이 없어 샌드박스 창을 못 띄운다 → 로그인된 콘솔 세션에서 실행되는 작업으로 띄운다.
        exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsSandbox.exe"
        if not exe.exists():
            raise BoxError("WindowsSandbox.exe 없음 — 'Windows 기능 켜기/끄기'에서 Windows 샌드박스를 켜고 재부팅")
        for args in (["/Create", "/TN", TASK, "/TR", "%s %s" % (exe, wsb), "/SC", "ONCE", "/ST", "23:59", "/IT", "/F"],
                     ["/Run", "/TN", TASK]):
            p = subprocess.run(["schtasks"] + args, capture_output=True, text=True, errors="replace")
            if p.returncode:
                raise BoxError("schtasks %s 실패: %s" % (args[0], (p.stderr or p.stdout).strip()))

    def stop(self, force=False, keep_lock=False):
        if not self.run:
            return "이미 꺼짐"
        run = self.run
        try:
            self._send({"op": "stop"})
        except OSError:
            pass
        if self.local:
            p = getattr(self, "proc", None)
            try:
                p and p.wait(15)
            except Exception:
                p.kill()
        else:
            time.sleep(0 if force else 8)
            _kill_sandbox()
        self.run = None
        if not keep_lock:
            release()
        return "종료. 산출물: %s" % run

    def reset(self, network=None):
        """잠금을 쥔 채 버리고 새로 부팅 — 고치고 다시 깔아 보는 반복용."""
        self._need()
        net, mem = network or self.network, self.memory_mb
        self.stop(keep_lock=True)
        try:
            return self.start(net, mem, _locked=True)
        except Exception:
            release()
            raise

    def trial(self, host_path, command, clean=True, snapshot=True, network=None, timeout_s=600):
        """한 번의 시험: (새 샌드박스) → 스냅샷 pre → 넣기 → 실행 → 스냅샷 post → 비교."""
        log = []
        if not self.run:
            log.append(self.start(network or "on"))
        elif clean:
            log.append(self.reset(network))
        if snapshot:
            log.append(self.snapshot("pre"))
        g = self.copy_in(host_path)
        log.append("넣음: " + g)
        r = self.exec(command.replace("{in}", g), timeout_s)
        log.append("exit=%s timed_out=%s %sms\n--stdout--\n%s\n--stderr--\n%s" % (
            r.get("exit"), r.get("timed_out"), r.get("ms"), (r.get("stdout") or "")[-4000:], (r.get("stderr") or "")[-2000:]))
        if snapshot:
            log.append(self.snapshot("post"))
            log.append(self.diff("pre", "post"))
        return "\n\n".join(log)

    # -- 우편함 --------------------------------------------------------------
    def _send(self, req):
        # 샌드박스 공유폴더는 새 파일 이름을 ~20초 늦게 보여주지만(실측), 이미 있는 파일의 내용 변경은 바로 보인다
        # → 요청은 새 파일이 아니라 req.json 한 개를 덮어써서 보낸다. 게스트는 id가 바뀌면 처리.
        rid = uuid.uuid4().hex[:12]
        (self.mail / "req.json").write_text(json.dumps(dict(req, id=rid), ensure_ascii=False), encoding="utf-8")
        return rid

    def exec(self, command, timeout_s=120):
        self._need()
        rid = self._send({"op": "exec", "command": command, "timeout": int(timeout_s)})
        res = self.mail / "res" / (rid + ".json")
        t0 = time.time()
        while not res.exists():
            if time.time() - t0 > timeout_s + 60:
                raise BoxError("응답 없음 (%ds)" % (timeout_s + 60))
            time.sleep(0.2)
        r = json.loads(res.read_text(encoding="utf-8-sig"))
        res.unlink()
        return r

    def gpath(self, *parts):
        return "\\".join([str(self.groot)] + list(parts))

    # -- 파일 ----------------------------------------------------------------
    def copy_in(self, host_path):
        self._need()
        src = Path(host_path)
        if not src.exists():
            raise BoxError("호스트에 없음: %s" % src)
        dst = self.inbox / src.name
        if dst.is_dir():  # 고친 빌드를 다시 넣을 때 덮어쓰기
            shutil.rmtree(str(dst))
        elif dst.exists():
            dst.unlink()
        (shutil.copytree if src.is_dir() else shutil.copy2)(str(src), str(dst))
        g = self.gpath("in", src.name)
        if not self.local:  # 샌드박스는 새로 넣은 파일을 늦게 본다(실측 ~20초) → 보일 때까지 기다려야 바로 실행해도 안전
            files = [f for f in dst.rglob("*") if f.is_file()] if dst.is_dir() else [dst]
            n, size = len(files), sum(f.stat().st_size for f in files)
            r = self.exec("$p='%s'; $t=Get-Date; do { $f=@(Get-ChildItem -LiteralPath $p -Recurse -File -Force -EA 0); "
                          "if ($f.Count -eq %d -and ($f | Measure Length -Sum).Sum -eq %d) { exit 0 }; Start-Sleep -m 300 } "
                          "while (((Get-Date)-$t).TotalSeconds -lt 90); exit 1" % (g.replace("'", "''"), n, size), 120)
            if r.get("exit"):
                raise BoxError("넣은 파일이 90초 안에 샌드박스에 안 보임: %s" % g)
        return g

    def copy_out(self, guest_path):
        self._need()
        name = guest_path.rstrip("\\").split("\\")[-1]
        r = self.exec("Copy-Item -LiteralPath '%s' -Destination '%s' -Recurse -Force"
                      % (guest_path.replace("'", "''"), self.gpath("mail", "out", name)))
        if r.get("exit"):
            raise BoxError(r.get("stderr") or "복사 실패")
        return str(self.mail / "out" / name)

    def screenshot(self):
        self._need()
        name = "shot-%s.png" % time.strftime("%H%M%S")
        r = self.exec("& '%s' -Out '%s'" % (self.gpath("tools", "screenshot.ps1"), self.gpath("mail", "out", name)), 60)
        f = self.mail / "out" / name
        if not f.exists():
            raise BoxError("캡처 실패: %s" % (r.get("stderr") or r))
        return f

    def snapshot(self, name):
        self._need()
        if not name.replace("-", "").replace("_", "").isalnum():
            raise BoxError("name은 영문·숫자·-_만")
        r = self.exec("& '%s' -Out '%s'" % (self.gpath("tools", "snapshot.ps1"), self.gpath("mail", "out", "snap-%s.json" % name)), 600)
        f = self.mail / "out" / ("snap-%s.json" % name)
        if not f.exists():
            raise BoxError("스냅샷 실패: %s" % (r.get("stderr") or r))
        data = json.loads(f.read_text(encoding="utf-8-sig"))
        return "스냅샷 %s: " % name + ", ".join("%s %d" % (k, len(v or {})) for k, v in data.items())

    def diff(self, before, after):
        self._need()
        load = lambda n: json.loads((self.mail / "out" / ("snap-%s.json" % n)).read_text(encoding="utf-8-sig"))
        d = diff(load(before), load(after))
        f = self.mail / "out" / ("diff-%s-%s.json" % (before, after))
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        return diff_summary(d) + "\n\n전체: %s" % f


# -- MCP (JSON-RPC 2.0, 줄 단위 stdio) ----------------------------------------
def _p(**props):
    return {"type": "object", "properties": props, "required": [k for k, v in props.items() if v.pop("req", False)]}


S = {"type": "string"}
TOOLS = [
    ("box_start", "깨끗한 Windows 샌드박스 부팅. network=off면 네트워크 어댑터 자체가 없음(모르는 exe 실행용). "
     "샌드박스는 호스트에 한 대뿐 — 다른 에이전트가 쓰는 중이면 에러, wait_s초만큼 줄을 선다.",
     _p(network=dict(S, enum=["on", "off"]), memory_mb={"type": "integer"}, owner=dict(S), wait_s={"type": "integer"})),
    ("box_status", "샌드박스 실행 여부, 꺼져 있으면 누가 쓰는 중인지.", _p()),
    ("box_reset", "지금 샌드박스를 버리고 깨끗한 새 샌드박스로(자리는 유지).", _p(network=dict(S, enum=["on", "off"]))),
    ("box_trial", "고치고 다시 깔아 보는 반복 1회: 새 샌드박스→스냅샷 pre→host_path 넣기→command 실행({in}=넣은 경로)→스냅샷 post→비교.",
     _p(host_path=dict(S, req=True), command=dict(S, req=True), clean={"type": "boolean"}, snapshot={"type": "boolean"},
        network=dict(S, enum=["on", "off"]), timeout_s={"type": "integer"})),
    ("box_exec", "샌드박스 안에서 PowerShell 실행 → exit/stdout/stderr.", _p(command=dict(S, req=True), timeout_s={"type": "integer"})),
    ("box_copy_in", "호스트(Windows) 파일·폴더를 샌드박스 C:\\winbox\\in 으로 넣기(샌드박스 쪽은 읽기 전용).", _p(host_path=dict(S, req=True))),
    ("box_copy_out", "샌드박스 파일·폴더를 호스트 run\\mail\\out 으로 꺼내기.", _p(guest_path=dict(S, req=True))),
    ("box_screenshot", "샌드박스 화면 PNG.", _p()),
    ("box_snapshot", "파일·레지스트리·서비스·예약작업·자동실행·프로세스·연결·DNS 기록.", _p(name=dict(S, req=True))),
    ("box_diff", "두 스냅샷 비교: 무엇이 생기고/지워지고/바뀌었나.", _p(before=dict(S, req=True), after=dict(S, req=True))),
    ("box_stop", "샌드박스 폐기(안의 모든 것 삭제). 산출물 폴더는 호스트에 남음.", _p()),
]


def call(box, name, a):
    if name == "box_start":
        return box.start(a.get("network", "on"), a.get("memory_mb", 4096), a.get("owner"), a.get("wait_s", 0))
    if name == "box_status":
        return box.status()
    if name == "box_reset":
        return box.reset(a.get("network"))
    if name == "box_trial":
        return box.trial(a["host_path"], a["command"], a.get("clean", True), a.get("snapshot", True),
                         a.get("network"), a.get("timeout_s", 600))
    if name == "box_exec":
        return box.exec(a["command"], a.get("timeout_s", 120))
    if name == "box_copy_in":
        return box.copy_in(a["host_path"])
    if name == "box_copy_out":
        return box.copy_out(a["guest_path"])
    if name == "box_screenshot":
        f = box.screenshot()
        return [{"type": "image", "mimeType": "image/png", "data": base64.b64encode(f.read_bytes()).decode()},
                {"type": "text", "text": str(f)}]
    if name == "box_snapshot":
        return box.snapshot(a["name"])
    if name == "box_diff":
        return box.diff(a["before"], a["after"])
    if name == "box_stop":
        return box.stop()
    raise BoxError("모르는 도구: %s" % name)


def handle(box, msg):
    m, params = msg.get("method"), msg.get("params") or {}
    if m == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}}, "serverInfo": {"name": "winbox", "version": VERSION}}
    if m == "ping":
        return {}
    if m == "tools/list":
        return {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s in TOOLS]}
    if m == "tools/call":
        try:
            out = call(box, params.get("name"), params.get("arguments") or {})
            if isinstance(out, dict):
                out = json.dumps(out, ensure_ascii=False, indent=1)
            content = out if isinstance(out, list) else [{"type": "text", "text": str(out)}]
            return {"content": content, "isError": False}
        except (BoxError, OSError, KeyError, ValueError) as e:
            return {"content": [{"type": "text", "text": "%s: %s" % (type(e).__name__, e)}], "isError": True}
    raise LookupError(m)


def main():
    for s in (sys.stdin, sys.stdout):
        s.reconfigure(encoding="utf-8")
    box = Box()
    try:
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            if not line.strip():
                continue
            msg = json.loads(line)
            if "id" not in msg:
                continue  # notification
            try:
                resp = {"jsonrpc": "2.0", "id": msg["id"], "result": handle(box, msg)}
            except LookupError as e:
                resp = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "method not found: %s" % e}}
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    finally:
        if box.run:  # 클라이언트가 끊기면 샌드박스도 치운다
            box.stop(force=True)


if __name__ == "__main__":
    main()

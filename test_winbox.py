"""winbox 자가검사 — 샌드박스 없이 어디서나: python3 test_winbox.py"""
import json
import winbox


def test_wsb():
    x = winbox.wsb_xml(r"C:\a&b\guest", r"C:\r\mail", r"C:\r\in", network="off", memory_mb=2048)
    assert "<Networking>Disable</Networking>" in x and "<MemoryInMB>2048</MemoryInMB>" in x
    assert r"C:\a&amp;b\guest" in x  # XML 이스케이프
    assert x.count("<ReadOnly>true</ReadOnly>") == 2 and x.count("<ReadOnly>false</ReadOnly>") == 1
    assert "<ClipboardRedirection>Disable</ClipboardRedirection>" in x
    assert "<Networking>Default</Networking>" in winbox.wsb_xml("t", "m", "i")


def test_diff():
    a = {"files": {"x": "1|1", "y": "2|2"}, "dns": {}}
    b = {"files": {"x": "1|9", "z": "3|3"}, "dns": {"evil.example": "1.2.3.4"}, "tasks": {"\\T": "a.exe"}}
    d = winbox.diff(a, b)
    assert d["files"] == {"added": ["z"], "removed": ["y"], "changed": ["x"]}
    assert d["dns"]["added"] == ["evil.example"] and d["tasks"]["added"] == ["\\T"]
    s = winbox.diff_summary(d, cap=1)
    assert "[files] +1 -1 ~1" in s and "+ evil.example" in s
    assert winbox.diff_summary(winbox.diff(a, a)) == "변화 없음"


def test_mcp():
    box = winbox.Box()
    r = winbox.handle(box, {"method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
    assert r["protocolVersion"] == "2025-03-26" and r["capabilities"] == {"tools": {}}
    tools = winbox.handle(box, {"method": "tools/list"})["tools"]
    assert len(tools) == 11 and all(t["inputSchema"]["type"] == "object" for t in tools)
    ex = next(t for t in tools if t["name"] == "box_exec")["inputSchema"]
    assert ex["required"] == ["command"]
    r = winbox.handle(box, {"method": "tools/call", "params": {"name": "box_exec", "arguments": {"command": "x"}}})
    assert r["isError"] and "box_start" in r["content"][0]["text"]  # 기동 전 호출은 에러로 돌려준다
    r = winbox.handle(box, {"method": "tools/call", "params": {"name": "box_start", "arguments": {"network": "maybe"}}})
    assert r["isError"]
    try:
        winbox.handle(box, {"method": "nope"})
        assert False
    except LookupError:
        pass
    json.dumps(tools, ensure_ascii=False)


def test_lock():
    import os, tempfile
    from pathlib import Path
    winbox.LOCK = Path(tempfile.mkdtemp()) / "lock.json"
    assert winbox.acquire("a") is False and winbox.holder()["owner"] == "a"
    try:
        winbox.acquire("b")  # 같은 pid라도 살아 있으니 거절
        assert False
    except winbox.BoxError as e:
        assert "a" in str(e)
    assert "다른 에이전트" in winbox.Box().status()
    winbox.release()
    assert not winbox.LOCK.exists() and winbox.Box().status() == "꺼짐"
    dead = 2 ** 22 + 12345  # 존재하지 않는 pid
    winbox.LOCK.write_text(json.dumps({"owner": "ghost", "pid": dead}), encoding="utf-8")
    assert winbox.holder() is None and winbox.acquire("c") is True  # 죽은 주인의 잠금 회수
    winbox.LOCK.write_text('{"owner": "x", "pid": %d}' % dead, encoding="utf-8")
    winbox.release()  # 내 것이 아니면 안 지운다
    assert winbox.LOCK.exists()
    winbox.LOCK.write_text("{", encoding="utf-8")  # 쓰는 중(10초 이내)은 잡힌 것으로 본다
    assert winbox.holder() is not None


def test_copy_in_overwrite():
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    b = winbox.Box()
    b.run, b.inbox, b.groot = d, d / "in", Path(r"C:\winbox")
    b.inbox.mkdir()
    (d / "build").mkdir()
    (d / "build" / "a.txt").write_text("v1")
    b.copy_in(str(d / "build"))
    (d / "build" / "a.txt").write_text("v2")
    assert b.copy_in(str(d / "build")) == r"C:\winbox\in\build"
    assert (b.inbox / "build" / "a.txt").read_text() == "v2"
    (d / "f.exe").write_text("1"); b.copy_in(str(d / "f.exe")); (d / "f.exe").write_text("2"); b.copy_in(str(d / "f.exe"))
    assert (b.inbox / "f.exe").read_text() == "2"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

"""SSH 너머 winbox MCP 왕복 시험. 사용: WINBOX_HOST=user@host python3 mcp_probe.py [local] < steps.json
(호스트 홈의 winbox-mcp 폴더에 이 폴더가 복사돼 있어야 함)"""
import json, os, subprocess, sys, time

HOST = os.environ["WINBOX_HOST"]  # 예: user@my-windows-pc
cmd = r"cd winbox-mcp && py -3 winbox.py"
if sys.argv[1:] == ["local"]:
    cmd = r"cd winbox-mcp && set WINBOX_LOCAL=1&& py -3 winbox.py"
p = subprocess.Popen(["ssh", "-T", "-o", "BatchMode=yes", HOST, cmd], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
n = 0
def rpc(method, params=None):
    global n; n += 1
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n, "method": method, "params": params or {}}) + "\n"); p.stdin.flush()
    return json.loads(p.stdout.readline())
def tool(_tool, **a):
    t = time.time(); r = rpc("tools/call", {"name": _tool, "arguments": a})["result"]
    txt = " | ".join(c.get("text", "<%s %d bytes>" % (c["type"], len(c.get("data", "")))) for c in r["content"])
    print("%-14s %5.1fs err=%s %s" % (_tool, time.time() - t, r["isError"], txt[:600].replace("\n", " ⏎ ")))
    return r

print(rpc("initialize", {"protocolVersion": "2025-06-18"})["result"]["serverInfo"])
p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"); p.stdin.flush()
print([t["name"] for t in rpc("tools/list")["result"]["tools"]])
for step in json.loads(sys.stdin.read() or "[]"):
    tool(step.pop("tool"), **step)
p.stdin.close(); p.wait(30)

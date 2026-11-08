#!/bin/sh
# Windows 호스트에 winbox를 깔고(홈\winbox-mcp) 자가검사까지 돌린다.  사용: ./install.sh user@host
set -e
H="${1:?사용: ./install.sh user@host}"
cd "$(dirname "$0")"
ssh -o BatchMode=yes "$H" "if not exist winbox-mcp\guest mkdir winbox-mcp\guest"
scp -q winbox.py test_winbox.py "$H:winbox-mcp/"
scp -q guest/*.ps1 "$H:winbox-mcp/guest/"
ssh -o BatchMode=yes "$H" "cd winbox-mcp && py -3 test_winbox.py && if exist %SystemRoot%\System32\WindowsSandbox.exe (echo sandbox: ON) else (echo sandbox: OFF - enable Windows Sandbox in Windows Features, then reboot)"

---
name: winbox-mcp
description: "Use when 깨끗한 윈도우에서 애드인·설치기 시험이나 모르는 exe 동적분석할 때. SSH-only MCP over Windows Sandbox: boot, exec, copy, screenshot, snapshot/diff, discard."
version: 0.2.0
license: MIT
metadata:
  hermes:
    tags: [windows, sandbox, mcp, ssh, excel-addin, installer-test, reverse-engineering]
---

# winbox-mcp — 일회용 Windows 샌드박스

Windows 호스트의 `winbox.py`를 SSH로 띄워 MCP 도구 11개(`box_*`)를 쓴다. 설치·등록은 README.md.

## 언제 쓰나

- **애드인·설치기 시험**: "새 PC에서도 깔리나", "어디에 뭘 등록하나", "지우면 찌꺼기 남나".
- **리버스 엔지니어링 실험**: 모르는 exe를 `network=off`로 실행해 자동실행·서비스·예약작업·새 파일·연결 시도·DNS 조회를 본다.
- 정적 분석(디컴파일·문자열)은 샌드박스가 필요 없다 — 실행해 봐야 알 때만 쓴다.

## 순서 (항상 이 틀)

1. `box_start` (모르는 파일이면 `network: "off"`)
2. `box_snapshot before`
3. `box_copy_in` → `box_exec`로 설치·실행 (`Start-Process …; Start-Sleep 60`)
4. `box_snapshot after` → `box_diff before after`
5. 필요하면 `box_screenshot`, `box_copy_out`
6. **`box_stop`을 반드시 호출** (안 하면 30분 뒤 스스로 꺼짐)

## 반복 시험 (고치고 다시 깔기)

- 빌드를 고칠 때마다 `box_trial host_path=… command="& {in} /quiet"` 한 번. 매번 새 샌드박스·전후 비교가 자동이다.
- 빠르게 돌릴 땐 `clean=false snapshot=false`. 마지막 확인은 반드시 `clean=true`로 한다(앞 회차 찌꺼기 때문에 통과한 것일 수 있다).

## 여러 에이전트

- 샌드박스는 호스트에 한 대. `box_start`가 "다른 에이전트가 사용 중"이면 기다릴 수 있을 때만 `wait_s`를 주고, 아니면 사용자에게 알린다.
- `owner`에 자기 이름을 넣는다. 다 쓰면 바로 `box_stop` — 다른 에이전트가 줄 서 있을 수 있다.

## 판정 규칙

- `box_diff` 결과에서 볼 곳: 애드인=`files`의 `AddIns`·`XLSTART`, `registry`의 `Software\Microsoft\Office`, `clsid`. 동적분석=`registry`의 `Run`·`Winlogon`·`Image File Execution Options`, `services`, `tasks`, `network`, `dns`.
- 레지스트리 키는 `…\`로 끝나고, 값은 `키\\값이름` 형식이다.
- `mail\out`에서 꺼낸 파일은 샌드박스가 쓴 것이라 **믿지 않는다**. 열어 실행하지 않는다.
- 샌드박스에는 Office·winget·스토어 앱이 없다. 엑셀 안에서 실제 로드까지 봐야 하면 Office 오프라인 설치가 먼저다(미실측 — 결과를 단정하지 말 것).

## 함정

- 호스트 콘솔에 로그인돼 있지 않으면 `box_start`가 240초 뒤 "준비 신호 없음"으로 실패한다.
- Windows Sandbox는 한 번에 하나. 이미 켜져 있으면 `box_stop` 먼저.
- `WINBOX_LOCAL=1`은 격리 없는 배선 시험 모드다. 여기서 `box_snapshot`은 실제 PC 전체를 훑어 수 분·수백 MB가 걸린다.

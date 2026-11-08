# winbox-mcp

**SSH 한 줄로 붙는, 일회용 Windows 샌드박스 MCP 서버.**
엑셀 애드인·설치 프로그램 시험과 리버스 엔지니어링 실험(모르는 exe 실행)을 깨끗한 Windows에서 하고, 끝나면 통째로 버린다.

- Python 표준 라이브러리 + PowerShell만 사용. `pip install`, Node, npm 없음.
- 호스트 쪽에 포트를 열지 않는다. MCP 통신은 SSH 표준입출력, 호스트↔샌드박스는 공유 폴더 우편함 하나.
- 그래서 **네트워크를 끈 샌드박스에서도** 같은 도구가 그대로 동작한다.

```
 맥/리눅스 에이전트 ──ssh(-T)──▶ Windows 호스트: winbox.py (MCP)
                                    │ 공유 폴더 우편함 (mail\req → mail\res)
                                    ▼
                               Windows Sandbox: guest\agent.ps1
                               (네트워크 on/off, 종료 시 전부 삭제)
```

## 준비물 (Windows 호스트)

1. Windows 10/11 **Pro·Enterprise·Education** (Home은 샌드박스 없음), 가상화 켜짐
2. `Windows 기능 켜기/끄기` → **Windows 샌드박스** 체크 → 재부팅
3. OpenSSH 서버 (Tailscale 등으로 원격 접속 가능하면 됨)
4. Python 3.9+ (`py -3`)
5. 맥/리눅스에서 `./install.sh <user>@<호스트>` — 호스트 홈의 `winbox-mcp`로 복사하고 자가검사까지 돌린다
6. 호스트 콘솔에 **로그인된 상태**여야 한다 — 샌드박스 창은 로그인된 데스크톱 세션에 뜬다. SSH로 불러도 winbox가 예약 작업(`schtasks /IT`)으로 그 세션에 띄워 준다.

## 에이전트에 붙이기

SSH 키 로그인이 되어 있어야 한다(비밀번호 프롬프트가 뜨면 MCP가 멈춘다). 아래 어느 쪽이든 결국 같은 한 줄이다:
`ssh -T -o BatchMode=yes <user>@<호스트> "py -3 winbox-mcp\winbox.py"`

**Claude Code — 플러그인** (MCP 서버 + 사용법 스킬이 같이 깔린다)

```
claude plugin marketplace add kims6305-bjk/winbox-mcp
claude plugin install winbox@winbox --config host=<user>@<호스트>
```

**Hermes** — `config.yaml`에 넣고, 사용법 스킬은 `skills/winbox`를 `~/.hermes/skills/`로 복사

```yaml
mcp_servers:
  winbox:
    command: ssh
    args: ["-T", "-o", "BatchMode=yes", "<user>@<호스트>", "py -3 winbox-mcp\\winbox.py"]
    timeout: 900
```

**Codex CLI**

```
codex mcp add winbox -- ssh -T -o BatchMode=yes <user>@<호스트> "py -3 winbox-mcp\winbox.py"
```

그 밖의 MCP 클라이언트도 `command: ssh`와 위 인자만 넣으면 된다.

## 도구 11개

| 도구 | 하는 일 |
|---|---|
| `box_start` | 깨끗한 샌드박스 부팅. `network: off`면 네트워크 어댑터 자체가 없음 |
| `box_status` | 켜져 있나, 꺼져 있으면 다른 에이전트가 쓰는 중인지 |
| `box_reset` | 지금 샌드박스를 버리고 새것으로 (자리는 놓지 않음) |
| `box_trial` | 반복 시험 1회: 새 샌드박스 → 스냅샷 → 파일 넣기 → 실행 → 스냅샷 → 비교 |
| `box_exec` | 샌드박스 안에서 PowerShell 실행 → 종료코드·stdout·stderr (시간 제한) |
| `box_copy_in` | 호스트 파일·폴더를 샌드박스 `C:\winbox\in`으로 (샌드박스 쪽 읽기 전용) |
| `box_copy_out` | 샌드박스 파일을 호스트로 꺼내기 |
| `box_screenshot` | 화면 PNG |
| `box_snapshot` | 파일·레지스트리·COM 등록·서비스·예약작업·프로세스·TCP 연결·DNS 기록 |
| `box_diff` | 두 스냅샷 비교 — 생긴 것/지워진 것/바뀐 것 |
| `box_stop` | 샌드박스 폐기. 산출물 폴더(`%LOCALAPPDATA%\winbox\runs\…`)는 남음 |

## 쓰는 법 — 대표 시나리오

### 1) 엑셀 애드인·설치기 시험 (깨끗한 PC에서 되나?)

```
box_start → box_snapshot before → box_copy_in setup.exe → box_exec "& C:\winbox\in\setup.exe /quiet"
→ box_snapshot installed → box_diff before installed      # 무엇을 어디에 깔았나 (AddIns·XLSTART·HKCU\Software\Microsoft\Office·CLSID)
→ (제거 실행) → box_snapshot removed → box_diff before removed   # 지운 뒤 찌꺼기
→ box_stop
```

샌드박스에는 **Office가 없다**. 엑셀 안에서 애드인이 실제로 뜨는지까지 보려면 매번 Office를 설치해야 한다
(Office 배포 도구로 호스트에 설치 원본을 한 번 받아 두고 `box_copy_in` → 오프라인 설치). 이 경로는 아직 실측 전이다.

### 2) 리버스 엔지니어링 실험 (모르는 exe가 실제로 뭘 하나?)

```
box_start network=off → box_snapshot before → box_copy_in sample.exe
→ box_exec "Start-Process C:\winbox\in\sample.exe; Start-Sleep 60"
→ box_snapshot after → box_diff before after   # 자동실행·서비스·예약작업·새 파일·연결 시도·DNS 조회
→ box_screenshot → box_stop
```

Procmon·x64dbg 같은 분석 도구는 샌드박스에 없다. 필요하면 포터블판을 `box_copy_in`으로 넣는다.

### 3) 고치고 다시 깔아 보기 (반복)

빌드를 고칠 때마다 `box_trial` 한 번이면 된다. 매번 깨끗한 샌드박스에서 시작하고, `{in}`은 넣은 파일 경로로 바뀐다.

```
box_trial host_path=C:\build\MyAddin command="& {in} /quiet"     # 1회차: 실패 → 고침
box_trial host_path=C:\build\MyAddin command="& {in} /quiet"     # 2회차: 새 샌드박스에서 다시
box_trial ... clean=false snapshot=false                          # 빨리 돌릴 땐 같은 샌드박스·스냅샷 생략
```

같은 이름의 파일·폴더를 다시 넣으면 덮어쓴다.

### 여러 에이전트가 같이 쓸 때

Windows 샌드박스는 호스트에 **한 대뿐**이다. 그래서 winbox는 호스트 전역 잠금(`%LOCALAPPDATA%\winbox\lock.json`)으로 자리를 나눈다.

- 누가 쓰는 중이면 `box_start`가 "다른 에이전트가 사용 중: <owner> (pid, 시작 시각)"으로 거절한다.
- `box_start wait_s=600`처럼 주면 자리가 날 때까지 줄을 선다.
- `owner`(또는 환경변수 `WINBOX_OWNER`)로 이름표를 단다. `box_status`가 지금 누가 쓰는지 알려 준다.
- 쓰던 winbox가 죽으면 잠금 주인이 없어진 것으로 보고 다음 사람이 넘겨받는다. 남은 샌드박스는 그때 치운다.

### 샌드박스 없이 배선만 시험

`WINBOX_LOCAL=1`이면 샌드박스 대신 **호스트에서** 에이전트를 직접 띄운다. SSH·MCP·우편함 배선 점검용이며 격리가 없으니
신뢰하는 명령만 쓴다. 이 모드에서 에이전트는 절대 컴퓨터를 끄지 않는다(종료 명령은 샌드박스 전용 계정 `WDAGUtilityAccount`에서만 실행).

## 보안 메모

- 샌드박스는 Hyper-V로 분리된 별도 커널이고, 닫으면 안의 모든 것이 지워진다.
- 클립보드·마이크·카메라·프린터 연결은 꺼져 있다.
- 호스트와 공유하는 폴더는 3개뿐: `tools`(읽기 전용), `in`(읽기 전용), `mail`(읽고 쓰기).
- `mail` 폴더는 샌드박스 안에서 쓸 수 있으니 꺼내온 결과물은 **믿지 않는 자료**로 다룬다. winbox는 거기서 JSON·PNG를 읽기만 하고 실행하지 않는다.
- 에이전트는 30분 동안 요청이 없으면 샌드박스를 스스로 끈다. MCP 연결이 정상 종료되면 바로 정리하고, 강제로 끊긴 경우는 이 30분 유휴 종료에 맡긴다.
- 샌드박스 탈출 취약점까지 막아 주지는 않는다. 진짜 악성코드 분석은 전용 분석 PC를 쓴다.

## 실측 메모 (v0.2.0)

맥 → Tailscale SSH → Windows 11 호스트, **로컬 모드**(샌드박스 대신 호스트에서 직접 실행)에서 확인한 것:

- 도구 11개 전부 왕복. 기동 1초, `box_exec` 왕복 0.6초, 한글 출력·종료코드·stderr·시간초과 정상.
- 두 에이전트 동시 접속: A가 쓰는 동안 B의 `box_start`는 즉시 거절, `wait_s=60`으로 줄 선 B는 A가 놓은 직후(12초) 자리를 받았다.
- `box_trial` 2회 연속(새 샌드박스로 리셋 1.8초, 리셋 없이 0.4초).
- `box_snapshot`을 **실제 사용 중인 PC**에서 돌리면 파일 93만 개·레지스트리 20만 값, 1장에 약 4분·219MB. 비교는 6.5초에 심어 둔 애드인 파일과 엑셀 자동로드 레지스트리 값을 정확히 잡았다.
- Claude Code 플러그인으로 설치 → `claude mcp list`에서 SSH 너머 연결 ✔, 실제 `box_status` 호출 응답 확인.

**아직 실측 전**: 진짜 Windows 샌드박스 안에서의 실행(기능을 켜야 함), 빈 샌드박스의 스냅샷 크기·시간, 샌드박스 화면 캡처(로컬 모드에선 SSH 세션에 화면이 없어 빈 이미지), Codex 등록.

## 원본 계열 도구보다 작은 이유

비슷한 공개 도구들은 Windows 앱 개발자용이라 MSIX 패키지, 런타임 자동 설치, 화면 녹화, UI 자동화, 다른 에이전트용 포장 여러 벌을 함께 싣는다.
winbox는 **애드인·설치기 시험**과 **동적 분석** 두 용도만 본다. 대신 그 두 용도에 필요한 것 — 설치 전후 비교, 반복 시험, 여러 에이전트 줄 서기 — 은 넣었다.

## 일부러 뺀 것

UI 자동화(버튼 찾아 누르기), 화면 녹화, MSIX 앱, 런타임 자동 설치. 엑셀 화면을 직접 눌러 봐야 할 때 UI 자동화부터 붙인다.

## 시험

```
python3 test_winbox.py                                       # 어디서나 (설정 생성·비교·잠금·MCP 응답)
WINBOX_HOST=<user>@<호스트> python3 mcp_probe.py local < steps.json   # SSH 너머 실제 왕복 (WINBOX_LOCAL)
```

## 라이선스

MIT

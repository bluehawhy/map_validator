# map_validator Windows 제어 UI

참고 UI: https://github.com/bluehawhy/nv_c_test (PyQt6, 작은 반투명 상단 고정창, 드래그 헤더, 상태·로그 표시).

## 실행 조건

Windows 11 + Python 3.11 권장. Python 3.11이 없어 `No runtime installed that matches 3.11` 오류가 발생하면 PowerShell에서 `py install 3.11` 또는 `py list`로 설치된 버전을 확인합니다. 꼭 3.11이어야 하는 것은 아니므로 지원되는 Python이 설치되어 있으면 `py -m venv .venv`를 사용합니다.

```powershell
git clone https://github.com/bluehawhy/map_validator.git
cd map_validator
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-ui.txt
# AI 분석 시 추가 설치
python -m pip install -r requirements-ai.txt
Copy-Item config.example.yaml config.yaml
python -m UI
```

혹은 `UI/run_ui.bat` 더블클릭.

## UI 항목

- **검수 ID**: 영문/숫자/하이픈/밑줄만 입력. `results/<ID>/`에 저장.
- **업무 창 제목**: 로드뷰 버튼을 가진 Windows 업무 프로그램 제목 일부.
- **로드뷰 창 제목**: 별도로 열리는 로드뷰 창 제목 일부.
- **템플릿 이미지**: 업무 프로그램의 로드뷰 열기 버튼을 작게 캡처한 PNG. 실제 화면/고객정보가 담긴 파일은 Git 업로드하지 말 것.
- **이동**: 없음 / W 전진 / S 후진. 횟수는 0~설정 최대 5회.
- **분석 전 로드뷰 열기**: 켜면 업무 프로그램에서 버튼을 누르고 창이 뜰 때까지 잠시 대기.
- **로드뷰 열기**: 버튼 템플릿을 찾아 클릭. 분석 없음.
- **캡처만**: 각 시점 PNG 저장. AI 미사용.
- **좌·우 도로 후보 분석**: AI 도로 마스크/후보 점수 산출 + 증거 이미지/JSON 저장.
- **중지**: 다음 처리 지점에서 중단 요청. AI 모델 로딩이나 추론을 강제 종료하지 않음.
- **설정 저장**: `config.yaml`에 제목/이미지 경로 저장(개인 로컬 설정, Git 제외).
- **결과 폴더**: 현재 완료된 검수 결과 폴더를 Windows 탐색기에서 열기.

## UX 및 안정성

- UI는 `UI/`에 분리되어 분석 엔진 모듈(`map_validator/`)과 독립.
- PyQt6 QThread로 업무 프로그램 조작과 AI 분석을 백그라운드 실행하며 창 멈춤 방지.
- 원격 화면 캡처/로드뷰 키 동작 직전에 UI를 숨겼다가 캡처 후 다시 표시해 오버레이가 스크린샷에 들어가지 않게 함.
- PyAutoGUI FAILSAFE 활성화. 마우스를 화면 왼쪽 상단으로 이동하면 PyAutoGUI 제어 명령에서 긴급 중단이 발생.
- 원본 화면/분석 화면 및 JSON 보고서 저장; **업무 프로그램에 검증 완료/오류를 자동 저장하지 않음**.
- 탐지 결과는 `possible`, `not_detected_review_required`, `not_analyzed`이고 실제 연결도로 여부 확정 아님.
- UI를 닫을 때 작업 중이라면 중지 요청 후 작업 스레드 종료까지 창 닫기를 보류.
- 2D 하늘색/파란색/주황색 선형 자체를 자동 인식해 로드뷰와 비교하는 기능은 이 초기 버전에 아직 포함되지 않음.

## 제약

Windows 실제 업무 환경에서 검증 전. 로드뷰 도구의 고유 조작 방식과 표본 이미지에 따라 템플릿/AI 후보 검출을 보정해야 함. 화면이 가려졌거나 잠긴 세션에서는 캡처/조작 실패 가능. UI 첫 실행 시 AI 모델 다운로드에는 네트워크가 필요할 수 있으며 장시간 소요될 수 있음.

테스트 코드는 별도 요청 전까지 생성하지 않음.

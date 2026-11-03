# map_validator

Windows 업무 프로그램에서 버튼으로 열리는 로드뷰를 분석해 **골목길 교차로의 좌회전·우회전 연결도로가 실제로 있는지** 1차로 검토하는 Python 도구입니다.

> **v0.1 초기 골격:** 좌/우 도로 후보를 표시하는 실험적 분석만 제공합니다. 현 단계에서 진입 가능한 골목길을 확정 판정하지 않습니다. 사람이 최종 검수합니다.

## 업무 조건

- 업무 프로그램의 2D 폴리라인: **하늘색 = 원도로(진입)**, **파란색 = 나가는 도로(진출)**, **주황색 = 교차점 연결 경로**
- 로드뷰는 별도 창으로 열리며 **W 전진 / S 후진**만 자동 조작합니다.
- 좌우 회전(Space+마우스) 없음. 직진·차로 수·노면 화살표·교통규칙 검증 없음.
- 실제 좌·우회전 연결도로 존재 여부만 1차로 확인. 최종 확인은 사람.
- 현재 버전은 로드뷰 후보 탐지만 가능하며 2D 경로와 자동 비교는 향후 기능입니다.

## 설치 (Windows 11)

```powershell
# 기본 설치된 호환 Python 버전 사용 (3.11이 없다면: py install 3.11)
py list
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-ui.txt
# AI 분석 기능을 사용할 때만 추가
python -m pip install -r requirements-ai.txt
Copy-Item config.example.yaml config.yaml
```

`config.yaml`에 업무 프로그램/로드뷰 창의 제목 일부를 지정합니다. AI 모델은 첫 실행 시 다운로드되며 초기 실행에는 인터넷과 충분한 저장 공간이 필요합니다.

## GUI 제어창 실행 (nv_c_test 스타일)

Windows용 별도 **[UI/](UI/)** 폴더에 PyQt6 제어창을 추가했습니다. 참조 프로젝트의 반투명·항상 위·드래그 이동 가능한 작은 창과 상태/로그 표시 구조를 따릅니다.

```powershell
python -m UI
```

또는 탐색기에서 `UI\run_ui.bat`을 실행할 수 있습니다.

UI에서 검수 ID와 Windows 창 제목, 버튼 이미지 경로, W/S 이동 방향과 횟수를 지정하고 **로드뷰 열기 / 캡처만 / 좌·우 도로 후보 분석 / 중지**를 조작합니다. 설정 저장은 Git 제외 대상인 `config.yaml`에만 기록합니다. UI는 화면 캡처 시 잠깐 숨겨 오버레이가 캡처에 섞이지 않도록 합니다. 중지는 캡처/AI 단계 사이에 확인되며, AI 모델 최초 다운로드/추론 중에는 즉시 멈추지 않을 수 있습니다.

자세한 내용: [UI 조작 안내](docs/UI.md)

## CLI 실행

```powershell
# 로드뷰를 직접 연 다음 캡처만 수행
python -m map_validator --case-id sample001 --no-ai

# AI로 좌우 연결도로 후보 탐색(이동 없이)
python -m map_validator --case-id sample001

# W로 3회 전진하면서 각 시점 기록
python -m map_validator --case-id sample001 --move forward --steps 3

# S로 2회 후진
python -m map_validator --case-id sample001 --move backward --steps 2

# assets/open_roadview.png 버튼 템플릿이 준비된 경우
python -m map_validator --case-id sample001 --open-roadview --move forward --steps 2
```

출력은 `results/<case-id>/` 아래 PNG 원본, AI 오버레이, JSON 보고서로 저장됩니다. 결과는 모두 `requires_human_review`로 기록합니다. 마우스를 화면 맨 왼쪽 위로 움직이면 PyAutoGUI 긴급 중단이 작동합니다.

## 결과 해석

- `possible`: 이미지 측면에서 도로 영역 후보가 검출됨. 실제 좌/우 분기 연결이 확인된 것은 아님.
- `not_detected_review_required`: 후보 미검출. 도로가 없다는 뜻이 아님.
- `not_analyzed`: AI 분석 없이 캡처만 진행.
- `requires_human_review`: 최종 사람 검수 필수.

**한계:** SegFormer는 도로 영역 픽셀을 분할하지만 골목길의 실제 연결이나 좌·우회전 가능성을 증명하지 않습니다. 커브, 주차장, 그림자, 가림, 촬영 각도 등으로 오탐이 발생합니다. 실무 판정 전에는 사례별 보정이 필요합니다.

## 문서

- [요구사항 및 판정 기준](docs/REQUIREMENTS.md)
- [아키텍처](docs/ARCHITECTURE.md)
- [개발 계획](docs/ROADMAP.md)

## 공개 저장소 보안

실무 로드뷰 캡처, 개인정보, 교차로 식별자, 로컬 설정 및 AI 모델은 Git 추적 대상에서 제외합니다. 로드뷰 제공사의 이용 조건을 확인해야 합니다. 자동 최종 승인/저장은 구현하지 않았습니다.

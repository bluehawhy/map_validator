# map_validator

Windows 업무 프로그램에서 선택한 교차로의 입력도구 화면과 로드뷰를 캡처하고, **2D 경로선에서 확인하려는 좌회전·우회전 차로가 실제 도로 화면에도 보이는지** 사람이 빠르게 검수하도록 돕는 Python 도구입니다.

> **현재 UI 단계:** 두 창을 WGC로 캡처해 저장하고, **도로후보 분석** 버튼으로 현재 검수 ID의 입력툴 하늘색 진입선 → 주황색 연결선 → 파란색 진출선과 **로드뷰 도로 형태**를 비교합니다. 저장된 사진만 사용하고 폴더 팝업·새 캡처·로드뷰 자동 이동은 없습니다. 결과는 **방향·형태 일치 후보/불일치 의심/판단 보류**이며 정확한 3D 정합이나 최종 판단을 대신하지 않습니다.

## 검수 대상과 범위

업무 프로그램의 2D 선형은 다음 색으로 구분됩니다.

| 색 | 의미 |
|---|---|
| 하늘색 | 원도로 경로(진입) |
| 파란색 | 나가는 도로 경로(진출) |
| 주황색 | 교차점 연결 경로 |

업무 프로그램에서 교차로를 선택하고 로드뷰를 연 뒤, 도로뷰를 **앞뒤로만 이동**하면서 경로가 나타내는 좌·우회전 방향의 차로 또는 도로가 현장 화면에 있는지 살펴봅니다. 화면 회전은 하지 않습니다. AI 표시는 검수할 위치를 찾기 위한 후보이며, 2D 선형과 실제 차로를 자동으로 확정 비교하지 않습니다.

- 포함: Windows 업무 프로그램/로드뷰 창 제어, W/S 이동, 프레임 캡처, 좌·우 후보 표시, 검수용 이미지와 JSON 저장
- 제외: 좌우 회전 조작, 직진 차로·차로 수·노면 화살표·교통 규칙 검증, 업무 데이터 자동 수정/승인
- 최종 판단: 사람이 원본 캡처와 업무 프로그램의 2D 경로를 대조

자세한 내용은 [프로젝트 컨셉](docs/PROJECT_CONCEPT.md), [요구사항 및 판정 기준](docs/REQUIREMENTS.md), [폴더 구조](docs/FOLDER_STRUCTURE.md)를 참고하세요.

## Windows 11 설치

```powershell
py list
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-ui.txt
# AI 분석 기능을 사용할 때만 추가
python -m pip install -r requirements-ai.txt
```

Python 3.11이 꼭 필요한 것은 아닙니다. 설치된 호환 버전으로 가상환경을 만들 수 있습니다. `config.yaml`이 없으면 UI가 예제 기본값으로 시작하며, UI에서 설정 저장 시 새 파일을 만듭니다. 기존 `config.yaml`은 예제 파일로 덮어쓰지 마세요. 새 기본 항목은 기존 값을 건드리지 않고 자동 보충됩니다.

## 제어 UI

`UI/`에 별도 PyQt6 제어창이 있습니다. `nv_c_test` 스타일을 참고한 작은 반투명 창에서 검수 ID, 창 제목, 저장 경로 등을 설정합니다.

```powershell
python -m UI
```

또는 `UI\run_ui.bat`을 실행합니다. UI의 버튼은 **캡쳐만 | 도로후보 분석 | 분석 중지** 세 개입니다. **도로후보 분석** 버튼은 설정한 저장 경로의 현재 검수 ID 폴더에서 기존 `HD_3D Tool`과 `NLadybugSv` PNG를 대조하고, `analysis.json`, 선형 표시 이미지(`*_geometry.png`) 및 로드뷰 오버레이를 저장합니다. 원본 스크린샷과 `result.json`은 유지합니다. 사진이 없다면 먼저 **캡쳐만**을 실행해야 합니다. AI 기능 사용 시 `requirements-ai.txt` 설치가 필요합니다. 자세한 조작은 [UI 안내](docs/UI.md)를 참고하세요.

## CLI 예시

```powershell
# 이미 로드뷰가 열린 상태에서 캡처
python -m map_validator --case-id sample001 --no-ai

# 이동 없이 좌·우 후보 분석
python -m map_validator --case-id sample001

# W로 3회 전진하거나 S로 2회 후진하며 기록
python -m map_validator --case-id sample001 --move forward --steps 3
python -m map_validator --case-id sample001 --move backward --steps 2
```

결과는 `results/<case-id>/`에 캡처 PNG, 분석 오버레이, JSON 보고서로 저장됩니다. `possible`은 도로 영역 후보가 보인다는 뜻일 뿐 좌·우회전 차로의 존재를 확정하지 않습니다. 후보가 검출되지 않아도 도로가 없다는 뜻은 아닙니다. 모든 결과에 사람 검수가 필요합니다.

## 문서

- [프로젝트 컨셉](docs/PROJECT_CONCEPT.md)
- [요구사항 및 판정 기준](docs/REQUIREMENTS.md)
- [아키텍처](docs/ARCHITECTURE.md)
- [폴더 구조](docs/FOLDER_STRUCTURE.md)
- [개발 계획](docs/ROADMAP.md)
- [UI 조작 안내](docs/UI.md)
- [입력툴-로드뷰 선형 비교 기준](docs/LINE_GEOMETRY.md)

## 데이터와 이용 조건

실무 로드뷰 캡처, 교차로 식별정보, 업무 화면, 로컬 설정, 결과 파일 및 모델 캐시는 Git 추적 대상에서 제외합니다. 로드뷰 캡처·분석은 제공사의 이용 조건을 확인한 뒤 사용하세요.
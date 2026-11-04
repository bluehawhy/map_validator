# map_validator

Windows 업무 프로그램 **HD_3D Tool의 교차로 기대 정보**와 **NLadybugSv 로드뷰의 실제 현장 정보**를 수동 4단계 촬영 후 항목별로 비교하는 Python 데스크톱 도구입니다.

> **현재 UI 기능:** **진입 전 → 진입 후 좌 → 직 → 우** 네 단계에서 사용자가 직접 시점을 맞춰 촬영합니다. 해당 방향에 도로가 없어도 반드시 사진을 찍고, 프로그램은 입력툴 경로와 로드뷰 도로·건물 후보를 비교해 **일치 후보 / 불일치 의심 / 판단 보류**를 표시합니다. **차로 수·복합 화살표·유도선 개수 등 정확한 판독은 아직 현장 검증/추가 구현 대상**이며 자동 최종 판정은 하지 않습니다.

## 검수 대상과 범위

업무 프로그램의 2D 선형은 다음 색으로 구분됩니다.

| 색 | 의미 |
|---|---|
| 하늘색 | 원도로 경로(진입) |
| 파란색 | 나가는 도로 경로(진출) |
| 주황색 | 교차점 연결 경로 |

검수자가 직접 로드뷰 위치와 시점을 조정하고 진입 전·진입 후 좌/직/우를 각각 촬영합니다. **촬영 시 프로그램이 로드뷰를 이동하거나 확대/회전하지 않습니다.** 입력툴에서 예상 도로가 있는 방향에 실제 건물 등 비도로 영역만 보이는지 비교하고, 정지선·차로 수·화살표·유도선도 단계별 검수 대상으로 관리합니다.

- 포함: 4단계 수동 WGC 촬영, 버전별 PNG 보존, 도로·건물 후보 분석, **입력툴 시안색 가로 정지선 ↔ 로드뷰 실제 흰색 정지선의 PASS/FAIL/REVIEW 비교**, 색상 선형 후보, 항목별 근거·보류 결과 저장. **횡단보도는 정지선으로 취급하지 않으며**, 로드뷰 검출 threshold(기본 0.68)를 UI에서 조절 가능
- 추가 구현·검증: 차로 수·화살표·유도선 색상/개수의 정확한 자동 판독, 건물 오탐 감소, 2D↔3D 정밀 정합
- 제외: 자동 카메라 이동·촬영·Zoom 조작 및 업무 데이터 자동 수정/승인
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

또는 `UI\run_ui.bat`을 실행합니다. UI에는 **진입 전 촬영 / 진입 후 좌 촬영 / 진입 후 직 촬영 / 진입 후 우 촬영**, **촬영본 분석 / 분석 중지**가 있습니다. 네 방향 모두 사용자가 화면을 직접 맞춘 뒤 촬영하며 **도로가 없어도 사진을 남깁니다**. 사진은 `captures/<stage>/`, 이력은 `staged_capture.json`, 분석 결과는 `staged_analysis.json`과 `overlays/`에 저장됩니다. 기존 원본과 `result.json`은 보존합니다. AI 기능 사용 시 `requirements-ai.txt` 설치가 필요합니다. 자세한 내용은 [UI 안내](docs/UI.md)를 참고하세요.

## 교차로별 방향 스코어 데이터

`촬영본 분석`을 실행하면 같은 도로 SegFormer 마스크에서 총 **6개 스코어(0~1)**를 추출합니다.

| 구분 | 좌측 | 직진 | 우측 |
|---|---|---|---|
| 진입 전 | 진입 전 사진의 좌 영역 | 진입 전 사진의 중앙 영역 | 진입 전 사진의 우 영역 |
| 진입 후 | 좌회전 방향으로 찍은 사진의 **정면** | 직진 방향으로 찍은 사진의 **정면** | 우회전 방향으로 찍은 사진의 **정면** |

저장: **`<저장 경로>/road_scores.csv`**(모든 검수 ID의 최신 점수 한 행씩), **`<검수 ID>/road_scores.json`**(최신 상세 점수), **`<검수 ID>/score_history/`**(재분석 회차별 기록). 모델·ROI·촬영 버전·스코어 차이(후-전)도 보관합니다. 빠진 사진은 **빈값**으로 기록하며, 0은 실제 분석된 영역에서 도로 픽셀이 0개라는 뜻입니다.

스코어는 도로로 판독한 **화면 영역 내 픽셀 비율**이지 도로 유무의 확정 확률이나 차로 수가 아닙니다. 진입 전/후의 시점 차이를 고려하여 통계 비교용으로 사용하세요. [스코어 저장 기준](docs/INTERSECTION_REVIEW_DESIGN.md)을 참고하세요.

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
- [4단계 촬영·검수 디자인](docs/INTERSECTION_REVIEW_DESIGN.md)
- [개발 지침](docs/PROJECT_GUIDELINES.md) · [AGENTS.md](AGENTS.md)

## 데이터와 이용 조건

실무 로드뷰 캡처, 교차로 식별정보, 업무 화면, 로컬 설정, 결과 파일 및 모델 캐시는 Git 추적 대상에서 제외합니다. 로드뷰 캡처·분석은 제공사의 이용 조건을 확인한 뒤 사용하세요.
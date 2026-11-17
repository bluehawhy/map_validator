# 폴더 구조

## 현재 구조의 역할

```text
map_validator/
├── UI/                         # Windows 제어창 (PyQt6)
│   ├── __main__.py              # python -m UI 진입점
│   ├── app.py                   # UI 구성과 화면 전환
│   ├── ...                      # 위젯, 작업 스레드, UI 보조 코드
│   └── run_ui.bat               # Windows 실행 배치 파일
├── map_validator/               # 재사용 가능한 검수 엔진
│   ├── __main__.py              # python -m map_validator 진입점
│   ├── cli.py                   # 명령행 옵션과 실행 흐름
│   ├── windows.py               # 창 탐색, 입력, 캡처
│   ├── road_analysis.py         # 로드뷰 도로 영역 분할
│   ├── road_shape.py            # 로드뷰 도로 중심 경로 형상 추정
│   ├── line_geometry.py         # 입력툴 색상 선형 추출·대조 후보 계산
│   ├── saved_analysis.py        # 기존 형식 이미지 비교(호환용)
│   ├── stage_types.py           # 진입 전·좌·직·우 단계와 검수 필드
│   ├── staged_capture.py        # 단계별 사진 쌍·재촬영 버전·manifest
│   ├── input_features.py        # HD_3D Tool의 기대값 후보
│   ├── roadview_features.py     # 도로/건물 및 노면표시 후보
│   ├── stop_line.py             # 시안색 가로 정지선 / 단독 흰색 정지선 비교 근거
│   ├── road_scores.py           # 진입 전·후 여섯 방향 도로 점수와 JSON/CSV
│   ├── staged_compare.py        # 4단계 비교·근거 이미지·JSON
│   └── wgc_capture.py           # 두 창 공용 비활성 캡처
├── docs/                        # 프로젝트/개발 문서
│   ├── PROJECT_CONCEPT.md       # 목적, 사용자 흐름, 범위
│   ├── PROJECT_GUIDELINES.md    # 모든 작업 전 확인할 지침
│   ├── INTERSECTION_REVIEW_DESIGN.md # 4단계 UI·데이터 명세
│   ├── REQUIREMENTS.md          # 요구사항과 결과 해석 기준
│   ├── ARCHITECTURE.md          # 구성요소와 데이터 흐름
│   ├── FOLDER_STRUCTURE.md      # 폴더별 책임
│   ├── ROADMAP.md               # 단계별 개발 계획
│   └── UI.md                    # UI 설치와 조작 안내
├── assets/                      # 배포 가능한 비민감 정적 리소스
├── config.example.yaml          # 로컬 설정 예시
├── config.yaml                  # 개인 설정 (Git 제외)
├── results/                     # 검수별 캡처/보고서 (Git 제외)
├── requirements.txt             # 공통 의존성
├── requirements-ui.txt          # UI 의존성
├── requirements-ai.txt          # 선택 AI 의존성
├── AGENTS.md                    # AI 개발 작업용 필수 지침
└── README.md
```

실제 파일명이 추가·변경되면 이 문서도 함께 갱신한다. 위 구조에서 `...`는 저장소 내부의 구체적인 UI 모듈을 의미하며, 민감한 템플릿 이미지나 실무 캡처를 보관하는 공개 폴더가 아니다.

## 책임 분리

- **UI/**: 입력 폼, 작업 버튼, 진행 상태와 로그 표시, UI 이벤트를 엔진에 전달한다. AI 추론과 Windows 자동화 구현을 중복해서 갖지 않는다.
- **map_validator/**: GUI와 CLI가 함께 쓰는 창 제어, 이동, 캡처, 분석, 보고서 생성을 맡는다.
- **docs/**: 사용 목적, 실행 조건, 검수 기준, 설계 이유를 기록한다.
- **assets/**: 공개해도 되는 예시·기본 이미지 리소스만 둔다. 실제 업무 프로그램 캡처나 사용자별 버튼 템플릿은 제외한다.
- **results/**: 검수 ID별 원본과 분석 산출물을 로컬에 저장한다. Git에 커밋하지 않는다.
- **config.yaml**: 각 PC의 창 제목, 버튼 이미지 경로 같은 환경별 설정을 저장한다. 예시 파일만 공유한다.

## 권장 엔진 경계

현재 코드와 다음 확장 작업은 아래 역할을 유지한다.

| 책임 | 모듈 |
|---|---|
| Windows 창 찾기, 클릭, W/S 입력, 화면 캡처 | `map_validator/windows.py` |
| 도로 마스크와 좌·우 후보 표시 | `map_validator/road_analysis.py` |
| 로드뷰의 도로 중심 경로 추정 | `map_validator/road_shape.py` |
| 입력툴의 하늘색→주황색→파란색 선형 경로 추출 및 후보 대조 | `map_validator/line_geometry.py` |
| 기존 형식 이미지 비교 | `map_validator/saved_analysis.py` |
| 단계별 촬영 상태·이미지 쌍 이력 | `map_validator/stage_types.py`, `staged_capture.py` |
| 입력툴 기대값(정지선·색상 선형) | `map_validator/input_features.py` |
| 로드뷰 실제 관측(도로·건물 등) | `map_validator/roadview_features.py` |
| 진입 전 정지선 검출(시안색/흰색), 횡단보도 구분, threshold | `map_validator/stop_line.py` |
| 4단계 검수 비교/보고서 | `map_validator/staged_compare.py` |
| 진입 전 좌/직/우 + 진입 후 좌/직/우 정면 점수 계산·저장 | `map_validator/road_scores.py` |
| 두 프로그램 비활성 캡처 | `map_validator/wgc_capture.py` |
| CLI 인자와 전체 작업 실행 | `map_validator/cli.py` |
| PyQt6 사용자 인터페이스 | `UI/` |
| 보고서 형식·판정 상태 설명 | `docs/REQUIREMENTS.md` 및 엔진 보고서 코드 |

새로 구현한 4단계 수동 촬영·선형/도로/건물 후보 비교는 단계 정의, 이미지 추출, 검수 비교 모듈로 분리했다. 점수 데이터는 검수 ID별 `road_scores.json`·`score_history/`에 보존하고 모든 교차로의 최신값은 `output.directory/road_scores.csv` 한 파일에서 집계한다. 해당 CSV와 원본 스코어 이력은 로컬 업무 자료이므로 Git에서 제외한다. 차로 수·복합 화살표·유도선 개수 등의 정확한 자동 인식은 현장 표본과 명확한 입력툴 표시 기준을 바탕으로 보완한다. 향후 정확한 3D 도로 좌표 비교가 필요하면 지도 기준점·카메라 자세·위치 보정 기능을 별도 모듈로 설계한다. 실제 데이터와 결과는 `results/`, `config.yaml`, 로컬 캐시에 두고 버전 관리하지 않는다.

## 2026-11-16 추가된 항목 중심 분석 구조

```text
map_validator/
├── analysis/
│   ├── findings.py                # unknown/candidate 공통 증거값
│   ├── input_tool/               # 입력툴 기대값: 항목별 인식
│   │   ├── features.py           # 항목별 호출 조합
│   │   ├── road_geometry.py      # 기존 색상 경로 후보
│   │   ├── lane_count.py
│   │   ├── stop_line.py
│   │   ├── lane_arrows.py
│   │   ├── guidance_line.py
│   │   ├── colored_guidance.py
│   │   ├── red_marker.py         # 개별 촬영 빨간 기준점 후보
│   │   └── local_stop_line.py    # 기준점 주변 시안색 선 후보
│   └── roadview/                 # 로드뷰 관측: 항목별 인식
│       ├── features.py
│       ├── road_presence.py
│       ├── lane_count.py
│       ├── stop_line.py
│       ├── lane_arrows.py
│       ├── guidance_line.py
│       └── colored_guidance.py
├── comparison/                   # 도로별이 아닌 항목별 판정 규칙
│   ├── rules.py
│   ├── common.py
│   ├── road_presence.py
│   ├── lane_count.py
│   ├── stop_line.py
│   ├── lane_arrows.py
│   ├── guidance_line.py
│   └── colored_guidance.py
├── intersection/roads.py        # road_id / angle_deg / role / checks
└── individual_capture.py        # 개별 원본·근거·보고서·이력 저장

UI/app.py                           # 두 탭, 개별 근거 이미지 열기
UI/worker.py                        # 기존 4단계와 개별 WGC 작업
```

기존 `input_features.py` / `roadview_features.py`는 호환 진입점으로 유지하며, 이전 `stop_line.py` 등에는 기존 검출 코드가 남아있다. 더 이상 호출되지 않는 레거시를 **참조 검증 없이 삭제하지 않는다**.

자세한 데이터 구분은 [FEATURE_ANALYSIS_REFACTOR.md](FEATURE_ANALYSIS_REFACTOR.md).

## 개별 촬영 증거 확장 (2026-11-16)

```text
output.directory/
├── <검수 ID>/
│   └── captures/individual/
│       ├── input_tool_r001.png
│       ├── input_tool_r001_overlay.png    # S1…SN 번호·선·끝점
│       └── input_tool_r001_focus.png      # 탭 내 확대 미리보기
└── _unassigned_individual/               # 검수 ID가 없는 개별 촬영만
    └── Unassigned_<UTC>_<unique>/
        ├── individual_capture.json
        ├── individual_analysis.json
        ├── individual_analysis_r001.json
        └── captures/individual/
            ├── input_tool_r001.png
            ├── input_tool_r001_overlay.png
            └── input_tool_r001_focus.png
```

`UI/image_preview.py`는 PyQt6 확대 근거 미리보기를 전담한다. 개별 임시 촬영 기록은 단계별 스테이지 원본이나 정식 검수 ID 폴더를 변경하지 않는다.

## 선 그룹 공통 모듈 (2026-11-16)

`map_validator/analysis/line_grouping.py`는 개별 정지선 후보를 비롯하여 향후 차선·중앙선·유도선에 재사용할 **선 조각 기하 그룹화**를 담당한다. 현재 정지선 후보와 노란 중앙선 후보에 재사용하며, 특징별 검출은 `analysis/input_tool/local_stop_line.py`와 `analysis/input_tool/local_center_line.py`로 분리한다. 기존 원본 PNG 파일 구조는 유지하며 C 포인트 및 중앙선 그룹은 `individual_analysis*.json`의 `checks.center_line`에 추가한다.

## 흰색 차선 포인트 검출 (2026-11-17)

- `map_validator/analysis/input_tool/local_center_line.py`: 중앙선/차선 공통 HSV·Hough·기하학적 그룹화 알고리즘
- `map_validator/analysis/input_tool/local_lane_line.py`: 흰색 마스크를 선택하는 차선 후보 진입점
- `map_validator/individual_capture.py`: 개별 촬영 재분석 시 `checks.lane_line` 기록과 오버레이 생성
- `UI/app.py`: L# 후보 개수·픽셀 좌표·그룹 구성 표시

## 2026-11-17 흰색 차선 실선 우선·점선 분리 탐지

- `analysis/input_tool/local_lane_line.py`: 기존 중앙선/흰색 차선의 공통 긴 선 검출기를 이용해 실선 L 그룹을 선별하고, 수용한 실선 부분을 제외한 마스크에서 짧은 흰색 점선을 D 그룹으로 탐지한다.
- `analysis/line_grouping.py`: 실선/점선 모두 공통 기울기·동일 선상 그룹화 로직을 재사용한다.
- `individual_capture.py`: 선택한 원본 재분석 시 `checks.lane_line`과 `checks.dashed_lane_line`를 분리 기록하고 동일 오버레이에 후보 포인트를 그린다.
- `UI/app.py`: 후보 분석 텍스트에 실선 L 및 점선 D의 그룹·간격·좌표를 표시한다. 원본 PNG 보존과 개별 촬영 목록 정책은 유지한다.

## 2026-11-17 원본 PNG 기준 개별 촬영 이력 복구

- `map_validator/individual_capture_index.py`: 개별 촬영 원본 `input_tool_rNNN.png` 탐색 및 버전 인덱스(표시용 JSON과 독립).
- `map_validator/individual_capture.py`: manifest의 누락된 버전만 원본 기준으로 복구하며 복구 시간의 출처를 기록. 원본 PNG와 기존 분석 데이터를 삭제하거나 변경하지 않는다.
- `UI/individual_review_controls.py`: 사진 목록을 manifest가 아닌 인덱스의 실제 원본 PNG 기준으로 작성한다.

## 2026-11-17 색상 후보 우선 검출 및 단계별 제외 설계

- **현재 구현:** 흰색 표시를 먼저 색상 기준으로 모두 수집하고 `W1...` 개별 포인트로 표시한다. 최소 Hough 선분 8px, 연결 허용 4px, 임계 5를 사용한다. 흰색 픽셀 점유율 74%와 실선/점선 판정, 축방향 제한, 그룹화, 실선 제거 마스크는 이 원시 검출 단계에 적용하지 않는다.
- 원본 HD_3D Tool 사진에서 흰색 HSV(H 0~179, S 0~65, V 185~255) 후보를 직접 검출하며, 사람 검수 전에는 선/문자/기호/다른 오브젝트도 버리지 않는다. `W#`는 차선 수나 실제 객체 수가 아닌 Hough 원시 조각 번호다. 중복 조각과 오탐도 표시된다.
- 개별 촬영 분석 JSON의 `checks.white_marking_candidates`에 원시 후보(좌표·중점·길이·방향) 및 검출 조건·미분류 상태를 보존한다. 신규 분석에서는 기존 `checks.lane_line`(L 실선)과 `checks.dashed_lane_line`(D 점선)을 산출하지 않으며, 과거 결과 JSON을 여는 UI는 기존 포맷과 호환한다. 기존 원본 및 다른 색상(S/G 정지선, C 중앙선) 검출기는 변경하지 않는다.
- **후속 설계(아직 미구현):** A 검출 → A가 차지한 픽셀 마스크만 제외 → 남은 원본에서 B 검출 → B 마스크 제외 → C 검출 … 순서의 단계형 검수. 각 검출 단계는 입력 원본·이전 단계 제외 마스크·검출 결과·미분류 후보를 구분하며, 마스킹 전에 후보 기록을 보존한다. 어떤 오브젝트를 A/B/C에 배치할지와 우선순위는 현장 이미지 검수 후 결정한다.
- 현재 이 단계형 제외 순서는 **자동 적용하지 않는다**. 다른 오브젝트가 흰색으로 그려질 수 있어 분류 전 마스킹은 오탐·미탐 원인이 될 수 있기 때문이다. 사람이 색상 후보를 먼저 확인하고 후속 분류 기준을 정한다. Windows 실환경 테스트는 별도 요청 시 진행한다.

## 2026-11-17 노면화살표 A# 구조 검출 및 색상 JSON 공통화

- `analysis/input_tool/color_ranges.json`에서 **흰색, 노란색, 초록색**의 OpenCV HSV 범위(각각 lower·upper)를 버전 1로 정의한다. 노면화살표 보조조건인 회색 배경 범위와 형태 임계값은 별도 `road_arrow` 항목에 둔다. `color_config.py`에서 로드/검증하고 중앙선·흰색 선·화살표 검출에 공통 적용한다.
- 초기 설정(현장 보정 전): 흰색 H0~179/S0~65/V185~255, 노란색 H18~38/S125~255/V135~255, 초록색 H40~85/S40~255/V48~255, 회색 바탕 H0~179/S0~40/V65~190. 이는 이미지 기반 후보 색역이며 의미론적 확정은 아니다.
- 노면화살표 검출 순서: **회색으로 채워진 연결 영역**을 검출 → `minAreaRect`로 회전 사각형 근사 → 가장자리 얇은 링에서 **초록색 테두리** 확인 → 사각형 내부 **흰색 픽셀** 포함 확인 → 모두 통과하면 `A1...` 후보 표시. 내부 화살표 방향/종류는 아직 판별하지 않는다.
- 결과 `checks.road_arrows`에 A# 중심점·회전각·사각형 외곽 좌표·초록 테두리/회색 영역/흰색 내부 픽셀·후보 조건을 저장한다. 분석 원본은 변경하지 않고 근거 이미지에 초록 A# 테두리와 번호를 표시한다.
- 색상 후보는 먼저 원본에서 검출해 `checks.white_marking_candidates_raw`에 **제외 전 W**를 보존한다. 이어서 A 후보의 **회전 사각형 내부 흰색 픽셀만** 탐색 마스크에서 제외하고 `checks.white_marking_candidates`에 **제외 후 W**를 다시 검출한다. 원본 픽셀·다른 색상·인접 차선·회색 및 초록 영역은 지우지 않는다.
- 이는 임시 화살표 후보 기반 필터이므로 오검출 시 일부 실제 흰색 차선 후보가 빠질 수 있다. 반드시 **제외 전/후 JSON을 비교하고 A 후보를 현장에서 검수**한다. A가 확정된 데이터라는 뜻이 아니다. 다음 오브젝트 B/C 우선순위 및 실선·점선 분류는 아직 미구현이다.
- Windows 현장 검증 및 자동 테스트는 별도 요청 전 실행하지 않는다.

## 2026-11-17 Link 정방향·역방향 접미사 지원

- 교차로 선형 검수 도구의 Link 항목명에 **`Link 888_정`, `Link 443_역`**처럼 정방향·역방향 접미사가 붙는 경우를 지원한다. `_정방향`, `_역방향` 표시도 각각 `_정`, `_역`으로 정규화한다. 기존 `Link 890`처럼 방향 접미사가 없는 ID도 계속 인식한다.
- `windows.py`의 선택 항목 추출은 숫자만 읽던 이전 패턴을 변경하여 **`<숫자>_정`/`<숫자>_역`을 완전한 Link 식별자**로 사용한다. 예: `Polygon 471729310- Link 888_정`. 기존에는 숫자 바로 뒤의 밑줄이 정규식 단어 경계를 막아 빠른 선택 조회에 실패할 수 있었고, 느린 Win32/UIA 대체 경로로 이어졌다.
- `stage_types.validate_case_id`에는 임의 한글이나 폴더 경로 문자를 허용하지 않고 **검수 ID 끝의 `_정`, `_역`만 추가 허용**한다. 서로 다른 방향은 촬영 폴더·분석 파일을 별도 ID로 관리한다. 기존 방향 미표시 촬영 기록은 자동 이름 변경·병합하지 않는다.
- Windows 수동 트리 선택·마우스 클릭 감시·작업 전 최신 ID 확인 모두 공통 ID 추출기를 사용하므로, 정/역 명칭이 붙더라도 빠른 선택 노드 조회가 적용된다. 실제 업무 도구에서의 조회 속도와 정상 입력은 사용자가 현장에서 확인해야 한다. **테스트 코드 작성 및 실행은 요청하지 않아 수행하지 않았다.**

## 2026-11-17 고정 UI 상태 문구 제외 및 흰선 검출 기준 재정리

- **현재 구현(위치 고정):** HD_3D Tool 검은 도면 상단 좌측의 `Z/Zoom/Dist`, `HDL View/Input`은 문자 크기와 위치가 변하지 않는다는 현장 조건에 따라 OCR 없이 고정 사각형으로 취급한다. `color_ranges.json.ui_text_exclusion`의 `canvas_top_left` 기준 픽셀 좌표를 사용한다.
- 초기 제외 영역(원본 WGC 픽셀, 검은 도면 시작점 기준, 오른쪽·아래쪽 끝은 비포함): `zoom_distance [10,24,610,73]`, `view_input [10,89,375,139]`. 도면 범위와 정지선 분석 ROI에 맞춰 자른 뒤 **해당 사각형의 흰색 픽셀만** 분석 마스크에서 제거한다. 원본 이미지/중앙선/시안 정지선/화살표 검출은 변경하지 않는다.
- 오버레이 근거 이미지에는 제외 영역을 연한 회색으로 표시한다. 결과 JSON `checks.ui_text_exclusion`에 위치·실제 제외된 흰색 픽셀 수를 저장하고, `checks.white_marking_candidates_raw`(제외 전), `checks.white_marking_candidates_after_ui`(문자 제외 후), `checks.white_marking_candidates`(문자+화살표 제외 후)를 각각 보존한다. 기존 분석 결과 형식은 계속 읽는다.
- **현재 적용된 W 검출 기준(이번 변경에서 유지):** 흰색 HSV H0~179/S0~65/V185~255, 최소 Hough 선분 **8px**, Hough 임계값 **5**, 연결 공백 **4px**, 방향 제한 없음(가로/세로/대각선 모두), 흰색 픽셀 점유율 제한 없음. 같은 물리적 차선의 여러 조각을 아직 L/D로 자동 그룹화하지 않으며 W#는 중복 및 다른 오브젝트를 포함하는 **미분류 후보**다.
- **후속 분류 설계(아직 미구현):** 고정 UI 문구 제외 → 초록 테두리/회색 바탕/흰색 내부 노면화살표 A 후보 검출 및 흰색 마스킹 → 남은 흰색 원시 조각 W 보존 → 실선 L 및 점선 D 순차 판단 → 분류되지 않은 후보 보존. 향후 실선/점선의 연결 길이·평행선 분리·각도 기준은 현장 영상으로 별도 합의한다. 확정되지 않은 그룹을 무조건 제거하지 않는다.
- **위험 및 미검증:** 상단 고정 영역 안을 통과하는 흰색 차선도 일부 마스킹될 수 있다. 도면 시작점·캡처 해상도·상태 문구 위치가 변하면 `ui_text_exclusion.regions`를 조정해야 한다. 현장 Windows 검출과 동작 테스트는 아직 진행하지 않았다.

## 2026-11-17 초록 테두리 기준 노면화살표 전체 영역 마스킹

- 기존에는 노면화살표 A# 회전 사각형 내부 **흰색 픽셀만** W# 후보 검출에서 제외했으나, 현장 이미지에서 A1/A2의 W# 조각이 남았다. 사용자가 주변 일부 차선 누락을 허용한 기준을 반영해 **초록 테두리 검증을 통과한 회전 사각형 전체 + 경계 3px**(`color_ranges.json.road_arrow.exclusion_margin_px`)을 후속 W# 검색 마스크로 사용한다.
- 제외 마스크와 교차하는 Hough W 선분은 통째로 제외하여 공백 4px 연결에 의해 A# 영역을 가로지르는 W#가 남지 않도록 한다. 원본 PNG, 빨강 마커, 시안 정지선 S/G, 노란 중앙선 C 및 A# 검출 조건은 유지한다.
- 결과 `checks.road_arrows`에 `excluded_region_pixels`, `excluded_white_pixels`, `mask_margin_px`를 기록하고 A 후보별 `mask_bbox`와 최종 W의 `rejected_mask_overlap_segments`를 기록한다. **원본 W → 고정 UI 문자 제외 후 W → A 영역 제외 후 W** 결과 JSON은 계속 보존한다.
- A#는 확정이 아닌 후보이므로 오검출 시 일부 실제 차선이 마스킹될 수 있다. Windows 현장 실행·테스트는 별도 요청 전 수행하지 않았다.

## 2026-11-17 HDL View 실제 글자 하단 기준 분석 범위 자동 조정

- 기존 **현재 위치 Y−높이 16%** 고정 상대비율 방식은 촬영 창 크기 변화에 따라 `HDL View` 문구를 포함하거나 지나치게 많이 잘라낼 수 있으므로 **사용하지 않는다**. 변경 후 분석 상단은 **실제 두 번째 흰색 상태 글자 행(HDL View / Input) 하단 + 10px**로 결정한다.
- 방법: WGC 원본의 검은 도면 경계에서 왼쪽 상단 문자 탐색 영역을 잡고 HSV 흰색 → 문자 크기 연결 요소 → 수평 글자 행 클러스터를 구성한다. `Z/Zoom/Dist` 행과 `HDL View/Input` 행이 **두 개의 왼쪽 정렬된 글자 행**이며, 순서·행 간 거리·문자 수·행 너비·왼쪽 시작점 조건을 충족해야 두 번째 행 하단을 사용한다. OCR이나 문자열 읽기는 하지 않는다.
- 결과 위치는 `color_ranges.json.hdl_view_roi`의 탐색 너비·높이/글자 기준/여유값으로 조절할 수 있다. `stop_line.roi_rules.text_anchor`에 검출 상태, 행 후보 및 실제 이미지 좌표, 분석 시작 Y를 저장하고 앱 후보 분석 텍스트와 로그에 표시한다.
- 두 상태 행을 구분하지 못하거나 계산된 ROI가 유효하지 않을 때는 **현재 위치 기반 비율·고정 좌표 등으로 임의 대체하지 않고** S/G·C·A·W의 공유 ROI 분석을 보류한다. 단, 현재 위치 탐지 상태와 원본 PNG·촬영 이력은 그대로 남긴다. 사람이 화면을 확인해 다시 촬영하거나 위치 탐지 기준을 조정할 수 있다.
- 검은 도면 경계 변화에 맞춰 매 촬영본에서 다시 계산한다. 가로 탐색 폭 570px 이내, 세로 탐색 높이 230px 이내로 제한하고 지도 전체를 OCR하지 않는다. 빨간 도로 선형은 ROI 기준이 아니다. 하단·좌우 범위와 색상/Hough·노면화살표 검출 기준은 유지한다.
- **미검증:** 밝은 도로 요소가 상태 문자와 겹치거나 두 줄 문자 형식이 달라지면 후보 행 검출이 실패할 수 있다. Windows 현장 실행 및 자동 테스트는 별도 요청 전 수행하지 않았다.

## 2026-11-17 색상 고정 유도선 연결 집합 및 차량 기준 GUIDE ROI

- 현장 이미지의 대표 색상 **초록 RGB(0,128,0), 주황 RGB(255,128,0), 진파랑 RGB(0,0,255)**을 `map_validator/analysis/input_tool/color_ranges.json.guide_lines`에 고정 정의한다. OpenCV WGC BGR 이미지에서 RGB 순서를 변환해 픽셀을 찾으며, 채널별 허용 오차는 초깃값 24다. 시안 RGB(0,128,255)와 진파랑은 구분한다.
- 유도선은 곡선/분기가 있을 수 있으므로 직선 Hough 기울기로 합치지 않는다. **색상별 마스크 → 3×3 작은 공백 메움 → 8방향 연결 요소**로 같은 색상의 이어진 픽셀 집합을 탐색해 `U1, U2…` 검수 후보로 기록한다. 초기 최소 연결 픽셀 30, 최소 외곽 장변 25px 기준이다. 서로 다른 색상은 교차해도 하나로 병합하지 않는다. 실제 유도선이나 주행 경로의 확정은 하지 않는다.
- **차량 현재 위치의 빨간 표시점 기준 유도선 전용 ROI**를 정지선 ROI와 별도 산출한다. 좌우 반폭: 이미지 너비 34%(최소 55px). 위쪽: 현재 위치−이미지 높이 34%(최소 45px), 단 **HDL View 하단으로 정해진 정지선 ROI 위쪽보다 6px 아래**까지만 허용. 아래쪽: 현재 위치+이미지 높이 24%(최소 35px), 정지선 ROI 하단을 넘지 않음. 수치는 `guide_lines.roi` JSON에서 조정한다.
- 근거 이미지에 기존 주황 `STOP ROI`와 구분되는 **자주색 `GUIDE ROI` 2px 사각형 테두리/라벨**을 마지막 렌더링 단계에 표시한다. U 그룹의 외곽 윤곽·대표점·번호를 표시하고, `checks.guidance_lines` JSON에 ROI, RGB 색상, 연결 그룹 중심·외곽·연결 픽셀수·색상별 집계·설정을 보존한다.
- 현재 위치 마커 또는 HDL View 기준 정지선 ROI를 구하지 못한 경우에는 유도선 ROI를 억지로 추정하지 않고 분석 보류로 기록한다. 원본 WGC 사진, 정지선 S/G, 중앙선 C, 노면화살표 A, 흰색 W 검출과 기존 검수 기록은 유지한다.
- 이 기능은 **연결 집합의 1차 후보 검출**이며 색상이 같은 다른 도형, 좁은 접점 때문에 합쳐지는 경우, 끊어진 곡선이 여러 U 그룹으로 갈라지는 경우가 있을 수 있다. 사용자 현장 검수 후 색상 허용 오차·ROI·연결 커널을 조정한다. Windows 실환경 테스트와 테스트 코드는 요청받지 않아 진행하지 않았다.

## 2026-11-17 파랑 4종 RGB 분리 및 색상별 후보·검수 범위

- 파란 계열 고정 RGB를 `color_ranges.json.blue_markings` 한곳에서 관리한다. **RGB(0,0,255) 교차로 외곽선은 후보에서 제외**, **RGB(0,128,255) 유도선 U#**, **RGB(0,255,255) 정지선 S/G**, **RGB(121,171,255) 교차로 진입 전 경로선 P#**로 분리한다. 이전 유도선 검출기에서 초록·주황 곡선 및 진파랑 외곽을 U 후보로 취급하던 동작은 제거한다.
- RGB는 WGC 원본 OpenCV BGR에서 정확히 변환하며 초기 허용 오차는 **채널당 0**이다. 외곽선 RGB(0,0,255) 픽셀은 검출 마스크에서만 제외하고 원본 및 기존 PNG는 보존한다. 시안 정지선은 기존 HSV 넓은 범위 대신 설정된 RGB 색상만 사용한다.
- 파랑 U 및 연파랑 P 후보는 **8방향 연결 요소 + 3x3 작은 공백 연결**, 최소 픽셀 18·최소 외곽 장변 18px로 1차 분류한다. 곡선 형태와 다중 선들을 하나의 직선으로 오인하지 않으며 색상별로 독립 처리한다. U/P가 동일 색상 다른 오브젝트와 연결되면 오탐 가능성이 있으므로 검수 후보로만 취급한다.
- **검수 위치 영역과 후보:** `STOP ROI`(주황)은 S/G·C·A·W 공유, `GUIDE ROI`(자주)는 U 후보, `PATH ROI`(연한 파랑)는 P 후보 전용이다. U와 P ROI는 차량 현재 위치를 기준으로 별도 계산하며 **HDL View 글자 하단 이하의 유효한 도면 분석 범위**를 넘지 않는다. ROI 3종 테두리와 번호별 후보점을 근거 이미지에 마지막으로 표시한다. `review_regions` JSON에는 각 오브젝트의 검사 ROI와 후보 수를 기록한다.
- S는 Hough 선분 중점, G는 그룹 중점, C/A/W 기존 포인트, U/P는 연결 집합 대표점과 외곽 박스가 결과에 포함된다. `checks.approach_paths`와 `checks.guidance_lines`는 색상·연결·ROI·좌표·픽셀 수를 저장하며 이전 개별 촬영 JSON은 UI에서 선택적으로 읽는다.
- 현장 검증 전에는 RGB 정확값 외곽의 안티앨리어싱 픽셀 누락·교차로 외곽선과 겹친 가는 선 손실 가능성이 있다. 사람 검수 이후 허용 오차나 연결 조건을 조정해야 한다. Windows 실행 테스트·테스트 코드는 별도 요청이 없어 수행하지 않았다.

## 2026-11-17 GUIDE/STOP/PATH ROI 위치 재설정 · LINE ROI 제거

- GUIDE ROI: 빨간 현재 위치 위쪽 교차로를 탐색하되, **차량 앞쪽 가장 가까운 시안색 정지선 후보 선분 위치까지 하단을 내린다**(4px 여유). 선분이 발견되지 않으면 현재 위치를 임시 기준으로 사용하고 `stop_line_reference.status`에서 `cyan_segment_candidate`와 `vehicle_position_fallback`을 구분한다. 시안색 후보는 실제 정지선으로 자동 확정하지 않는다.
- STOP ROI: **GUIDE ROI의 상단부터 전체 높이 70% 지점**까지 상단을 올리고, 하단은 현재 위치 아래 기존 10%를 유지한다. 정지선 S/G와 화살표 A는 같은 STOP ROI를 공유한다.
- PATH ROI: 현재 위치 빨간 마커를 아래쪽 기준점으로 삼아 **도면 높이 45% 위쪽**을 탐색한다. 마커 아래로는 4px 여유만 두며 도면 경계 밖으로 확장하지 않는다.
- **LINE ROI 삭제:** 회색 사각형과 'LINE ROI' 라벨, 별도의 context_roi 결과 및 UI 안내를 제거한다. 중앙선 C와 흰선 W는 세 ROI를 포함하는 내부 직사각형 탐색 범위(`candidate_search_bounds`)에서 계속 검출하되 **네 번째 테두리를 그리지 않는다**. C/W의 `review_regions.border`는 `none`이다.
- `blue_markings.guidance_roi/stop_roi/approach_roi` 수치를 갱신했고 ROI 3종(자주/주황/연파랑)은 유지한다. 기존 WGC 원본·검수 이력 보존. Windows 실환경 및 자동 테스트는 요청받지 않아 실행하지 않았다.

## 2026-11-17 ROI 오해 정정: 모두 현재 위치 기준으로 독립 계산

- **최신 확정 기준:** GUIDE, STOP, PATH의 상단/하단은 모두 **빨간 현재 위치 표시점 `red_marker.point`**의 화면 Y좌표에서 도면 높이의 고정 비율 또는 고정 px만큼 위아래로 이동하여 산정한다. ROI끼리 좌표를 참조하거나 먼저 검출된 시안색 선분을 ROI 경계로 사용하지 않는다. 위 2026-11-17 'GUIDE/STOP/PATH ROI 위치 재설정'에 기록된 **`stop_line_reference` 및 GUIDE 높이에 의존하는 STOP 상단 계산은 폐기**한다.
- 공통 `canvas_bounds`는 영상 도면의 클리핑과 비율 크기 계산에만 사용한다. `GUIDE ROI`: 위 65%, 아래 4%, 좌우 반폭 도면 너비 18%. `STOP ROI`: 위 **45.5%**, 아래 10%, 좌우 반폭 18%. 이 45.5%는 이전 GUIDE 상방 높이 65%의 **약 70%에 해당하는 고정 크기**라는 뜻이며 실제 GUIDE ROI 좌표와 무관하다. `PATH ROI`: 위 45%, 아래 4px, 좌우 반폭 30%. 작은 도면에서 각 `min_*_px` 기준을 적용한다.
- `map_validator/analysis/input_tool/local_stop_line.py`에서 `detect_stop_line_reference`를 삭제하고 `guide_roi`, `stop_reference` 인수와 연결된 계산을 제거한다. `local_guidance_line.py`에서도 `stop_line_y`, `stop_reference` 인수를 제거한다. `individual_capture.py`는 동일한 `point`와 `canvas_bounds`를 세 검출기에 각각 전달한다. JSON의 `stop_line_reference` 최상위 필드는 새 분석 결과에서 제거하며, 검사 목적 외부 원본 PNG와 이전 분석 이력은 보존한다.
- 기존 S/G 및 A 공통 STOP ROI, U GUIDE, P PATH, C/W의 내부 후보 검출(`candidate_search_bounds`)은 유지한다. LINE ROI 테두리는 복구하지 않는다. 또한 정지선 검출의 선 길이 계산에서 이미지 크기 변수의 기존 불일치(`height,width` 미정의)를 `h,w`로 바로잡는다.
- **검증 상태:** 원격 소스·호출 관계 정적 확인만 실시. Windows 현장 실행·자동 테스트 및 테스트 코드 추가는 요청받지 않아 수행하지 않았다.

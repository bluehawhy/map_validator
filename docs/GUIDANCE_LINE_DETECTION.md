# 유도선·진입 경로선 검출 기준

> 2026-11-17 최신 기준. 사용자 현장 검수 전까지 모든 결과는 **후보**이며 실제 객체 수를 확정하지 않습니다.

## 1. 파란 계열 RGB 색상표

| RGB | 종류 | 후보 코드 | 처리 |
|---|---|---|---|
| `(0, 0, 255)` | 교차로 외곽선 | 없음 | 분석 마스크에서 제외, 원본 유지 |
| `(0, 128, 255)` | 유도선 | `U#` | 같은 색상 연결 영역 그룹 |
| `(0, 255, 255)` | 정지선 후보 | `S# / G#` | 기존 Hough 조각/그룹 검출 |
| `(121, 171, 255)` | 교차로 진입 전 경로선 | `P#` | 같은 색상 연결 영역 그룹 |

정의 위치: `map_validator/analysis/input_tool/color_ranges.json.blue_markings`. WGC는 OpenCV BGR이므로 RGB를 변환해 사용합니다. **현재 색상 허용 오차는 채널별 0**(정확히 같은 RGB). 화면 가장자리의 안티앨리어싱 픽셀은 현장 결과에 따라 추후 보정합니다. 이전 초록·주황 곡선은 유도선 후보에서 제외했습니다.

## 2. 검출 순서와 후보 표시

1. WGC 원본과 차량 현재 위치, `HDL View` 하단을 확인합니다.
2. 교차로 외곽선의 진파랑 픽셀을 **후보 검출에서만 제외**합니다. 원본 PNG와 선형은 변경하지 않습니다.
3. 시안 `RGB(0,255,255)`: `STOP ROI` 안에서 Hough 선분 `S#` 및 기하학적 그룹 `G#`를 검출합니다. 각 조각과 그룹의 중점 좌표를 보존합니다.
4. 파랑 `RGB(0,128,255)`: `GUIDE ROI` 안에서 3×3 작은 공백 메움과 8방향 연결 요소로 곡선·분기 후보 `U#`를 검출합니다.
5. 연파랑 `RGB(121,171,255)`: `PATH ROI` 안에서 같은 방식으로 `P#` 후보를 검출합니다.
6. 근거 이미지에 후보 번호·대표점·윤곽과 **3종 ROI 테두리**를 표시합니다. 동일색상 외부 도형이나 짧은 단절로 생긴 오탐·중복은 사람이 검수합니다.

연결 그룹 초기 기준: 최소 18픽셀, 긴 변 18px 이상, 3×3 close, 8방향 연결. 이 값은 검출 후보용이며 확정 판정 기준은 아닙니다.

## 3. 검수 위치 테두리

| 이미지 테두리 | 검출 대상 | 기준 |
|---|---|---|
| 주황 `STOP ROI` | 정지선 `S/G`, 중앙선 `C`, 화살표 `A`, 흰선 `W`(공유) | 차량 위치 + HDL View 글자 하단 |
| 자주 `GUIDE ROI` | 유도선 `U` | 차량 주변 좌우 34%/상단 34%/하단 24% |
| 연파랑 `PATH ROI` | 진입 전 경로선 `P` | 차량 주변 좌우 30%/상단 20%/하단 44% |

유도선·경로선 ROI는 모두 유효한 정지선 도면 ROI의 상·하단을 넘지 않습니다. 세부 수치는 `blue_markings.guidance_roi`, `blue_markings.approach_roi`에서 조정할 수 있습니다. 감지하지 못한 ROI를 임의로 생성하지 않습니다.

## 4. 결과 JSON 및 검수

- `checks.stop_line`: S/G 검출 결과 및 `roi`
- `checks.guidance_lines`: U 후보의 RGB, 대표점 `point`, `bbox`, 연결 픽셀 수, `roi`
- `checks.approach_paths`: P 후보의 RGB, 대표점, `bbox`, 연결 픽셀 수, `roi`
- `review_regions`: S/G·C·A·W·U·P별 검출 범위, 후보 수, 테두리 종류

먼저 근거 이미지를 확인하여 세 영역이 현재 차량 위치를 적절히 포함하는지 보고, 다음으로 RGB 분류의 오탐/누락과 그룹 연결 결과를 조정합니다. **Windows 실환경 검증 및 자동 테스트는 아직 수행하지 않았습니다.**

## 변경 이력

- 2026-11-17: 초록·주황·진파랑 그룹을 U로 보는 초기 실험을 폐기하고, 실제 유도선 `RGB(0,128,255)`와 진입 경로선 `RGB(121,171,255)`를 독립 분류했습니다.

- 2026-11-17 오류 수정: `local_guidance_line.py`의 진입 경로선 이름 `approach_path`와 ROI 설정 키 `approach_roi`가 일치하지 않아 `KeyError: 'approach_path_roi'`가 발생하던 문제를 수정했습니다. 유도선은 `guidance_roi`, 진입 경로선은 `approach_roi`를 명시적으로 조회합니다. 기존 r001/r002 원본 및 검출 조건은 변경하지 않습니다. Windows 실환경 분석 재실행은 미검증입니다.

## 2026-11-17 현장 피드백: GUIDE ROI 차량 위치 기준 상향 배치

- 검수 이미지에서 GUIDE ROI가 지나치게 넓고 **HDL View 글자 하단(Y)부터 아래쪽까지** 이어져 차량 앞쪽 유도선 위치를 충분히 포함하지 못했다. 검수자가 분홍색으로 표시한 형태처럼 **현재 위치 빨간 사각형을 아래쪽 기준점**으로 삼고, 도면 위쪽으로 긴 세로 ROI를 배치한다.
- GUIDE ROI는 빨간 현재 위치 `point`와 검은 도면 경계 `canvas_bounds`로 독립 계산한다. **좌우 반폭 도면 너비의 18%(최소 55px), 위쪽 도면 높이 65%(최소 45px), 아래쪽 4%(최소 16px)**이며 도면 경계에 맞춰 자른다. 현재 위치가 유효하지 않으면 임의의 영역을 만들지 않는다. 빨간 현재 위치 표시점 주변의 상단 도면까지 포함할 수 있고, **STOP ROI의 상단 및 HDL View 글자 하단으로 GUIDE ROI 상단을 제한하지 않는다.**
- `GUIDE ROI` 자주색 테두리, U# 후보·원본 RGB(0,128,255)·8연결 그룹화는 유지한다. 결과 `checks.guidance_lines.roi`와 `roi_rules.positioning=vehicle_position_to_canvas_top`, `position_point_px`, `canvas_bounds`에 계산 기준을 기록한다.
- `STOP ROI`의 S/G/C/A/W와 `PATH ROI`의 P#는 **이번 변경에서 범위·기준을 수정하지 않는다**. WGC 수동 촬영 및 기존 원본 PNG·JSON 이력은 보존한다. Windows 실환경에서 ROI 크기/유도선 포함률은 별도 현장 확인이 필요하며 테스트 코드는 추가·실행하지 않았다.

## 2026-11-17 STOP ROI 축소 및 노면화살표 검출 범위 동일화

- 빨간 차량 현재 위치 `point`와 실제 검은 도면 `canvas_bounds` 기준으로 `STOP ROI`를 작게 계산한다. 좌우 반폭 도면 너비의 **18%**(최소 55px), 위쪽 도면 높이의 **25%**(최소 45px), 아래쪽 도면 높이의 **10%**(최소 35px). `blue_markings.stop_roi`에서 조정할 수 있으며 도면 경계를 넘지 않는다.
- **정지선 S#/G#와 노면화살표 A#는 같은 `checks.stop_line.roi` 좌표를 공유**한다. 기존 `local_road_arrow_candidates(..., roi=stop_line.get("roi"))`를 유지하여 화살표가 작은 STOP ROI 밖에서 검출되지 않도록 했다. 화살표 색상·회색 사각형·초록 테두리·흰색 제외 로직은 수정하지 않았다.
- 이전 넓은 검출 영역(HDL View/Input 글자 하단+10px 상단, 좌우 이미지 너비 31%, 현재위치 아래 이미지 높이 44%)은 `checks.stop_line.context_roi`로 분리했다. **중앙선 C, 흰선 W, 진입 경로선 P**는 이 넓은 영역을 계속 사용한다. GUIDE ROI(U)는 독립적으로 위쪽 탐색을 계속한다. 텍스트 기준이 확인되지 않으면 LINE 및 P 분석만 보류하고, STOP·A는 빨간 차량 위치가 검출되면 수행한다.
- 근거 이미지에 작은 주황색 `STOP ROI`(S/G·A)와 옅은 회색 `LINE ROI`(C/W/P) 테두리를 각각 표시한다. `review_regions`도 실제 분석 범위와 일치시킨다. 기존 WGC 원본·촬영 이력은 보존하고 새 분석 결과만 갱신한다.
- **현장 미검증:** 차량 위치가 교차로에 가까운 정도에 따라 STOP/A 후보가 작은 범위에서 누락될 수 있다. Windows 현장 분석과 자동 테스트는 요청받지 않아 실행하지 않았다.

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

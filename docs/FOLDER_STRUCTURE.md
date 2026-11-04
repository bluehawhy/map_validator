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
│   ├── saved_analysis.py        # 저장된 두 화면 대조와 분석 보고서
│   └── wgc_capture.py           # 두 창 공용 비활성 캡처
├── docs/                        # 프로젝트/개발 문서
│   ├── PROJECT_CONCEPT.md       # 목적, 사용자 흐름, 범위
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
| 저장된 화면 분석 및 보고서 | `map_validator/saved_analysis.py` |
| 두 프로그램 비활성 캡처 | `map_validator/wgc_capture.py` |
| CLI 인자와 전체 작업 실행 | `map_validator/cli.py` |
| PyQt6 사용자 인터페이스 | `UI/` |
| 보고서 형식·판정 상태 설명 | `docs/REQUIREMENTS.md` 및 엔진 보고서 코드 |

2D 경로 색상 인식과 로드뷰의 방향·곡률 후보 대조는 이미 입력 화면 분석·경로 추정·사진 보고서 모듈로 분리했다. 향후 정확한 3D 도로 좌표 비교가 필요하면 지도 기준점·카메라 자세·위치 보정 기능을 별도 모듈로 설계한다. 실제 데이터와 결과는 `results/`, `config.yaml`, 로컬 캐시에 두고 버전 관리하지 않는다.
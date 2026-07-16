# AeroInspect 구현 계획

항공기 축소 모형의 기준(정상) 사진과 점검 사진을 비교해 **부품 누락/이상을 탐지**하고, 가상 부품 카탈로그(mini-IPC)에서 근거를 찾아, 결정론적 규칙으로 검증한 뒤, **한국어 형상 점검 보고서(.docx)** 를 자동 생성하는 멀티에이전트 데모.

- LLM: **Google Gemini 전용** (`google-genai` SDK). 에이전트 프레임워크 금지 — 순수 Python 오케스트레이션.
- 구조화 출력: `response_mime_type="application/json"` + `response_schema=<Pydantic>` 강제.
- Vertex AI 전환: 환경변수만으로 가능 (`GOOGLE_GENAI_USE_VERTEXAI=true` 등), 클라이언트 생성은 `core/config.py` 단일 지점.

## 구현 단계

1. **core/schemas.py + core/config.py**
   - Pydantic 모델 전부: `Discrepancy`, `PartRecord`, `RefDoc`, `ValidationResult`, 보고서 서술 스키마
   - Gemini 클라이언트 팩토리(Developer API ↔ Vertex 자동 전환), 모델명 관리(`VISION_MODEL=gemini-3.1-pro` → 미가용 시 `gemini-3.5-flash` 폴백), 부품 체크리스트, confidence 임계값

2. **data/parts_catalog/ 가상 카탈로그 6개 + 체크리스트 추출**
   - 총칙 1 + 부위별 5 (미부 / 주익·파일런 / 랜딩기어 / 동체·캐노피 / 센서·프로브)
   - 부품 15~25개: 가상 P/N, 한/영 명칭, 좌/우 구분(별도 P/N), flight_critical, 장착 절차 5~8단계(가상 토크), 누락 시 조치, 가상 SB 번호
   - 카탈로그 부품명과 동일 문자열로 `config.py` 체크리스트 구성

3. **에이전트 4개** (vision → grounding → validator → reporter)
   - `VisionAgent`: 멀티모달 1회 호출로 기준/점검 비교, 체크리스트 기법, 좌/우 항공기 기준 통일, 차이 없으면 빈 배열
   - `GroundingAgent`: 1차 Gemini File Search(인용 메타데이터 필수) → 2차 롱컨텍스트 폴백(`via_fallback` 표시), 환각 방지 규칙
   - `Validator`: **LLM 미사용** 순수 규칙 엔진 — REVIEW_REQUIRED / ESCALATED / UNKNOWN_COMPONENT / SIDE_MISMATCH / UNGROUNDED
   - `ReportAgent`: Gemini 한국어 서술 생성 + `python-docx` 조립(기준·점검 사진 나란히, Pillow bbox 오버레이, 면책 문구)

4. **core/orchestrator.py**
   - `run(baseline_images, inspection_images, progress_callback)` — 단계별 이벤트 발행
   - Vision → 항목별 Grounding(`client.aio` asyncio 병렬) → Validator → Report
   - 단계별 원본 산출물 `runs/<timestamp>/` 저장

5. **app.py (Streamlit 단일 페이지)**
   - 기준 이미지 사전 등록(session_state), `st.camera_input` + 다중 업로더
   - 에이전트별 4개 카드 실시간 채움(bbox 오버레이, 인용, 플래그 색상, .docx 다운로드)
   - 사이드바: 모델 선택, confidence 슬라이더, 점검자 이름

6. **scripts/setup_file_search.py + tests/test_e2e.py + README.md**
   - File Search 스토어 생성/업로드 멱등 스크립트, 스토어 ID `.env` 기록
   - Gemini mock 기반 E2E 스모크 테스트(Vision→Report 전체 파이프라인)
   - README: 설치(uv), .env, File Search 셋업, 촬영 가이드, 데모 리허설 체크리스트

## 품질 기준

- 구조화 출력 파싱 실패 시 1회 재시도 → 재실패 시 로그 + 실행 중단
- 모든 호출 타임아웃 + 지수 백오프 1회 + 토큰 사용량 `logs/*.jsonl` 로깅
- 전 코드 타입힌트 + docstring
- 감항성 판단은 LLM 단독 출력으로 확정하지 않음(Validator 결정론 규칙)

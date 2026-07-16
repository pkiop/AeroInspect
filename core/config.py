"""AeroInspect 전역 설정 — Gemini 클라이언트 생성 단일 지점.

- 클라이언트 생성은 반드시 이 모듈의 :func:`get_client` 만 사용한다.
- 기본 백엔드는 Gemini Developer API(``GEMINI_API_KEY``)이며,
  환경변수만으로 Vertex AI 전환이 가능하다
  (``GOOGLE_GENAI_USE_VERTEXAI=true`` + ``GOOGLE_CLOUD_PROJECT`` +
  ``GOOGLE_CLOUD_LOCATION``). ``genai.Client()`` 는 해당 환경변수를
  자동 인식하므로 코드 분기가 필요 없다.
- API 키 등 비밀값은 ``.env`` 로만 관리하며 로그/코드에 출력하지 않는다.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from google import genai

logger = logging.getLogger("aeroinspect.config")

# 프로젝트 루트 기준 경로
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = PROJECT_ROOT / "data" / "parts_catalog"
RUNS_DIR = PROJECT_ROOT / "runs"
LOGS_DIR = PROJECT_ROOT / "logs"

load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# 모델 설정 (하드코딩 금지 — 환경변수로 재정의 가능)
# ---------------------------------------------------------------------------

VISION_MODEL: str = os.getenv("AEROINSPECT_VISION_MODEL", "gemini-3.1-pro")
VISION_FALLBACK_MODEL: str = os.getenv(
    "AEROINSPECT_VISION_FALLBACK_MODEL", "gemini-3.5-flash"
)
GROUNDING_MODEL: str = os.getenv("AEROINSPECT_GROUNDING_MODEL", "gemini-3.5-flash")
REPORT_MODEL: str = os.getenv("AEROINSPECT_REPORT_MODEL", "gemini-3.5-flash")

#: confidence 임계값 기본값 (UI 슬라이더로 조절 가능)
CONFIDENCE_THRESHOLD: float = float(os.getenv("AEROINSPECT_CONFIDENCE_THRESHOLD", "0.6"))

#: File Search 스토어 이름 (scripts/setup_file_search.py가 .env에 기록)
FILE_SEARCH_STORE_NAME: str | None = os.getenv("AEROINSPECT_FILE_SEARCH_STORE") or None

#: Gemini 호출 타임아웃(ms) — google-genai http_options.timeout 단위
REQUEST_TIMEOUT_MS: int = int(os.getenv("AEROINSPECT_REQUEST_TIMEOUT_MS", "120000"))

#: UI 모델 선택 기본 후보 (환경변수 AEROINSPECT_MODEL_OPTIONS로 재정의 가능, 쉼표 구분)
MODEL_OPTIONS: tuple[str, ...] = tuple(
    m.strip()
    for m in os.getenv(
        "AEROINSPECT_MODEL_OPTIONS",
        "gemini-3.1-pro,gemini-3.1-pro-preview,gemini-3.5-flash,gemini-2.5-flash",
    ).split(",")
    if m.strip()
)


def model_options() -> list[str]:
    """UI 모델 선택 옵션 — 설정된 모델을 항상 포함한다 (중복 제거, 순서 유지).

    .env로 지정한 모델(VISION_MODEL 등)이 기본 후보 목록에 없어도
    선택 가능해야 하므로 목록 앞쪽에 합류시킨다.
    """
    candidates = [VISION_MODEL, GROUNDING_MODEL, REPORT_MODEL, VISION_FALLBACK_MODEL]
    candidates.extend(MODEL_OPTIONS)
    seen: set[str] = set()
    options: list[str] = []
    for name in candidates:
        if name and name not in seen:
            seen.add(name)
            options.append(name)
    return options


@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    """프로세스 전역 Gemini 클라이언트 (단일 생성 지점).

    ``GOOGLE_GENAI_USE_VERTEXAI=true`` 면 Vertex AI 백엔드,
    아니면 ``GEMINI_API_KEY`` 기반 Developer API 백엔드로 동작한다.
    """
    return genai.Client()


def list_available_models() -> set[str] | None:
    """``client.models.list()`` 로 가용 모델 ID 집합을 조회한다.

    조회 실패(네트워크/키 미설정 등) 시 None을 반환한다 — 치명적이지 않음.
    """
    try:
        return {
            m.name.removeprefix("models/")
            for m in get_client().models.list()
            if m.name
        }
    except Exception as exc:  # noqa: BLE001 — 가용성 확인 실패는 치명적이지 않음
        logger.warning("모델 목록 조회 실패: %s", exc)
        return None


def resolve_models(available: set[str] | None = None) -> dict[str, str]:
    """앱 시작 시 모델 가용성을 확인하고, 미가용 시 폴백한다.

    Args:
        available: 이미 조회해 둔 가용 모델 집합 (None이면 직접 조회).

    반환: ``{"vision": ..., "grounding": ..., "report": ...}``
    ``client.models.list()`` 실패(네트워크 등) 시에는 설정값을 그대로
    신뢰하고 경고만 남긴다.
    """
    vision, grounding, report = VISION_MODEL, GROUNDING_MODEL, REPORT_MODEL
    if available is None:
        available = list_available_models()
    if available is None:
        logger.warning("가용성 확인 불가 — 설정된 모델명을 그대로 사용")
        return {"vision": vision, "grounding": grounding, "report": report}

    def _pick(name: str, fallback: str, role: str) -> str:
        if name in available:
            return name
        if fallback in available:
            logger.warning("%s 모델 '%s' 미가용 — '%s' 로 폴백", role, name, fallback)
            return fallback
        logger.warning(
            "%s 모델 '%s' 및 폴백 '%s' 모두 목록에 없음 — 설정값 유지", role, name, fallback
        )
        return name

    return {
        "vision": _pick(vision, VISION_FALLBACK_MODEL, "Vision"),
        "grounding": _pick(grounding, VISION_FALLBACK_MODEL, "Grounding"),
        "report": _pick(report, VISION_FALLBACK_MODEL, "Report"),
    }


# ---------------------------------------------------------------------------
# 부품 레지스트리 / 체크리스트
# ---------------------------------------------------------------------------
# 카탈로그(data/parts_catalog/*.md)의 부품명·P/N과 **동일 문자열**로 유지한다.
# tests/test_e2e.py 가 카탈로그 ↔ 레지스트리 일치를 검증한다.


@dataclass(frozen=True)
class PartSpec:
    """가상 부품 카탈로그 등재 항목의 정규 레코드."""

    part_number: str
    name_ko: str
    name_en: str
    side: str  # "left" | "right" | "center"
    flight_critical: bool
    category: str  # 카탈로그 파일 구분용


PARTS_REGISTRY: tuple[PartSpec, ...] = (
    # --- 미부 (수직/수평꼬리날개) ---
    PartSpec("ACFT-VTS-R-001", "우측 수직꼬리날개", "Right Vertical Stabilizer", "right", True, "tail"),
    PartSpec("ACFT-VTS-L-001", "좌측 수직꼬리날개", "Left Vertical Stabilizer", "left", True, "tail"),
    PartSpec("ACFT-HTS-R-001", "우측 수평꼬리날개", "Right Horizontal Stabilizer", "right", True, "tail"),
    PartSpec("ACFT-HTS-L-001", "좌측 수평꼬리날개", "Left Horizontal Stabilizer", "left", True, "tail"),
    # --- 주익 / 파일런 / 장착물 ---
    PartSpec("ACFT-WNG-R-001", "우측 주익", "Right Main Wing", "right", True, "wing"),
    PartSpec("ACFT-WNG-L-001", "좌측 주익", "Left Main Wing", "left", True, "wing"),
    PartSpec("ACFT-PYL-R-001", "우측 익하 파일런", "Right Underwing Pylon", "right", False, "wing"),
    PartSpec("ACFT-PYL-L-001", "좌측 익하 파일런", "Left Underwing Pylon", "left", False, "wing"),
    PartSpec("ACFT-MSL-R-001", "우측 훈련용 미사일", "Right Training Missile", "right", False, "wing"),
    PartSpec("ACFT-MSL-L-001", "좌측 훈련용 미사일", "Left Training Missile", "left", False, "wing"),
    # --- 랜딩기어 ---
    PartSpec("ACFT-NLG-C-001", "전방 랜딩기어", "Nose Landing Gear", "center", True, "gear"),
    PartSpec("ACFT-MLG-R-001", "우측 주 랜딩기어", "Right Main Landing Gear", "right", True, "gear"),
    PartSpec("ACFT-MLG-L-001", "좌측 주 랜딩기어", "Left Main Landing Gear", "left", True, "gear"),
    PartSpec("ACFT-NGD-C-001", "전방 랜딩기어 도어", "Nose Gear Door", "center", False, "gear"),
    # --- 동체 / 캐노피 ---
    PartSpec("ACFT-CNP-C-001", "캐노피", "Canopy", "center", True, "fuselage"),
    PartSpec("ACFT-APN-C-001", "후방 동체 점검 패널", "Aft Fuselage Access Panel", "center", False, "fuselage"),
    PartSpec("ACFT-EFT-C-001", "동체 중앙 외부 연료탱크", "Centerline External Fuel Tank", "center", False, "fuselage"),
    PartSpec("ACFT-RDM-C-001", "노즈콘(레이돔)", "Nose Cone (Radome)", "center", True, "fuselage"),
    # --- 센서 / 프로브 ---
    PartSpec("ACFT-PIT-C-001", "피토 프로브", "Pitot Probe", "center", True, "sensor"),
    PartSpec("ACFT-AOA-R-001", "우측 받음각 센서", "Right AOA Vane", "right", True, "sensor"),
    PartSpec("ACFT-AOA-L-001", "좌측 받음각 센서", "Left AOA Vane", "left", True, "sensor"),
    PartSpec("ACFT-ANT-C-001", "VHF 블레이드 안테나", "VHF Blade Antenna", "center", False, "sensor"),
)

#: VisionAgent 프롬프트에 제공하는 부품 체크리스트 (카탈로그 명칭과 동일 문자열)
PART_CHECKLIST: tuple[str, ...] = tuple(p.name_ko for p in PARTS_REGISTRY)


def find_part_by_name(name_ko: str) -> PartSpec | None:
    """한국어 부품명으로 레지스트리에서 정규 레코드를 찾는다."""
    for part in PARTS_REGISTRY:
        if part.name_ko == name_ko:
            return part
    return None

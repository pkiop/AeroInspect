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
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from google import genai

logger = logging.getLogger("aeroinspect.config")

# 프로젝트 루트 기준 경로
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = PROJECT_ROOT / "data" / "parts_catalog"
RUNS_DIR = PROJECT_ROOT / "runs"
REPORTS_DIR = PROJECT_ROOT / "reports"
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


@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    """프로세스 전역 Gemini 클라이언트 (단일 생성 지점).

    ``GOOGLE_GENAI_USE_VERTEXAI=true`` 면 Vertex AI 백엔드,
    아니면 ``GEMINI_API_KEY`` 기반 Developer API 백엔드로 동작한다.
    """
    return genai.Client()


def resolve_models() -> dict[str, str]:
    """앱 시작 시 모델 가용성을 확인하고, 미가용 시 폴백한다.

    반환: ``{"vision": ..., "grounding": ..., "report": ...}``
    ``client.models.list()`` 실패(네트워크 등) 시에는 설정값을 그대로
    신뢰하고 경고만 남긴다.
    """
    vision, grounding, report = VISION_MODEL, GROUNDING_MODEL, REPORT_MODEL
    try:
        available = {
            m.name.removeprefix("models/")
            for m in get_client().models.list()
            if m.name
        }
    except Exception as exc:  # noqa: BLE001 — 가용성 확인 실패는 치명적이지 않음
        logger.warning("모델 목록 조회 실패 — 설정된 모델명을 그대로 사용: %s", exc)
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

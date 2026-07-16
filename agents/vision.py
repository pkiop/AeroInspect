"""VisionAgent — 기준/점검 이미지 멀티모달 비교 판독.

기준(정상 상태) 이미지 1~N장과 점검 이미지 1~M장을 Gemini 멀티모달 호출
**한 번**에 모두 넣고, 부품 체크리스트 기반으로 구성 차이(부품 누락·오장착·
이물질 등)만 탐지한다. 촬영 조건(각도/조명/그림자/배경) 차이는 이상으로
판단하지 않도록 시스템 프롬프트에서 강제한다.

출력은 :class:`core.schemas.Discrepancy` 목록이며, ``discrepancy_id`` 는
LLM이 아닌 이 에이전트가 파싱 후 ``D-001`` 형식으로 순서대로 부여한다.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from PIL import Image

from core import llm
from core.config import PART_CHECKLIST
from core.schemas import Discrepancy

logger = logging.getLogger("aeroinspect.vision")

#: PNG 매직넘버 (RFC 2083)
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
#: JPEG SOI 마커
_JPEG_MAGIC = b"\xff\xd8\xff"

#: 전송 전 이미지 축소 기준 — 긴 변 최대 픽셀 (Gemini 요청 20MB 한도 대비)
_MAX_IMAGE_SIDE = 1536
#: 재인코딩 JPEG 품질
_JPEG_QUALITY = 85

#: 시스템 프롬프트 — 오탐 억제 규칙을 포함한 판독 지침
_SYSTEM_INSTRUCTION = """\
당신은 항공기 축소 모형의 형상 비교 점검을 수행하는 항공 정비 검사관이다.
기준(정상 상태) 이미지와 점검 이미지를 비교하여 기체 '구성'의 차이만 판독한다.

반드시 다음 규칙을 지켜라.

1. 촬영 각도, 조명, 그림자, 배경, 반사, 색감, 화질의 차이는 절대 이상으로
   판단하지 말 것. 오직 구조물(부품)의 존재/부재/위치/자세 차이만 비교한다.
2. 좌/우 판정(aircraft_side)은 항공기 기준으로 통일한다. 즉, 조종사가 조종석에
   앉아 기수(앞)를 바라보는 방향을 기준으로 좌/우를 정한다. 이미지 프레임상의
   위치(화면에서 왼쪽/오른쪽 등)는 image_position_desc 필드에만 서술하고,
   두 기준을 한 문장 안에 섞어 쓰지 말 것.
3. 차이가 있는 경우에만 보고하라. 기준 이미지와 점검 이미지의 구성이 동일하면
   빈 배열을 반환할 것. 차이가 존재한다고 가정하거나 억지로 찾아내지 말 것.
4. component_name_ko는 가능한 한 제공된 부품 체크리스트의 명칭과 동일한
   문자열을 그대로 사용할 것.
5. bbox는 [x0, y0, x1, y1] 형식이며 각 값은 이미지 폭/높이에 대해 0~1로
   정규화한다. bbox_inspection은 점검 이미지 기준, bbox_baseline은 기준 이미지
   기준 좌표다. 이미지가 여러 장 입력된 경우, 차이가 가장 뚜렷하게 관찰되는
   이미지를 기준으로 좌표를 산출하고, 그 이미지가 목록에서 몇 번째인지(0부터)
   inspection_image_index / baseline_image_index에 기록할 것.
"""


def _prepare_image(data: bytes) -> bytes:
    """전송 전 이미지를 축소·재인코딩한다.

    고해상도 휴대폰 사진 여러 장이 인라인 전송 한도(20MB)를 넘지 않도록,
    긴 변이 ``_MAX_IMAGE_SIDE`` 를 초과하면 비율을 유지해 축소하고 JPEG로
    재인코딩한다. 디코딩 실패 시(지원 외 포맷 등) 원본을 그대로 반환한다.
    """
    try:
        image = Image.open(io.BytesIO(data))
        if max(image.size) <= _MAX_IMAGE_SIDE and len(data) < 2_000_000:
            return data
        image.thumbnail((_MAX_IMAGE_SIDE, _MAX_IMAGE_SIDE))
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=_JPEG_QUALITY)
        resized = buf.getvalue()
        logger.info(
            "이미지 축소: %.1fMB → %.1fMB", len(data) / 1e6, len(resized) / 1e6
        )
        return resized
    except Exception:  # noqa: BLE001 — 축소 실패는 원본 전송으로 폴백
        logger.warning("이미지 축소 실패 — 원본 전송", exc_info=True)
        return data


def _detect_mime(data: bytes) -> str:
    """이미지 bytes 앞부분 매직넘버로 MIME 타입을 판별한다.

    PNG/JPEG만 구분하며, 판별 불가 시 기본값 ``image/jpeg`` 를 반환한다.

    Args:
        data: 이미지 원본 bytes.

    Returns:
        ``"image/png"`` 또는 ``"image/jpeg"``.
    """
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    return "image/jpeg"


def _checklist_text() -> str:
    """부품 체크리스트를 번호 목록 텍스트로 렌더링한다."""
    return "\n".join(f"{i}. {name}" for i, name in enumerate(PART_CHECKLIST, start=1))


class VisionAgent:
    """기준/점검 이미지 비교 판독 에이전트 (Gemini 멀티모달, 단일 호출)."""

    def __init__(self, model: str) -> None:
        """VisionAgent를 생성한다.

        Args:
            model: 사용할 Gemini 모델명 (예: config.resolve_models()["vision"]).
        """
        self.model = model

    def analyze(
        self,
        baseline_images: list[bytes],
        inspection_images: list[bytes],
    ) -> list[Discrepancy]:
        """기준 이미지와 점검 이미지를 비교하여 구성 차이 목록을 반환한다.

        모든 이미지를 단일 멀티모달 호출에 넣고, 체크리스트 항목별로
        존재 여부를 대조시킨 뒤 상태가 다른 항목만 보고받는다.
        파싱된 결과에는 ``discrepancy_id`` 를 ``D-001`` 부터 순서대로 부여한다.

        Args:
            baseline_images: 기준(정상 상태) 이미지 bytes 목록 (1장 이상).
            inspection_images: 점검 대상 이미지 bytes 목록 (1장 이상).

        Returns:
            탐지된 :class:`Discrepancy` 목록. 차이가 없으면 빈 리스트.

        Raises:
            ValueError: 기준 또는 점검 이미지가 비어 있는 경우.
            core.llm.StructuredCallError: 구조화 출력 파싱이 최종 실패한 경우.
        """
        if not baseline_images:
            raise ValueError("기준 이미지가 최소 1장 필요합니다.")
        if not inspection_images:
            raise ValueError("점검 이미지가 최소 1장 필요합니다.")

        contents = self._build_contents(baseline_images, inspection_images)

        raw: Any = llm.generate_structured(
            agent="vision",
            model=self.model,
            contents=contents,
            response_schema=list[Discrepancy],
            system_instruction=_SYSTEM_INSTRUCTION,
        )

        discrepancies = [
            item if isinstance(item, Discrepancy) else Discrepancy.model_validate(item)
            for item in (raw or [])
        ]
        for index, disc in enumerate(discrepancies, start=1):
            disc.discrepancy_id = f"D-{index:03d}"

        logger.info("VisionAgent 판독 완료 — 차이 %d건 탐지", len(discrepancies))
        return discrepancies

    def _build_contents(
        self,
        baseline_images: list[bytes],
        inspection_images: list[bytes],
    ) -> list[Any]:
        """멀티모달 contents 시퀀스를 조립한다.

        구성: 기준 이미지 안내 텍스트 → 기준 이미지 Part들 →
        점검 이미지 안내 텍스트 → 점검 이미지 Part들 → 지시 텍스트(체크리스트 포함).
        """
        instruction = (
            "아래 부품 체크리스트의 각 항목에 대해, 해당 부품이 기준 이미지와 "
            "점검 이미지 각각에 존재하는지 항목별로 하나씩 확인하라. "
            "그 후 기준 이미지와 점검 이미지에서 상태(존재/부재/위치/자세)가 "
            "다른 항목만 보고하라. 체크리스트에 없는 이물질이나 손상도 실제로 "
            "관찰되는 경우에만 보고하라. 차이가 없으면 빈 배열을 반환하라.\n\n"
            "부품 체크리스트:\n"
            f"{_checklist_text()}"
        )

        prepared_baseline = [_prepare_image(img) for img in baseline_images]
        prepared_inspection = [_prepare_image(img) for img in inspection_images]
        contents: list[Any] = [
            f"다음은 기준(정상 상태) 이미지 {len(prepared_baseline)}장:",
            *(
                llm.image_part(img, mime_type=_detect_mime(img))
                for img in prepared_baseline
            ),
            f"다음은 점검 이미지 {len(prepared_inspection)}장:",
            *(
                llm.image_part(img, mime_type=_detect_mime(img))
                for img in prepared_inspection
            ),
            instruction,
        ]
        return contents

"""Validator — 순수 Python 결정론 규칙 엔진 (LLM 미사용).

설계 원칙: **감항성 관련 판단은 LLM 단독 출력으로 확정하지 않는다.**
VisionAgent/GroundingAgent의 LLM 출력은 반드시 이 모듈의 결정론적
규칙 검증을 거친 뒤에만 보고서·UI에 반영된다.

규칙 평가 순서 (validate 참조):
    1. SCHEMA_INVALID   — Pydantic 재검증 실패 (즉시 passed=False 반환)
    2. REVIEW_REQUIRED  — confidence 임계값 미달
    3. ESCALATED        — 비행 필수 부품 누락 → critical / ground_aircraft 강제 상향
    4. UNKNOWN_COMPONENT— 카탈로그 미등재 부품 → engineering_review
    5. SIDE_MISMATCH    — 항공기 좌/우 ↔ 카탈로그 좌/우 불일치
    6. UNGROUNDED       — 카탈로그 근거 문서 없음

문서화된 부수효과: 규칙 3(ESCALATED) 적용 시 전달받은 ``discrepancy``
객체의 ``severity`` 를 in-place로 ``"critical"`` 로 상향한다.
``record`` 는 절대 직접 수정하지 않으며, 조정이 필요한 경우
deep copy 본(``adjusted_record``)에만 반영한다.

이 모듈은 Gemini/네트워크 의존이 전혀 없어 단독 단위 테스트가 가능하다.
"""

from __future__ import annotations

from typing import Optional

from core.config import CONFIDENCE_THRESHOLD
from core.schemas import Discrepancy, PartRecord, ValidationResult

#: 플래그 → 한국어 설명 (UI/보고서 공용)
FLAG_DESCRIPTIONS: dict[str, str] = {
    "SCHEMA_INVALID": "스키마 재검증 실패 — 필수 필드 누락 또는 타입 오류로 결과를 신뢰할 수 없음",
    "REVIEW_REQUIRED": "탐지 신뢰도가 임계값 미만 — 육안 재검 필요",
    "ESCALATED": "비행 필수 부품 누락 — 심각도를 critical로, 조치를 ground_aircraft로 강제 상향",
    "UNKNOWN_COMPONENT": "부품 카탈로그에서 확인되지 않은 구성품 — 엔지니어링 검토 필요",
    "SIDE_MISMATCH": "항공기 기준 좌/우와 카탈로그 등재 좌/우가 불일치 — 좌/우 혼동 가능성",
    "UNGROUNDED": "카탈로그 근거 문서 미확정 — 보고서에 '근거 미확정' 표시",
}


class Validator:
    """LLM 출력에 대한 결정론적 사후 검증기.

    Args:
        confidence_threshold: 이 값 미만의 confidence는 육안 재검
            대상(``REVIEW_REQUIRED``)으로 플래그한다.
    """

    def __init__(self, confidence_threshold: float = CONFIDENCE_THRESHOLD) -> None:
        self.confidence_threshold: float = confidence_threshold

    def validate(self, discrepancy: Discrepancy, record: PartRecord) -> ValidationResult:
        """차이 1건과 카탈로그 레코드를 규칙 기반으로 검증한다.

        모듈 docstring의 규칙 1~6을 순서대로 평가한다.

        부수효과(문서화): 규칙 3(ESCALATED) 해당 시 ``discrepancy.severity``
        를 in-place로 ``"critical"`` 로 상향한다. ``record`` 는 수정하지
        않고, 조정 사항은 deep copy 본(``adjusted_record``)에만 반영한다.

        Args:
            discrepancy: VisionAgent가 탐지한 구성 차이.
            record: GroundingAgent가 조회한 부품 레코드.

        Returns:
            ``ValidationResult`` — ``passed`` 는 플래그가 없을 때만 True,
            ``adjusted_record`` 는 레코드 조정이 하나라도 발생했을 때만
            PartRecord 사본을 담는다(아니면 None).
        """
        flags: list[str] = []
        adjusted: Optional[PartRecord] = None

        def _ensure_adjusted() -> PartRecord:
            """레코드 조정이 처음 필요해질 때 deep copy를 생성한다."""
            nonlocal adjusted
            if adjusted is None:
                adjusted = record.model_copy(deep=True)
            return adjusted

        # --- 규칙 1: Pydantic 재검증 (필수 필드·타입) --------------------
        # model_construct 등으로 검증을 우회했거나 필드가 사후 변조된
        # 경우를 잡는다. 실패 시 예외를 전파하지 않고 즉시 반환.
        try:
            Discrepancy.model_validate(discrepancy.model_dump())
            PartRecord.model_validate(record.model_dump())
        except Exception:  # noqa: BLE001 — ValidationError 외 변조 케이스 포함
            return ValidationResult(passed=False, flags=["SCHEMA_INVALID"])

        # --- 규칙 2: confidence 임계값 ------------------------------------
        if discrepancy.confidence < self.confidence_threshold:
            flags.append("REVIEW_REQUIRED")

        # --- 규칙 3: 비행 필수 부품 누락 → 강제 상향 ----------------------
        if discrepancy.discrepancy_type == "missing_part" and record.flight_critical:
            escalated = False
            if discrepancy.severity != "critical":
                discrepancy.severity = "critical"  # 문서화된 in-place 부수효과
                escalated = True
            if record.disposition_if_missing != "ground_aircraft":
                _ensure_adjusted().disposition_if_missing = "ground_aircraft"
                escalated = True
            if escalated:
                flags.append("ESCALATED")

        # --- 규칙 4: 카탈로그 미등재 부품 ---------------------------------
        if record.found is False:
            flags.append("UNKNOWN_COMPONENT")
            current = adjusted if adjusted is not None else record
            # 규칙 3이 상향한 ground_aircraft(더 보수적 조치)는 하향하지 않는다.
            if current.disposition_if_missing not in (
                "engineering_review",
                "ground_aircraft",
            ):
                _ensure_adjusted().disposition_if_missing = "engineering_review"

        # --- 규칙 5: 좌/우 혼동 결정론 체크 -------------------------------
        lateral = ("left", "right")
        if (
            discrepancy.aircraft_side in lateral
            and record.catalog_side in lateral
            and discrepancy.aircraft_side != record.catalog_side
        ):
            flags.append("SIDE_MISMATCH")

        # --- 규칙 6: 근거 문서 없음 ---------------------------------------
        if not record.reference_docs:
            flags.append("UNGROUNDED")

        return ValidationResult(passed=not flags, flags=flags, adjusted_record=adjusted)

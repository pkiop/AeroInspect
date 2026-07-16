"""ReportAgent — 한국어 형상 점검 서술 생성.

파이프라인 산출물(:class:`~core.schemas.InspectionItem` 목록)을 받아
Gemini 구조화 출력(:class:`~core.schemas.ReportNarrative`)으로
점검 개요·종합 의견 서술을 생성한다
(이미지 없이 항목 요약 텍스트만 컨텍스트로 사용).

유형·심각도·조치·좌우 한국어 라벨 매핑은 UI에서 재사용할 수 있도록
모듈 상수로 노출한다.
"""

from __future__ import annotations

import logging

from core import llm
from core.schemas import InspectionItem, ReportNarrative

logger = logging.getLogger("aeroinspect.reporter")

# ---------------------------------------------------------------------------
# 한국어 라벨 매핑 (서술/UI 공용 — 모듈 상수로 export)
# ---------------------------------------------------------------------------

#: 결함 유형 → 한국어 라벨
TYPE_LABELS_KO: dict[str, str] = {
    "missing_part": "부품 누락",
    "misinstalled_part": "부품 오장착",
    "foreign_object": "이물질(FOD)",
    "surface_damage": "표면 손상",
    "other": "기타",
}

#: 심각도 → 한국어 라벨
SEVERITY_LABELS_KO: dict[str, str] = {
    "low": "낮음",
    "medium": "중간",
    "high": "높음",
    "critical": "심각",
}

#: 누락 시 조치(disposition) → 한국어 라벨
DISPOSITION_LABELS_KO: dict[str, str] = {
    "ground_aircraft": "비행 금지(운항 중지)",
    "install_before_flight": "비행 전 장착",
    "monitor": "상태 감시(모니터링)",
    "engineering_review": "기술 검토 필요",
}

#: 좌/우 위치 → 한국어 라벨 (aircraft_side / catalog_side 공용)
SIDE_LABELS_KO: dict[str, str] = {
    "left": "좌측",
    "right": "우측",
    "center": "중앙",
    "unknown": "미상",
    "na": "해당 없음",
}

_SYSTEM_INSTRUCTION: str = (
    "너는 항공정비 형상 점검 보고서의 서술부(점검 개요, 종합 의견)를 작성하는 "
    "기술 문서 작성자다. 담백하고 사실 중심적인 문체로, 제공된 점검 항목 요약에 "
    "근거해서만 서술하며 추측이나 과장을 하지 않는다. "
    "이 점검은 항공기 축소 모형을 대상으로 한 가상 데이터 기반 데모임을 인지하고 "
    "작성한다. 모든 문장은 격식 있는 한국어 보고서 문체로 쓴다."
)


# ---------------------------------------------------------------------------
# 서술 생성 컨텍스트
# ---------------------------------------------------------------------------


def _item_summary_line(item: InspectionItem) -> str:
    """서술 생성 컨텍스트용 항목 1건 요약 텍스트(이미지 미포함)."""
    d = item.discrepancy
    record = item.effective_record
    flags = ", ".join(item.validation.flags) if item.validation.flags else "없음"
    return (
        f"- ID={d.discrepancy_id}"
        f" | 유형={TYPE_LABELS_KO.get(d.discrepancy_type, d.discrepancy_type)}"
        f" | 부품명={d.component_name_ko}"
        f" | 좌우={SIDE_LABELS_KO.get(d.aircraft_side, d.aircraft_side)}"
        f" | 심각도={SEVERITY_LABELS_KO.get(d.severity, d.severity)}"
        f" | 조치={DISPOSITION_LABELS_KO.get(record.disposition_if_missing, record.disposition_if_missing)}"
        f" | 플래그={flags}"
        f" | 근거={d.evidence}"
    )


def _build_narrative_context(items: list[InspectionItem], inspector_name: str) -> str:
    """서술(개요/종합 의견) 생성용 텍스트 컨텍스트를 조립한다."""
    lines = [
        "항공기 축소 모형 형상 비교 점검(기준 사진 대비 점검 사진) 결과다.",
        f"점검자: {inspector_name}",
        f"탐지된 구성 차이: {len(items)}건",
    ]
    if items:
        lines.append("항목 요약:")
        lines.extend(_item_summary_line(item) for item in items)
    else:
        lines.append(
            "기준 형상과 점검 형상 간 구성 차이 미발견(이상 없음). "
            "이상이 발견되지 않았다는 취지로 점검 개요와 종합 의견을 작성하라."
        )
    lines.append("위 내용을 바탕으로 점검 개요(overview)와 종합 의견(overall_opinion)을 작성하라.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ReportAgent
# ---------------------------------------------------------------------------


class ReportAgent:
    """점검 결과를 한국어 서술(점검 개요·종합 의견)로 요약하는 에이전트.

    Args:
        model: 서술 생성에 사용할 Gemini 모델명 (하드코딩 금지 — 주입).
    """

    def __init__(self, model: str) -> None:
        self._model = model

    def build_narrative(
        self, items: list[InspectionItem], inspector_name: str
    ) -> ReportNarrative:
        """항목 요약 텍스트만으로 개요/종합 의견 서술을 생성한다.

        items가 비어 있어도 '이상 없음' 취지의 서술을 생성한다.

        Returns:
            생성된 ReportNarrative
        """
        context = _build_narrative_context(items, inspector_name)
        narrative = llm.generate_structured(
            agent="reporter",
            model=self._model,
            contents=[context],
            response_schema=ReportNarrative,
            system_instruction=_SYSTEM_INSTRUCTION,
            temperature=0.2,
        )
        if not isinstance(narrative, ReportNarrative):
            narrative = ReportNarrative.model_validate(narrative)
        logger.info("ReportAgent 서술 생성 완료 — 항목 %d건", len(items))
        return narrative

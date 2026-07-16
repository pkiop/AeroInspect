"""AeroInspect 파이프라인 전역 Pydantic 스키마.

모든 에이전트의 입출력 계약을 이 모듈 한 곳에서 정의한다.
LLM 구조화 출력(response_schema)에 그대로 사용되는 모델과,
파이프라인 내부 전달용 모델을 함께 둔다.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# VisionAgent 출력
# ---------------------------------------------------------------------------

DiscrepancyType = Literal[
    "missing_part",
    "misinstalled_part",
    "foreign_object",
    "surface_damage",
    "other",
]

AircraftSide = Literal["left", "right", "center", "unknown"]

Severity = Literal["low", "medium", "high", "critical"]


class Discrepancy(BaseModel):
    """기준/점검 이미지 비교에서 탐지된 구성 차이 1건.

    ``discrepancy_id`` 는 LLM이 아닌 파이프라인(오케스트레이터)이
    ``D-001`` 형식으로 자동 부여한다.
    """

    discrepancy_id: str = ""
    discrepancy_type: DiscrepancyType
    component_name_ko: str = Field(description="부품 체크리스트와 동일한 한국어 부품명")
    component_name_en: Optional[str] = None
    aircraft_side: AircraftSide = Field(
        description="항공기 기준(조종사가 기수를 보는 방향) 좌/우"
    )
    image_position_desc: str = Field(
        description="이미지 프레임 기준 위치 서술 (항공기 기준 좌/우와 혼용 금지)"
    )
    bbox_inspection: list[float] = Field(
        description="점검 이미지에서 이상 위치 [x0,y0,x1,y1], 0~1 정규화"
    )
    bbox_baseline: Optional[list[float]] = Field(
        default=None,
        description="기준 이미지에서 해당 부품의 정상 장착 위치 [x0,y0,x1,y1]",
    )
    inspection_image_index: int = Field(
        default=0,
        ge=0,
        description="bbox_inspection이 점검 이미지 목록 중 몇 번째 이미지 기준인지 (0부터)",
    )
    baseline_image_index: int = Field(
        default=0,
        ge=0,
        description="bbox_baseline이 기준 이미지 목록 중 몇 번째 이미지 기준인지 (0부터)",
    )
    evidence: str = Field(description="판단 근거 서술")
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("bbox_inspection", "bbox_baseline")
    @classmethod
    def _validate_bbox(cls, v: Optional[list[float]]) -> Optional[list[float]]:
        """bbox는 4개 좌표여야 하며, 값은 0~1로 클램프한다."""
        if v is None:
            return None
        if len(v) != 4:
            raise ValueError(f"bbox는 [x0,y0,x1,y1] 4개 값이어야 함 (got {len(v)})")
        return [min(max(float(x), 0.0), 1.0) for x in v]


# ---------------------------------------------------------------------------
# GroundingAgent 출력
# ---------------------------------------------------------------------------

CatalogSide = Literal["left", "right", "center", "na"]

Disposition = Literal[
    "ground_aircraft",
    "install_before_flight",
    "monitor",
    "engineering_review",
]


class RefDoc(BaseModel):
    """카탈로그 인용 메타데이터(문서명 + 섹션)."""

    doc: str
    section: str


class PartRecord(BaseModel):
    """가상 부품 카탈로그(mini-IPC)에서 조회한 부품 정보.

    ``via_fallback`` 은 LLM이 아니라 GroundingAgent 래퍼가
    폴백 경로 사용 여부에 따라 설정한다.
    """

    found: bool
    part_number: Optional[str] = None
    name_ko: str = ""
    name_en: str = ""
    catalog_side: CatalogSide = "na"
    flight_critical: bool = False
    installation_steps: list[str] = Field(default_factory=list)
    disposition_if_missing: Disposition = "engineering_review"
    reference_docs: list[RefDoc] = Field(default_factory=list)
    via_fallback: bool = False


# ---------------------------------------------------------------------------
# Validator 출력 (LLM 미사용 — 순수 규칙 엔진)
# ---------------------------------------------------------------------------


class ValidationResult(BaseModel):
    """결정론적 규칙 검증 결과."""

    passed: bool
    flags: list[str] = Field(default_factory=list)
    adjusted_record: Optional[PartRecord] = None


# ---------------------------------------------------------------------------
# ReportAgent 서술 (구조화 출력)
# ---------------------------------------------------------------------------


class ReportNarrative(BaseModel):
    """보고서용 한국어 서술 — Gemini 구조화 출력으로 생성."""

    overview: str = Field(description="점검 개요 서술 (2~4문장)")
    overall_opinion: str = Field(description="종합 의견 서술 (3~6문장)")


# ---------------------------------------------------------------------------
# 파이프라인 내부 전달용 모델
# ---------------------------------------------------------------------------


class InspectionItem(BaseModel):
    """결함 1건에 대한 파이프라인 산출물 묶음 (보고서/UI 공용)."""

    discrepancy: Discrepancy
    part_record: PartRecord
    validation: ValidationResult

    @property
    def effective_record(self) -> PartRecord:
        """Validator가 조정한 레코드가 있으면 그것을, 없으면 원본을 반환."""
        return self.validation.adjusted_record or self.part_record


class PipelineEvent(BaseModel):
    """오케스트레이터가 UI 콜백으로 발행하는 단계 이벤트."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    stage: Literal["vision", "grounding", "validation", "report"]
    status: Literal["started", "completed", "failed"]
    message: str = ""
    payload: Any = None


class PipelineResult(BaseModel):
    """전체 파이프라인 최종 결과."""

    items: list[InspectionItem] = Field(default_factory=list)
    narrative: Optional[ReportNarrative] = None
    report_path: Optional[str] = None
    run_dir: Optional[str] = None

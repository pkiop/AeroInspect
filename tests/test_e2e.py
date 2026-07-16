"""E2E 파이프라인 스모크 테스트 — Gemini 호출을 전부 mock.

실제 네트워크/모델 호출 없이 다음을 검증한다.

- Vision → Grounding(폴백 경로) → Validator → Report 전체 파이프라인 동작
- ``discrepancy_id`` 자동 부여(D-001), ESCALATED 상향, ``via_fallback`` 표시
- 보고서 서술(개요/종합 의견) 생성 및 ``runs/`` 산출물 저장
- ``PipelineEvent`` 발행 순서
- 카탈로그 ↔ ``config.PARTS_REGISTRY`` 일치성
- Validator 결정론 규칙(플래그) 단위 동작

모든 Gemini 접근은 ``core/llm.py`` 의 4개 공개 함수 +
``core/config.get_client`` 를 경유하므로, 그 지점만 monkeypatch 한다.
"""

from __future__ import annotations

import io
import typing
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from core import config
from core.schemas import (
    Discrepancy,
    PartRecord,
    PipelineEvent,
    RefDoc,
    ReportNarrative,
)

# ---------------------------------------------------------------------------
# 테스트용 이미지 / mock 데이터 헬퍼
# ---------------------------------------------------------------------------


def _solid_jpeg(color: tuple[int, int, int], size: tuple[int, int] = (400, 300)) -> bytes:
    """Pillow로 단색 JPEG 이미지 bytes를 생성한다."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def _mock_discrepancy() -> Discrepancy:
    """Vision mock 응답 — 우측 수직꼬리날개 누락 1건.

    - ``discrepancy_id`` 는 비워 둔다 → VisionAgent가 D-001을 부여해야 함
    - ``severity="high"`` (의도적으로 critical 아님) → ESCALATED 상향 검증용
    """
    return Discrepancy(
        discrepancy_id="",
        discrepancy_type="missing_part",
        component_name_ko="우측 수직꼬리날개",
        component_name_en="Right Vertical Stabilizer",
        aircraft_side="right",
        image_position_desc="이미지 프레임 좌측 상단 (항공기 기준 우측)",
        bbox_inspection=[0.6, 0.1, 0.9, 0.5],
        bbox_baseline=[0.6, 0.1, 0.9, 0.5],
        evidence="기준 이미지에는 우측 수직꼬리날개가 장착되어 있으나 점검 이미지에서는 보이지 않음",
        severity="high",
        confidence=0.9,
    )


def _mock_part_record() -> PartRecord:
    """Grounding mock 응답 — 카탈로그 조회 성공 레코드.

    - ``disposition_if_missing="install_before_flight"`` (의도적으로
      ground_aircraft 아님) → Validator ESCALATED 조정 검증용
    - ``via_fallback`` 은 GroundingAgent 래퍼가 설정해야 하므로 건드리지 않는다.
    """
    return PartRecord(
        found=True,
        part_number="ACFT-VTS-R-001",
        name_ko="우측 수직꼬리날개",
        name_en="Right Vertical Stabilizer",
        catalog_side="right",
        flight_critical=True,
        installation_steps=[
            "수직꼬리날개 장착부 표면 이물질 제거 및 손상 여부 확인",
            "가이드 핀에 맞춰 수직꼬리날개를 동체 장착부에 결합",
            "고정 볼트를 규정 토크로 체결 후 유격 없음 확인",
        ],
        disposition_if_missing="install_before_flight",
        reference_docs=[
            RefDoc(doc="01_tail.md", section="## [ACFT-VTS-R-001] 우측 수직꼬리날개")
        ],
    )


# ---------------------------------------------------------------------------
# Gemini mock 픽스처
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """core.llm 공개 함수 4개 + get_client를 전부 mock한다.

    - ``generate_structured``: response_schema로 분기
      (list[Discrepancy] → 결함 1건, ReportNarrative → 서술)
    - ``agenerate_structured``: PartRecord 반환 (롱컨텍스트 폴백 경로)
    - ``generate_text`` / ``agenerate_text``: 호출 즉시 실패
      (store_name=None 폴백 테스트이므로 File Search 미사용이어야 함)
    - ``get_client``: 호출 즉시 실패 (네트워크 접근 금지 보장)

    반환값: 호출 횟수 카운터 dict.
    """
    import core.llm as llm

    calls = {"structured": 0, "astructured": 0}

    def fake_generate_structured(**kwargs: Any) -> Any:
        calls["structured"] += 1
        schema = kwargs["response_schema"]
        if typing.get_origin(schema) is list:
            return [_mock_discrepancy()]
        if schema is ReportNarrative:
            return ReportNarrative(
                overview="기준 이미지와 점검 이미지를 비교한 결과 구성 차이 1건이 탐지되었다. "
                "우측 수직꼬리날개가 점검 이미지에서 확인되지 않는다.",
                overall_opinion="우측 수직꼬리날개는 비행 안전에 직결되는 부품으로, "
                "재장착 및 재점검 완료 전까지 비행을 금지할 것을 권고한다. "
                "장착 절차는 카탈로그 절차서를 따르고 완료 후 재촬영 검증이 필요하다.",
            )
        raise AssertionError(f"예상치 못한 response_schema: {schema!r}")

    async def fake_agenerate_structured(**kwargs: Any) -> PartRecord:
        calls["astructured"] += 1
        return _mock_part_record()

    def fail_generate_text(**kwargs: Any) -> Any:
        raise AssertionError(
            "generate_text 호출 금지 — store_name=None 폴백 경로에서는 File Search를 쓰면 안 됨"
        )

    async def fail_agenerate_text(**kwargs: Any) -> Any:
        raise AssertionError(
            "agenerate_text 호출 금지 — store_name=None 폴백 경로에서는 File Search를 쓰면 안 됨"
        )

    def fail_get_client() -> Any:
        raise AssertionError("mock 테스트에서 get_client가 호출되면 안 됨 (네트워크 접근 금지)")

    monkeypatch.setattr(llm, "generate_structured", fake_generate_structured)
    monkeypatch.setattr(llm, "agenerate_structured", fake_agenerate_structured)
    monkeypatch.setattr(llm, "generate_text", fail_generate_text)
    monkeypatch.setattr(llm, "agenerate_text", fail_agenerate_text)
    monkeypatch.setattr(llm, "get_client", fail_get_client)
    monkeypatch.setattr(config, "get_client", fail_get_client)
    return calls


@pytest.fixture
def isolated_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """RUNS_DIR를 tmp_path 하위로 격리한다.

    ``from core import config`` 후 속성 접근 방식과
    ``from core.config import RUNS_DIR`` 방식(모듈 상수 재바인딩) 모두를
    커버하기 위해 관련 모듈 속성도 함께 교체한다(raising=False).
    """
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    monkeypatch.setattr(config, "RUNS_DIR", runs_dir)

    import core.orchestrator as orchestrator_module

    monkeypatch.setattr(orchestrator_module, "RUNS_DIR", runs_dir, raising=False)
    return runs_dir


# ---------------------------------------------------------------------------
# 1) 파이프라인 E2E 스모크 테스트
# ---------------------------------------------------------------------------


def test_pipeline_e2e_smoke(mock_llm: dict[str, int], isolated_output: Path) -> None:
    """mock Gemini로 4단계 파이프라인 전체를 관통 실행한다."""
    from core.orchestrator import Orchestrator

    baseline_images = [_solid_jpeg((88, 108, 138))]
    inspection_images = [_solid_jpeg((100, 120, 150))]

    events: list[PipelineEvent] = []
    orchestrator = Orchestrator(
        models={"vision": "mock", "grounding": "mock", "report": "mock"},
        store_name=None,  # File Search 미사용 → 롱컨텍스트 폴백 경로
        inspector_name="테스트",
    )
    result = orchestrator.run(
        baseline_images, inspection_images, progress_callback=events.append
    )

    # --- 결함 항목: 1건 + discrepancy_id 자동 부여 ---
    assert len(result.items) == 1
    item = result.items[0]
    assert item.discrepancy.discrepancy_id == "D-001"

    # --- Validator: ESCALATED 상향 (severity=critical, 조치=ground_aircraft) ---
    assert "ESCALATED" in item.validation.flags
    assert item.discrepancy.severity == "critical"
    assert item.effective_record.disposition_if_missing == "ground_aircraft"

    # --- Grounding: store_name=None 이므로 폴백 경로 사용 표시 ---
    assert item.part_record.via_fallback is True

    # --- 보고서 서술: 개요/종합 의견 생성 ---
    assert result.narrative is not None
    assert result.narrative.overview
    assert result.narrative.overall_opinion

    # --- PipelineEvent 발행 순서 ---
    assert [(e.stage, e.status) for e in events] == [
        ("vision", "started"),
        ("vision", "completed"),
        ("grounding", "started"),
        ("grounding", "completed"),
        ("validation", "started"),
        ("validation", "completed"),
        ("report", "started"),
        ("report", "completed"),
    ]

    # completed 이벤트 payload 규약 (스팟 체크)
    vision_completed = events[1]
    assert isinstance(vision_completed.payload, list)
    assert len(vision_completed.payload) == 1
    grounding_completed = events[3]
    assert grounding_completed.payload[0]["discrepancy_id"] == "D-001"
    assert isinstance(grounding_completed.payload[0]["record"], PartRecord)

    # --- runs/<timestamp>/ 단계별 산출물 저장 ---
    assert result.run_dir is not None
    run_dir = Path(result.run_dir)
    for artifact in ("vision.json", "grounding.json", "validation.json", "narrative.json"):
        assert (run_dir / artifact).is_file(), f"{artifact} 이 run_dir에 없음"


# ---------------------------------------------------------------------------
# 2) 카탈로그 ↔ 레지스트리 일치성
# ---------------------------------------------------------------------------


def test_catalog_registry_consistency() -> None:
    """data/parts_catalog/*.md 가 6개이며, 레지스트리의 모든 P/N·부품명을 담는지 검증."""
    md_files = sorted(config.CATALOG_DIR.glob("*.md"))
    assert len(md_files) == 6, f"카탈로그 파일은 6개여야 함 (현재 {len(md_files)}개)"

    full_text = "\n".join(p.read_text(encoding="utf-8") for p in md_files)
    for part in config.PARTS_REGISTRY:
        assert part.part_number in full_text, f"카탈로그에 P/N 누락: {part.part_number}"
        assert part.name_ko in full_text, f"카탈로그에 부품명 누락: {part.name_ko}"


# ---------------------------------------------------------------------------
# 3) Validator 규칙 단위 테스트
# ---------------------------------------------------------------------------


def _discrepancy(**overrides: Any) -> Discrepancy:
    """Validator 테스트용 Discrepancy 빌더 (기본: 정상 통과 케이스)."""
    base: dict[str, Any] = {
        "discrepancy_id": "D-001",
        "discrepancy_type": "missing_part",
        "component_name_ko": "우측 훈련용 미사일",
        "component_name_en": "Right Training Missile",
        "aircraft_side": "right",
        "image_position_desc": "이미지 프레임 좌측 하단",
        "bbox_inspection": [0.1, 0.6, 0.4, 0.9],
        "bbox_baseline": [0.1, 0.6, 0.4, 0.9],
        "evidence": "기준 이미지 대비 우측 파일런에서 훈련용 미사일이 보이지 않음",
        "severity": "medium",
        "confidence": 0.9,
    }
    base.update(overrides)
    return Discrepancy(**base)


def _record(**overrides: Any) -> PartRecord:
    """Validator 테스트용 PartRecord 빌더 (기본: 비행 필수 아님 → ESCALATED 배제)."""
    base: dict[str, Any] = {
        "found": True,
        "part_number": "ACFT-MSL-R-001",
        "name_ko": "우측 훈련용 미사일",
        "name_en": "Right Training Missile",
        "catalog_side": "right",
        "flight_critical": False,
        "installation_steps": ["파일런 러그 정렬", "고정 스트랩 체결", "유격 점검"],
        "disposition_if_missing": "install_before_flight",
        "reference_docs": [
            RefDoc(doc="02_wing.md", section="## [ACFT-MSL-R-001] 우측 훈련용 미사일")
        ],
        "via_fallback": False,
    }
    base.update(overrides)
    return PartRecord(**base)


def test_validator_rules() -> None:
    """Validator 결정론 규칙 5종 — LLM 없이 단독 동작해야 한다."""
    from agents.validator import FLAG_DESCRIPTIONS, Validator

    validator = Validator(confidence_threshold=0.6)

    # 1) REVIEW_REQUIRED — confidence가 임계값 미만
    result = validator.validate(_discrepancy(confidence=0.3), _record())
    assert "REVIEW_REQUIRED" in result.flags

    # 2) UNKNOWN_COMPONENT — 카탈로그에서 부품을 찾지 못함
    result = validator.validate(_discrepancy(), _record(found=False, part_number=None))
    assert "UNKNOWN_COMPONENT" in result.flags

    # 3) SIDE_MISMATCH — 탐지 좌/우와 카탈로그 좌/우 불일치
    result = validator.validate(
        _discrepancy(aircraft_side="left"), _record(catalog_side="right")
    )
    assert "SIDE_MISMATCH" in result.flags

    # 4) UNGROUNDED — 카탈로그 인용(reference_docs)이 비어 있음
    result = validator.validate(_discrepancy(), _record(reference_docs=[]))
    assert "UNGROUNDED" in result.flags

    # 5) 플래그 없음 — 정상 통과 케이스
    result = validator.validate(_discrepancy(), _record())
    assert result.passed is True
    assert result.flags == []

    # 모든 플래그는 UI/보고서용 한국어 설명을 가져야 한다
    for flag in (
        "REVIEW_REQUIRED",
        "UNKNOWN_COMPONENT",
        "SIDE_MISMATCH",
        "UNGROUNDED",
        "ESCALATED",
    ):
        assert flag in FLAG_DESCRIPTIONS, f"FLAG_DESCRIPTIONS에 {flag} 설명 누락"


# ---------------------------------------------------------------------------
# 4) 동일 프로세스 반복 실행 회귀 테스트
# ---------------------------------------------------------------------------


def test_pipeline_repeated_runs(mock_llm: dict[str, int], isolated_output: Path) -> None:
    """같은 프로세스에서 파이프라인을 연속 실행해도 실패하지 않아야 한다.

    회귀 방지: 실행마다 asyncio.run으로 이벤트 루프를 만들고 닫으면
    genai 비동기 클라이언트의 커넥션 풀이 닫힌 루프에 남아 두 번째
    실행부터 'Event loop is closed'가 발생했다 (Streamlit 재클릭 시나리오).
    """
    from core.orchestrator import Orchestrator

    orchestrator = Orchestrator(
        models={"vision": "mock", "grounding": "mock", "report": "mock"},
        store_name=None,
        inspector_name="테스트",
    )
    baseline_images = [_solid_jpeg((88, 108, 138))]
    inspection_images = [_solid_jpeg((100, 120, 150))]

    for _ in range(2):
        result = orchestrator.run(baseline_images, inspection_images)
        assert len(result.items) == 1
        assert result.narrative is not None

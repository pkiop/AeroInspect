"""AeroInspect 파이프라인 오케스트레이터 (순수 Python, 프레임워크 미사용).

흐름: Vision(전체 이미지 비교 1회) → 항목별 Grounding(asyncio 병렬)
→ Validator(항목별 규칙 검증) → Report(보고서 생성).

- 단계별 :class:`~core.schemas.PipelineEvent` 를 progress_callback으로 발행한다.
- 각 단계의 원본 산출물을 ``config.RUNS_DIR/<YYYYMMDD_HHMMSS>/`` 에 JSON으로
  저장해 재현성과 디버깅을 보장한다.
- 단계 실패 시 ``(stage, "failed")`` 이벤트 발행 및 ``error.json`` 기록 후
  예외를 재-raise 한다.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

from agents.grounding import GroundingAgent
from agents.reporter import ReportAgent
from agents.validator import Validator
from agents.vision import VisionAgent
from core import config
from core.config import CONFIDENCE_THRESHOLD, FILE_SEARCH_STORE_NAME
from core.schemas import (
    Discrepancy,
    InspectionItem,
    PartRecord,
    PipelineEvent,
    PipelineResult,
    ValidationResult,
)

logger = logging.getLogger("aeroinspect.orchestrator")

#: progress_callback 타입 별칭
ProgressCallback = Callable[[PipelineEvent], None]


class Orchestrator:
    """멀티에이전트 점검 파이프라인의 동기 진입점.

    Args:
        models: ``{"vision": ..., "grounding": ..., "report": ...}`` 모델명 맵.
            None이면 :func:`core.config.resolve_models` 로 결정한다.
        confidence_threshold: Validator confidence 임계값.
        store_name: File Search 스토어 이름 (GroundingAgent에 전달).
        inspector_name: 보고서에 기입할 점검자 이름.
    """

    def __init__(
        self,
        models: dict[str, str] | None = None,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
        store_name: str | None = FILE_SEARCH_STORE_NAME,
        inspector_name: str = "점검자 미입력",
    ) -> None:
        self.models: dict[str, str] = models or config.resolve_models()
        self.confidence_threshold = confidence_threshold
        self.store_name = store_name
        self.inspector_name = inspector_name

        self._vision = VisionAgent(model=self.models["vision"])
        self._grounding = GroundingAgent(
            model=self.models["grounding"], store_name=store_name
        )
        self._validator = Validator(confidence_threshold=confidence_threshold)
        self._reporter = ReportAgent(model=self.models["report"])

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def run(
        self,
        baseline_images: list[bytes],
        inspection_images: list[bytes],
        progress_callback: ProgressCallback | None = None,
    ) -> PipelineResult:
        """전체 파이프라인을 실행하고 :class:`PipelineResult` 를 반환한다.

        Args:
            baseline_images: 기준(정상) 이미지 bytes 목록.
            inspection_images: 점검 대상 이미지 bytes 목록.
            progress_callback: 단계 이벤트 수신 콜백 (None이면 발행 생략).
        """
        run_dir = self._create_run_dir()
        logger.info("파이프라인 시작 — run_dir=%s, models=%s", run_dir, self.models)

        # --- 1) Vision: 전체 이미지 비교 1회 ---------------------------------
        self._emit(progress_callback, "vision", "started")
        t0 = time.perf_counter()
        try:
            discrepancies = self._vision.analyze(baseline_images, inspection_images)
            discrepancies = self._ensure_ids(discrepancies)
        except Exception as exc:  # noqa: BLE001 — 이벤트/기록 후 재-raise
            self._handle_failure("vision", exc, run_dir, progress_callback)
            raise
        self._save_json(
            run_dir,
            "vision.json",
            [d.model_dump(mode="json") for d in discrepancies],
        )
        logger.info(
            "vision 완료 — %d건 탐지 (%.2fs)",
            len(discrepancies),
            time.perf_counter() - t0,
        )
        self._emit(progress_callback, "vision", "completed", payload=discrepancies)

        # --- 2) Grounding: 항목별 카탈로그 조회 (asyncio 병렬) ----------------
        self._emit(progress_callback, "grounding", "started")
        t0 = time.perf_counter()
        try:
            records = self._lookup_all(discrepancies) if discrepancies else []
        except Exception as exc:  # noqa: BLE001
            self._handle_failure("grounding", exc, run_dir, progress_callback)
            raise
        self._save_json(
            run_dir,
            "grounding.json",
            {
                d.discrepancy_id: r.model_dump(mode="json")
                for d, r in zip(discrepancies, records)
            },
        )
        logger.info(
            "grounding 완료 — %d건 조회 (%.2fs)", len(records), time.perf_counter() - t0
        )
        self._emit(
            progress_callback,
            "grounding",
            "completed",
            payload=[
                {"discrepancy_id": d.discrepancy_id, "record": r}
                for d, r in zip(discrepancies, records)
            ],
        )

        # --- 3) Validation: 항목별 규칙 검증 ---------------------------------
        self._emit(progress_callback, "validation", "started")
        t0 = time.perf_counter()
        try:
            # Validator.validate는 ESCALATED 시 discrepancy.severity를
            # in-place로 critical 상향한다(문서화된 부수효과).
            validations: list[ValidationResult] = [
                self._validator.validate(d, r)
                for d, r in zip(discrepancies, records)
            ]
        except Exception as exc:  # noqa: BLE001
            self._handle_failure("validation", exc, run_dir, progress_callback)
            raise
        self._save_json(
            run_dir,
            "validation.json",
            {
                d.discrepancy_id: v.model_dump(mode="json")
                for d, v in zip(discrepancies, validations)
            },
        )
        logger.info(
            "validation 완료 — %d건 검증 (%.2fs)",
            len(validations),
            time.perf_counter() - t0,
        )
        self._emit(
            progress_callback,
            "validation",
            "completed",
            payload=[
                {"discrepancy_id": d.discrepancy_id, "validation": v}
                for d, v in zip(discrepancies, validations)
            ],
        )

        # ESCALATED severity 상향이 반영된 discrepancy로 항목 구성
        items = [
            InspectionItem(discrepancy=d, part_record=r, validation=v)
            for d, r, v in zip(discrepancies, records, validations)
        ]

        # --- 4) Report: 보고서 생성 (0건이면 '이상 없음' 보고서) --------------
        self._emit(progress_callback, "report", "started")
        t0 = time.perf_counter()
        try:
            report_path, narrative = self._reporter.build_report(
                items,
                baseline_images,
                inspection_images,
                self.inspector_name,
            )
        except Exception as exc:  # noqa: BLE001
            self._handle_failure("report", exc, run_dir, progress_callback)
            raise
        self._save_json(run_dir, "narrative.json", narrative.model_dump(mode="json"))
        self._save_json(
            run_dir,
            "result.json",
            {
                "discrepancy_count": len(items),
                "report_path": str(report_path),
                "models": self.models,
                "confidence_threshold": self.confidence_threshold,
                "inspector_name": self.inspector_name,
                "run_dir": str(run_dir),
            },
        )
        logger.info(
            "report 완료 — %s (%.2fs)", report_path, time.perf_counter() - t0
        )
        self._emit(
            progress_callback,
            "report",
            "completed",
            payload={"report_path": str(report_path), "narrative": narrative},
        )

        logger.info("파이프라인 종료 — 총 %d건, run_dir=%s", len(items), run_dir)
        return PipelineResult(
            items=items,
            narrative=narrative,
            report_path=str(report_path),
            run_dir=str(run_dir),
        )

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _lookup_all(self, discrepancies: list[Discrepancy]) -> list[PartRecord]:
        """GroundingAgent.lookup(async)을 asyncio.gather로 병렬 실행한다."""

        async def _gather() -> list[PartRecord]:
            results = await asyncio.gather(
                *[self._grounding.lookup(d) for d in discrepancies]
            )
            return list(results)

        return asyncio.run(_gather())

    @staticmethod
    def _ensure_ids(discrepancies: list[Discrepancy]) -> list[Discrepancy]:
        """discrepancy_id 미부여 항목에 D-001 형식 ID를 방어적으로 채운다.

        (VisionAgent가 부여하는 것이 원칙이나, 누락 시에도 후속 단계의
        키 매핑이 깨지지 않도록 보강한다.)
        """
        for idx, disc in enumerate(discrepancies, start=1):
            if not disc.discrepancy_id:
                disc.discrepancy_id = f"D-{idx:03d}"
        return discrepancies

    def _emit(
        self,
        callback: ProgressCallback | None,
        stage: str,
        status: str,
        message: str = "",
        payload: Any = None,
    ) -> None:
        """PipelineEvent를 콜백으로 발행한다. 콜백 예외는 삼키고 경고만 남긴다."""
        if callback is None:
            return
        event = PipelineEvent(stage=stage, status=status, message=message, payload=payload)
        try:
            callback(event)
        except Exception:  # noqa: BLE001 — UI 콜백 오류가 파이프라인을 중단시키면 안 됨
            logger.warning(
                "progress_callback 실행 중 예외 — 무시 (stage=%s, status=%s)",
                stage,
                status,
                exc_info=True,
            )

    def _handle_failure(
        self,
        stage: str,
        exc: Exception,
        run_dir: Path,
        callback: ProgressCallback | None,
    ) -> None:
        """단계 실패 처리: failed 이벤트 발행 + error.json 기록 (re-raise는 호출부)."""
        logger.error("%s 단계 실패: %s", stage, exc)
        self._save_json(
            run_dir, "error.json", {"stage": stage, "error": str(exc)}
        )
        self._emit(callback, stage, "failed", message=str(exc))

    @staticmethod
    def _create_run_dir() -> Path:
        """``config.RUNS_DIR/<YYYYMMDD_HHMMSS>/`` 실행 디렉토리를 생성한다."""
        run_dir = config.RUNS_DIR / _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    @staticmethod
    def _save_json(run_dir: Path, filename: str, obj: Any) -> None:
        """산출물을 run_dir에 JSON으로 저장한다 (저장 실패는 경고 로그 후 계속)."""
        path = run_dir / filename
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.warning("산출물 저장 실패 (%s): %s", path, exc)

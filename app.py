"""AeroInspect — Streamlit 단일 페이지 UI.

멀티에이전트 파이프라인(Vision → Grounding → Validator → Report)의
중간 산출물을 에이전트별 카드(st.status)로 단계별 실시간 표시하는 데모 화면.

실행법::

    streamlit run app.py
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Callable

import streamlit as st

from agents.validator import FLAG_DESCRIPTIONS
from core import config, imaging
from core.orchestrator import Orchestrator
from core.schemas import (
    Discrepancy,
    PartRecord,
    PipelineEvent,
    PipelineResult,
    ValidationResult,
)

# ---------------------------------------------------------------------------
# 상수 (표시용 라벨)
# ---------------------------------------------------------------------------

#: 파이프라인 단계 → 카드 제목
STAGE_LABELS: dict[str, str] = {
    "vision": "1️⃣ Vision — 형상 비교 판독",
    "grounding": "2️⃣ Grounding — 부품 카탈로그 검색",
    "validation": "3️⃣ Validator — 규칙 검증",
    "report": "4️⃣ Report — 보고서 생성",
}

#: Discrepancy 유형 → 한국어 라벨
DISCREPANCY_TYPE_LABELS: dict[str, str] = {
    "missing_part": "부품 누락",
    "misinstalled_part": "오장착",
    "foreign_object": "이물질(FOD)",
    "surface_damage": "표면 손상",
    "other": "기타",
}

#: 좌/우 구분 → 한국어 라벨
SIDE_LABELS: dict[str, str] = {
    "left": "좌측",
    "right": "우측",
    "center": "중앙",
    "unknown": "미상",
    "na": "해당 없음",
}

#: 누락 시 조치(disposition) → 한국어 라벨
DISPOSITION_LABELS: dict[str, str] = {
    "ground_aircraft": "비행 금지 (Ground Aircraft)",
    "install_before_flight": "비행 전 장착 필요",
    "monitor": "상태 감시",
    "engineering_review": "엔지니어링 검토",
}

#: 빨강 계열(st.error)로 표시할 검증 플래그
RED_FLAGS: frozenset[str] = frozenset({"ESCALATED", "SIDE_MISMATCH", "UNKNOWN_COMPONENT"})

#: 주황 계열(st.warning)로 표시할 검증 플래그
ORANGE_FLAGS: frozenset[str] = frozenset({"REVIEW_REQUIRED", "UNGROUNDED"})

#: .docx MIME 타입
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _default_model_index(model_name: str, options: list[str]) -> int:
    """설정된 기본 모델의 옵션 인덱스를 찾는다 (목록에 없으면 0)."""
    return options.index(model_name) if model_name in options else 0


@st.cache_resource(show_spinner="모델 가용성 확인 중…")
def _startup_models() -> tuple[dict[str, str], set[str] | None]:
    """앱 시작 시 1회: models.list() 가용성 확인 + 폴백된 기본 모델 결정.

    반환: (resolve_models() 결과, 가용 모델 ID 집합 — 조회 실패 시 None)
    """
    available = config.list_available_models()
    return config.resolve_models(available=available), available


# ---------------------------------------------------------------------------
# 사이드바
# ---------------------------------------------------------------------------


def _build_sidebar() -> dict[str, Any]:
    """사이드바(모델/임계값/점검자/File Search 상태/기준 이미지)를 그리고 설정값을 반환한다."""
    resolved_models, available_models = _startup_models()
    model_options = config.model_options()

    with st.sidebar:
        st.header("⚙️ 설정")

        vision_model = st.selectbox(
            "Vision 모델",
            model_options,
            index=_default_model_index(resolved_models["vision"], model_options),
            help="형상 비교 판독(멀티모달)에 사용할 모델",
        )
        text_model = st.selectbox(
            "텍스트 모델 (Grounding·Report)",
            model_options,
            index=_default_model_index(resolved_models["grounding"], model_options),
            help="카탈로그 검색과 보고서 서술 생성에 사용할 모델",
        )
        if available_models is not None:
            unavailable = [
                m for m in {vision_model, text_model} if m not in available_models
            ]
            if unavailable:
                st.warning(
                    "선택한 모델이 현재 계정에서 확인되지 않습니다: "
                    + ", ".join(sorted(unavailable))
                    + " — 실행 시 오류가 날 수 있습니다."
                )
        if resolved_models["vision"] != config.VISION_MODEL:
            st.caption(
                f"⚠️ 기본 Vision 모델 '{config.VISION_MODEL}' 미가용 — "
                f"'{resolved_models['vision']}' 로 폴백되었습니다."
            )
        confidence_threshold = st.slider(
            "Confidence 임계값",
            min_value=0.0,
            max_value=1.0,
            value=float(config.CONFIDENCE_THRESHOLD),
            step=0.05,
            help="이 값 미만의 confidence는 Validator에서 REVIEW_REQUIRED 처리",
        )
        inspector_name = st.text_input("점검자 이름", value="")

        if config.FILE_SEARCH_STORE_NAME:
            st.success("File Search 연결됨")
        else:
            st.info("File Search 스토어 미설정 — 폴백(롱컨텍스트) 모드로 동작합니다.")

        st.divider()
        st.subheader("기준(정상) 이미지 등록")
        baseline_files = st.file_uploader(
            "기준 이미지 업로드 (jpg/png, 다중 선택 가능)",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True,
            key="baseline_uploader",
        )
        # 업로더 현재 상태와 항상 동기화 — 파일을 제거하면 등록도 해제된다.
        st.session_state["baseline_images"] = (
            [f.getvalue() for f in baseline_files] if baseline_files else []
        )
        baseline_images: list[bytes] = st.session_state["baseline_images"]
        st.caption(f"등록된 기준 이미지: {len(baseline_images)}장")
        if baseline_images:
            st.image(baseline_images, width=88)

    return {
        "vision_model": vision_model,
        "text_model": text_model,
        "confidence_threshold": confidence_threshold,
        "inspector_name": inspector_name,
        "baseline_images": baseline_images,
    }


# ---------------------------------------------------------------------------
# 단계별 카드 렌더러
# ---------------------------------------------------------------------------


def _render_vision(
    discrepancies: list[Discrepancy],
    baseline_images: list[bytes],
    inspection_images: list[bytes],
) -> None:
    """Vision 카드 — bbox 오버레이 이미지 2장 + 판독 결과 표."""
    if baseline_images and inspection_images:
        # 각 discrepancy의 이미지 인덱스가 가리키는 이미지에 누적 오버레이한다.
        def _safe_index(idx: int, images: list[bytes]) -> int:
            return idx if 0 <= idx < len(images) else 0

        base_views: dict[int, bytes] = {}
        insp_views: dict[int, bytes] = {}
        for disc in discrepancies:
            bi = _safe_index(disc.baseline_image_index, baseline_images)
            ii = _safe_index(disc.inspection_image_index, inspection_images)
            base_views[bi] = imaging.annotate_baseline(
                base_views.get(bi, baseline_images[bi]), disc.bbox_baseline
            )
            insp_views[ii] = imaging.annotate_inspection(
                insp_views.get(ii, inspection_images[ii]), disc.bbox_inspection
            )
        if not discrepancies:
            base_views[0] = baseline_images[0]
            insp_views[0] = inspection_images[0]
        col_base, col_insp = st.columns(2)
        with col_base:
            for i in sorted(base_views):
                st.image(
                    base_views[i],
                    caption=f"기준 이미지 #{i + 1} (정상 장착 상태)",
                    use_container_width=True,
                )
        with col_insp:
            for i in sorted(insp_views):
                st.image(
                    insp_views[i],
                    caption=f"점검 이미지 #{i + 1} (이상 위치)",
                    use_container_width=True,
                )

    if not discrepancies:
        st.success("구성 차이 미발견")
        return

    rows = [
        {
            "ID": d.discrepancy_id,
            "유형": DISCREPANCY_TYPE_LABELS.get(d.discrepancy_type, d.discrepancy_type),
            "부품명": d.component_name_ko,
            "항공기 좌우": SIDE_LABELS.get(d.aircraft_side, d.aircraft_side),
            "이미지상 위치": d.image_position_desc,
            "심각도": d.severity,
            "confidence": d.confidence,
            "근거": d.evidence,
        }
        for d in discrepancies
    ]
    st.dataframe(rows, use_container_width=True)


def _render_grounding(entries: list[dict[str, Any]]) -> None:
    """Grounding 카드 — 항목별 부품 정보 + 인용 목록 + 조회 경로 배지."""
    if not entries:
        st.info("구성 차이가 없어 카탈로그 조회를 건너뛰었습니다.")
        return

    for i, entry in enumerate(entries):
        record: PartRecord = entry["record"]
        discrepancy_id: str = entry.get("discrepancy_id", "?")
        if i:
            st.divider()
        st.markdown(f"#### {discrepancy_id} — {record.name_ko or '미확인 부품'}")

        if record.via_fallback:
            st.warning("🔁 폴백(롱컨텍스트) 경로로 조회")
        else:
            st.info("🔍 File Search 경로로 조회")

        if not record.found:
            st.error("카탈로그에서 해당 부품을 찾지 못했습니다.")

        flight_critical = "⚠️ 예 (Flight Critical)" if record.flight_critical else "아니오"
        st.markdown(
            f"- **P/N**: `{record.part_number or '-'}`\n"
            f"- **부품명(영문)**: {record.name_en or '-'}\n"
            f"- **카탈로그 좌/우**: {SIDE_LABELS.get(record.catalog_side, record.catalog_side)}\n"
            f"- **Flight Critical**: {flight_critical}\n"
            f"- **누락 시 조치**: "
            f"{DISPOSITION_LABELS.get(record.disposition_if_missing, record.disposition_if_missing)}"
        )

        if record.reference_docs:
            st.markdown("**인용 목록**")
            for ref in record.reference_docs:
                st.markdown(f"- 📄 {ref.doc} — {ref.section}")


def _render_validation(entries: list[dict[str, Any]]) -> None:
    """Validator 카드 — 항목별 passed/failed와 색상 구분 플래그 목록."""
    if not entries:
        st.info("검증할 항목이 없습니다.")
        return

    for i, entry in enumerate(entries):
        validation: ValidationResult = entry["validation"]
        discrepancy_id: str = entry.get("discrepancy_id", "?")
        if i:
            st.divider()
        verdict = "✅ 검증 통과" if validation.passed else "❌ 검증 불통과"
        st.markdown(f"#### {discrepancy_id} — {verdict}")

        if not validation.flags:
            st.success("통과 — 플래그 없음")
            continue
        for flag in validation.flags:
            description = FLAG_DESCRIPTIONS.get(flag, "")
            text = f"**{flag}** — {description}" if description else f"**{flag}**"
            if flag in RED_FLAGS:
                st.error(text)
            elif flag in ORANGE_FLAGS:
                st.warning(text)
            else:
                st.info(text)


def _render_report(payload: dict[str, Any]) -> None:
    """Report 카드 — 개요/종합의견 미리보기 + .docx 다운로드 버튼."""
    narrative = payload.get("narrative")
    report_path = payload.get("report_path")

    if narrative is not None:
        st.markdown("**점검 개요**")
        st.write(narrative.overview)
        st.markdown("**종합 의견**")
        st.write(narrative.overall_opinion)

    if not report_path:
        st.warning("보고서 경로가 없습니다.")
        return
    path = Path(report_path)
    data: bytes | None = st.session_state.get("report_bytes")
    if data is None and path.exists():
        with open(path, "rb") as f:
            data = f.read()
    if data:
        st.download_button(
            "📄 점검 보고서(.docx) 다운로드",
            data=data,
            file_name=path.name,
            mime=DOCX_MIME,
            key="report_download",
        )
    else:
        st.warning(f"보고서 파일을 찾을 수 없습니다: {path}")


# ---------------------------------------------------------------------------
# 진행 콜백 / 결과 재렌더 / 오류 표시
# ---------------------------------------------------------------------------


def _make_progress_callback(
    status_boxes: dict[str, Any],
    baseline_images: list[bytes],
    inspection_images: list[bytes],
    progress: dict[str, Any],
) -> Callable[[PipelineEvent], None]:
    """PipelineEvent를 받아 해당 단계 st.status 카드를 갱신하는 콜백을 만든다.

    Streamlit은 스크립트 실행 중 동기 호출된 콜백이 미리 만든 컨테이너에
    그리면 실시간으로 표시된다.
    """
    renderers: dict[str, Callable[[Any], None]] = {
        "vision": lambda payload: _render_vision(
            payload or [], baseline_images, inspection_images
        ),
        "grounding": lambda payload: _render_grounding(payload or []),
        "validation": lambda payload: _render_validation(payload or []),
        "report": lambda payload: _render_report(payload or {}),
    }

    def _callback(event: PipelineEvent) -> None:
        box = status_boxes.get(event.stage)
        if box is None:
            return
        if event.status == "started":
            box.update(state="running", expanded=True)
        elif event.status == "completed":
            progress.setdefault("payloads", {})[event.stage] = event.payload
            with box:
                renderers[event.stage](event.payload)
            box.update(state="complete", expanded=True)
        else:  # failed
            progress["failed_stage"] = event.stage
            with box:
                st.error(f"{STAGE_LABELS[event.stage]} 단계 실패: {event.message}")
            box.update(state="error", expanded=True)

    return _callback


def _render_result(status_boxes: dict[str, Any], result: PipelineResult) -> None:
    """세션에 저장된 PipelineResult로 4개 카드를 최종 렌더한다 (rerun 대응)."""
    baseline_images: list[bytes] = st.session_state.get("last_baseline", [])
    inspection_images: list[bytes] = st.session_state.get("last_inspection", [])

    # Vision 카드는 판독 시점 스냅샷(있으면)을 사용 — Validator의 severity
    # 상향이 실행 중 표시와 rerun 표시를 어긋나게 하지 않도록 한다.
    vision_snapshot: list[Discrepancy] | None = st.session_state.get("vision_snapshot")
    discrepancies = (
        vision_snapshot
        if vision_snapshot is not None
        else [item.discrepancy for item in result.items]
    )
    with status_boxes["vision"]:
        _render_vision(discrepancies, baseline_images, inspection_images)

    grounding_entries = [
        {"discrepancy_id": item.discrepancy.discrepancy_id, "record": item.part_record}
        for item in result.items
    ]
    with status_boxes["grounding"]:
        _render_grounding(grounding_entries)

    validation_entries = [
        {"discrepancy_id": item.discrepancy.discrepancy_id, "validation": item.validation}
        for item in result.items
    ]
    with status_boxes["validation"]:
        _render_validation(validation_entries)

    with status_boxes["report"]:
        _render_report({"report_path": result.report_path, "narrative": result.narrative})


def _show_error(error: dict[str, str]) -> None:
    """사용자 친화 오류 메시지 + traceback expander."""
    st.error(error["message"])
    with st.expander("상세 오류 (traceback)"):
        st.code(error["traceback"])


def _make_status_boxes(initial_state: str) -> dict[str, Any]:
    """에이전트별 st.status 카드 4개를 미리 생성한다."""
    return {
        stage: st.status(label, expanded=False, state=initial_state)
        for stage, label in STAGE_LABELS.items()
    }


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------


def main() -> None:
    """단일 페이지 앱 엔트리포인트."""
    st.set_page_config(page_title="AeroInspect", layout="wide", page_icon="✈️")

    settings = _build_sidebar()
    baseline_images: list[bytes] = settings["baseline_images"]

    st.title("✈️ AeroInspect — 항공기 형상 비교 점검")
    st.caption(
        "Vision → Grounding → Validator → Report 멀티에이전트 파이프라인의 "
        "중간 산출물을 단계별로 확인합니다."
    )

    # --- 점검 이미지 입력 (카메라 / 파일 업로드 병행) ---
    st.subheader("점검 이미지 입력")
    inspection_images: list[bytes] = []
    tab_camera, tab_upload = st.tabs(["📷 카메라 촬영", "📁 파일 업로드"])
    with tab_camera:
        shot = st.camera_input("점검 대상 촬영")
        if shot is not None:
            inspection_images.append(shot.getvalue())
    with tab_upload:
        uploads = st.file_uploader(
            "점검 이미지 업로드 (jpg/png, 다중 선택 가능)",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True,
            key="inspection_uploader",
        )
        if uploads:
            inspection_images.extend(f.getvalue() for f in uploads)
    st.caption(f"준비된 점검 이미지: {len(inspection_images)}장")

    start = st.button("🚀 형상 점검 시작", type="primary", use_container_width=True)

    run_requested = start
    if run_requested and (not baseline_images or not inspection_images):
        st.warning("기준(정상) 이미지와 점검 이미지를 모두 등록해야 점검을 시작할 수 있습니다.")
        run_requested = False

    last_result: PipelineResult | None = st.session_state.get("last_result")
    last_error: dict[str, str] | None = st.session_state.get("last_error")

    if run_requested:
        # 새 실행 — 이전 결과/오류 초기화 후 파이프라인 실행
        st.session_state["last_result"] = None
        st.session_state["last_error"] = None
        st.session_state["report_bytes"] = None
        st.session_state["vision_snapshot"] = None
        st.session_state["last_baseline"] = baseline_images
        st.session_state["last_inspection"] = inspection_images

        status_boxes = _make_status_boxes(initial_state="running")
        progress: dict[str, Any] = {"failed_stage": None}
        callback = _make_progress_callback(
            status_boxes, baseline_images, inspection_images, progress
        )
        try:
            orchestrator = Orchestrator(
                models={
                    "vision": settings["vision_model"],
                    "grounding": settings["text_model"],
                    "report": settings["text_model"],
                },
                confidence_threshold=settings["confidence_threshold"],
                inspector_name=settings["inspector_name"].strip() or "점검자 미입력",
            )
            result = orchestrator.run(
                baseline_images, inspection_images, progress_callback=callback
            )
        except Exception as exc:  # noqa: BLE001 — 사용자 친화 메시지로 변환
            failed_stage = progress.get("failed_stage")
            stage_label = STAGE_LABELS.get(failed_stage, "파이프라인") if failed_stage else "파이프라인"
            error = {
                "message": f"'{stage_label}' 단계에서 점검이 중단되었습니다: {exc}",
                "traceback": traceback.format_exc(),
            }
            st.session_state["last_error"] = error
            _show_error(error)
        else:
            st.session_state["last_result"] = result
            st.session_state["vision_snapshot"] = progress.get("payloads", {}).get(
                "vision"
            )
            if result.report_path and Path(result.report_path).exists():
                st.session_state["report_bytes"] = Path(result.report_path).read_bytes()
            st.toast("형상 점검 완료", icon="✅")
    elif last_result is not None:
        # 이전 실행 결과를 카드에 재렌더 (다운로드 클릭 등 rerun 대응)
        status_boxes = _make_status_boxes(initial_state="complete")
        _render_result(status_boxes, last_result)
    elif last_error is not None:
        _show_error(last_error)
    else:
        st.info(
            "사이드바에서 기준(정상) 이미지를 등록하고, 위에서 점검 이미지를 입력한 뒤 "
            "'형상 점검 시작'을 누르세요."
        )


main()

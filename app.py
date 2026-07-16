"""AeroInspect — 다중 에이전트 감항 검증 터미널 (Streamlit).

`aeroinspect_dashboard.html`(시네마틱 단일 무대) 디자인의 Streamlit 이식.

무대 구성:
    형상 대조 작업대(REF | LIVE) → 에이전트 파이프라인 레일 → 최종 판정 → 결과 탭

데모 조작부(모델/임계값/점검자/기준 이미지)는 전부 오퍼레이터 패널(사이드바)로
격리한다 — 무대에는 노출하지 않는다.

실행법::

    streamlit run app.py
"""

from __future__ import annotations

import traceback
from datetime import datetime
from typing import Any, Callable

import streamlit as st

from agents.validator import FLAG_DESCRIPTIONS
from core import config, imaging
from core.orchestrator import Orchestrator
from core.schemas import Discrepancy, InspectionItem, PipelineEvent, PipelineResult
from ui import components as C
from ui import theme

# ---------------------------------------------------------------------------
# 표시용 라벨
# ---------------------------------------------------------------------------

STAGE_ORDER: tuple[str, ...] = ("vision", "grounding", "validation", "report")

STAGE_LABELS: dict[str, str] = {
    "vision": "VisionAgent — 형상 비교 판독",
    "grounding": "GroundingAgent — 부품 카탈로그 검색",
    "validation": "Validator — 규칙 검증",
    "report": "Reporter — 보고서 생성",
}

DISCREPANCY_TYPE_LABELS: dict[str, str] = {
    "missing_part": "부품 누락",
    "misinstalled_part": "오장착",
    "foreign_object": "이물질(FOD)",
    "surface_damage": "표면 손상",
    "other": "기타",
}

SIDE_LABELS: dict[str, str] = {
    "left": "좌측",
    "right": "우측",
    "center": "중앙",
    "unknown": "미상",
    "na": "해당 없음",
}

DISPOSITION_LABELS: dict[str, str] = {
    "ground_aircraft": "비행 금지",
    "install_before_flight": "비행 전 장착",
    "monitor": "상태 감시",
    "engineering_review": "엔지니어링 검토",
}

#: alert(red) 계열 플래그 — 결함/NO-GO 전용
RED_FLAGS: frozenset[str] = frozenset(
    {"ESCALATED", "SIDE_MISMATCH", "UNKNOWN_COMPONENT", "SCHEMA_INVALID"}
)
#: warn(amber) 계열 플래그
AMBER_FLAGS: frozenset[str] = frozenset({"REVIEW_REQUIRED", "UNGROUNDED"})

#: 점검 결과 말미 고정 면책 문구
DISCLAIMER_TEXT: str = (
    "본 점검 결과는 가상 데이터 기반 데모 산출물로, 실제 감항성 판단에 사용할 수 없습니다."
)


def _default_model_index(model_name: str, options: list[str]) -> int:
    """설정된 기본 모델의 옵션 인덱스 (목록에 없으면 0)."""
    return options.index(model_name) if model_name in options else 0


@st.cache_resource(show_spinner="모델 가용성 확인 중…")
def _startup_models() -> tuple[dict[str, str], set[str] | None]:
    """앱 시작 시 1회: 모델 가용성 확인 + 폴백 기본 모델 결정."""
    available = config.list_available_models()
    return config.resolve_models(available=available), available


# ---------------------------------------------------------------------------
# 오퍼레이터 패널 (사이드바) — 무대에 노출되지 않는 조작부
# ---------------------------------------------------------------------------


def _operator_panel() -> dict[str, Any]:
    """모델/임계값/점검자/기준 이미지 설정을 받아 반환한다."""
    resolved, available = _startup_models()
    options = config.model_options()

    with st.sidebar:
        st.markdown(
            '<div style="font-size:13px;font-weight:700;color:#fff">오퍼레이터 패널</div>'
            '<div style="font-size:11px;color:#64748b;margin-bottom:10px">'
            "시연 전 설정 · 무대에 노출되지 않음</div>",
            unsafe_allow_html=True,
        )

        st.markdown(C.section_title("기준 형상 DB"), unsafe_allow_html=True)
        baseline_files = st.file_uploader(
            "기준(정상) 이미지",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True,
            key="baseline_uploader",
            help="AI가 DB에서 매칭해 온 '정상 기준 형상' 역할",
        )
        # 업로더 상태와 항상 동기화 — 파일을 지우면 등록도 해제된다.
        baseline_images: list[bytes] = (
            [f.getvalue() for f in baseline_files] if baseline_files else []
        )
        st.session_state["baseline_images"] = baseline_images
        st.caption(f"등록된 기준 형상: {len(baseline_images)}장")

        st.markdown(C.section_title("추론 매개변수"), unsafe_allow_html=True)
        vision_model = st.selectbox(
            "판독 모델 (Vision)",
            options,
            index=_default_model_index(resolved["vision"], options),
        )
        text_model = st.selectbox(
            "텍스트 모델 (Grounding·Report)",
            options,
            index=_default_model_index(resolved["grounding"], options),
        )
        if available is not None:
            missing = [m for m in {vision_model, text_model} if m not in available]
            if missing:
                st.warning("계정에서 확인되지 않는 모델: " + ", ".join(sorted(missing)))
        if resolved["vision"] != config.VISION_MODEL:
            st.caption(
                f"기본 Vision 모델 '{config.VISION_MODEL}' 미가용 → "
                f"'{resolved['vision']}' 폴백"
            )

        confidence_threshold = st.slider(
            "검증 임계값 (Confidence)",
            min_value=0.0,
            max_value=1.0,
            value=float(config.CONFIDENCE_THRESHOLD),
            step=0.05,
        )
        inspector_name = st.text_input("점검 기술자", value="")

        if config.FILE_SEARCH_STORE_NAME:
            st.caption("✅ File Search 연결됨")
        else:
            st.caption("⚠️ File Search 미설정 — 폴백(롱컨텍스트) 모드")

    return {
        "vision_model": vision_model,
        "text_model": text_model,
        "confidence_threshold": confidence_threshold,
        "inspector_name": inspector_name,
        "baseline_images": baseline_images,
    }


# ---------------------------------------------------------------------------
# 판정 계산
# ---------------------------------------------------------------------------


def _compute_verdict(items: list[InspectionItem]) -> tuple[str, str, str]:
    """검증 결과에서 최종 판정 (verdict, part, reason) 을 도출한다.

    NO-GO  : 비행 필수 부품 누락(ESCALATED) 또는 비행 금지 조치.
    REVIEW : 규칙 검증 불통과 또는 비필수 구성 차이.
    GO     : 이상 없음.
    """
    if not items:
        return (
            "GO",
            "전 항목 기준 형상 일치",
            "기준 형상과의 대조에서 유의미한 구성 차이가 검출되지 않았습니다.",
        )

    blocking = [
        it
        for it in items
        if "ESCALATED" in it.validation.flags
        or it.effective_record.disposition_if_missing == "ground_aircraft"
    ]
    if blocking:
        top = blocking[0]
        rec = top.effective_record
        pn = f" · P/N {rec.part_number}" if rec.part_number else ""
        return (
            "NO-GO",
            f"{top.discrepancy.component_name_ko or '미확인 부품'}{pn}",
            f"비행 필수 부품 이상이 확인되어 출고를 제한합니다. "
            f"검출 {len(items)}건 중 비행 금지 대상 {len(blocking)}건.",
        )

    unresolved = [it for it in items if not it.validation.passed]
    if unresolved:
        top = unresolved[0]
        return (
            "REVIEW",
            top.discrepancy.component_name_ko or "미확인 부품",
            f"규칙 검증을 통과하지 못한 항목이 있어 육안 재검이 필요합니다. "
            f"검출 {len(items)}건 중 재검 대상 {len(unresolved)}건.",
        )

    return (
        "REVIEW",
        items[0].discrepancy.component_name_ko or "미확인 부품",
        f"구성 차이 {len(items)}건이 검출되었으나 비행 필수 항목은 아닙니다. "
        "정비 계획에 반영하십시오.",
    )


# ---------------------------------------------------------------------------
# 무대 — 형상 대조 작업대
# ---------------------------------------------------------------------------


def _annotated_views(
    discrepancies: list[Discrepancy],
    baseline_images: list[bytes],
    inspection_images: list[bytes],
) -> tuple[list[bytes], list[bytes]]:
    """bbox 오버레이가 누적된 (기준, 점검) 이미지 목록을 만든다."""

    def _safe(idx: int, images: list[bytes]) -> int:
        return idx if 0 <= idx < len(images) else 0

    base_views: dict[int, bytes] = {}
    insp_views: dict[int, bytes] = {}
    if baseline_images and inspection_images:
        for d in discrepancies:
            bi = _safe(d.baseline_image_index, baseline_images)
            ii = _safe(d.inspection_image_index, inspection_images)
            base_views[bi] = imaging.annotate_baseline(
                base_views.get(bi, baseline_images[bi]), d.bbox_baseline
            )
            insp_views[ii] = imaging.annotate_inspection(
                insp_views.get(ii, inspection_images[ii]), d.bbox_inspection
            )
    if not base_views and baseline_images:
        base_views[0] = baseline_images[0]
    if not insp_views and inspection_images:
        insp_views[0] = inspection_images[0]
    return (
        [base_views[i] for i in sorted(base_views)],
        [insp_views[i] for i in sorted(insp_views)],
    )


def _render_stage(
    baseline_images: list[bytes],
    inspection_images: list[bytes],
    discrepancies: list[Discrepancy] | None = None,
) -> None:
    """REF | LIVE 2분할 무대."""
    base_views, insp_views = _annotated_views(
        discrepancies or [], baseline_images, inspection_images
    )
    col_ref, col_live = st.columns(2)
    with col_ref:
        st.markdown(C.stage_label("ref", "REF · 공인 기준 형상"), unsafe_allow_html=True)
        if base_views:
            for img in base_views:
                st.image(img, use_container_width=True)
        else:
            st.markdown(
                C.empty("오퍼레이터 패널에서 기준 형상을 등록하십시오."),
                unsafe_allow_html=True,
            )
    with col_live:
        st.markdown(C.stage_label("live", "LIVE · 점검 대상"), unsafe_allow_html=True)
        if insp_views:
            for img in insp_views:
                st.image(img, use_container_width=True)
        else:
            st.markdown(C.empty("점검 대상 사진을 등록하십시오."), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 결과 탭
# ---------------------------------------------------------------------------


def _render_vision_tab(items: list[InspectionItem]) -> None:
    """비전 검출 — 판정 데이터 테이블 + 근거 + 구조화 JSON."""
    rows = [
        {
            "id": it.discrepancy.discrepancy_id,
            "type": DISCREPANCY_TYPE_LABELS.get(
                it.discrepancy.discrepancy_type, it.discrepancy.discrepancy_type
            ),
            "part": it.discrepancy.component_name_ko,
            "side": SIDE_LABELS.get(
                it.discrepancy.aircraft_side, it.discrepancy.aircraft_side
            ),
            "severity": it.discrepancy.severity,
            "confidence": it.discrepancy.confidence,
        }
        for it in items
    ]
    left, right = st.columns([7, 5])
    with left:
        st.markdown(C.discrepancy_table(rows), unsafe_allow_html=True)
        evidence = (
            "\n\n".join(
                f"[{it.discrepancy.discrepancy_id}] {it.discrepancy.evidence}"
                for it in items
            )
            or "구성 차이가 검출되지 않았습니다."
        )
        st.markdown(C.evidence_box(evidence), unsafe_allow_html=True)
    with right:
        st.markdown('<div class="ai-cap">구조화 응답 (JSON)</div>', unsafe_allow_html=True)
        st.json([it.discrepancy.model_dump(mode="json") for it in items], expanded=False)


def _render_grounding_tab(items: list[InspectionItem]) -> None:
    """부품 규격서 — mini-IPC 연계 결과."""
    if not items:
        st.markdown(
            C.empty("구성 차이가 없어 카탈로그 조회를 건너뛰었습니다."),
            unsafe_allow_html=True,
        )
        return
    for i, it in enumerate(items):
        rec = it.effective_record
        if i:
            st.divider()
        route = "폴백(롱컨텍스트)" if rec.via_fallback else "File Search"
        found = "등재 확인" if rec.found else "카탈로그 미확인"
        st.markdown(
            C.section_title(
                f"{it.discrepancy.discrepancy_id} — {rec.name_ko or '미확인 부품'}",
                f"{route} · {found}",
            ),
            unsafe_allow_html=True,
        )
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(
                C.spec_sheet(
                    [
                        ("부품 등록명", rec.name_ko or "—"),
                        ("영문명", rec.name_en or "—"),
                        ("Part Number", rec.part_number or "—"),
                        ("카탈로그 방향", SIDE_LABELS.get(rec.catalog_side, "—")),
                        ("감항 등급", "Flight Critical" if rec.flight_critical else "일반"),
                        (
                            "누락 시 조치",
                            DISPOSITION_LABELS.get(
                                rec.disposition_if_missing, rec.disposition_if_missing
                            ),
                        ),
                    ],
                    [f"{r.doc} — {r.section}" for r in rec.reference_docs],
                ),
                unsafe_allow_html=True,
            )
        with col_b:
            st.markdown(C.steps_list(rec.installation_steps), unsafe_allow_html=True)


def _render_validator_tab(items: list[InspectionItem]) -> None:
    """무결성 검증 — 결정론적 가드레일 결과."""
    if not items:
        st.markdown(C.empty("검증할 항목이 없습니다."), unsafe_allow_html=True)
        return
    for i, it in enumerate(items):
        if i:
            st.divider()
        v = it.validation
        st.markdown(
            C.section_title(
                f"{it.discrepancy.discrepancy_id} — "
                f"{it.discrepancy.component_name_ko or '미확인 부품'}",
                "검증 통과" if v.passed else "검증 불통과",
            ),
            unsafe_allow_html=True,
        )
        if not v.flags:
            st.markdown(
                C.flag_item("PASS", "규칙 위반 없음 — 결정론적 검증을 통과했습니다.", "gray"),
                unsafe_allow_html=True,
            )
            continue
        for flag in v.flags:
            tone = (
                "alert" if flag in RED_FLAGS else "warn" if flag in AMBER_FLAGS else "gray"
            )
            st.markdown(
                C.flag_item(flag, FLAG_DESCRIPTIONS.get(flag, ""), tone),
                unsafe_allow_html=True,
            )


def _render_report_tab(result: PipelineResult, inspector: str) -> None:
    """감항 보고서 — 문서 미리보기 + .docx 다운로드."""
    verdict, _, _ = _compute_verdict(result.items)
    narrative = result.narrative
    summary = (
        f"{narrative.overview}\n\n{narrative.overall_opinion}"
        if narrative
        else "보고서가 아직 생성되지 않았습니다."
    )
    table_rows = [
        [
            it.discrepancy.discrepancy_id,
            it.discrepancy.component_name_ko,
            it.effective_record.part_number or "—",
            it.discrepancy.severity,
            DISPOSITION_LABELS.get(
                it.effective_record.disposition_if_missing,
                it.effective_record.disposition_if_missing,
            ),
        ]
        for it in result.items
    ]
    st.markdown(
        C.report_doc(
            meta_left=[
                ("기종 분류", "Scale-Jet Model"),
                ("점검 부위", "형상 대조 전 영역"),
                ("획득 방식", "라이브 카메라 / 업로드"),
            ],
            meta_right=[
                ("점검 일시", datetime.now().strftime("%Y-%m-%d %H:%M")),
                ("담당 정비사", inspector or "점검자 미입력"),
                ("최종 판정", verdict),
            ],
            summary=summary,
            table_rows=table_rows,
            disclaimer=DISCLAIMER_TEXT,
        ),
        unsafe_allow_html=True,
    )


def _render_tabs(
    result: PipelineResult, inspector: str, logs: list[tuple[str, str]]
) -> None:
    """결과 탭 5종."""
    tabs = st.tabs(["비전 검출", "부품 규격서", "무결성 검증", "감항 보고서", "로그"])
    with tabs[0]:
        _render_vision_tab(result.items)
    with tabs[1]:
        _render_grounding_tab(result.items)
    with tabs[2]:
        _render_validator_tab(result.items)
    with tabs[3]:
        _render_report_tab(result, inspector)
    with tabs[4]:
        st.markdown(C.terminal(logs), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 진행 콜백
# ---------------------------------------------------------------------------


def _make_callback(
    rail_slot: Any,
    term_slot: Any,
    states: dict[str, str],
    logs: list[tuple[str, str]],
) -> Callable[[PipelineEvent], None]:
    """PipelineEvent → 레일/터미널 실시간 갱신 콜백."""

    def _cb(event: PipelineEvent) -> None:
        label = STAGE_LABELS.get(event.stage, event.stage)
        if event.status == "started":
            states[event.stage] = "running"
            logs.append(("", f"{label} 시작"))
        elif event.status == "completed":
            states[event.stage] = "done"
            logs.append(("ok", f"{label} 완료"))
        else:
            states[event.stage] = "fail"
            logs.append(("err", f"{label} 실패: {event.message}"))
            # 후속 단계는 '미실행'으로 명시 — 영구 대기 표시로 남지 않게 한다.
            pos = STAGE_ORDER.index(event.stage)
            for later in STAGE_ORDER[pos + 1 :]:
                states[later] = "fail"
                logs.append(("err", f"{STAGE_LABELS[later]} — 이전 단계 실패로 미실행"))
        rail_slot.markdown(C.agent_rail(states), unsafe_allow_html=True)
        term_slot.markdown(C.terminal(logs), unsafe_allow_html=True)

    return _cb


def _show_error(error: dict[str, str]) -> None:
    """사용자 친화 오류 + traceback."""
    st.error(error["message"])
    with st.expander("상세 오류 (traceback)"):
        st.code(error["traceback"])


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------


def main() -> None:
    """단일 페이지 앱 엔트리포인트."""
    st.set_page_config(
        page_title="AeroInspect — 감항 검증 터미널",
        layout="wide",
        page_icon="✈️",
    )
    theme.inject()

    settings = _operator_panel()
    baseline_images: list[bytes] = settings["baseline_images"]

    last_result: PipelineResult | None = st.session_state.get("last_result")
    last_error: dict[str, str] | None = st.session_state.get("last_error")

    header_slot = st.empty()

    # --- 무대: 형상 대조 작업대 ---
    with st.container(border=True):
        st.markdown(
            C.section_title("형상 대조 작업대", "REF · 공인 기준 형상 ↔ LIVE · 점검 대상"),
            unsafe_allow_html=True,
        )

        tab_cam, tab_file = st.tabs(["카메라 촬영", "파일 등록"])
        with tab_cam:
            shot = st.camera_input("점검 대상 촬영", label_visibility="collapsed")
        with tab_file:
            uploads = st.file_uploader(
                "점검 대상 사진",
                type=["jpg", "jpeg", "png"],
                accept_multiple_files=True,
                key="inspection_uploader",
                label_visibility="collapsed",
            )

        camera_shots: list[bytes] = [shot.getvalue()] if shot is not None else []
        upload_shots: list[bytes] = [f.getvalue() for f in uploads] if uploads else []
        inspection_images: list[bytes] = camera_shots + upload_shots

        # 판독이 끝났으면 그 시점 bbox를 무대에 얹는다 (rerun 대응).
        stage_discrepancies: list[Discrepancy] | None = st.session_state.get(
            "vision_snapshot"
        )
        show_base, show_insp = baseline_images, inspection_images
        if not inspection_images and last_result is not None:
            show_base = st.session_state.get("last_baseline", [])
            show_insp = st.session_state.get("last_inspection", [])

        _render_stage(show_base, show_insp, stage_discrepancies)

        ready = bool(baseline_images and inspection_images)
        note = (
            f"기준 형상 {len(baseline_images)}장 · 점검 대상 {len(inspection_images)}장 등록됨"
            if ready
            else "기준 형상과 점검 대상을 모두 등록해야 점검을 개시할 수 있습니다."
        )
        col_note, col_run = st.columns([3, 1])
        with col_note:
            st.markdown(
                f'<div style="font-size:12px;color:#64748b;padding-top:9px">{note}</div>',
                unsafe_allow_html=True,
            )
        with col_run:
            start = st.button(
                "형상 비교 점검 개시",
                type="primary",
                use_container_width=True,
                disabled=not ready,
            )

    # --- 헤더 (상태가 확정된 뒤 슬롯에 채운다) ---
    if last_error is not None and not start:
        phase, status, tone = "verdict", "점검 중단", "alert"
    elif last_result is not None and not start:
        v, _, _ = _compute_verdict(last_result.items)
        phase = "verdict"
        status = f"판정 완료 · {v}"
        tone = "ok" if v == "GO" else "alert" if v == "NO-GO" else "warn"
    elif ready:
        phase, status, tone = "compare", "점검 개시 대기", "focus"
    else:
        phase, status, tone = "capture", "대상 등록 대기", "gray"
    header_slot.markdown(C.header(phase, status, tone), unsafe_allow_html=True)

    # --- 에이전트 파이프라인 레일 ---
    with st.container(border=True):
        st.markdown(C.section_title("에이전트 파이프라인"), unsafe_allow_html=True)
        rail_slot = st.empty()

    states: dict[str, str] = {s: "idle" for s in STAGE_ORDER}
    if last_result is not None and not start:
        states = {s: "done" for s in STAGE_ORDER}
    rail_slot.markdown(C.agent_rail(states), unsafe_allow_html=True)

    verdict_slot = st.empty()
    term_slot = st.empty()
    logs: list[tuple[str, str]] = []

    # --- 실행 ---
    if start:
        st.session_state.update(
            last_result=None,
            last_error=None,
            vision_snapshot=None,
            last_baseline=baseline_images,
            last_inspection=inspection_images,
        )
        callback = _make_callback(rail_slot, term_slot, states, logs)
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
            failed = next((s for s in STAGE_ORDER if states.get(s) == "fail"), None)
            label = STAGE_LABELS.get(failed, "파이프라인") if failed else "파이프라인"
            error = {
                "message": f"'{label}' 단계에서 점검이 중단되었습니다: {exc}",
                "traceback": traceback.format_exc(),
            }
            st.session_state["last_error"] = error
            _show_error(error)
        else:
            st.session_state["last_result"] = result
            st.session_state["vision_snapshot"] = [it.discrepancy for it in result.items]
            term_slot.empty()
            verdict, part, reason = _compute_verdict(result.items)
            verdict_slot.markdown(
                C.verdict_banner(verdict, part, reason), unsafe_allow_html=True
            )
            _render_tabs(result, settings["inspector_name"], logs)

    elif last_result is not None:
        verdict, part, reason = _compute_verdict(last_result.items)
        verdict_slot.markdown(
            C.verdict_banner(verdict, part, reason), unsafe_allow_html=True
        )
        _render_tabs(last_result, settings["inspector_name"], logs)

    elif last_error is not None:
        _show_error(last_error)


main()

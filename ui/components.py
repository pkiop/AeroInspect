"""AeroInspect 대시보드 HTML 컴포넌트 빌더.

목업(aeroinspect_dashboard.html)의 정적 마크업을 파이프라인 실데이터로
렌더하는 순수 함수 모음. LLM/사용자 유래 문자열은 전부 escape 한다.
"""

from __future__ import annotations

import html
from typing import Any

# 파이프라인 단계 → (번호, 표시명, 설명)
AGENTS: list[tuple[str, str, str, str]] = [
    ("vision", "01", "VisionAgent", "다중 픽셀 대조 검출"),
    ("grounding", "02", "GroundingAgent", "규격서 카탈로그 연동"),
    ("validation", "03", "Validator", "결정론적 규칙 검증"),
    ("report", "04", "Reporter", "감항 보고서 생성"),
]

#: 노드 상태 → (CSS 클래스, 표시 텍스트)
_NODE_STATE: dict[str, tuple[str, str]] = {
    "idle": ("", "READY"),
    "running": ("n-run", "RUNNING"),
    "done": ("n-done", "COMPLETE"),
    "fail": ("n-fail", "FAILED"),
}

_PHASES: list[tuple[str, str]] = [
    ("capture", "01 등록"),
    ("compare", "02 대조"),
    ("verify", "03 검증"),
    ("verdict", "04 판정"),
]


def _e(value: Any) -> str:
    """None-안전 HTML escape."""
    return html.escape(str(value if value is not None else "—"))


# ---------------------------------------------------------------------------
# 헤더
# ---------------------------------------------------------------------------


def header(phase: str, status_text: str, status_tone: str = "gray") -> str:
    """상단 헤더 — 워드마크 + 단계 pill + 상태 pill."""
    reached = [p for p, _ in _PHASES]
    idx = reached.index(phase) if phase in reached else 0
    pills = []
    for i, (key, label) in enumerate(_PHASES):
        cls = "ai-pill-on" if i == idx else ("ai-pill-done" if i < idx else "")
        pills.append(f'<span class="ai-pill {cls}">{_e(label)}</span>')
    return f"""
<div class="ai-hd">
  <div class="ai-hd-l">
    <div class="ai-mark">✈</div>
    <div>
      <div class="ai-wordmark">AEROINSPECT</div>
      <div class="ai-tag">다중 에이전트 감항 검증 터미널</div>
    </div>
  </div>
  <div class="ai-pills">{''.join(pills)}</div>
  <div class="ai-status"><span class="ai-dot d-{_e(status_tone)}"></span>{_e(status_text)}</div>
</div>
"""


def section_title(title: str, note: str = "") -> str:
    """패널 섹션 헤더."""
    right = f'<div class="ai-sec-n">{_e(note)}</div>' if note else ""
    return (
        f'<div class="ai-sec"><div class="ai-sec-t">'
        f'<span class="ai-rulebar"></span>{_e(title)}</div>{right}</div>'
    )


def stage_label(kind: str, text: str) -> str:
    """무대 이미지 위 REF/LIVE 라벨."""
    cls = "ai-lbl-ref" if kind == "ref" else "ai-lbl-live"
    return f'<div class="ai-lbl {cls}">{_e(text)}</div>'


# ---------------------------------------------------------------------------
# 에이전트 레일
# ---------------------------------------------------------------------------


def agent_rail(states: dict[str, str]) -> str:
    """4개 에이전트 노드 + 진행 레일.

    Args:
        states: stage → "idle" | "running" | "done" | "fail"
    """
    done = sum(1 for s, *_ in AGENTS if states.get(s) == "done")
    pct = int(done / len(AGENTS) * 100)
    nodes = []
    for stage, num, name, desc in AGENTS:
        cls, label = _NODE_STATE.get(states.get(stage, "idle"), _NODE_STATE["idle"])
        nodes.append(
            f'<div class="ai-node {cls}">'
            f'<div class="ai-dotn">{num}</div>'
            f'<div><div class="ai-node-name">{_e(name)}</div>'
            f'<div class="ai-node-desc">{_e(desc)}</div>'
            f'<div class="ai-node-st">{label}</div></div></div>'
        )
    return (
        f'<div class="ai-rail"><div class="ai-rail-line">'
        f'<div class="ai-rail-fill" style="width:{pct}%"></div></div>'
        f'<div class="ai-nodes">{"".join(nodes)}</div></div>'
    )


# ---------------------------------------------------------------------------
# 판정 배너
# ---------------------------------------------------------------------------


def verdict_banner(verdict: str, part: str, reason: str) -> str:
    """GO / NO-GO / REVIEW 최종 판정 배너."""
    tone = {"GO": "ai-v-go", "NO-GO": "ai-v-no"}.get(verdict, "ai-v-rev")
    return f"""
<div class="ai-verdict {tone}">
  <div class="ai-v-title">{_e(verdict)}</div>
  <div class="ai-v-rule"></div>
  <div class="ai-v-part">{_e(part)}</div>
  <div class="ai-v-reason">{_e(reason)}</div>
</div>
"""


# ---------------------------------------------------------------------------
# 비전 검출
# ---------------------------------------------------------------------------

_SEVERITY_BADGE: dict[str, str] = {
    "critical": "b-alert",
    "high": "b-alert",
    "medium": "b-warn",
    "low": "b-gray",
}


def discrepancy_table(rows: list[dict[str, Any]]) -> str:
    """검출 판정 데이터 테이블."""
    if not rows:
        return (
            '<div class="ai-tw"><div class="ai-empty">구성 차이 미검출 — '
            "기준 형상과 일치합니다.</div></div>"
        )
    body = []
    for r in rows:
        sev = str(r.get("severity", "low"))
        badge = _SEVERITY_BADGE.get(sev, "b-gray")
        body.append(
            f'<tr><td class="ai-mono">{_e(r.get("id"))}</td>'
            f'<td><span class="ai-bdg {badge}">{_e(r.get("type"))}</span></td>'
            f'<td>{_e(r.get("part"))}</td>'
            f'<td>{_e(r.get("side"))}</td>'
            f'<td class="num">{r.get("confidence", 0):.2f}</td></tr>'
        )
    return f"""
<div class="ai-tw"><table class="ai-tb">
<thead><tr><th>ID</th><th>분류</th><th>부품</th><th>방향</th>
<th style="text-align:right">신뢰도</th></tr></thead>
<tbody>{''.join(body)}</tbody></table></div>
"""


def evidence_box(text: str) -> str:
    """판정 근거 서술 박스."""
    return (
        f'<div class="ai-box" style="margin-top:12px">'
        f'<div class="ai-cap">판정 근거</div>'
        f'<p class="ai-body">{_e(text)}</p></div>'
    )


# ---------------------------------------------------------------------------
# 부품 규격서 / 무결성 검증
# ---------------------------------------------------------------------------


def spec_sheet(rows: list[tuple[str, str]], citations: list[str]) -> str:
    """부품 규격서 카드 — 항목 행 + 인용."""
    body = "".join(
        f'<div class="ai-row"><span class="ai-k">{_e(k)}</span>'
        f'<span class="ai-v">{_e(v)}</span></div>'
        for k, v in rows
    )
    cite = "".join(
        f'<div class="ai-box ai-mono" style="padding:7px 10px;margin-top:5px;'
        f'font-size:10.5px">{_e(c)}</div>'
        for c in citations
    ) or '<div class="ai-body" style="font-size:11.5px">근거 문서 미확정</div>'
    return (
        f'<div class="ai-box">{body}'
        f'<div class="ai-cap" style="margin:12px 0 4px">출처 인용</div>{cite}</div>'
    )


def steps_list(steps: list[str]) -> str:
    """재설치 시방서 절차 목록."""
    if not steps:
        return (
            '<div class="ai-box"><div class="ai-cap">재설치 절차</div>'
            '<p class="ai-body">등재된 절차가 없습니다.</p></div>'
        )
    items = "".join(f"<li>{_e(s)}</li>" for s in steps)
    return (
        f'<div class="ai-box"><div class="ai-cap">재설치 절차</div>'
        f'<ol class="ai-body" style="padding-left:18px;margin:0">{items}</ol></div>'
    )


def flag_item(flag: str, description: str, tone: str) -> str:
    """검증 플래그 1건."""
    return (
        f'<div class="ai-flag f-{_e(tone)}"><div class="ai-fn">{_e(flag)}</div>'
        f'<div class="ai-fd">{_e(description)}</div></div>'
    )


def empty(text: str) -> str:
    """빈 상태 안내."""
    return f'<div class="ai-box"><div class="ai-empty">{_e(text)}</div></div>'


# ---------------------------------------------------------------------------
# 로그 터미널
# ---------------------------------------------------------------------------


def terminal(lines: list[tuple[str, str]]) -> str:
    """로그 터미널 — (tone, text) 목록. tone: ok | err | ''."""
    if not lines:
        lines = [("", "터미널 준비 완료. 점검 대상 등록을 대기합니다.")]
    body = "".join(
        f'<div><span class="t-tag">[{"SYSTEM" if not t else t.upper()}]</span> '
        f'<span class="{"t-" + t if t else ""}">{_e(m)}</span></div>'
        for t, m in lines
    )
    return f'<div class="ai-term">{body}</div>'


# ---------------------------------------------------------------------------
# 감항 보고서 문서
# ---------------------------------------------------------------------------


def report_doc(
    meta_left: list[tuple[str, str]],
    meta_right: list[tuple[str, str]],
    summary: str,
    table_rows: list[list[str]],
    disclaimer: str,
) -> str:
    """백지 문서 룩의 감항 보고서."""

    def _meta(rows: list[tuple[str, str]]) -> str:
        return "".join(
            f'<tr><td class="k">{_e(k)}</td><td class="v">{_e(v)}</td></tr>'
            for k, v in rows
        )

    if table_rows:
        trs = "".join(
            "<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row) + "</tr>"
            for row in table_rows
        )
        table = f"""
<table class="ai-dt"><thead><tr><th>ID</th><th>부품</th><th>P/N</th>
<th>심각도</th><th>조치</th></tr></thead><tbody>{trs}</tbody></table>
"""
    else:
        table = '<p style="font-size:11px;color:#64748b">검출된 이상 형상이 없습니다.</p>'

    return f"""
<div class="ai-doc">
  <div class="ai-doc-h">
    <div class="ai-doc-t">형상 검증 및 부품 감항 보고서</div>
    <div class="ai-doc-s">AEROINSPECT MULTI-AGENT COMPLIANCE REPORT</div>
  </div>
  <div style="display:flex;gap:20px">
    <table class="ai-dm">{_meta(meta_left)}</table>
    <table class="ai-dm">{_meta(meta_right)}</table>
  </div>
  <h3>1. 종합 의견</h3>
  <p>{_e(summary)}</p>
  <h3>2. 이상 검출 형상</h3>
  {table}
  <div class="ai-doc-note">{_e(disclaimer)}</div>
</div>
"""

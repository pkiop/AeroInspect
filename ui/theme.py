"""AeroInspect 테마 — aeroinspect_dashboard.html(시네마틱 단일 무대)의 Streamlit 이식.

컬러 규율 (목업 주석과 동일):
    focus(cyan)  : "지금 봐야 할 곳" 전용 — 활성 에이전트 / 주 CTA.
    alert(red)   : 결함 및 NO-GO 판정 전용.
    ok(green)    : 기준 형상 및 검증 통과 전용.
    그 외 전부   : 회색. 강조색을 아껴야 강조가 작동한다.
"""

from __future__ import annotations

import streamlit as st

INK_900 = "#04060c"
FOCUS = "#00E5FF"
ALERT = "#FF3B3B"
WARN = "#FFB020"
OK = "#22C55E"

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;700&display=swap');

:root {
    --ink-900:#04060c; --ink-800:#080c16; --ink-700:#0d1320; --ink-600:#141c2e; --ink-500:#1e2940;
    --focus:#00E5FF; --alert:#FF3B3B; --warn:#FFB020; --ok:#22C55E;
    --muted:#64748b;
}

/* ── 배경: 상단 타원 글로우 + 격자 ─────────────────────────────── */
[data-testid="stAppViewContainer"] {
    background: radial-gradient(ellipse 90% 60% at 50% -10%, #0f1e3d 0%, transparent 60%), #04060c;
    background-attachment: fixed;
}
[data-testid="stAppViewContainer"]::before {
    content:""; position:fixed; inset:0; z-index:0; pointer-events:none;
    background-size:48px 48px;
    background-image:
        linear-gradient(to right, rgba(255,255,255,.028) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(255,255,255,.028) 1px, transparent 1px);
    -webkit-mask-image: radial-gradient(ellipse 70% 55% at 50% 30%, #000 20%, transparent 75%);
    mask-image: radial-gradient(ellipse 70% 55% at 50% 30%, #000 20%, transparent 75%);
}
[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }

html, body, [class*="css"] { font-family:'Inter',-apple-system,sans-serif; }
.block-container { padding-top:1rem; padding-bottom:2.5rem; max-width:1500px; }

::-webkit-scrollbar { width:10px; height:10px; }
::-webkit-scrollbar-track { background:#04060c; }
::-webkit-scrollbar-thumb { background:#1e2940; border-radius:5px; border:2px solid #04060c; }

/* ── 패널: st.container(border=True) ───────────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {
    background: linear-gradient(160deg, rgba(20,28,46,.72) 0%, rgba(8,12,22,.86) 100%);
    border:1px solid rgba(255,255,255,.07);
    border-top-color: rgba(255,255,255,.11);
    border-radius:16px;
    backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
}

/* ── 오퍼레이터 패널 = 사이드바 ────────────────────────────────── */
[data-testid="stSidebar"] {
    background: rgba(8,12,22,.97);
    border-right:1px solid rgba(255,255,255,.1);
}
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color:#fff; }

/* ── 버튼 ──────────────────────────────────────────────────────── */
.stButton > button, .stDownloadButton > button {
    font-weight:700; font-size:.8rem; border-radius:10px;
    border:1px solid rgba(255,255,255,.1);
    background: rgba(255,255,255,.05); color:#cbd5e1;
    transition: all .25s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    background: rgba(255,255,255,.1); color:#fff; border-color: rgba(255,255,255,.2);
}
.stButton > button:active:not(:disabled) { transform: scale(.97); }
/* 주 CTA만 focus 색 — 규율상 시선 유도는 여기 하나 */
.stButton > button[kind="primary"] {
    background: var(--focus); color:#04060c; border:none; font-weight:800;
    letter-spacing:.03em;
}
.stButton > button[kind="primary"]:hover {
    background:#5cf0ff; color:#04060c; box-shadow:0 0 28px rgba(0,229,255,.45);
}
.stButton > button:disabled { background: rgba(255,255,255,.03); color:#475569; }

/* ── 입력 ──────────────────────────────────────────────────────── */
[data-testid="stTextInput"] input,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
    background: rgba(0,0,0,.4) !important;
    border:1px solid rgba(255,255,255,.1) !important;
    border-radius:8px !important; color:#cbd5e1 !important; font-size:.78rem !important;
}
[data-testid="stWidgetLabel"] p { font-size:.72rem !important; color:var(--muted) !important; font-weight:600; }
[data-testid="stFileUploaderDropzone"] {
    background: rgba(0,0,0,.3); border:1px dashed rgba(255,255,255,.12); border-radius:12px;
}
[data-testid="stFileUploaderDropzone"]:hover { border-color: rgba(0,229,255,.5); }
[data-testid="stImage"] img { border-radius:10px; background:#05070d; }
[data-testid="stImageCaption"] { font-size:.68rem !important; color:var(--muted) !important; }

/* ── 탭 ────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    gap:0; background: rgba(0,0,0,.25);
    border-bottom:1px solid rgba(255,255,255,.07); border-radius:12px 12px 0 0;
}
.stTabs [data-baseweb="tab"] {
    flex:1; justify-content:center; font-size:.75rem; font-weight:700;
    letter-spacing:.03em; color:var(--muted); border-bottom:2px solid transparent; padding:13px 8px;
}
.stTabs [aria-selected="true"] { color:var(--focus) !important; border-bottom:2px solid var(--focus) !important; }
.stTabs [data-baseweb="tab-highlight"] { display:none; }

/* ── 헤더 ──────────────────────────────────────────────────────── */
.ai-hd {
    display:flex; align-items:center; justify-content:space-between; gap:20px; flex-wrap:wrap;
    border-bottom:1px solid rgba(255,255,255,.07); padding:0 2px 14px; margin-bottom:18px;
}
.ai-hd-l { display:flex; align-items:center; gap:12px; }
.ai-mark {
    width:36px; height:36px; border-radius:9px;
    background: linear-gradient(135deg,#f1f5f9,#94a3b8);
    display:flex; align-items:center; justify-content:center; font-size:17px;
}
.ai-wordmark { font-size:15px; font-weight:900; letter-spacing:.16em; color:#fff; line-height:1.25; }
.ai-tag { font-size:11px; color:var(--muted); letter-spacing:.02em; }

.ai-pills { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
.ai-pill {
    font-size:11px; font-weight:700; padding:5px 10px; border-radius:6px;
    color:#475569; font-family:'JetBrains Mono',monospace; letter-spacing:.04em;
}
.ai-pill-on { background: rgba(0,229,255,.12); color:var(--focus); }
.ai-pill-done { color:#64748b; }

.ai-status {
    display:inline-flex; align-items:center; gap:7px; padding:6px 12px; border-radius:999px;
    border:1px solid rgba(255,255,255,.1); background: rgba(255,255,255,.03);
    font-size:11px; font-weight:700; letter-spacing:.03em; color:#94a3b8;
}
.ai-dot { width:7px; height:7px; border-radius:50%; display:inline-block; }
.d-ok { background:var(--ok); box-shadow:0 0 8px var(--ok); }
.d-focus { background:var(--focus); box-shadow:0 0 8px var(--focus); }
.d-alert { background:var(--alert); box-shadow:0 0 8px var(--alert); }
.d-warn { background:var(--warn); box-shadow:0 0 8px var(--warn); }
.d-gray { background:#475569; }

/* ── 섹션 타이틀 ───────────────────────────────────────────────── */
.ai-sec { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; }
.ai-sec-t { font-size:13px; font-weight:700; letter-spacing:.02em; color:#cbd5e1; display:flex; align-items:center; gap:9px; }
.ai-sec-n { font-size:12px; color:var(--muted); }
.ai-rulebar { width:3px; height:14px; border-radius:2px; background:var(--focus); display:inline-block; }

/* ── 무대 라벨 ─────────────────────────────────────────────────── */
.ai-lbl {
    display:inline-flex; align-items:center; gap:6px; padding:5px 9px; border-radius:6px;
    background: rgba(4,6,12,.85); font-size:11px; font-weight:700; letter-spacing:.06em;
    font-family:'JetBrains Mono',monospace; margin-bottom:6px;
}
.ai-lbl-ref { border:1px solid rgba(34,197,94,.25); color:var(--ok); }
.ai-lbl-live { border:1px solid rgba(255,255,255,.15); color:#cbd5e1; }

/* ── 에이전트 레일 ─────────────────────────────────────────────── */
.ai-rail { position:relative; margin:6px 0 2px; }
.ai-rail-line {
    position:absolute; top:19px; left:12.5%; right:12.5%; height:2px;
    background:var(--ink-500); border-radius:999px; overflow:hidden;
}
.ai-rail-fill { height:100%; background:var(--focus); border-radius:999px; transition:width .5s ease; }
.ai-nodes { position:relative; display:grid; grid-template-columns:repeat(4,1fr); gap:8px; }
.ai-node { display:flex; flex-direction:column; align-items:center; text-align:center; gap:7px; }
.ai-dotn {
    width:40px; height:40px; border-radius:50%;
    border:1px solid var(--ink-500); background:var(--ink-800); color:#475569;
    display:flex; align-items:center; justify-content:center;
    font-family:'JetBrains Mono',monospace; font-size:12px; font-weight:700;
    transition: all .3s ease;
}
.ai-node-name { font-size:12.5px; font-weight:700; color:#475569; }
.ai-node-desc { font-size:11px; color:#475569; }
.ai-node-st { font-size:10px; font-weight:700; letter-spacing:.09em; font-family:'JetBrains Mono',monospace; color:#334155; }
/* 활성 노드만 focus — 나머지는 회색 유지 */
.n-run .ai-dotn { border-color:var(--focus); color:var(--focus); box-shadow:0 0 20px rgba(0,229,255,.35); }
.n-run .ai-node-name, .n-run .ai-node-st { color:var(--focus); }
.n-done .ai-dotn { border-color:rgba(34,197,94,.5); color:var(--ok); }
.n-done .ai-node-name { color:#94a3b8; }
.n-done .ai-node-st { color:var(--ok); }
.n-fail .ai-dotn { border-color:var(--alert); color:var(--alert); }
.n-fail .ai-node-name, .n-fail .ai-node-st { color:var(--alert); }

/* ── 판정 배너 ─────────────────────────────────────────────────── */
@keyframes slam { 0%{transform:scale(1.35);opacity:0} 60%{transform:scale(.97);opacity:1} 100%{transform:scale(1)} }
.ai-verdict {
    text-align:center; padding:26px 20px; border-radius:16px;
    animation: slam .55s cubic-bezier(.2,1.15,.35,1) both;
}
.ai-v-go { background: rgba(34,197,94,.07); border:1px solid rgba(34,197,94,.3); }
.ai-v-no { background: rgba(255,59,59,.07); border:1px solid rgba(255,59,59,.35); }
.ai-v-rev { background: rgba(255,176,32,.07); border:1px solid rgba(255,176,32,.3); }
.ai-v-title { font-size:clamp(40px,7vw,84px); font-weight:900; line-height:.95; letter-spacing:-.02em; margin:0; }
.ai-v-go .ai-v-title { color:var(--ok); }
.ai-v-no .ai-v-title { color:var(--alert); }
.ai-v-rev .ai-v-title { color:var(--warn); }
.ai-v-rule { height:3px; max-width:340px; margin:14px auto; border-radius:2px; }
.ai-v-go .ai-v-rule { background:var(--ok); }
.ai-v-no .ai-v-rule { background:var(--alert); }
.ai-v-rev .ai-v-rule { background:var(--warn); }
.ai-v-part { font-size:clamp(15px,2vw,22px); font-weight:700; color:#fff; }
.ai-v-reason { font-size:13px; color:#94a3b8; max-width:640px; margin:8px auto 0; line-height:1.7; }

/* ── 테이블 ────────────────────────────────────────────────────── */
.ai-tw { border:1px solid rgba(255,255,255,.07); border-radius:10px; overflow:hidden; background:rgba(0,0,0,.25); }
.ai-tb { width:100%; border-collapse:collapse; font-size:12.5px; }
.ai-tb thead tr { background:rgba(255,255,255,.03); color:var(--muted); font-size:10.5px; letter-spacing:.08em; text-transform:uppercase; }
.ai-tb th { padding:10px 14px; text-align:left; font-weight:700; }
.ai-tb td { padding:10px 14px; border-top:1px solid rgba(255,255,255,.06); color:#cbd5e1; }
.ai-tb .num { text-align:right; font-family:'JetBrains Mono',monospace; }

/* ── 배지 ──────────────────────────────────────────────────────── */
.ai-bdg { display:inline-block; padding:2px 8px; border-radius:5px; font-size:10.5px; font-weight:700; letter-spacing:.03em; }
.b-alert { background:rgba(255,59,59,.14); color:#ff8f8f; border:1px solid rgba(255,59,59,.3); }
.b-warn  { background:rgba(255,176,32,.14); color:#ffd08a; border:1px solid rgba(255,176,32,.3); }
.b-ok    { background:rgba(34,197,94,.14); color:#6ee7a0; border:1px solid rgba(34,197,94,.3); }
.b-gray  { background:rgba(148,163,184,.12); color:#94a3b8; border:1px solid rgba(148,163,184,.25); }

/* ── 소형 박스 ─────────────────────────────────────────────────── */
.ai-box { background:rgba(0,0,0,.25); border:1px solid rgba(255,255,255,.07); border-radius:10px; padding:14px 16px; }
.ai-cap { font-size:11px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); margin-bottom:8px; }
.ai-body { font-size:12.5px; color:#94a3b8; line-height:1.75; margin:0; }
.ai-row { display:flex; justify-content:space-between; gap:12px; padding:7px 0; border-bottom:1px solid rgba(255,255,255,.06); font-size:12.5px; }
.ai-row:last-child { border-bottom:none; }
.ai-k { color:var(--muted); }
.ai-v { color:#fff; font-weight:600; text-align:right; }
.ai-mono { font-family:'JetBrains Mono',monospace; }
.ai-empty { text-align:center; padding:34px 16px; color:#475569; font-size:12px; }

/* ── 플래그 ────────────────────────────────────────────────────── */
.ai-flag { border-radius:8px; padding:10px 13px; margin-bottom:7px; font-size:12.5px; border-left:3px solid; }
.f-alert { background:rgba(255,59,59,.08); border-left-color:var(--alert); color:#fecaca; }
.f-warn  { background:rgba(255,176,32,.08); border-left-color:var(--warn); color:#fde3b0; }
.f-gray  { background:rgba(148,163,184,.06); border-left-color:#475569; color:#cbd5e1; }
.ai-fn { font-weight:700; font-family:'JetBrains Mono',monospace; }
.ai-fd { color:#94a3b8; font-size:11.5px; margin-top:2px; }

/* ── 터미널 ────────────────────────────────────────────────────── */
.ai-term {
    background:rgba(0,0,0,.6); border:1px solid rgba(255,255,255,.07); border-radius:10px;
    padding:14px 16px; font-family:'JetBrains Mono',monospace; font-size:11.5px;
    line-height:1.85; color:#94a3b8; max-height:300px; overflow-y:auto;
}
.t-tag { color:#475569; }
.t-ok { color:var(--ok); }
.t-err { color:var(--alert); }

/* ── 보고서 문서 ───────────────────────────────────────────────── */
.ai-doc {
    background:#fff; color:#0f172a; border-radius:10px; padding:28px 32px;
    max-height:400px; overflow-y:auto; font-size:12px; line-height:1.75;
}
.ai-doc-h { text-align:center; border-bottom:2px double #94a3b8; padding-bottom:12px; margin-bottom:16px; }
.ai-doc-t { font-size:17px; font-weight:900; letter-spacing:.12em; }
.ai-doc-s { font-size:9.5px; color:#64748b; margin-top:4px; letter-spacing:.14em; }
.ai-doc h3 { font-size:12.5px; font-weight:700; border-left:4px solid #1e293b; padding-left:8px; margin:16px 0 6px; }
.ai-doc p { color:#334155; font-size:11.5px; margin:0; }
.ai-dm { width:100%; font-size:11px; }
.ai-dm .k { font-weight:700; width:88px; padding:2px 0; }
.ai-dm .v { color:#334155; }
.ai-dt { width:100%; border-collapse:collapse; font-size:10px; margin-top:6px; }
.ai-dt th, .ai-dt td { border:1px solid #cbd5e1; padding:5px 7px; text-align:left; }
.ai-dt th { background:#f1f5f9; font-weight:700; }
.ai-doc-note { font-size:9.5px; color:#94a3b8; border-top:1px solid #e2e8f0; padding-top:8px; margin-top:14px; }
</style>
"""


def inject() -> None:
    """전역 CSS 주입 (스크립트 실행마다 1회)."""
    st.markdown(_CSS, unsafe_allow_html=True)

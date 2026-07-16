"""GroundingAgent — 탐지된 차이(Discrepancy)를 가상 부품 카탈로그에 대조한다.

1차 경로: Gemini File Search 스토어 질의 후 구조화 추출 (2단계 호출 —
툴 사용과 response_schema는 한 호출에 결합할 수 없음).
2차 경로(폴백): ``config.CATALOG_DIR`` 의 카탈로그 문서 전체를 롱컨텍스트로
직접 주입해 동일 추출.

폴백 전환 조건:
- ``store_name`` 이 없음
- File Search 경로 호출 중 예외 발생
- File Search 응답의 grounding_chunks가 비어 있음

부품이 카탈로그에 없어 ``found=False`` 인 것은 폴백 사유가 아니며,
그대로 반환한다 (단, ``found=False`` 면 ``part_number=None`` /
``installation_steps=[]`` / ``reference_docs=[]`` 를 코드에서 강제).
"""

from __future__ import annotations

import logging
import re

from google.genai import types

from core import config, llm
from core.schemas import Discrepancy, PartRecord, RefDoc

logger = logging.getLogger("aeroinspect.grounding")

_AGENT_NAME = "grounding"

#: 인용 section 폴백 시 스니펫 첫 줄에서 취하는 최대 길이
_SECTION_FALLBACK_LEN = 40

#: 환각 방지 시스템 프롬프트 (1차/2차 경로 공용)
_SYSTEM_INSTRUCTION = (
    "너는 항공기 축소 모형의 부품 카탈로그(mini-IPC) 조회 담당자다. "
    "반드시 제공된 카탈로그 내용에 근거해서만 답하라. "
    "카탈로그에 없는 P/N(부품번호)·절차·수치를 만들어내지 말 것. "
    "카탈로그에서 해당 부품을 찾지 못하면 found=false로 반환할 것."
)


def _build_query(discrepancy: Discrepancy) -> str:
    """discrepancy로부터 카탈로그 검색 질의문을 만든다."""
    name_en = discrepancy.component_name_en or "미상(부품명으로 추정)"
    return (
        f"부품명(한국어): {discrepancy.component_name_ko}\n"
        f"부품명(영어, 추정): {name_en}\n"
        f"항공기 기준 좌/우: {discrepancy.aircraft_side}\n\n"
        "위 부품을 부품 카탈로그에서 찾아 다음 정보를 확인하라: "
        "P/N(부품번호), 장착 위치, flight critical 여부, 장착 절차, "
        "누락 시 조치(disposition), 참조 문서."
    )


def _extract_section(snippet: str) -> str:
    """스니펫에서 인용 section 문자열을 결정론적으로 뽑는다.

    첫 번째 마크다운 헤딩("## ..." 또는 "### ...")을 사용하고,
    없으면 스니펫 첫 줄의 앞 40자를 사용한다.
    """
    match = re.search(r"^#{2,3}\s+(.+?)\s*$", snippet, flags=re.MULTILINE)
    if match:
        return match.group(1).strip()
    first_line = snippet.strip().splitlines()[0] if snippet.strip() else ""
    return first_line[:_SECTION_FALLBACK_LEN]


def _extract_grounding(
    response: types.GenerateContentResponse,
) -> tuple[list[RefDoc], list[str]]:
    """File Search 응답에서 (결정론적 RefDoc 목록, 스니펫 목록)을 뽑는다.

    grounding_metadata / grounding_chunks / retrieved_context 가 각각
    None일 수 있으므로 방어적으로 접근한다. RefDoc은 (doc, section)
    기준으로 중복을 제거한다.
    """
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return [], []
    metadata = getattr(candidates[0], "grounding_metadata", None)
    chunks = getattr(metadata, "grounding_chunks", None) if metadata else None
    if not chunks:
        return [], []

    ref_docs: list[RefDoc] = []
    snippets: list[str] = []
    seen: set[tuple[str, str]] = set()
    for chunk in chunks:
        context = getattr(chunk, "retrieved_context", None)
        if context is None:
            continue
        doc = getattr(context, "title", None) or "unknown"
        text = getattr(context, "text", None) or ""
        section = _extract_section(text)
        if text:
            snippets.append(text)
        key = (doc, section)
        if key not in seen:
            seen.add(key)
            ref_docs.append(RefDoc(doc=doc, section=section))
    return ref_docs, snippets


def _normalize_not_found(record: PartRecord) -> PartRecord:
    """``found=False`` 레코드의 파생 필드를 코드에서 강제로 비운다."""
    if not record.found:
        record.part_number = None
        record.installation_steps = []
        record.reference_docs = []
    return record


class GroundingAgent:
    """component_name_ko + aircraft_side로 부품 카탈로그를 조회하는 에이전트."""

    def __init__(self, model: str, store_name: str | None = None) -> None:
        """
        Args:
            model: Gemini 모델명 (하드코딩 금지 — 호출자가 주입)
            store_name: File Search 스토어 리소스 이름
                (``fileSearchStores/...``). None이면 롱컨텍스트 폴백만 사용.
        """
        self.model = model
        self.store_name = store_name

    async def lookup(self, discrepancy: Discrepancy) -> PartRecord:
        """discrepancy 1건에 대한 부품 카탈로그 레코드를 조회한다.

        1차 File Search 경로가 불가하면 롱컨텍스트 폴백으로 전환한다.
        """
        if self.store_name:
            try:
                record = await self._lookup_via_file_search(discrepancy)
                if record is not None:
                    return record
                logger.warning(
                    "[%s] grounding_chunks 비어 있음 — 롱컨텍스트 폴백 전환",
                    discrepancy.discrepancy_id,
                )
            except Exception as exc:  # noqa: BLE001 — 폴백으로 항상 복구
                logger.warning(
                    "[%s] File Search 경로 실패(%s) — 롱컨텍스트 폴백 전환",
                    discrepancy.discrepancy_id,
                    exc,
                )
        return await self._lookup_via_fallback(discrepancy)

    # ------------------------------------------------------------------
    # 1차 경로: File Search
    # ------------------------------------------------------------------

    async def _lookup_via_file_search(
        self, discrepancy: Discrepancy
    ) -> PartRecord | None:
        """File Search 스토어 질의 → 구조화 추출 (2단계 호출).

        Returns:
            PartRecord — 성공 시. grounding_chunks가 비어 있으면 None
            (호출자가 폴백으로 전환).
        """
        assert self.store_name is not None
        tool = types.Tool(
            file_search=types.FileSearch(file_search_store_names=[self.store_name])
        )
        # (a) File Search 툴로 카탈로그 검색
        response = await llm.agenerate_text(
            agent=_AGENT_NAME,
            model=self.model,
            contents=[_build_query(discrepancy)],
            tools=[tool],
            system_instruction=_SYSTEM_INSTRUCTION,
        )

        # (b) 인용(RefDoc)은 코드로 결정론적으로 구축
        ref_docs, snippets = _extract_grounding(response)
        if not ref_docs:
            return None  # 폴백 전환 조건: grounding_chunks 비어 있음

        # (c) 검색 응답 텍스트 + 스니펫을 컨텍스트로 구조화 추출
        answer_text = getattr(response, "text", None) or ""
        snippet_block = "\n\n".join(
            f"[스니펫 {i + 1}]\n{s}" for i, s in enumerate(snippets)
        )
        extraction_context = (
            f"{_build_query(discrepancy)}\n\n"
            f"=== 카탈로그 검색 답변 ===\n{answer_text}\n\n"
            f"=== 카탈로그 검색 스니펫 ===\n{snippet_block}\n\n"
            "위 검색 결과에 근거하여 이 부품의 카탈로그 레코드를 추출하라."
        )
        record: PartRecord = await llm.agenerate_structured(
            agent=_AGENT_NAME,
            model=self.model,
            contents=[extraction_context],
            response_schema=PartRecord,
            system_instruction=_SYSTEM_INSTRUCTION,
        )
        # 인용은 LLM 출력 대신 (b)의 결정론적 인용으로 덮어쓴다 (환각 차단)
        record.reference_docs = ref_docs
        record.via_fallback = False
        return _normalize_not_found(record)

    # ------------------------------------------------------------------
    # 2차 경로: 롱컨텍스트 폴백
    # ------------------------------------------------------------------

    def _load_catalog(self) -> tuple[str, list[str]]:
        """카탈로그 *.md 전체를 (합본 컨텍스트, 실제 파일명 목록)으로 읽는다."""
        paths = sorted(config.CATALOG_DIR.glob("*.md"))
        filenames: list[str] = []
        blocks: list[str] = []
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("카탈로그 파일 읽기 실패(%s): %s", path.name, exc)
                continue
            filenames.append(path.name)
            blocks.append(f"=== 문서: {path.name} ===\n{text}")
        return "\n\n".join(blocks), filenames

    async def _lookup_via_fallback(self, discrepancy: Discrepancy) -> PartRecord:
        """카탈로그 문서 전체를 롱컨텍스트로 주입해 PartRecord를 추출한다."""
        catalog_context, filenames = self._load_catalog()
        if not filenames:
            logger.warning(
                "카탈로그 디렉토리(%s)에 문서가 없음 — found=False 반환",
                config.CATALOG_DIR,
            )
            return PartRecord(
                found=False,
                name_ko=discrepancy.component_name_ko,
                name_en=discrepancy.component_name_en or "",
                via_fallback=True,
            )

        extraction_context = (
            f"{_build_query(discrepancy)}\n\n"
            f"=== 부품 카탈로그 전체 ===\n{catalog_context}\n\n"
            "위 카탈로그에 근거하여 이 부품의 카탈로그 레코드를 추출하라. "
            "reference_docs의 doc에는 반드시 위 '=== 문서: ... ===' 구분자에 "
            "표기된 실제 파일명만 사용하라."
        )
        record: PartRecord = await llm.agenerate_structured(
            agent=_AGENT_NAME,
            model=self.model,
            contents=[extraction_context],
            response_schema=PartRecord,
            system_instruction=_SYSTEM_INSTRUCTION,
        )
        record.via_fallback = True
        # 실제 파일명 목록에 없는 doc 인용은 코드에서 제거 (환각 차단)
        valid = set(filenames)
        record.reference_docs = [r for r in record.reference_docs if r.doc in valid]
        return _normalize_not_found(record)

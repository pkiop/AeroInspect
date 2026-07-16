"""공용 Gemini 호출 래퍼.

모든 에이전트의 Gemini 호출은 이 모듈을 통해 이루어진다:

- 요청 타임아웃 (``http_options.timeout``)
- 전송 오류 시 지수 백오프 재시도 1회
- 구조화 출력 파싱 실패 시 동일 요청 1회 재시도, 재실패 시 원문 로깅 후 중단
- 호출별 사용 토큰 수를 ``logs/gemini_calls.jsonl`` 에 기록

비밀값(API 키)은 절대 로그에 남기지 않는다.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
import time
from typing import Any, Sequence, TypeVar

from google.genai import errors as genai_errors
from google.genai import types
from pydantic import TypeAdapter

from core.config import LOGS_DIR, REQUEST_TIMEOUT_MS, get_client

logger = logging.getLogger("aeroinspect.llm")

T = TypeVar("T")

#: 전송 오류 백오프 대기(초) — 1회 재시도
_TRANSPORT_BACKOFF_SEC = 2.0


class StructuredCallError(RuntimeError):
    """구조화 출력 파싱이 재시도 후에도 실패했을 때 발생."""


def _usage_log_path() -> str:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return str(LOGS_DIR / f"gemini_calls_{_dt.date.today():%Y%m%d}.jsonl")


def _log_usage(agent: str, model: str, response: Any, note: str = "") -> None:
    """호출별 토큰 사용량을 JSONL로 기록한다 (프롬프트 원문/키는 기록하지 않음)."""
    usage = getattr(response, "usage_metadata", None)
    entry = {
        "ts": _dt.datetime.now().isoformat(timespec="seconds"),
        "agent": agent,
        "model": model,
        "prompt_tokens": getattr(usage, "prompt_token_count", None),
        "output_tokens": getattr(usage, "candidates_token_count", None),
        "total_tokens": getattr(usage, "total_token_count", None),
        "note": note,
    }
    try:
        with open(_usage_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:  # 로깅 실패가 파이프라인을 중단시키면 안 됨
        logger.warning("토큰 사용량 로깅 실패: %s", exc)


def _build_config(
    *,
    response_schema: Any | None = None,
    system_instruction: str | None = None,
    tools: list[types.Tool] | None = None,
    temperature: float = 0.0,
) -> types.GenerateContentConfig:
    """공통 GenerateContentConfig 조립 (타임아웃 포함)."""
    kwargs: dict[str, Any] = {
        "temperature": temperature,
        "http_options": types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
    }
    if system_instruction is not None:
        kwargs["system_instruction"] = system_instruction
    if tools is not None:
        kwargs["tools"] = tools
    if response_schema is not None:
        kwargs["response_mime_type"] = "application/json"
        kwargs["response_schema"] = response_schema
    return types.GenerateContentConfig(**kwargs)


def _parse_structured(response: Any, response_schema: Any) -> Any:
    """SDK parsed 결과 우선, 실패 시 response.text를 직접 검증한다."""
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        return parsed
    text = getattr(response, "text", None)
    if not text:
        raise ValueError("응답 본문이 비어 있음")
    return TypeAdapter(response_schema).validate_json(text)


def _is_retryable_transport_error(exc: Exception) -> bool:
    """일시적 전송/서버 오류인지 판정 (429/5xx/타임아웃)."""
    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None)
        return code in (429, 500, 502, 503, 504)
    return isinstance(exc, (TimeoutError, ConnectionError))


def _call_with_transport_retry(agent: str, fn: Any) -> Any:
    """전송 오류 시 지수 백오프로 1회 재시도."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        if not _is_retryable_transport_error(exc):
            raise
        logger.warning("[%s] 일시적 오류, %.1fs 후 재시도: %s", agent, _TRANSPORT_BACKOFF_SEC, exc)
        time.sleep(_TRANSPORT_BACKOFF_SEC)
        return fn()


async def _acall_with_transport_retry(agent: str, fn: Any) -> Any:
    """비동기 버전 — 전송 오류 시 지수 백오프로 1회 재시도."""
    try:
        return await fn()
    except Exception as exc:  # noqa: BLE001
        if not _is_retryable_transport_error(exc):
            raise
        logger.warning("[%s] 일시적 오류, %.1fs 후 재시도: %s", agent, _TRANSPORT_BACKOFF_SEC, exc)
        await asyncio.sleep(_TRANSPORT_BACKOFF_SEC)
        return await fn()


# ---------------------------------------------------------------------------
# 공개 API — 동기
# ---------------------------------------------------------------------------


def generate_structured(
    *,
    agent: str,
    model: str,
    contents: Sequence[Any],
    response_schema: Any,
    system_instruction: str | None = None,
    temperature: float = 0.0,
) -> Any:
    """구조화 출력 호출. 파싱 실패 시 동일 요청 1회 재시도.

    재시도 후에도 실패하면 응답 원문을 로그에 남기고
    :class:`StructuredCallError` 를 발생시킨다.
    """
    config = _build_config(
        response_schema=response_schema,
        system_instruction=system_instruction,
        temperature=temperature,
    )
    client = get_client()
    last_text: str | None = None
    for attempt in (1, 2):
        response = _call_with_transport_retry(
            agent,
            lambda: client.models.generate_content(
                model=model, contents=list(contents), config=config
            ),
        )
        _log_usage(agent, model, response, note=f"structured attempt={attempt}")
        try:
            return _parse_structured(response, response_schema)
        except Exception as exc:  # noqa: BLE001
            last_text = getattr(response, "text", None)
            logger.warning("[%s] 구조화 출력 파싱 실패(시도 %d): %s", agent, attempt, exc)
    logger.error("[%s] 구조화 출력 최종 실패. 응답 원문:\n%s", agent, last_text)
    raise StructuredCallError(f"[{agent}] 구조화 출력 파싱이 재시도 후에도 실패했습니다.")


def generate_text(
    *,
    agent: str,
    model: str,
    contents: Sequence[Any],
    system_instruction: str | None = None,
    tools: list[types.Tool] | None = None,
    temperature: float = 0.0,
) -> types.GenerateContentResponse:
    """자유 텍스트(또는 툴 사용) 호출 — 원본 응답을 반환한다.

    File Search처럼 grounding_metadata가 필요한 경우 사용.
    """
    config = _build_config(
        system_instruction=system_instruction, tools=tools, temperature=temperature
    )
    client = get_client()
    response = _call_with_transport_retry(
        agent,
        lambda: client.models.generate_content(
            model=model, contents=list(contents), config=config
        ),
    )
    _log_usage(agent, model, response, note="text")
    return response


# ---------------------------------------------------------------------------
# 공개 API — 비동기 (client.aio)
# ---------------------------------------------------------------------------


async def agenerate_structured(
    *,
    agent: str,
    model: str,
    contents: Sequence[Any],
    response_schema: Any,
    system_instruction: str | None = None,
    temperature: float = 0.0,
) -> Any:
    """:func:`generate_structured` 의 비동기 버전 (``client.aio``)."""
    config = _build_config(
        response_schema=response_schema,
        system_instruction=system_instruction,
        temperature=temperature,
    )
    client = get_client()
    last_text: str | None = None
    for attempt in (1, 2):
        response = await _acall_with_transport_retry(
            agent,
            lambda: client.aio.models.generate_content(
                model=model, contents=list(contents), config=config
            ),
        )
        _log_usage(agent, model, response, note=f"structured attempt={attempt}")
        try:
            return _parse_structured(response, response_schema)
        except Exception as exc:  # noqa: BLE001
            last_text = getattr(response, "text", None)
            logger.warning("[%s] 구조화 출력 파싱 실패(시도 %d): %s", agent, attempt, exc)
    logger.error("[%s] 구조화 출력 최종 실패. 응답 원문:\n%s", agent, last_text)
    raise StructuredCallError(f"[{agent}] 구조화 출력 파싱이 재시도 후에도 실패했습니다.")


async def agenerate_text(
    *,
    agent: str,
    model: str,
    contents: Sequence[Any],
    system_instruction: str | None = None,
    tools: list[types.Tool] | None = None,
    temperature: float = 0.0,
) -> types.GenerateContentResponse:
    """:func:`generate_text` 의 비동기 버전 (``client.aio``)."""
    config = _build_config(
        system_instruction=system_instruction, tools=tools, temperature=temperature
    )
    client = get_client()
    response = await _acall_with_transport_retry(
        agent,
        lambda: client.aio.models.generate_content(
            model=model, contents=list(contents), config=config
        ),
    )
    _log_usage(agent, model, response, note="text")
    return response


def image_part(data: bytes, mime_type: str = "image/jpeg") -> types.Part:
    """이미지 bytes를 Gemini 멀티모달 Part로 변환."""
    return types.Part.from_bytes(data=data, mime_type=mime_type)

"""이미지 어노테이션 유틸 — bbox 오버레이 (보고서/UI 공용).

Pillow로 정규화 bbox([x0,y0,x1,y1], 0~1)를 그리고 라벨을 붙인다.
한국어 라벨을 위해 시스템 한글 폰트를 탐색하고, 없으면 영문 라벨로
대체한다(기본 비트맵 폰트는 한글 미지원).
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

#: 플랫폼별 한글 지원 폰트 후보 경로
_KOREAN_FONT_CANDIDATES: tuple[str, ...] = (
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",  # macOS
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",  # macOS
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",  # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Linux
    "C:/Windows/Fonts/malgun.ttf",  # Windows
)


@lru_cache(maxsize=1)
def _korean_font_path() -> str | None:
    """사용 가능한 한글 폰트 경로를 찾는다 (없으면 None)."""
    for candidate in _KOREAN_FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def _load_font(size: int) -> tuple[ImageFont.ImageFont | ImageFont.FreeTypeFont, bool]:
    """(폰트, 한글지원여부) 반환."""
    path = _korean_font_path()
    if path:
        try:
            return ImageFont.truetype(path, size=size), True
        except OSError:
            pass
    return ImageFont.load_default(), False


def to_png_bytes(image: Image.Image) -> bytes:
    """PIL 이미지를 PNG bytes로 직렬화."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def annotate_bbox(
    image_bytes: bytes,
    bbox: list[float] | None,
    label_ko: str,
    label_en: str,
    color: tuple[int, int, int] = (220, 40, 40),
) -> bytes:
    """이미지에 정규화 bbox와 라벨을 그려 PNG bytes로 반환.

    Args:
        image_bytes: 원본 이미지 (jpg/png bytes)
        bbox: ``[x0, y0, x1, y1]`` 0~1 정규화 좌표. None이면 원본에
            라벨 배너만 붙인다.
        label_ko: 한국어 라벨 (예: "누락 위치")
        label_en: 한글 폰트가 없을 때 대체할 영문 라벨
        color: 박스/배너 색 (RGB)
    """
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    w, h = image.size
    line_width = max(3, round(min(w, h) * 0.006))
    font, korean_ok = _load_font(size=max(16, round(min(w, h) * 0.035)))
    label = label_ko if korean_ok else label_en

    if bbox is not None:
        x0, y0, x1, y1 = (
            bbox[0] * w,
            bbox[1] * h,
            bbox[2] * w,
            bbox[3] * h,
        )
        # 좌표 정렬(모델이 뒤집힌 좌표를 줄 수 있음)
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        draw.rectangle([x0, y0, x1, y1], outline=color, width=line_width)

        # 라벨 배너 — 박스 위쪽(공간 없으면 아래쪽)
        text_bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
        pad = round(th * 0.4)
        banner_h = th + pad * 2
        by = y0 - banner_h if y0 - banner_h >= 0 else min(y1, h - banner_h)
        bx = min(max(x0, 0), max(w - (tw + pad * 2), 0))
        draw.rectangle([bx, by, bx + tw + pad * 2, by + banner_h], fill=color)
        draw.text((bx + pad, by + pad - text_bbox[1]), label, fill=(255, 255, 255), font=font)
    else:
        # bbox 없음 — 상단 배너만
        text_bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
        pad = round(th * 0.4)
        draw.rectangle([0, 0, tw + pad * 2, th + pad * 2], fill=color)
        draw.text((pad, pad - text_bbox[1]), label, fill=(255, 255, 255), font=font)

    return to_png_bytes(image)


def annotate_baseline(image_bytes: bytes, bbox: list[float] | None) -> bytes:
    """기준 이미지 오버레이 — '정상 장착 상태' (녹색)."""
    return annotate_bbox(
        image_bytes, bbox, "정상 장착 상태", "BASELINE: INSTALLED", color=(30, 150, 60)
    )


def annotate_inspection(image_bytes: bytes, bbox: list[float] | None) -> bytes:
    """점검 이미지 오버레이 — '누락 위치' (적색)."""
    return annotate_bbox(
        image_bytes, bbox, "누락 위치", "MISSING HERE", color=(220, 40, 40)
    )

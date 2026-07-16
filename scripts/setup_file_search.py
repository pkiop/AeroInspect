"""Gemini File Search 스토어 셋업 스크립트 (멱등 실행).

- display_name "aeroinspect-parts-catalog" 스토어를 찾고, 없으면 생성한다.
- 신규 생성 시 ``data/parts_catalog/*.md`` 전부를 업로드하고 인덱싱 완료까지
  대기한다. 기존 스토어 재사용 시 업로드는 생략한다.
- ``--force-reupload`` 플래그로 기존 스토어를 삭제 후 재생성할 수 있다.
- 완료 후 스토어 리소스 이름을 프로젝트 루트 ``.env`` 의
  ``AEROINSPECT_FILE_SEARCH_STORE=`` 라인에 멱등하게 기록한다.

실행: ``python scripts/setup_file_search.py [--force-reupload]``
(API 키 등 비밀값은 절대 출력하지 않는다.)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

# "python scripts/setup_file_search.py" 직접 실행을 위해 프로젝트 루트를 sys.path에 추가
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core import config  # noqa: E402

#: File Search 스토어 표시명 (멱등 매칭 키)
STORE_DISPLAY_NAME = "aeroinspect-parts-catalog"

#: .env에 기록하는 환경변수 키
ENV_KEY = "AEROINSPECT_FILE_SEARCH_STORE"

#: 인덱싱 완료 폴링 간격(초)
_POLL_INTERVAL_SEC = 2.0


def find_store(client: Any) -> Any | None:
    """display_name으로 기존 스토어를 찾는다 (없으면 None)."""
    for store in client.file_search_stores.list():
        if getattr(store, "display_name", None) == STORE_DISPLAY_NAME:
            return store
    return None


def upload_catalog(client: Any, store_name: str, catalog_files: list[Path]) -> None:
    """카탈로그 파일들을 스토어에 업로드하고 인덱싱 완료까지 대기한다."""
    for i, path in enumerate(catalog_files, start=1):
        print(f"  [{i}/{len(catalog_files)}] 업로드 중: {path.name}")
        op = client.file_search_stores.upload_to_file_search_store(
            file=str(path),
            file_search_store_name=store_name,
            config={"display_name": path.name},
        )
        while not op.done:
            time.sleep(_POLL_INTERVAL_SEC)
            op = client.operations.get(op)
        print(f"  [{i}/{len(catalog_files)}] 인덱싱 완료: {path.name}")


def update_env(store_name: str) -> Path:
    """프로젝트 루트 .env에 스토어 이름을 멱등하게 기록한다.

    ``AEROINSPECT_FILE_SEARCH_STORE=`` 라인이 있으면 교체하고, 없으면
    추가한다. 다른 라인은 보존하며, .env가 없으면 새로 만든다.
    """
    env_path = config.PROJECT_ROOT / ".env"
    new_line = f"{ENV_KEY}={store_name}"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    replaced = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{ENV_KEY}="):
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        lines.append(new_line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_path


def main() -> int:
    """스토어를 준비하고 .env에 이름을 기록한다."""
    parser = argparse.ArgumentParser(
        description="AeroInspect 부품 카탈로그 File Search 스토어 셋업 (멱등)"
    )
    parser.add_argument(
        "--force-reupload",
        action="store_true",
        help="기존 스토어를 삭제하고 카탈로그를 재업로드한다",
    )
    args = parser.parse_args()

    client = config.get_client()

    print(f"스토어 확인 중: display_name='{STORE_DISPLAY_NAME}'")
    store = find_store(client)

    if store is not None and args.force_reupload:
        print(f"--force-reupload: 기존 스토어 삭제 중 ({store.name})")
        client.file_search_stores.delete(name=store.name, config={"force": True})
        store = None

    if store is None:
        catalog_files = sorted(config.CATALOG_DIR.glob("*.md"))
        if not catalog_files:
            print(f"오류: 카탈로그 문서가 없습니다 — {config.CATALOG_DIR}/*.md")
            return 1
        print(f"스토어 신규 생성: '{STORE_DISPLAY_NAME}'")
        store = client.file_search_stores.create(
            config={"display_name": STORE_DISPLAY_NAME}
        )
        print(f"카탈로그 업로드 시작 ({len(catalog_files)}개 문서)")
        upload_catalog(client, store.name, catalog_files)
    else:
        print(f"기존 스토어 재사용 (업로드 생략): {store.name}")

    env_path = update_env(store.name)
    print(f".env 기록 완료: {ENV_KEY} → {store.name} ({env_path})")
    print("셋업 완료.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

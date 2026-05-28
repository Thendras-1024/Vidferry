from __future__ import annotations

import asyncio
import sys
from typing import Sequence

from app.cli.dispatcher import dispatch as _dispatch
from app.cli.models import (
    BilibiliVideoUploadRequest,
    DouyinNoteUploadRequest,
    DouyinVideoUploadRequest,
    KuaishouNoteUploadRequest,
    KuaishouVideoUploadRequest,
    XiaohongshuNoteUploadRequest,
    XiaohongshuVideoUploadRequest,
)
from app.cli.parser import build_parser
from app.cli.platforms.bilibili import check_bilibili_account, login_bilibili_account, upload_bilibili_video
from app.cli.platforms.douyin import check_douyin_account, login_douyin_account, upload_note, upload_video
from app.cli.platforms.kuaishou import (
    check_kuaishou_account,
    login_kuaishou_account,
    upload_kuaishou_note,
    upload_kuaishou_video,
)
from app.cli.platforms.xiaohongshu import (
    check_xiaohongshu_account,
    login_xiaohongshu_account,
    upload_xiaohongshu_note,
    upload_xiaohongshu_video,
)
from app.cli.utils import (
    SCHEDULE_FORMAT,
    add_runtime_flags,
    existing_file_path,
    has_interactive_terminal,
    parse_image_files,
    parse_schedule,
    parse_tags,
    resolve_account_file,
    resolve_runtime_home,
    schedule_value,
)


async def dispatch(args):
    return await _dispatch(args, provider=sys.modules[__name__])


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return asyncio.run(dispatch(args))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

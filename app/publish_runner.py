from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Sequence

SCHEDULE_FORMAT = "%Y-%m-%d %H:%M"
PUBLISH_STRATEGY_IMMEDIATE = "immediate"
PUBLISH_STRATEGY_SCHEDULED = "scheduled"


def _safe_text(value) -> str:
    return str(value or "").strip()


def _parse_tags(raw_tags: str | None) -> list[str]:
    tags = []
    for item in (raw_tags or "").split(","):
        cleaned = item.strip().lstrip("#")
        if cleaned:
            tags.append(cleaned)
    return tags


def _parse_schedule(raw_schedule: str | None) -> datetime | int:
    if not raw_schedule:
        return 0
    return datetime.strptime(raw_schedule, SCHEDULE_FORMAT)


async def _upload_douyin(args: argparse.Namespace) -> None:
    from uploader.douyin_uploader.main import DouYinVideo

    publish_date = _parse_schedule(args.schedule)
    app = DouYinVideo(
        _safe_text(args.title),
        str(args.file),
        _parse_tags(args.tags),
        publish_date,
        str(args.account_file),
        thumbnail_landscape_path=str(args.thumbnail) if args.thumbnail else None,
        desc=_safe_text(args.desc),
        productLink=_safe_text(args.product_link),
        productTitle=_safe_text(args.product_title),
        publish_strategy=PUBLISH_STRATEGY_SCHEDULED if args.schedule else PUBLISH_STRATEGY_IMMEDIATE,
        debug=args.debug,
        headless=args.headless,
    )
    await app.douyin_upload_video()


async def _upload_xiaohongshu(args: argparse.Namespace) -> None:
    from uploader.xiaohongshu_uploader.main import XiaoHongShuVideo

    publish_date = _parse_schedule(args.schedule)
    app = XiaoHongShuVideo(
        title=_safe_text(args.title),
        file_path=str(args.file),
        desc=_safe_text(args.desc),
        tags=_parse_tags(args.tags),
        publish_date=publish_date,
        account_file=str(args.account_file),
        thumbnail_path=str(args.thumbnail) if args.thumbnail else None,
        publish_strategy=PUBLISH_STRATEGY_SCHEDULED if args.schedule else PUBLISH_STRATEGY_IMMEDIATE,
        debug=args.debug,
        headless=args.headless,
    )
    await app.main()


async def _upload_bilibili(args: argparse.Namespace) -> None:
    from uploader.bilibili_uploader.runtime import run_biliup_command

    command = [
        "-u",
        str(args.account_file),
        "upload",
        str(args.file),
        "--title",
        _safe_text(args.title),
        "--desc",
        _safe_text(args.desc),
        "--tid",
        str(args.tid or 249),
    ]
    tags = _parse_tags(args.tags)
    if tags:
        command.extend(["--tag", ",".join(tags)])
    publish_date = _parse_schedule(args.schedule)
    if isinstance(publish_date, datetime):
        command.extend(["--dtime", str(int(publish_date.timestamp()))])

    result = run_biliup_command(command)
    if result.returncode != 0:
        raise RuntimeError(((result.stderr or "") + "\n" + (result.stdout or "")).strip() or "B站发布失败")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backend isolated publish runner")
    parser.add_argument("--platform", required=True, choices=["douyin", "xiaohongshu", "bilibili"])
    parser.add_argument("--account-file", required=True, type=Path)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--desc", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--schedule", default="")
    parser.add_argument("--thumbnail", type=Path)
    parser.add_argument("--product-link", default="")
    parser.add_argument("--product-title", default="")
    parser.add_argument("--tid", type=int, default=249)
    parser.add_argument("--headless", action="store_true", default=False)
    parser.add_argument("--debug", action="store_true", default=False)
    return parser


async def dispatch(args: argparse.Namespace) -> None:
    if not args.account_file.is_file():
        raise RuntimeError(f"账号 Cookie 文件不存在: {args.account_file}")
    if not args.file.is_file():
        raise RuntimeError(f"发布视频文件不存在: {args.file}")
    if not _safe_text(args.title):
        raise RuntimeError("发布标题不能为空")

    if args.platform == "douyin":
        await _upload_douyin(args)
        return
    if args.platform == "xiaohongshu":
        await _upload_xiaohongshu(args)
        return
    if args.platform == "bilibili":
        await _upload_bilibili(args)
        return
    raise RuntimeError(f"不支持的平台: {args.platform}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        asyncio.run(dispatch(args))
        return 0
    except Exception as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

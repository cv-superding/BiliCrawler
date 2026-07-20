"""命令行入口：``python -m bili_crawler`` 启动 Web 面板，或执行单次采集。"""

from __future__ import annotations

import argparse
import sys

from .config.settings import load_settings
from .utils.logger import get_logger

logger = get_logger("cli")


def _run_web(settings) -> None:
    """启动 Flask Web 控制面板。"""
    from .web.app import create_app

    web_cfg = settings.web
    host = web_cfg.get("host", "127.0.0.1")
    port = int(web_cfg.get("port", 5000))
    debug = bool(web_cfg.get("debug", False))

    app = create_app(settings)
    logger.info("B站弹幕/评论爬取面板已启动 → http://%s:%s", host, port)
    app.run(host=host, port=port, debug=debug, threaded=True)


def _run_once(settings, args) -> None:
    """命令行单次采集（不启动 Web）。"""
    from .crawlers.comment import CommentCrawler
    from .crawlers.danmaku import DanmakuCrawler
    from .crawlers.douyin import DouyinCommentCrawler
    from .exporters.csv_exporter import CsvExporter
    from .exporters.json_exporter import JsonExporter
    from .utils.http import HTTPClient

    http = HTTPClient(settings)
    hooks = None  # 命令行无需进度回调
    platform = getattr(args, "platform", "bilibili")
    if platform == "douyin":
        if args.danmaku:
            logger.error("抖音视频不支持弹幕采集（仅支持评论）")
            sys.exit(2)
        crawler = DouyinCommentCrawler(http, hooks)
        records = [c.to_dict() for c in crawler.crawl(args.input)]
    elif args.danmaku:
        crawler = DanmakuCrawler(http, hooks)
        records = [d.to_dict() for d in crawler.crawl(args.input)]
    elif args.comment:
        crawler = CommentCrawler(http, hooks)
        records = [c.to_dict() for c in crawler.crawl(args.input, sort=args.sort)]
    else:
        logger.error("请指定 --danmaku 或 --comment")
        sys.exit(2)

    exporter = JsonExporter() if args.format == "json" else CsvExporter()
    out = exporter.export(records, args.output)
    logger.info("已导出 %d 条记录 → %s", len(records), out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="bili-crawler", description="B站弹幕与评论数据爬取工具"
    )
    sub = parser.add_subparsers(dest="cmd")

    # web 子命令（默认）
    sub.add_parser("web", help="启动 Web 控制面板（默认）")

    # crawl 子命令
    p_crawl = sub.add_parser("crawl", help="命令行单次采集")
    p_crawl.add_argument("input", help="BV 号 / 视频 URL / av 号（B站）；视频链接 / aweme_id（抖音）")
    g = p_crawl.add_mutually_exclusive_group(required=True)
    g.add_argument("--danmaku", action="store_true", help="采集弹幕")
    g.add_argument("--comment", action="store_true", help="采集评论")
    p_crawl.add_argument("--platform", choices=["bilibili", "douyin"], default="bilibili",
                         help="采集平台（默认 bilibili）")
    p_crawl.add_argument("--sort", choices=["time", "hot"], default="time", help="评论排序（仅 B站）")
    p_crawl.add_argument("--format", choices=["json", "csv"], default="json", help="导出格式")
    p_crawl.add_argument("--output", default="data/exports/result", help="输出路径（不含扩展名）")

    args = parser.parse_args(argv)
    settings = load_settings()

    if args.cmd == "crawl":
        _run_once(settings, args)
    else:
        # 默认启动 Web
        _run_web(settings)


if __name__ == "__main__":
    main()

"""Flask Web 控制面板：提供 4 个页面与配套 REST API。

页面：
- ``/video``   视频数据采集（输入 BV/URL，选择弹幕/评论/全部）
- ``/batch``   批量采集（UP 主/收藏夹/合集/频道 + 并发/延迟参数）
- ``/tasks``   任务队列（实时进度、状态、暂停/恢复/取消）
- ``/export``  数据导出（选择已完成任务，导出 JSON/CSV 下载）

API 见各路由 docstring。
"""

from __future__ import annotations

import os

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from .task_manager import TaskManager
from ..utils.logger import get_logger

logger = get_logger("web")


def create_app(settings) -> Flask:
    """构建 Flask 应用并注册路由。"""
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.config["tm"] = TaskManager(settings)

    # ---------- 页面 ----------
    @app.route("/")
    def index():
        return redirect(url_for("page_video"))

    @app.route("/video")
    def page_video():
        return render_template("video.html")

    @app.route("/batch")
    def page_batch():
        return render_template("batch.html")

    @app.route("/tasks")
    def page_tasks():
        return render_template("tasks.html")

    @app.route("/export")
    def page_export():
        return render_template("export.html")

    # ---------- 采集提交 ----------
    @app.route("/api/crawl/video", methods=["POST"])
    def api_crawl_video():
        """提交视频采集任务。Body: {input, types:[danmaku|comment], platform:bilibili|douyin}"""
        tm: TaskManager = app.config["tm"]
        body = request.get_json(silent=True) or {}
        inp = (body.get("input") or "").strip()
        types = body.get("types") or []
        types = [t for t in types if t in ("danmaku", "comment")]
        platform = body.get("platform") or "bilibili"
        if platform not in ("bilibili", "douyin"):
            return jsonify({"ok": False, "error": "不支持的平台"}), 400
        if not inp:
            return jsonify({"ok": False, "error": "请输入视频号或链接"}), 400
        if not types:
            return jsonify({"ok": False, "error": "请至少选择一种采集类型"}), 400
        if platform == "douyin" and "danmaku" in types:
            return jsonify({"ok": False, "error": "抖音视频不支持弹幕采集（仅支持评论）"}), 400
        created = []
        for t in types:
            task = tm.submit_video(inp, t, platform)
            created.append(task.to_dict())
        return jsonify({"ok": True, "tasks": created})

    @app.route("/api/crawl/batch", methods=["POST"])
    def api_crawl_batch():
        """提交批量采集任务。Body: {source, source_type, kinds, concurrency, platform}"""
        tm: TaskManager = app.config["tm"]
        body = request.get_json(silent=True) or {}
        source = (body.get("source") or "").strip()
        source_type = body.get("source_type") or "auto"
        kinds = body.get("kinds") or ["comment"]
        kinds = tuple(k for k in kinds if k in ("danmaku", "comment"))
        concurrency = int(body.get("concurrency") or 3)
        platform = body.get("platform") or "bilibili"
        if platform not in ("bilibili", "douyin"):
            return jsonify({"ok": False, "error": "不支持的平台"}), 400
        if not source:
            return jsonify({"ok": False, "error": "请输入来源链接或 ID"}), 400
        if not kinds:
            return jsonify({"ok": False, "error": "请至少选择一种采集类型"}), 400
        if platform == "douyin" and "danmaku" in kinds:
            return jsonify({"ok": False, "error": "抖音不支持弹幕采集（仅支持评论）"}), 400
        task = tm.submit_batch(source, source_type, kinds, concurrency, platform)
        return jsonify({"ok": True, "task": task.to_dict()})

    # ---------- 任务查询与控制 ----------
    @app.route("/api/tasks", methods=["GET"])
    def api_tasks():
        tm: TaskManager = app.config["tm"]
        return jsonify({"ok": True, "tasks": tm.list_tasks()})

    @app.route("/api/tasks/<task_id>", methods=["GET"])
    def api_task_detail(task_id):
        tm: TaskManager = app.config["tm"]
        t = tm.get_task(task_id)
        if not t:
            return jsonify({"ok": False, "error": "任务不存在"}), 404
        return jsonify({"ok": True, "task": t})

    @app.route("/api/tasks/<task_id>/pause", methods=["POST"])
    def api_task_pause(task_id):
        tm: TaskManager = app.config["tm"]
        return jsonify({"ok": tm.pause(task_id)})

    @app.route("/api/tasks/<task_id>/resume", methods=["POST"])
    def api_task_resume(task_id):
        tm: TaskManager = app.config["tm"]
        return jsonify({"ok": tm.resume(task_id)})

    @app.route("/api/tasks/<task_id>/cancel", methods=["POST"])
    def api_task_cancel(task_id):
        tm: TaskManager = app.config["tm"]
        return jsonify({"ok": tm.cancel(task_id)})

    @app.route("/api/tasks/<task_id>", methods=["DELETE"])
    def api_task_delete(task_id):
        """删除任务。

        Query:
            purge=1 同时删除该任务对应的本地数据文件（原始 JSON 及已导出的文件）；
            purge=0（默认）仅移除任务记录，保留磁盘上的真实数据文件。

        返回 {ok}；任务不存在返回 404。
        """
        tm: TaskManager = app.config["tm"]
        purge = request.args.get("purge", "0") in ("1", "true", "True")
        ok = tm.delete_task(task_id, purge_files=purge)
        if not ok:
            return jsonify({"ok": False, "error": "任务不存在"}), 404
        return jsonify({"ok": True})

    # ---------- Cookie 自检 ----------
    @app.route("/api/health/cookie", methods=["GET"])
    def api_health_cookie():
        """按平台检查当前配置的 Cookie 登录态。

        Query: platform=bilibili|douyin（默认 bilibili）。

        - bilibili：调用 nav 接口判断 isLogin；
        - douyin：用 aweme/detail 探测 Cookie 是否被服务端接受（有效 Cookie 返回合法
          JSON；失效/风控则返回 HTML 验证页，无法解析为 JSON）。

        返回 {ok, platform, logged_in, uname, cookie_len, detail?}，失败也返回 200 + JSON，
        避免前端收到 HTML。
        """
        tm: TaskManager = app.config["tm"]
        settings = tm.settings
        platform = (request.args.get("platform") or "bilibili").lower()
        try:
            from ..utils.http import HTTPClient

            http = HTTPClient(settings)
            if platform == "douyin":
                from ..crawlers.douyin import check_douyin_cookie

                cookie_len = len((settings.cookie.get("douyin") or "").strip())
                accepted, message = check_douyin_cookie(http)
                return jsonify({
                    "ok": True,
                    "platform": "douyin",
                    "logged_in": accepted,
                    "uname": "",
                    "cookie_len": cookie_len,
                    "detail": message,
                })
            # 默认 / bilibili
            cookie_len = len((settings.cookie.get("session") or "").strip())
            nav = http.get_json("https://api.bilibili.com/x/web-interface/nav")
            d = (nav or {}).get("data") or {}
            return jsonify({
                "ok": True,
                "platform": "bilibili",
                "logged_in": bool(d.get("isLogin")),
                "uname": d.get("uname") or d.get("name") or "",
                "cookie_len": cookie_len,
            })
        except Exception as exc:  # 即使失败也返回 200 + JSON，避免前端收到 HTML
            return jsonify({
                "ok": False,
                "error": str(exc),
                "platform": platform,
                "cookie_len": 0,
            })

    # ---------- 导出 ----------
    @app.route("/api/export/options", methods=["GET"])
    def api_export_options():
        """列出可导出（已完成）的任务。"""
        tm: TaskManager = app.config["tm"]
        opts = []
        for t in tm.list_tasks():
            if t["status"] == "completed" and t["result_path"]:
                meta = t.get("meta") or {}
                opts.append({
                    "task_id": t["task_id"],
                    "name": t["name"],
                    "kind": t["kind"],
                    "platform": t.get("platform", "bilibili"),
                    "title": meta.get("title") or t["name"],
                    "author": meta.get("author") or "",
                })
        return jsonify({"ok": True, "options": opts})

    @app.route("/api/export/<task_id>", methods=["GET"])
    def api_export(task_id):
        """导出任务结果。Query: format=json|csv, sub=danmaku|comment（仅批量任务需要）。

        返回文件附件（Content-Disposition: attachment）；任何异常均以 JSON 形式返回，
        避免把 HTML 错误页当成文件下载（浏览器会存成随机名 .htm）。
        """
        tm: TaskManager = app.config["tm"]
        fmt = (request.args.get("format") or "json").lower()
        sub = request.args.get("sub")
        try:
            path = tm.export(task_id, fmt, sub)
        except (FileNotFoundError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        # 二次校验：导出文件必须真实存在且为普通文件
        if not os.path.isfile(path):
            return jsonify({
                "ok": False,
                "error": f"导出文件未生成：{path}",
            }), 500

        download_name = os.path.basename(path)
        try:
            return send_file(
                path,
                as_attachment=True,
                download_name=download_name,
                mimetype="application/json" if fmt == "json" else "text/csv",
            )
        except Exception as exc:  # 兜底：任何读取/发送失败都回 JSON，而非 HTML
            logger.error("导出文件发送失败: %s", exc)
            return jsonify({"ok": False, "error": f"文件发送失败：{exc}"}), 500

    return app

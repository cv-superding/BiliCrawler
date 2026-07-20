"""抖音模块离线冒烟测试（无需联网）。

覆盖：
1. X-Bogus 签名：确定性、格式（Base64 风格长串）、随输入/UA 变化。
2. sign_douyin_url：正确追加 X-Bogus（及 a_bogus 钩子占位）。
3. 输入解析：extract_aweme_id / extract_sec_uid / 分享短链判定。
4. 模型：DouyinComment.to_dict 字段齐全、时间 ISO 正确。
5. 采集器解析：用 mock http 喂入真实结构的评论 JSON，验证 parent/root 还原与二级回复。
"""

import sys
import urllib.parse

sys.path.insert(0, ".")

from bili_crawler.utils.douyin_sign import (
    DEFAULT_UA,
    gen_a_bogus,
    gen_x_bogus,
    sign_douyin_url,
)
from bili_crawler.utils.douyin_parse import (
    extract_aweme_id,
    extract_sec_uid,
    is_share_link,
)
from bili_crawler.models.douyin_comment import DouyinComment
from bili_crawler.crawlers.douyin import DouyinCommentCrawler, is_douyin


def check(name, cond):
    print(("✓ " if cond else "✗ ") + name)
    if not cond:
        raise SystemExit(f"FAILED: {name}")


# 1) X-Bogus 确定性 & 格式
U = DEFAULT_UA
url = "https://www.douyin.com/aweme/v1/web/comment/list/?device_platform=webapp&aid=6383&aweme_id=7341234567890123456&cursor=0&count=20"
xb1 = gen_x_bogus(url, U)
xb2 = gen_x_bogus(url, U)
check("X-Bogus 确定性（同输入两次相同）", xb1 == xb2)
check("X-Bogus 非空且为 Base64 风格长串", 20 <= len(xb1) <= 200 and set(xb1) <= set("Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe="))
xb_other = gen_x_bogus(url + "&cursor=1", U)
check("X-Bogus 随输入变化", xb_other != xb1)
xb_ua = gen_x_bogus(url, "Mozilla/5.0 (X11; Linux x86_64)")
check("X-Bogus 随 UA 变化", xb_ua != xb1)

# 2) sign_douyin_url
signed = sign_douyin_url(url, U)
check("sign_douyin_url 追加 X-Bogus", "&X-Bogus=" in signed and signed.startswith(url))
check("默认不追加 a_bogus", "a_bogus=" not in signed)
# a_bogus 钩子：worker 不存在时返回 None（不报错）
ab = gen_a_bogus(urllib.parse.urlparse(url).query, U)
check("gen_a_bogus 无 worker 时安全返回 None", ab is None)
# 带 a_bogus 但 worker 缺失 → 不附加
signed2 = sign_douyin_url(url, U, with_a_bogus=True)
check("with_a_bogus 但无 worker 时不附加 a_bogus", "a_bogus=" not in signed2)

# 3) 输入解析
check("extract_aweme_id 长链", extract_aweme_id("https://www.douyin.com/video/7341234567890123456") == "7341234567890123456")
check("extract_aweme_id 纯数字", extract_aweme_id("7341234567890123456") == "7341234567890123456")
check("extract_aweme_id note 链接", extract_aweme_id("https://www.douyin.com/note/734999") == "734999")
check("extract_sec_uid 参数", extract_sec_uid("https://www.douyin.com/user/MS4wLjABAAAAabc") == "MS4wLjABAAAAabc")
check("extract_sec_uid /user/", extract_sec_uid("https://www.douyin.com/user/MS4wLjABAAAAxyz") == "MS4wLjABAAAAxyz")
check("is_share_link v.douyin.com", is_share_link("https://v.douyin.com/iRqXyKp/"))
check("is_douyin 判断", is_douyin("https://www.douyin.com/video/734"))

# 4) 模型
c = DouyinComment(
    comment_id=111, aweme_id="734", user_id=22, username="小明",
    content="很棒", create_time=1700000000, digg_count=5,
    parent_id=0, root_id=111, ip_label="北京", is_author=True,
)
d = c.to_dict()
check("模型 to_dict 含 评论ID", d["评论ID"] == 111)
check("模型 to_dict 含时间 ISO", d["发布时间"].startswith("2023-11-1"))
check("模型 IP属地 已去除前缀", d["IP属地"] == "北京")
check("模型 根评论ID 指向自身", d["根评论ID"] == 111)

# 5) 采集器解析（mock http）
class FakeResp:
    def __init__(self, payload):
        self._p = payload
    def json(self):
        return self._p
    @property
    def text(self):
        import json as _j
        return _j.dumps(self._p)

class FakeHTTP:
    """按 aweme_id 返回一级评论；二级回复按 comment_id 返回。"""
    def __init__(self, settings=None):
        self.settings = settings or type("S", (), {"cookie": {}})()
        self.calls = []
    def request(self, method, url, headers=None, params=None):
        self.calls.append(url)
        # 一级评论列表
        if "comment/list/" in url and "reply" not in url:
            return FakeResp({
                "status_code": 0,
                "comments": [
                    {
                        "cid": "9001", "text": "一级评论A", "create_time": 1700000000,
                        "digg_count": 3, "reply_comment_total": 1,
                        "reply_id": 0, "is_author": False,
                        "user": {"uid": "55", "nickname": "甲", "ip_label": "IP属地：上海",
                                 "avatar_thumb": {"url_list": ["http://a.jpg"]}, "user_level": 4},
                    },
                    {
                        "cid": "9002", "text": "一级评论B", "create_time": 1700000100,
                        "digg_count": 0, "reply_comment_total": 0, "reply_id": 0,
                        "user": {"uid": "66", "nickname": "乙", "ip_label": ""},
                    },
                ],
                "cursor_info": {"cursor": 0, "has_more": False},
            })
        # 二级回复（comment_id=9001）
        if "comment/list/reply/" in url:
            return FakeResp({
                "status_code": 0,
                "comments": [
                    {
                        "cid": "9101", "text": "二级回复", "create_time": 1700000200,
                        "digg_count": 1, "reply_id": 9001,
                        "user": {"uid": "77", "nickname": "丙", "ip_label": "IP属地：北京"},
                    }
                ],
                "cursor_info": {"cursor": 0, "has_more": False},
            })
        return FakeResp({"status_code": 0, "comments": [], "has_more": False})

crawler = DouyinCommentCrawler(FakeHTTP(), None)
comments = crawler.crawl("7341234567890123456")
check("采集器一级+二级合计 3 条", len(comments) == 3)
top_a = next(c for c in comments if c.comment_id == 9001)
sub = next(c for c in comments if c.comment_id == 9101)
check("一级评论 parent=0 root=自身", top_a.parent_id == 0 and top_a.root_id == 9001)
check("二级回复 root 指向一级", sub.root_id == 9001 and sub.parent_id == 9001)
check("二级回复用户名解析", sub.username == "丙")
check("一级评论 IP 去前缀", top_a.ip_label == "上海")

print("\n全部抖音离线测试通过 ✓")

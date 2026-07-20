"""B站弹幕与评论数据爬取工具。

模块化分层架构：
- ``bili_crawler.crawlers``  采集器层（弹幕 / 评论 / 批量）
- ``bili_crawler.models``    数据模型层（snake_case 统一命名）
- ``bili_crawler.exporters`` 数据导出层（JSON / CSV，UTF-8 BOM）
- ``bili_crawler.utils``     工具层（HTTP、反爬、protobuf 解析等）
- ``bili_crawler.web``       Web 控制面板（Flask）
"""

__version__ = "0.1.0"

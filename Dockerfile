# 使用官方轻量 Python 镜像
FROM python:3.11-slim

WORKDIR /app

# 先装依赖（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目源码（敏感文件由 .dockerignore 排除，不会进镜像）
COPY . .

# 运行时目录占位（实际数据通过 -v 挂载到宿主机，便于持久化与查看）
RUN mkdir -p data/exports data/results data/state

# Web 控制面板默认端口
EXPOSE 5000

# 启动 Web 控制面板；监听地址可用环境变量 BILI_WEB_HOST 覆盖（如 0.0.0.0）
CMD ["python", "-m", "bili_crawler", "web"]

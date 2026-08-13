# ============================================================
# Exam Extract API — Docker 镜像
# ============================================================
FROM python:3.12-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        tzdata && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo "$TZ" > /etc/timezone && \
    rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

WORKDIR /app

# ── 依赖层（利用 Docker 缓存） ──
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r requirements.txt

# ── 应用代码 ──
# README.md 必须存在 — get_project_root() 靠它定位项目根目录
COPY README.md .
COPY main.py .
COPY cli.py .
COPY bin/ ./bin/
COPY conf/ ./conf/
COPY core/ ./core/
COPY libs/ ./libs/
COPY model/ ./model/
COPY service/ ./service/
COPY utils/ ./utils/
COPY logs/ ./logs/
COPY prompts/ ./prompts/

# 创建临时输出目录
RUN mkdir -p /app/tmp && chown -R appuser:appuser /app

USER appuser

EXPOSE 8085

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8085/health')" || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8085", "--log-level", "info"]

# syntax=docker/dockerfile:1
# 后端通用 Dockerfile：两个构建目标共享依赖层
#   - code-light : auth/user/admin/file（只 COPY 单服务目录，镜像小）
#   - code-agent : chat/kb（COPY 整个项目根 + playwright chromium，依赖 AIRAGAgent 引擎）
#
# 构建示例：
#   docker build --target code-light --build-arg SERVICE=auth_service -t lc-auth .
#   docker build --target code-agent --build-arg SERVICE=chat_service -t lc-chat .
#
# 运行时端口由 PORT 环境变量决定（compose 中按服务设 8001-8006）。

ARG PYTHON_IMAGE=python:3.13-slim

# ═══════════════════════════════════════════════════════════
# Stage: deps —— 系统库 + Python 依赖（所有后端镜像共享此层）
# ═══════════════════════════════════════════════════════════
FROM ${PYTHON_IMAGE} AS deps

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8

# 通用系统依赖：curl(healthcheck)、ca-certificates、mysql 客户端库、字体
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
        default-libmysqlclient-dev pkg-config \
        fonts-liberation fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 用 uv 从 uv.lock 导出精确依赖清单，再用 pip 装到系统环境（不装项目本身）
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv \
    && uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# ═══════════════════════════════════════════════════════════
# Stage: agent-deps —— 在 deps 之上装 Playwright Chromium（仅 chat/kb 需要）
# ═══════════════════════════════════════════════════════════
FROM deps AS agent-deps

# 淘宝镜像加速 chromium 下载
ENV PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

# --with-deps 自动安装 chromium 所需系统库
RUN playwright install --with-deps chromium

# ═══════════════════════════════════════════════════════════
# Stage: code-light —— 轻服务（auth/user/admin/file）
# ═══════════════════════════════════════════════════════════
FROM deps AS code-light
ARG SERVICE=auth_service
ARG SERVICE_PORT=8001
COPY services/${SERVICE}/ /app/services/${SERVICE}/
WORKDIR /app/services/${SERVICE}
ENV PORT=${SERVICE_PORT}
EXPOSE ${SERVICE_PORT}
# shell 形式以展开 $PORT；exec 让 uvicorn 接管 PID 1 以正确接收 SIGTERM
CMD exec python -m uvicorn main:app --app-dir . --host 0.0.0.0 --port "${PORT}" --log-level info

# ═══════════════════════════════════════════════════════════
# Stage: code-agent —— 依赖 AIRAGAgent 引擎的服务（chat/kb）
# ═══════════════════════════════════════════════════════════
FROM agent-deps AS code-agent
ARG SERVICE=chat_service
ARG SERVICE_PORT=8003
# 需要整个项目根：AIRAGAgent/ 引擎 + config/*.yml + services/<svc>/
COPY . /app/
WORKDIR /app/services/${SERVICE}
# PYTHONPATH=项目根，使 `from AIRAGAgent.* import ...` 可解析（等价 start.sh 的 AGENT_HOME）
ENV PYTHONPATH=/app \
    PORT=${SERVICE_PORT} \
    AGENT_HOME=/app
EXPOSE ${SERVICE_PORT}
CMD exec python -m uvicorn main:app --app-dir . --host 0.0.0.0 --port "${PORT}" --log-level info

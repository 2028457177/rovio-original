# syntax=docker/dockerfile:1
# 迁移执行器：独立轻量镜像，避免在应用镜像里引入 alembic 依赖。
# compose 中作为一次性服务（service_completed_successfully）先于应用启动运行。
FROM python:3.13-slim

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install alembic pymysql python-dotenv

WORKDIR /app
COPY migrations/ ./migrations/
COPY alembic.ini ./

# 依次对 5 个目标库执行 upgrade（每个 baseline 声明了 branch_labels=<target>，
# 用 <target>@head 消除多 root 多 head 歧义；baseline 用 CREATE TABLE IF NOT EXISTS，幂等）
CMD ["sh", "-c", "for t in auth user chat kb admin; do echo '>>> migrate target:' $t; alembic -x target=$t upgrade ${t}@head || exit 1; done"]

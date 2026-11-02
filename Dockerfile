# 复现用镜像：锁定 Python 3.13 + requirements-lock.txt。
# 密钥不进镜像：运行时通过 --env-file / compose env_file 注入。
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 先装依赖，利用镜像层缓存：只改业务代码时不必重装依赖。
# 默认走 PyPI；国内网络可用 --build-arg PIP_INDEX_URL=<镜像> 覆盖（compose 默认用清华源）。
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements-lock.txt ./
RUN pip install --index-url "$PIP_INDEX_URL" --retries 5 --timeout 120 -r requirements-lock.txt

COPY app.py README.md ./
COPY core ./core
COPY data ./data
COPY eval ./eval
COPY tools ./tools
COPY docs ./docs

# 非 root 运行；eval 报告目录需要可写。
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/eval \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"

CMD ["python", "-m", "streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]

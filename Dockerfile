FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml ./
COPY agentra ./agentra
RUN pip wheel --wheel-dir /wheels .

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/opt/browsers TIKTOKEN_CACHE_DIR=/opt/tokenizer
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && python -m playwright install --with-deps chromium && useradd --create-home --uid 10001 agentra && chmod -R a+rX /opt/browsers && rm -rf /wheels
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" && chmod -R a+rX /opt/tokenizer
USER agentra
WORKDIR /home/agentra
EXPOSE 8000
CMD ["uvicorn", "agentra.server:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

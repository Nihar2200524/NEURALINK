FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/opt/browsers TIKTOKEN_CACHE_DIR=/opt/tokenizer
WORKDIR /build
COPY pyproject.toml ./
RUN python -c "import tomllib,subprocess,sys; subprocess.check_call([sys.executable,'-m','pip','install','--no-cache-dir']+tomllib.load(open('pyproject.toml','rb'))['project']['dependencies'])"
RUN python -m playwright install --with-deps chromium && useradd --create-home --uid 10001 agentra && chmod -R a+rX /opt/browsers
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" && chmod -R a+rX /opt/tokenizer
COPY agentra ./agentra
RUN pip install --no-cache-dir --no-deps . && rm -rf /build
USER agentra
WORKDIR /home/agentra
EXPOSE 8000
CMD ["uvicorn", "agentra.server:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--limit-concurrency", "64", "--timeout-keep-alive", "5"]

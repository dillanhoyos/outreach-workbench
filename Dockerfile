FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WORKBENCH_DATA=/data
WORKDIR /app
COPY scripts/install_codex.py /tmp/install_codex.py
RUN python /tmp/install_codex.py && rm /tmp/install_codex.py
COPY pyproject.toml requirements.lock ./
COPY src ./src
RUN pip install --no-cache-dir -c requirements.lock . && useradd --uid 10001 --create-home workbench && mkdir /data && chown workbench:workbench /data
USER workbench
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health',timeout=2)"
CMD ["outreach-workbench", "serve"]

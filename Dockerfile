FROM python:3.12-slim

ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}
ENV DATA_DIR=/data

LABEL org.opencontainers.image.title="ywsj-sub-translator"
LABEL org.opencontainers.image.description="Web-based subtitle translation tool"
LABEL org.opencontainers.image.source="https://github.com/yyzq-cf/ywsj-sub-translator"

RUN groupadd -r appgroup && useradd -r -g appgroup appuser \
    && mkdir -p /data && chown appuser:appgroup /data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appgroup . .

USER appuser

EXPOSE 5200

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5200/health')" || exit 1

CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5200", "--timeout", "300", "--access-logfile", "-", "--error-logfile", "-", "app:app"]

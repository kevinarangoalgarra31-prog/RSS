FROM python:3.12-alpine

WORKDIR /app
COPY rss_server.py /app/rss_server.py
RUN mkdir -p /app/data && addgroup -S rss && adduser -S rss -G rss && chown -R rss:rss /app/data
USER rss

ENV HOST=0.0.0.0 PORT=8000 DATABASE=/app/data/events.db PYTHONUNBUFFERED=1
EXPOSE 8000
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

CMD ["python", "rss_server.py"]

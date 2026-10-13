FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOST=0.0.0.0
WORKDIR /srv/server
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home openguard
COPY app ./app
COPY dashboard ./dashboard
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
RUN mkdir -p /data && chown openguard:openguard /data
USER openguard
ENV DATABASE_URL=sqlite:////data/openguard.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready',timeout=3)"
CMD ["python", "-m", "app.start"]

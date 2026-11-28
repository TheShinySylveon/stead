# Stead multi-user image. Knowledge is the mounted context/ volume.
# The process will not start unless an account exists in private/ or
# STEAD_ACCESS_TOKEN is set for initial bootstrap.
# Published as ghcr.io/theshinysylveon/stead
FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/TheShinySylveon/stead" \
      org.opencontainers.image.description="Stead local context system" \
      org.opencontainers.image.licenses="Apache-2.0"

RUN command -v setpriv && useradd --create-home --shell /bin/sh stead

WORKDIR /app
COPY --chown=stead:stead ctx ./ctx
COPY --chown=stead:stead stead ./stead
COPY --chown=stead:stead docs ./docs
COPY --chown=stead:stead factories ./factories
COPY --chown=stead:stead inbox ./inbox
COPY --chown=stead:stead examples ./examples
COPY --chown=stead:stead context ./context
COPY --chown=stead:stead AGENTS.md CONVENTIONS.md README.md LICENSE ./
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && mkdir -p /app/private && chown -R stead:stead /app

ENV HOME=/home/stead \
    PYTHONUNBUFFERED=1 \
    STEAD_DEPLOYMENT=multi \
    STEAD_BIND=0.0.0.0 \
    STEAD_PORT=8765

EXPOSE 8765
VOLUME ["/app/context", "/app/private", "/app/inbox"]

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "stead", "ui", "--no-browser", "--deploy"]

# Stead multi-user image. Knowledge is the mounted context/ volume.
# The process will not start unless STEAD_ACCESS_TOKEN is set.
FROM python:3.12-slim

WORKDIR /app
COPY ctx ./ctx
COPY docs ./docs
COPY factories ./factories
COPY inbox ./inbox
COPY examples ./examples
COPY context ./context
COPY AGENTS.md CONVENTIONS.md README.md LICENSE ./

ENV PYTHONUNBUFFERED=1 \
    STEAD_DEPLOYMENT=multi \
    STEAD_BIND=0.0.0.0 \
    STEAD_PORT=8765

EXPOSE 8765
VOLUME ["/app/context"]

CMD ["python", "-m", "ctx", "ui", "--no-browser", "--deploy"]

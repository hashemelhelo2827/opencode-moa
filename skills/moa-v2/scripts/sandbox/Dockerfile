# moa-v2-sandbox — Gate C runtime image.
# Base: python:3.12-slim + nodejs/npm + pytest/bandit, non-root user, /work entrypoint.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest bandit

# Low-priv runtime user (also enforced at docker run with --user 1000:1000).
RUN useradd --create-home --uid 1000 sandbox
USER sandbox

WORKDIR /work

CMD ["/bin/bash"]

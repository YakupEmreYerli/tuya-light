# tuya-light server (phone page + API) in a container.
#   docker build -t tuya-light .
# See compose.yaml for the two ways to run it (home server, cloud server).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TUYA_LIGHT_CONFIG=/config/devices.json

# The source is mounted for the install only, so no copy of it stays in the image.
RUN --mount=type=bind,source=backend,target=/src,rw \
    pip install "/src[web]" \
 && useradd --system --uid 10001 --user-group --home-dir /config --shell /usr/sbin/nologin tuya \
 && mkdir /config && chown tuya:tuya /config

USER tuya
WORKDIR /config
VOLUME /config
EXPOSE 8892

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8892/icon.svg', timeout=4)"]

ENTRYPOINT ["tuya-light"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8892"]

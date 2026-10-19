FROM python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4
ARG BUILD_VERSION=0.3.0
ARG BUILD_ARCH=aarch64
LABEL io.hass.version="${BUILD_VERSION}" io.hass.type="app" io.hass.arch="${BUILD_ARCH}"
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY app.py collector.py evcc.py sources.py recordings.py /app/
COPY static /app/static
CMD ["python", "-u", "/app/app.py"]

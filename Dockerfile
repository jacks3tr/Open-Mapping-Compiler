FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY schemas ./schemas
COPY examples ./examples
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels ".[server]"

FROM python:3.11-slim

RUN useradd --create-home --uid 10001 openmapping
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
USER openmapping
WORKDIR /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD ["python", "-c", "import os,urllib.request; request=urllib.request.Request('http://127.0.0.1:8080/health', headers={'Authorization':'Bearer '+os.environ['OPEN_MAPPING_SERVER_KEY']}); urllib.request.urlopen(request, timeout=2)"]
ENTRYPOINT ["open-mapping", "serve"]
CMD ["/data/mapping.omc", "--host", "0.0.0.0", "--allow-remote", "--api-key-env", "OPEN_MAPPING_SERVER_KEY"]

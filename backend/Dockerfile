FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    YOLO_CONFIG_DIR=/tmp/ultralytics MPLCONFIGDIR=/tmp/matplotlib TORCH_HOME=/tmp/torch HF_HOME=/tmp/huggingface
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 libereye
COPY pyproject.toml requirements.txt constraints.txt README.md ./
COPY libereye ./libereye
COPY scripts ./scripts
ARG INSTALL_VISION=0
RUN pip install --constraint constraints.txt . \
    && if [ "$INSTALL_VISION" = "1" ]; then pip install --constraint constraints.txt '.[vision]'; fi
USER libereye
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
CMD ["python", "scripts/run_cloud.py"]

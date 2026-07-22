FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libgdal-dev libspatialindex-dev libffi-dev \
    curl git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy EVERYTHING needed for install first
COPY pyproject.toml ./
COPY src/ ./src/

# Now install — src/ exists so editable install works
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copy cached demo data
COPY data/processed/ ./data/processed/
COPY data/raw/ ./data/raw/

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "equilibria.api:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

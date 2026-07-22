# Equilibria — FastAPI Backend
# Builds a container that includes pre-cached Kano demo data so the
# first pipeline run on Render doesn't need to re-download 500MB of rasters.

FROM python:3.11-slim

# System deps needed by GeoPandas / rasterio / OSMnx
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libgdal-dev libspatialindex-dev libffi-dev \
    curl git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies first (layer caching)
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[dev]"

# Copy source code
COPY src/ ./src/

# Copy pre-cached Kano data so the demo works instantly on first run
COPY data/processed/ ./data/processed/
COPY data/raw/ ./data/raw/

# Expose FastAPI port
EXPOSE 8000

# Run the FastAPI backend
CMD ["python", "-m", "uvicorn", "equilibria.api:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libgdal-dev libspatialindex-dev libffi-dev \
    curl git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy everything pip needs BEFORE installing
COPY README.md ./
COPY pyproject.toml ./
COPY src/ ./src/

# Install dependencies (not editable — production build)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        geopandas shapely pyproj networkx osmnx \
        scikit-learn rasterio folium matplotlib \
        fastapi uvicorn python-dotenv geopy \
        pydantic openpyxl groq scipy requests \
        google-adk mcp

# Copy cached demo data last (changes often, keep at end for layer caching)
COPY data/processed/ ./data/processed/
COPY data/raw/ ./data/raw/

ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn equilibria.api:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]

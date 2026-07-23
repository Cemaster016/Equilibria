FROM python:3.11-slim

# Install ALL system libraries needed by GeoPandas, rasterio, OSMnx
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    libexpat1 libexpat1-dev \
    libgdal-dev gdal-bin \
    libspatialindex-dev \
    libffi-dev libssl-dev \
    libproj-dev proj-data proj-bin \
    libgeos-dev \
    curl git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy source first so pip install finds it
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install Python packages
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    fastapi uvicorn python-dotenv geopy pydantic \
    openpyxl groq scipy requests \
    google-adk mcp \
    geopandas shapely pyproj networkx \
    osmnx scikit-learn rasterio folium matplotlib

# Copy cached Kano demo data
COPY data/processed/ ./data/processed/
COPY data/raw/ ./data/raw/

ENV PYTHONPATH=/app/src

EXPOSE 8000

# sh -c form so $PORT expands correctly at runtime
CMD ["sh", "-c", "python -m uvicorn equilibria.api:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]

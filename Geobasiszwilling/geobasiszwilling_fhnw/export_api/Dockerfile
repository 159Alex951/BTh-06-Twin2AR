FROM ghcr.io/osgeo/gdal:ubuntu-full-3.8.5

# Minimal Python web stack
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip ca-certificates assimp-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt
RUN pip install pyproj

COPY app.py /app/app.py

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "--threads", "4", "--timeout", "300", "app:app"]

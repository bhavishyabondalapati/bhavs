# Recommender training image (ARM64, CPU). Build context: ml/   ->   make build-train
# Packages are installed in separate layers on purpose: small layers push reliably through Docker Desktop's proxy.
FROM python:3.12-slim-bookworm
RUN pip install --no-cache-dir numpy scipy boto3
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
WORKDIR /app
COPY bhavs_rec /app/bhavs_rec
COPY train.py best_model.txt /app/
RUN useradd -m runner && mkdir /app/artifacts && chown runner /app/artifacts
USER runner
CMD ["python", "train.py", "--model", "auto"]

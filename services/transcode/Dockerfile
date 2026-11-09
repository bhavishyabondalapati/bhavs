# ARM64 image for Fargate (Graviton). Build + push: make build-transcode
# Alpine keeps it small. The install is split into several RUN steps on purpose: smaller layers upload
# reliably through Docker Desktop's network proxy (one 270 MB layer kept failing to push).
FROM alpine:3.21
RUN apk add --no-cache python3 py3-boto3 ca-certificates \
 && adduser -D runner
RUN apk add --no-cache ffmpeg-libavcodec
RUN apk add --no-cache ffmpeg-libavfilter
RUN apk add --no-cache ffmpeg
WORKDIR /app
COPY transcode.py /app/transcode.py
USER runner
ENTRYPOINT ["python3", "/app/transcode.py"]

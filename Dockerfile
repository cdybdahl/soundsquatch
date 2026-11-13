# Soundsquatch in a container: the service and the app, its data in /data (a volume).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir pillow==11.3.0 mutagen==1.47.0  # tzdata: the house's own day (TZ), for On this day and the log
WORKDIR /soundsquatch
COPY soundsquatch.py lms_qobuz.py lms_keep_album.py library.py genres.py listening.py stage-photos.json ./
COPY app/ app/
ENV SOUNDSQUATCH_DATA=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8097
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s CMD python3 -c "import os, urllib.request; h = os.environ.get('MUSIC_APP_BIND', '0.0.0.0'); urllib.request.urlopen('http://%s:%s/' % ('127.0.0.1' if h == '0.0.0.0' else h, os.environ.get('MUSIC_APP_PORT', '8097')), timeout=4)"
COPY entrypoint.sh ./
ENTRYPOINT ["./entrypoint.sh"]

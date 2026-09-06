FROM python:3.13-slim
WORKDIR /app
ARG GUKO_VERSION=0.5.7
ENV GUKO_VERSION=${GUKO_VERSION}
LABEL org.opencontainers.image.version=${GUKO_VERSION}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-client sshpass ca-certificates fonts-dejavu-core fonts-noto-cjk fonts-noto-core curl gnupg librsvg2-bin chromium \
 && curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*
COPY telegram-bot/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
RUN npm install -g playwright@1.59.1
ENV NODE_PATH=/usr/lib/node_modules PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
COPY auth.py guko.py jiaoops.py /app/
RUN mkdir -p /data/keys /data/media /data/tmp
COPY telegram-bot/bot.py telegram-bot/render_checkplace.py telegram-bot/render_ansi.js /app/
COPY telegram-bot/resources/checkplace-terminal/ /app/resources/checkplace-terminal/
# xyBarNQ is an operator-supplied private display font, not distributed here.
ENV CHECKPLACE_TERMINAL_FONT=/data/fonts/xyBarNQ.ttf
RUN node --check /app/render_ansi.js
# Fail the build if a required regular/bold/oblique face is missing. Private
# xyBarMono stays outside the public image; mount it via CHECKPLACE_GRAPH_FONT.
RUN python -c "from PIL import ImageFont; import render_checkplace as r; [ImageFont.truetype(getattr(r, name), 28) for name in ('DEFAULT_LATIN', 'DEFAULT_LATIN_ITALIC', 'DEFAULT_LATIN_BOLD', 'DEFAULT_LATIN_BOLD_ITALIC', 'DEFAULT_CJK', 'DEFAULT_CJK_BOLD', 'DEFAULT_SYMBOLS')]"
COPY telegram-bot/tools/ /app/tools/
ENV BGP_FETCH=/app/tools/bgp_fetch.py IPPURE_DOWNLOAD=/app/tools/download_ippure.js
CMD ["python", "/app/bot.py"]

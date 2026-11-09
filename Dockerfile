FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY static.zip ./static.zip
RUN python -m zipfile -e static.zip static
# Overlay editable sources so Render serves SEO fixes even before static.zip
# is rebuilt for a separate Cloudflare Pages upload.
COPY cloudflare-pages/frontend/ ./frontend_overrides/
RUN cp -a frontend_overrides/. static/
RUN python -c "from pathlib import Path; p=Path('static/index.html'); s=p.read_text(encoding='utf-8'); tag='<meta name=\"google-site-verification\" content=\"C9zss3TBFeuRPm8NITYwpskEATsY9FX_-aom9kCX2G4\" />'; assert '<head>' in s; p.write_text(s if tag in s else s.replace('<head>', '<head>\\n'+tag, 1), encoding='utf-8')"
ENV GOLDCHAT_HOST=0.0.0.0 GOLDCHAT_DATA_DIR=/tmp/goldchat PYTHONUNBUFFERED=1
EXPOSE 10000
CMD ["python", "server.py"]

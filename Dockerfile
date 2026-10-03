FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY static.zip ./static.zip
RUN python -m zipfile -e static.zip static
ENV GOLDCHAT_HOST=0.0.0.0 GOLDCHAT_DATA_DIR=/tmp/goldchat PYTHONUNBUFFERED=1
EXPOSE 10000
CMD ["python", "server.py"]

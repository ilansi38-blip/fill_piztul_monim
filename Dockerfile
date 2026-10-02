FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    TZ=Asia/Jerusalem \
    FORM_FILLER_HEADLESS=1 \
    FORM_FILLER_HOST=0.0.0.0 \
    FORM_FILLER_PORT=8765

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py parser.py web_gui.py forms.json ./
COPY web/ web/
COPY templates/ templates/
COPY configs/ configs/
RUN mkdir -p output

EXPOSE 8765

# Web UI by default. For the CLI instead:  docker run --rm form-filler python main.py
CMD ["python", "web_gui.py"]

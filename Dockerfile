FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 BOT_TIMEZONE=WIB DB_PATH=/data/pengeluaran.db
COPY bot.py core.py app.py features.py v22.py storage_v22.py v23.py storage_v23.py schedule_v23.py v24.py storage_v24.py excel_cash.py backups.py cadangan.py ui.py excel_export.py ./
COPY assets/rekap-template.xlsx ./assets/rekap-template.xlsx
COPY assets/arus-kas-template.xlsx ./assets/arus-kas-template.xlsx
CMD ["python", "bot.py"]

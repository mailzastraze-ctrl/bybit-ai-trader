# One container = trading bot + manager + research worker + web terminal (Railway: one volume per service).
FROM freqtradeorg/freqtrade:2026.10

ENV PYTHONUNBUFFERED=1 \
    AITRADER_APP=/app \
    AITRADER_DATA=/data \
    PYTHONUSERBASE=/home/ftuser/.local \
    MALLOC_ARENA_MAX=2 \
    NUMEXPR_MAX_THREADS=2

USER root
RUN mkdir -p /app /data && chown -R ftuser:ftuser /app /data
USER ftuser
WORKDIR /app
COPY --chown=ftuser:ftuser pyproject.toml ./
COPY --chown=ftuser:ftuser src ./src
RUN pip install --user --no-cache-dir --no-deps -e . \
 && python -c "import aitrader, freqtrade; print('aitrader', aitrader.__version__, 'freqtrade', freqtrade.__version__)"
COPY --chown=ftuser:ftuser ft ./ft
COPY --chown=ftuser:ftuser config ./config

# Railway volumes are mounted as root → run as root; Python packages stay in ftuser's user base.
USER root
EXPOSE 8000
ENTRYPOINT []
CMD ["python", "-m", "aitrader.supervisor"]

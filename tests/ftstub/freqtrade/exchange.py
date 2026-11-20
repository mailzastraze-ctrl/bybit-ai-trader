def timeframe_to_minutes(tf: str) -> int:
    n, unit = int(tf[:-1]), tf[-1]
    return n * {"m": 1, "h": 60, "d": 1440}[unit]

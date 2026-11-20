class BaseParameter:
    def __init__(self, low, high, *, default, space=None, optimize=True, **kw):
        self.low, self.high, self.value, self.space = low, high, default, space


class IntParameter(BaseParameter):
    pass


class DecimalParameter(BaseParameter):
    def __init__(self, low, high, *, default, decimals=3, **kw):
        super().__init__(low, high, default=round(default, decimals), **kw)


class IStrategy:
    def __init__(self, config: dict):
        self.config = config


def stoploss_from_absolute(stop_rate, current_rate, is_short=False, leverage=1.0):
    if current_rate == 0:
        return 1
    stoploss = 1 - (stop_rate / current_rate)
    if is_short:
        stoploss = -stoploss
    return max(stoploss * leverage, 0.0)


def merge_informative_pair(dataframe, informative, timeframe, timeframe_inf, ffill=True,
                           append_timeframe=True, date_column="date", suffix=None):
    """Same alignment as freqtrade: a higher-timeframe candle becomes visible on the last
    lower-timeframe candle inside it (i.e. once it has closed), then forward-filled."""
    import pandas as pd

    from freqtrade.exchange import timeframe_to_minutes
    m, mi = timeframe_to_minutes(timeframe), timeframe_to_minutes(timeframe_inf)
    informative = informative.copy()
    if m == mi:
        informative["date_merge"] = informative[date_column]
    else:
        informative["date_merge"] = informative[date_column] + pd.to_timedelta(mi, "m") - pd.to_timedelta(m, "m")
    informative.columns = [f"{c}_{timeframe_inf}" for c in informative.columns]
    dm = f"date_merge_{timeframe_inf}"
    out = pd.merge(dataframe, informative, left_on="date", right_on=dm, how="left").drop(dm, axis=1)
    return out.ffill() if ffill else out

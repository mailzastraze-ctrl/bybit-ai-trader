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

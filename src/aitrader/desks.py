"""Coin desks – the demo as one experiment (owner, 2026-11-23).

"Top 25–30 coins; on each coin trades the strategy that is best on that coin; the strategies
differ, including in how often they trade (active ones and rare precise ones); after ~3 weeks
every coin has the real statistics of one strategy that passed all the tests on history."

- **Pool:** strategies that passed the research tests (validated / exploratory, the autopilot,
  the owner's configurations, forward-proven `fw-`), never rejected or retired ones.
- **Best on a coin = return and stability:** the strategy's own out-of-sample profit per month on
  that coin (walk-forward `pair_stats`, at least `MIN_COIN_TRADES` trades there), reduced in
  proportion to the strategy's out-of-sample max drawdown (zero at `MAX_DD`, which excludes it).
- **Frequency mix:** trades per month on the coin put each choice in a bucket (active /
  medium / rare, the pool's terciles). Among the near-best strategies of a coin (≥ `NEAR_BEST`
  of the best profit) the least-filled bucket wins, so the desks hold all three kinds.
- **One strategy, one coin:** a strategy runs on at most one desk; its live record is the
  coin's record (the sleeve id is the strategy id, so the explorer and statistics work as before).
- **Frozen:** the assignment is made once and kept for the whole experiment. No queue, no
  rotation, no retirement. A coin without a qualifying strategy stays open and is filled when a
  later lab import brings one. `DESK_EPOCH` (env) starts a new experiment with a fresh choice.

Pure selection here; persistence and the manifest are in `lifecycle`."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass

MIN_COIN_TRADES = 3     # out-of-sample trades of the strategy on this coin
MAX_DD = 0.30           # out-of-sample max drawdown at which a strategy's score reaches zero
NEAR_BEST = 0.5         # a desk may take a strategy with ≥ half the coin's best score to vary frequency
DAYS_PER_MONTH = 30.44
BUCKETS = ("active", "medium", "rare")


@dataclass
class Option:
    """One strategy's evidence on one coin."""
    strategy: str
    family: str
    timeframe: str
    pnl: float          # out-of-sample profit on this coin (backtest money)
    trades: int         # out-of-sample trades on this coin
    days: float         # length of that out-of-sample record
    dd: float = 0.0     # the strategy's out-of-sample max drawdown (fraction)
    rank: tuple = ()    # evidence class, research score (tie-break)

    @property
    def months(self) -> float:
        return max(self.days, 1.0) / DAYS_PER_MONTH

    @property
    def per_month(self) -> float:
        return self.trades / self.months

    @property
    def pnl_month(self) -> float:
        return self.pnl / self.months

    @property
    def score(self) -> float:
        """Return with a stability discount: profit per month on the coin × (1 − drawdown / MAX_DD)."""
        return self.pnl_month * max(0.0, 1.0 - self.dd / MAX_DD)

    def qualifies(self) -> bool:
        return self.trades >= MIN_COIN_TRADES and self.pnl > 0 and self.dd < MAX_DD


def coin_name(pair: str) -> str:
    return str(pair).split("/")[0]


def picks(desk: dict) -> list[dict]:
    """The strategies a desk trades: the automatic choice (one), or the owner's own choice from
    the coin's list of best strategies (`picks`, any number, possibly none)."""
    if isinstance(desk.get("picks"), list):
        return [p for p in desk["picks"] if isinstance(p, dict) and p.get("strategy")]
    return [desk] if desk.get("strategy") else []


def bucket_cuts(options: list[Option]) -> tuple[float, float]:
    """Terciles of trades per month over the qualifying options (active above `hi`, rare below `lo`)."""
    f = sorted(o.per_month for o in options)
    if not f:
        return (0.0, 0.0)
    return (f[len(f) // 3], f[(2 * len(f)) // 3])


def bucket(per_month: float, cuts: tuple[float, float]) -> str:
    lo, hi = cuts
    if per_month >= hi and hi > lo:
        return "active"
    if per_month < lo:
        return "rare"
    return "medium"


def assign(evidence: dict[str, list[Option]], coin_order: list[str], n_desks: int,
           frozen: dict[str, dict] | None = None, cuts: tuple[float, float] | None = None,
           excluded: set[str] | None = None) -> tuple[dict[str, dict], tuple[float, float]]:
    """Desks for up to `n_desks` coins. `frozen` desks are kept as they are; only open coins are
    filled. Coins are taken in `coin_order` (liquidity), then any other coin with evidence (best
    score first). Returns (desks by pair, bucket cuts)."""
    desks = dict(frozen or {})
    excluded = excluded or set()
    pool = {c: sorted((o for o in xs if o.qualifies()), key=lambda o: (-o.score, tuple(-x for x in o.rank)))
            for c, xs in evidence.items() if c not in excluded}
    pool = {c: xs for c, xs in pool.items() if xs}
    if cuts is None:
        cuts = bucket_cuts([o for xs in pool.values() for o in xs])
    rest = sorted((c for c in pool if c not in coin_order), key=lambda c: -pool[c][0].score)
    order = [c for c in coin_order if c in pool] + rest
    used = Counter(d["strategy"] for d in desks.values())
    counts = Counter(d["bucket"] for d in desks.values())
    families = Counter(d["family"] for d in desks.values())
    for coin in order:
        if len(desks) >= n_desks:
            break
        if coin in desks:
            continue
        fresh = [o for o in pool[coin] if not used[o.strategy]]
        if not fresh:
            continue  # every strategy with evidence here already runs another coin
        best = fresh[0]
        near = [o for o in fresh if o.score >= NEAR_BEST * best.score]
        first: dict[str, Option] = {}
        for o in near:  # the best option of each frequency bucket
            first.setdefault(bucket(o.per_month, cuts), o)
        b = min(first, key=lambda k: (counts[k], families[first[k].family], -first[k].score))
        pick = first[b]
        desks[coin] = {"pair": coin, "strategy": pick.strategy, "family": pick.family,
                       "timeframe": pick.timeframe, "bucket": b,
                       "per_month": round(pick.per_month, 2), "pnl_month": round(pick.pnl_month, 2),
                       "max_dd": round(pick.dd, 4), "score": round(pick.score, 2),
                       "oos_trades": pick.trades, "oos_days": round(pick.days),
                       "best_on_coin": pick.strategy == best.strategy}
        used[pick.strategy] += 1
        counts[b] += 1
        families[pick.family] += 1
    return desks, cuts


def summary(desks: dict[str, dict]) -> dict:
    c = Counter(d.get("bucket") for d in desks.values())
    return {"coins": len(desks), **{b: c.get(b, 0) for b in BUCKETS}}


def option_dict(o: Option) -> dict:
    return asdict(o)

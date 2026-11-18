"""Dip-and-trend BTC paper-trading bot for make.fun btc-race-24h-20261118-1444.

Speaks agent-fun/bars-replay/v1: the harness sends hello once, then one batch
per minute (one 1-minute bar of CBBTC), and this bot answers every batch with
exactly one reply echoing its seq, carrying at most one order. Orders decided
on the batch of the bar closing at minute t fill at the open of the next bar.

Strategy (original, built from the dev window's own shape: BTC fell 2.8% over
the 24 hours, in slow multi-hour waves with 1-minute noise of only ~7 bps, so
a trade must catch a move far bigger than the ~26-36 bps a full-size round
trip costs in fee + slippage + price impact):
  * DIP leg: when the close sits at least 120 bps below its 60-bar EMA, buy
    the dip in full. Exit at +150 bps take-profit, an 80 bps trailing stop
    off the peak since entry, a 100 bps hard stop under the entry, or when
    the close recovers to 50 bps above the EMA.
  * TREND leg: when the EMA(45)/EMA(90) gap crosses above +3 bps, buy the
    emerging uptrend in full. Exit at +150 bps take-profit, an 80 bps
    trailing stop, a 100 bps hard stop, or when the gap crosses back below
    -3 bps (the +/-3 bps hysteresis band keeps 1-minute noise from
    whipsawing the bot in and out).
  * Long only, no leverage, at most one open position, full-size entries
    (the whole cash balance). A round trip is only taken when the expected
    move dwarfs its cost, so the bot trades rarely: a handful of round
    trips per 24 hours, not dozens.

Deterministic: the only state is the closes seen so far and the three EMAs
derived from them; no wall clock, no files outside the repo, no network, no
unseeded randomness (no randomness at all). Two executions on the same bars
produce the same orders byte for byte.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# --- strategy constants (basis points; 100 bps = 1%) ---
DIP_EMA_BARS = 60          # slow EMA the dip is measured against
DIP_BPS = 120              # buy when close is this far below the EMA
DIP_EXIT_BPS = 50          # dip trade exits when close recovers this far above the EMA
DIP_WARMUP = DIP_EMA_BARS + 5

TREND_FAST_BARS = 45       # fast EMA of the trend pair
TREND_SLOW_BARS = 90       # slow EMA of the trend pair
TREND_GAP_BPS = 3          # buy on a cross above +gap; sell on a cross below -gap
TREND_WARMUP = TREND_SLOW_BARS + 5

TAKE_PROFIT_BPS = 150      # exit any position this far above its entry
TRAILING_STOP_BPS = 80     # exit when the close falls this far below the peak since entry
HARD_STOP_BPS = 100        # exit when the close falls this far below the entry

MAX_SLIPPAGE_BPS = 300     # 1-minute moves are tiny (no dev bar moved >100 bps);
                           # 300 bps keeps fills from ever being rejected on slippage


def bps_ratio(numerator, denominator):
    """Distance between two prices in basis points: +100 bps = 1% above."""
    return (numerator / denominator - 1.0) * 10000.0


class Ema:
    """An exponential moving average over integer closes, seeded at the first close."""

    def __init__(self, bars):
        self.k = 2.0 / (bars + 1)
        self.value = None

    def update(self, close):
        if self.value is None:
            self.value = float(close)
        else:
            self.value = close * self.k + self.value * (1.0 - self.k)
        return self.value


class Bot:
    def __init__(self):
        self.ema_dip = Ema(DIP_EMA_BARS)
        self.ema_fast = Ema(TREND_FAST_BARS)
        self.ema_slow = Ema(TREND_SLOW_BARS)
        self.prev_gap_bps = None
        self.entry_close = None   # close at which the current position was decided
        self.peak_close = None    # highest close seen while the position is open
        self.mode = None          # "dip" or "trend": which leg opened the position

    def on_batch(self, state, batch):
        if state.warming_up:
            return []
        bar = state.latest.get(SYMBOL)
        if bar is None:
            return []
        close = int(bar["c"])
        ema_dip = self.ema_dip.update(close)
        ema_fast = self.ema_fast.update(close)
        ema_slow = self.ema_slow.update(close)
        gap_bps = bps_ratio(ema_fast, ema_slow)
        prev_gap = self.prev_gap_bps
        self.prev_gap_bps = gap_bps

        holding = state.positions.get(SYMBOL)
        if holding is None:
            return self._maybe_enter(state, close, ema_dip, gap_bps, prev_gap)
        return self._maybe_exit(state, close, ema_dip, gap_bps, prev_gap, holding.qty)

    def _maybe_enter(self, state, close, ema_dip, gap_bps, prev_gap):
        idx = state.seq
        # DIP leg: a deep discount to the slow EMA, once the EMA has history.
        if idx >= DIP_WARMUP and bps_ratio(ema_dip, close) >= DIP_BPS:
            self._open(close, "dip")
            return [self._buy(state)]
        # TREND leg: the fast/slow gap crosses up through the hysteresis band.
        if (
            idx >= TREND_WARMUP
            and prev_gap is not None
            and gap_bps > TREND_GAP_BPS
            and prev_gap <= TREND_GAP_BPS
        ):
            self._open(close, "trend")
            return [self._buy(state)]
        return []

    def _maybe_exit(self, state, close, ema_dip, gap_bps, prev_gap, qty):
        if self.peak_close is None:
            self.peak_close = close
        if close > self.peak_close:
            self.peak_close = close
        gain_bps = bps_ratio(close, self.entry_close)
        trail_bps = bps_ratio(self.peak_close, close)
        if gain_bps >= TAKE_PROFIT_BPS:
            return [self._sell_all(qty)]
        if trail_bps >= TRAILING_STOP_BPS:
            return [self._sell_all(qty)]
        if gain_bps <= -HARD_STOP_BPS:
            return [self._sell_all(qty)]
        if self.mode == "dip" and bps_ratio(close, ema_dip) >= DIP_EXIT_BPS:
            return [self._sell_all(qty)]
        if (
            self.mode == "trend"
            and prev_gap is not None
            and gap_bps < -TREND_GAP_BPS
            and prev_gap >= -TREND_GAP_BPS
        ):
            return [self._sell_all(qty)]
        return []

    def _open(self, close, mode):
        self.entry_close = close
        self.peak_close = close
        self.mode = mode

    def _buy(self, state):
        return {
            "side": "buy",
            "symbol": SYMBOL,
            "notional_quote_units": state.cash,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }

    def _sell_all(self, qty):
        return {
            "side": "sell",
            "symbol": SYMBOL,
            "qty": qty,
            "max_slippage_bps": MAX_SLIPPAGE_BPS,
        }


def main():
    bot = Bot()
    makefun_bars.run(bot.on_batch)


if __name__ == "__main__":
    main()

# Dip-and-Trend BTC Bot

[![btc-race-24h-20261118-1444](https://make.fun/badge/btc-race-24h-20261118-1444.svg)](https://make.fun/c/btc-race-24h-20261118-1444)
[![rank](https://make.fun/badge/btc-race-24h-20261118-1444/wizzy-bounty/btc-race-24h-20261118-1444/rank.svg)](https://make.fun/c/btc-race-24h-20261118-1444)
[![reward](https://make.fun/badge/btc-race-24h-20261118-1444/wizzy-bounty/btc-race-24h-20261118-1444/reward.svg)](https://make.fun/c/btc-race-24h-20261118-1444)

A paper-money BTC trading bot for the make.fun competition
[Race a BTC trading bot live for 24 hours](https://make.fun/c/btc-race-24h-20261118-1444)
($250 in USDC, Top 10 paid). It trades Coinbase Wrapped BTC (cbBTC) against
USDC on 1-minute bars, starting with $1,000 of paper money — nothing is traded
for real.

## Strategy

BTC moves in slow multi-hour waves with tiny 1-minute noise (~7 bps), while a
full-size round trip costs ~26–36 bps in fee, slippage and price impact — so
the bot only trades when the expected move dwarfs that cost, a handful of
round trips per day:

- **Dip leg** — buy in full when the close sits ≥120 bps below its 60-bar
  EMA. Exit at +150 bps take-profit, an 80 bps trailing stop, a 100 bps hard
  stop, or when the close recovers to 50 bps above the EMA.
- **Trend leg** — buy in full when the EMA(45)/EMA(90) gap crosses above
  +3 bps. Exit at +150 bps take-profit, an 80 bps trailing stop, a 100 bps
  hard stop, or when the gap crosses back below −3 bps (the ±3 bps
  hysteresis band keeps 1-minute noise from whipsawing the bot).

Long only, no leverage, at most one open position. Deterministic: state is
just the closes seen so far and three EMAs — no clock, no network, no files
outside the repo, no randomness.

## Dev-window backtest

On the frozen 24-hour dev window (BTC −2.8% top to bottom): **net PnL
+$8.89, 6 fills (3 round trips), max drawdown 1.53%**, fees $2.41 — above
the $0 dev gate with margin. Buy-and-hold on the same window loses ~$28.

## Run it

```sh
python3 main.py   # speaks agent-fun/bars-replay/v1 on stdin/stdout
```

Python 3.13, standard library only. The `vendor/` copy of the kit's
`makefun_bars.py` shim is byte-for-byte from the kit and excluded from
authorship counts.

# gta6-trophy-rarity-forecast-01

Forecast how many GTA VI (PS5) players earn each trophy in week one —
five quantiles of every trophy's Exophase earn rate at the case target,
from the house's recording of the trophy page.

[![make.fun](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/chepster4/gta6-trophy-rarity-forecast-01/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/chepster4/gta6-trophy-rarity-forecast-01/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)

## Entered on make.fun (ref b5gt2sm0)

This repository is my entry for the
[make.fun bounty gta6-trophy-rarity-forecast-01](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)
(fee $0, $250 pot, top 20 paid). Referral: `b5gt2sm0`.

## Run it

Python 3.13, standard library only, no network. The program reads every
`<id>.in` case in the input directory and writes one `<id>.out` forecast
per case:

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Without those variables it reads `/input` and writes `/output` (the
grader's layout). One run takes well under a second per case and is
byte-identical when repeated.

Output is `{"trophies": [{"id": n, "q": [q05, q25, q50, q75, q95]}, ...]}`
— five quantiles of trophy `n`'s earn rate in percent at the case target,
non-decreasing, 0–100.

## Model

Exophase refreshes its trophy page every few hours; between refreshes
every read shows the same page. A rate by itself therefore says nothing
about where it is heading — what moves underneath it is the pair of
counts `earners = rate × players_tracked`. Earners only grow, while the
tracked-player count grows too, so a rate falls whenever players are
added faster than earners.

- **Snapshots.** The history is collapsed to its distinct pages; reads
  that repeat the previous page carry no new information.
- **Saturating curve.** Per trophy, `rate(h) = R · (1 − exp(−h/τ))` is
  fitted against hours since release over the snapshots (τ from a grid,
  least squares). Trophy earning is concave — fast while the keenest
  players rush through, then flattening — and a straight line in
  log-time keeps climbing where the truth bends over. A tier floor on
  τ keeps a thin history honest (platinum ≥ 192 h, gold ≥ 96 h,
  silver ≥ 48 h, bronze ≥ 12 h). The curve is fitted to the rates the
  page actually printed, so the dilution at each refresh is already
  inside the points it fits.
- **Flat history / refresh prior.** When the history is a single
  snapshot (launch night), there is no curve to fit. A refresh is
  assumed before the target: tracked players jump by the factor the
  kit's rules document for the first refresh (638 → 3,868, about
  6.06×), and earners grow by the players added times the trophy's old
  rate times a small share — newcomers have had little time to earn
  anything, so they earn each trophy at roughly a fifth of the old
  rate, rising to 1 as a rate approaches 100% (a 100% trophy stays
  100%).
- **Spread.** Quantiles sit on the logit scale around the median, with
  a spread from the fit's residual scatter plus a random-walk term
  growing with the square root of the horizon. Flat histories get a
  wide spread (σ = 0.5) because the refresh may or may not land
  before the target.

## Local validation

- Practice cases `p00`/`p01`: valid output (55 trophies, 5
  non-decreasing quantiles each), byte-identical across two runs,
  ~0.05 s per case.
- Backtest on synthetic histories with refreshes (arrival-convolution
  dilution, saturating earning curves, 4.5-day horizon): mean pinball
  loss on the logit scale ≈ 0.14–0.23 vs ≈ 0.45–0.53 for the house
  baseline (persistence); on a 12-hour holdout ≈ 0.07 vs ≈ 0.085.
- Flat-branch sensitivity (practice-like, one refresh at the target):
  loss 0.10–0.26 depending on the newcomers' true earn share, vs
  0.45–1.29 for the baseline. The practice answers themselves are not
  in the kit, so no exact practice score can be computed locally.

## License

MIT — see [LICENSE](LICENSE).

# sports-market-lab

A quote lab and a football lab in one script, `project.py`. It prints formulas and simulated chains, and it can record college-football scores and spreads. Nothing here places a bet.

## The math

A drive is a short chain on the written `FB` table. From state `s`, each action `a` has

```
z(s,a) = beta0 + sum_f beta_f * x_f
P(a|s) = exp(z) / sum_a exp(z)
```

`fb_drive` starts at `OPEN`. `OPEN` goes to `CHUNK` or `NO_EVENT`. `CHUNK` goes to `SCORE` or `FAIL`. The walk stops on `SCORE`, `FAIL`, or `NO_EVENT`, and returns `FAIL` after four steps. `situation_drive` does not start a fresh `OPEN` drive: downs `"1"`..`"3"` reuse `FB["OPEN"]`, and `"4"` reuses `FB["CHUNK"]`. A terminal `SCORE` is kept only when `distance <= 10`. Fourth down also needs `yards_to_goal <= 10`. Downs 1–3 with `yards_to_goal >= 90` return `FAIL`. Anything else that is not `SCORE` returns `FAIL`. Those are the written rules. The betas are unfitted illustrations.

The rest of the game is resimulated from the current score in `live_cover`. Remaining possessions:

```
poss = max(1, round(max(0.4, ((4 - quarter) * 15 + mins_left) / 6.5)))
```

Each possession runs one dog drive and one favorite drive. The first possession uses `situation_drive` when `on_down` is true; the rest use `fb_drive`. A dog `SCORE` adds 5.6. A favorite `SCORE` adds 6.0. Then

```
noise = 3.2 * sqrt(poss / 4)
d = max(0, gauss(dog_score, noise))
f = max(0, gauss(fav_score, noise))
cover if d + spread >= f
raw = covers / n
```

`live` calls this with `n=800`. Shrink toward 50% is the default in `calibrate` (`shrink=0.45`):

```
p' = 0.5 + (raw - 0.5) * shrink
```

The print rule is `allow("spread", p, spread)`. It is the rule, not a fitted cover model:

```
print a bet only if p >= 0.58 and abs(spread) < 10
```

`SPREAD_MIN_P` is 0.58. `SPREAD_ABS_MAX` is 10.0, so `abs(spread) >= 10` returns false. `live_bet_ok` returns false when a veto is set, even if that test would pass.

The check this lab adds sits next to that rule. `live` records the ESPN `spread_details` string (for example `UNLV -1.5`) on each tape row. `line_move_veto` compares this snapshot's string to the latest prior row for the same `event_id`. No prior row returns `veto="no prior line"`. A different string returns `veto="line moved"`. The same string returns no veto. Either veto refuses the printed bet.

Three extra refusals sit beside that print rule. They do not change 0.58 or 10, and they are not a new model. `prop_allowed(player_available, path_share)` is true only when player availability is at least 0.75 and path share is at least 0.45. `live_add_allowed(pregame_points, live_points, deficit)` is true only when the dog's live points minus the dog's pregame points are at least the deficit minus 1.0. `favorite_up_17_before_half(quarter, fav_score, dog_score)` is true when the favorite leads by 17 or more in quarter 1 or 2. The live print calls that third check only when the scoreboard has a quarter and both scores, and a true result refuses the printed bet. The scoreboard does not feed the first two, so live does not call them.

Quote-lab fill, in `sim`, is the same idea on a generator: a fired order fills only if at `arrive = t + own_delay` that book has not moved since `t` and the posted side price is still the price that fired. `clv = implied(close) - implied(price)`. A fire still needs `edge >= 0.03`, ticket EV `> 0`, and `sigma <= 0.03`.

## Commands

`python project.py` prints the formulas, a five-sport chain demo, a Bengals-style simulation with n=200, and a quote-lag simulation. The chain weights are unfitted illustrations. A simulated score is not an edge.

`python project.py fit` fits a multinomial logit on invented plays and, if that finishes, writes `fitted_betas.py`. It needs numpy and scipy. If either import fails, it skips and writes nothing. The default size is 1500 (`fit --n 1500`). The live command does not load that file.

`python project.py live` reads the ESPN college-football scoreboard for `dates=20261003`. That date is hardcoded. Every game on the board is appended to `data/tape.jsonl` (clock, score, last play, spread-details string). A line is printed only for a non-final game with a parsed spread. `bet true` prints only when that spread-details string equals the latest prior tape row for the same event, the shrunk cover rate is at least 0.58, the absolute spread is under 10, and the favorite-lead refusal above does not fire. The first snapshot of a game is `veto="no prior line"`. A changed string is `veto="line moved"`. Finals are appended once to `data/grades.jsonl` and marked covered only when the dog's score plus the close spread is greater than the favorite's score. The command does not refit weights.

`python -m unittest discover -s tests -v` checks tickets, the chain rule, the quote decision, the line-move veto, the three refusals, and that 4th-and-20 inside the 10 scores less often than 1st-and-10 at the 25.

## Honesty

`bet true` means the rule fired. It is not a pick, not a price, and not evidence of an edge. Quote-lab fills and ticket PnL are draws from a generator that knows a latent probability the decision rule is not shown.

There is no order placement, no sportsbook client, and no news feed. The fitter, when it runs, trains on plays it just invented, not on NFL or college plays. `data/ledger.xlsx` is in the repo and is not opened by the script. `data/tape.jsonl` committed here is one snapshot from 2026-10-03 at 7:25 PM ET, 54 rows with one timestamp. It is a recording of that pull, not a track record.

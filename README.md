# sports-market-lab

A quote lab and a football lab in one script, `project.py`. It prints formulas and simulated chains, and it can record college-football scores and spreads. A line with no prior snapshot, or a spread string that has already changed, is refused. Nothing here places a bet.

## Commands

`python project.py` prints the formulas, a five-sport chain demo (football, baseball, hockey, UFC, basketball), a Bengals-style simulation with n=200, and a quote-lag simulation. The chain weights are unfitted illustrations. A simulated score is not an edge.

`python project.py fit` fits a multinomial logit on invented plays and, if that finishes, writes `fitted_betas.py`. It needs numpy and scipy. If either import fails, it skips and writes nothing. The default size is 1500 (`fit --n 1500`). The live command does not load that file.

`python project.py live` reads the ESPN college-football scoreboard for `dates=20261003`. That date is hardcoded. Every game on the board is appended to `data/tape.jsonl` (clock, score, last play, spread-details string). A line is printed only for a non-final game with a parsed spread. `bet true` prints only when that spread-details string equals the latest prior tape row for the same event, the shrunk cover rate is at least 0.58, and the absolute spread is under 10. The first snapshot of a game is `veto="no prior line"`. A changed string is `veto="line moved"`. Finals are appended once to `data/grades.jsonl` and marked covered only when the dog's score plus the close spread is greater than the favorite's score. The command does not refit weights.

`python -m unittest discover -s tests -v` checks tickets, the chain rule, the quote decision, the line-move veto, and that 4th-and-20 inside the 10 scores less often than 1st-and-10 at the 25.

## Honesty

`bet true` means the rule fired. It is not a pick, not a price, and not evidence of an edge. Quote-lab fills and ticket PnL are draws from a generator that knows a latent probability the decision rule is not shown.

There is no order placement, no sportsbook client, and no news feed. The fitter, when it runs, trains on plays it just invented, not on NFL or college plays. `data/ledger.xlsx` is in the repo and is not opened by the script. `data/tape.jsonl` committed here is one snapshot from 2026-10-03 at 7:25 PM ET, 54 rows with one timestamp. It is a recording of that pull, not a track record.

# sports-market-lab

A lab in one file. Run `python project.py`.

That prints the formulas, a five-sport chain demo, a Bengals-style sim
with n=200, and a quote-lag sim. Parameters are illustrations. A sim
score is not an edge. Do not bet real money.

`data/ledger.xlsx` sits beside the script. The script does not bet it.

`python project.py fit --n 1500` fits betas on synthetic draws and writes
`fitted_betas.py`. It needs numpy and scipy. If either import fails, it
skips and writes nothing. Synthetic recovery is not NFL data.

`python project.py live` reads the 20261003 NCAAF scoreboard. A game on a
down is simulated from that down, not a fresh drive. Each game is appended
to `data/tape.jsonl` (clock, score, last play, spread details). A bet
prints only when that spread details string matches the prior tape row
and the spread rule passes. A moved line or a missing prior row is a veto,
not a bet. Finals are appended to `data/grades.jsonl` and graded against
the close. It does not refit weights and it does not place a bet.

`python -m unittest discover -s tests -v` checks tickets, the chain rule,
the quote decision, and that 4th-and-20 inside the 10 scores less often
than 1st-and-10 at the 25.

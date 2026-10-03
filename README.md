# sports-market-lab

A lab in one file. Run `python project.py`.

That prints the formulas, a five-sport chain demo, a Bengals-style sim
with n=200, and a quote-lag sim. Parameters are illustrations. A sim
score is not an edge. Do not bet real money.

`data/ledger.xlsx` sits beside the script. The script does not bet it.

`python project.py fit --n 1500` fits betas on synthetic draws and writes
`fitted_betas.py`. It needs numpy and scipy. If either import fails, it
skips and writes nothing. Synthetic recovery is not NFL data.

`python -m unittest discover -s tests -v` checks tickets, the chain rule,
and the quote decision.

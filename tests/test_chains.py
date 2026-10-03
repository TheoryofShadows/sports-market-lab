import subprocess
import sys
import unittest
from pathlib import Path

import project

ROOT = Path(__file__).resolve().parents[1]


class AllowTests(unittest.TestCase):
    def test_spread_thresholds(self):
        self.assertFalse(project.allow("spread", 0.57, spread=3))
        self.assertTrue(project.allow("spread", 0.58, spread=3))
        self.assertFalse(project.allow("spread", 0.90, spread=10))

    def test_winner_three_points(self):
        imp = project.implied(-110)
        self.assertFalse(project.allow("winner", imp + 0.029, price=-110))
        self.assertTrue(project.allow("winner", imp + 0.03, price=-110))

    def test_total_near_fifty_and_price_test(self):
        self.assertFalse(project.allow("total", 0.90, price=-150, under_implied=0.60))
        under = project.implied(100)
        self.assertLessEqual(abs(under - 0.50), 0.02)
        self.assertFalse(project.allow("total", under + 0.029, price=100, under_implied=under))
        self.assertTrue(project.allow("total", under + 0.03, price=100, under_implied=under))

    def test_hockey_uses_calibrated_not_raw(self):
        imp = project.implied(-110)
        raw = imp + 0.03
        decided = project.decide_winner(raw, -110, shrink=0.5)
        self.assertGreaterEqual(raw, imp + 0.03)
        self.assertLess(decided["p"], imp + 0.03)
        self.assertFalse(decided["bet"])


class DemoTests(unittest.TestCase):
    def test_default_command_exits_zero(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "project.py")],
            cwd=ROOT,
            timeout=180,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        out = proc.stdout
        self.assertIn("z(s,a) = b0 + sum b_f * x_f", out)
        self.assertIn('betas are unfitted; "bet": true means the rule printed, not that you should bet.', out)
        self.assertIn("BENGALS-STYLE SIM n=200", out)
        self.assertIn("a positive number on this generator is not evidence of an edge", out)
        self.assertIn("QUOTE LAB", out)

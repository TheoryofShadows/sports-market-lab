import unittest

import project


class TicketTests(unittest.TestCase):
    def test_minus_110(self):
        self.assertAlmostEqual(project.ticket_payoff(-110, True), 100 / 110)
        self.assertEqual(project.ticket_payoff(-110, False), -1)

    def test_plus_price(self):
        self.assertAlmostEqual(project.ticket_payoff(150, True), 1.5)
        self.assertEqual(project.ticket_payoff(150, False), -1)


class DecisionTests(unittest.TestCase):
    def test_both_sides_from_a_stale_quote(self):
        home = project.decide_side({"home": 200, "away": -250}, p_hat=0.55, sigma=0.01)
        self.assertEqual(home["side"], "home")
        self.assertTrue(home["fire"])
        away = project.decide_side({"home": -250, "away": 200}, p_hat=0.45, sigma=0.01)
        self.assertEqual(away["side"], "away")
        self.assertTrue(away["fire"])

    def test_minus_110_at_even_is_negative_ev_and_not_a_fire(self):
        ev = project.ticket_ev(0.50, -110)
        self.assertLess(ev, 0.0)
        decision = project.decide_side({"home": -110, "away": -110}, p_hat=0.50, sigma=0.01)
        self.assertFalse(decision["fire"])
        self.assertLess(decision["ev"], 0.0)

    def test_sigma_above_threshold_refuses(self):
        decision = project.decide_side({"home": 200, "away": -250}, p_hat=0.55, sigma=0.04)
        self.assertFalse(decision["fire"])
        self.assertEqual(decision["reason"], "sigma")


class ConsensusTests(unittest.TestCase):
    def test_default_six_book_sigma(self):
        sigma = project.consensus_sigma(project.default_noises())
        self.assertGreater(sigma, 0.0)
        self.assertLess(sigma, 0.05)
        # A few probability points, not tens of thousands of basis points.
        self.assertLess(sigma, 0.03)


class SimTests(unittest.TestCase):
    def test_sim_keys(self):
        result = project.sim()
        self.assertIn("fills", result)
        self.assertIn("mean_pnl", result)
        self.assertIn("mean_clv", result)
        self.assertGreaterEqual(result["signals"], 0)
        self.assertGreaterEqual(result["fires"], result["fills"])

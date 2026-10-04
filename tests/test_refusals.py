import unittest

import project


class PropAllowedTests(unittest.TestCase):
    def test_both_thresholds_are_inclusive(self):
        self.assertTrue(project.prop_allowed(0.75, 0.45))
        self.assertTrue(project.prop_allowed(1.0, 1.0))

    def test_either_shortfall_refuses(self):
        self.assertFalse(project.prop_allowed(0.749, 0.45))
        self.assertFalse(project.prop_allowed(0.75, 0.449))
        self.assertFalse(project.prop_allowed(0.0, 0.0))


class LiveAddAllowedTests(unittest.TestCase):
    def test_cushion_is_deficit_minus_one(self):
        # Dog's number, positive. Equality is allowed.
        self.assertTrue(project.live_add_allowed(14.5, 14.5, 1.0))
        self.assertTrue(project.live_add_allowed(10.0, 14.0, 5.0))
        self.assertFalse(project.live_add_allowed(14.5, 13.5, 1.0))
        self.assertFalse(project.live_add_allowed(10.0, 13.9, 5.0))


class KillSwitchTests(unittest.TestCase):
    def test_seventeen_or_more_before_half_refuses(self):
        self.assertTrue(project.favorite_up_17_before_half(1, 17, 0))
        self.assertTrue(project.favorite_up_17_before_half(2, 24, 7))
        self.assertFalse(project.favorite_up_17_before_half(2, 23, 7))
        self.assertFalse(project.favorite_up_17_before_half(1, 16, 0))

    def test_second_half_does_not_kill(self):
        self.assertFalse(project.favorite_up_17_before_half(3, 40, 0))
        self.assertFalse(project.favorite_up_17_before_half(4, 40, 0))

    def test_missing_board_fields_are_not_a_score(self):
        self.assertIsNone(project._present_quarter({}))
        self.assertIsNone(project._present_quarter({"period": 0}))
        self.assertIsNone(project._present_quarter({"period": None}))
        self.assertEqual(project._present_quarter({"period": 2}), 2)
        self.assertIsNone(project._present_score({}))
        self.assertIsNone(project._present_score({"score": None}))
        self.assertIsNone(project._present_score({"score": ""}))
        self.assertEqual(project._present_score({"score": "0"}), 0)
        self.assertEqual(project._present_score({"score": "24"}), 24)

    def test_live_calls_the_kill_only_as_an_extra_refusal(self):
        import inspect
        src = inspect.getsource(project.cmd_live)
        self.assertIn("favorite_up_17_before_half", src)
        self.assertIn("_present_quarter", src)
        self.assertIn("_present_score", src)
        # The spread rule itself is unchanged.
        self.assertTrue(project.live_bet_ok(None, 0.58, 3.5))
        self.assertFalse(project.live_bet_ok(None, 0.57, 3.5))
        self.assertFalse(project.live_bet_ok(None, 0.90, 10))
        veto = {"veto": "favorite up 17 before half"}
        self.assertFalse(project.live_bet_ok(veto, 0.90, 3.5))
        line = project.format_live_line(
            "DOG", "FAV", 0, 24, "Q2 8:11", "1st & 10",
            "DOG", "+3.5", 0.90, False, veto,
        )
        self.assertIn('veto="favorite up 17 before half"', line)
        self.assertNotIn("bet true", line)

import tempfile
import unittest
from pathlib import Path

import project


def _row(details, utc, event_id="401"):
    return {
        "clock": "Q2 8:11",
        "event_id": event_id,
        "last_play": "run for 4 yards",
        "score": "7-10",
        "short_name": "A @ B",
        "spread_details": details,
        "utc": utc,
    }


class LineMoveVetoTests(unittest.TestCase):
    def test_same_spread_allows_a_bet_when_the_rule_passes(self):
        # Two tape rows, same spread details. The second snapshot may bet.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tape.jsonl"
            first = _row("OSU -3.5", "2026-10-03T20:00:00Z")
            second = _row("OSU -3.5", "2026-10-03T20:05:00Z")
            project.append_tape([first], path)
            project.append_tape([second], path)
            loaded = project.load_tape(path)
            self.assertEqual(len(loaded), 2)
            prior = project.prior_tape_rows(loaded[:1], "401")
            veto = project.line_move_veto(prior, second["spread_details"])
            self.assertIsNone(veto)
            self.assertTrue(project.live_bet_ok(veto, 0.58, 3.5))
            # The rule still refuses a short cover or a wide spread.
            self.assertFalse(project.live_bet_ok(veto, 0.57, 3.5))
            self.assertFalse(project.live_bet_ok(veto, 0.90, 10))

    def test_different_spreads_force_a_veto(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tape.jsonl"
            first = _row("OSU -3.5", "2026-10-03T20:00:00Z")
            second = _row("OSU -7", "2026-10-03T20:05:00Z")
            project.append_tape([first], path)
            loaded = project.load_tape(path)
            veto = project.line_move_veto(
                project.prior_tape_rows(loaded, "401"),
                second["spread_details"],
            )
            self.assertEqual(veto["veto"], "line moved")
            self.assertEqual(veto["old"], "OSU -3.5")
            self.assertEqual(veto["new"], "OSU -7")
            # Even a cover the rule would take does not print a bet.
            self.assertFalse(project.live_bet_ok(veto, 0.90, 3.5))
            line = project.format_live_line(
                "OSU", "PSU", 7, 10, "Q2 8:11", "2nd & 6",
                "OSU", "+3.5", 0.90, False, veto,
            )
            self.assertIn('veto="line moved"', line)
            self.assertIn('old="OSU -3.5"', line)
            self.assertIn('new="OSU -7"', line)
            self.assertNotIn("bet true", line)
            # Appending the new row does not drop the old one.
            project.append_tape([second], path)
            self.assertEqual(len(project.load_tape(path)), 2)

    def test_no_prior_line_is_not_a_bet(self):
        veto = project.line_move_veto([], "OSU -3.5")
        self.assertEqual(veto["veto"], "no prior line")
        self.assertFalse(project.live_bet_ok(veto, 0.90, 3.5))
        line = project.format_live_line(
            "OSU", "PSU", 0, 0, "Q1 15:00", "1st & 10 at the 25",
            "OSU", "+3.5", 0.90, False, veto,
        )
        self.assertIn('veto="no prior line"', line)
        self.assertNotIn("bet true", line)

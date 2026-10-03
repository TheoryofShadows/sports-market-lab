import unittest

import project


class DriveStartTests(unittest.TestCase):
    def test_fourth_and_20_inside_the_10_scores_less_than_first_and_10(self):
        # Down states alias the written rows. No new weights.
        self.assertIs(project.down_chain_table()["1"], project.FB["OPEN"])
        self.assertIs(project.down_chain_table()["4"], project.FB["CHUNK"])
        self.assertEqual(project.current_drive_start(4), "4")
        self.assertNotEqual(project.current_drive_start(4), "OPEN")
        seed = 20261003
        # 4th-and-20 inside the 10 (yards to the goal) vs 1st-and-10 at the 25.
        bad = project.drive_score_rate(4, 20, 8, n=400, seed=seed)
        good = project.drive_score_rate(1, 10, 75, n=400, seed=seed)
        self.assertLess(bad, good)

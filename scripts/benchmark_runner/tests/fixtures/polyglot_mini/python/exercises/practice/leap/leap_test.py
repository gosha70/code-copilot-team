import unittest

from leap import leap_year


class LeapYearTest(unittest.TestCase):
    def test_year_divisible_by_4_not_century(self) -> None:
        self.assertTrue(leap_year(2024))

    def test_year_not_divisible_by_4(self) -> None:
        self.assertFalse(leap_year(2023))

    def test_year_divisible_by_400(self) -> None:
        self.assertTrue(leap_year(2000))

    def test_year_divisible_by_100_not_400(self) -> None:
        self.assertFalse(leap_year(1900))


if __name__ == "__main__":
    unittest.main()

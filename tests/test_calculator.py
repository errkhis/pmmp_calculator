import unittest

from calculator import calculate_lot
from scraper import Bidder, ConsultationData


class CalculatorTests(unittest.TestCase):
    def test_prefers_closest_price_below_reference(self):
        data = ConsultationData(
            reference="123",
            object="Test consultation",
            estimated_price=100.0,
            estimated_price_currency="MAD",
            procedure="AOO",
            category="Works",
            bidders=[
                Bidder(rank=1, name="A", admin_status="ok", financial_status="ok", price=80.0),
                Bidder(rank=2, name="B", admin_status="ok", financial_status="ok", price=90.0),
                Bidder(rank=3, name="C", admin_status="ok", financial_status="ok", price=120.0),
            ],
        )

        result = calculate_lot(data)

        self.assertEqual(result.reference_price, 98.33)
        self.assertEqual(result.winner_names, ["B"])
        self.assertEqual(result.rankings[0].distance_to_estimation, 10.0)

    def test_falls_back_to_above_reference_when_no_offer_below(self):
        data = ConsultationData(
            reference="124",
            object="Test consultation",
            estimated_price=100.0,
            estimated_price_currency="MAD",
            procedure="AOO",
            category="Works",
            bidders=[
                Bidder(rank=1, name="A", admin_status="ok", financial_status="ok", price=110.0),
                Bidder(rank=2, name="B", admin_status="ok", financial_status="ok", price=120.0),
            ],
        )

        result = calculate_lot(data)

        self.assertEqual(result.winner_names, ["A"])
        self.assertEqual(result.rankings[0].side, "above")

    def test_appends_bidders_without_prices(self):
        data = ConsultationData(
            reference="125",
            object="Test consultation",
            estimated_price=100.0,
            estimated_price_currency="MAD",
            procedure="AOO",
            category="Works",
            bidders=[
                Bidder(rank=1, name="A", admin_status="ok", financial_status="ok", price=95.0),
                Bidder(rank=2, name="B", admin_status="ok", financial_status="ok", price=None),
            ],
        )

        result = calculate_lot(data)

        self.assertEqual(len(result.rankings), 2)
        self.assertEqual(result.rankings[1].note, "Eliminated - no price")


if __name__ == "__main__":
    unittest.main()

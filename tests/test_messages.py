import unittest
from datetime import datetime, timedelta, timezone

from bot.messages import account_status_message, build_winner_message, subscription_limit_message
from calculator import LotCalculation, RankedBidder
from database import User


class MessageTests(unittest.TestCase):
    def test_subscription_limit_mentions_premium_contact(self):
        text = subscription_limit_message("winner_admin")
        self.assertIn("@winner_admin", text)
        self.assertIn("5", text)

    def test_account_message_for_premium(self):
        user = User(
            telegram_id=1,
            username="demo",
            first_name="Demo",
            plan="premium",
            premium_expires_at=datetime.now(timezone.utc) + timedelta(days=10),
            free_winner_requests_used=5,
        )
        text = account_status_message(user, "winner_admin")
        self.assertIn("Premium", text)
        self.assertIn("unlimited", text)

    def test_build_winner_message_contains_distances(self):
        lot = LotCalculation(
            lot_id="1",
            lot_label=None,
            bidder_count=2,
            priced_offer_count=2,
            estimated_price=100.0,
            estimated_price_currency="MAD",
            average_offer_price=95.0,
            reference_price=97.5,
            winner_names=["Company A"],
            winner_price=96.0,
            rankings=[
                RankedBidder(
                    position=1,
                    name="Company A",
                    price=96.0,
                    distance_to_ref=1.5,
                    distance_to_reference=1.5,
                    distance_to_estimation=4.0,
                    estimation_gap_percent=-4.0,
                    side="below",
                    admin_status="ok",
                    financial_status="ok",
                    is_eligible=True,
                    note="Winner",
                )
            ],
        )
        text = build_winner_message("REF-1", [lot], "Object")
        self.assertIn("ΔP", text)
        self.assertIn("ΔE", text)
        self.assertIn("Company A", text)


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime, timedelta, timezone

from database import FREE_WINNER_LIMIT, User, can_create_winner_request


class DatabaseLogicTests(unittest.TestCase):
    def test_free_user_hits_limit(self):
        user = User(
            telegram_id=1,
            username="demo",
            first_name="Demo",
            plan="free",
            premium_expires_at=None,
            free_winner_requests_used=FREE_WINNER_LIMIT,
        )
        self.assertFalse(can_create_winner_request(user))
        self.assertEqual(user.remaining_free_requests, 0)

    def test_premium_user_bypasses_limit(self):
        user = User(
            telegram_id=1,
            username="demo",
            first_name="Demo",
            plan="premium",
            premium_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            free_winner_requests_used=FREE_WINNER_LIMIT,
        )
        self.assertTrue(can_create_winner_request(user))


if __name__ == "__main__":
    unittest.main()

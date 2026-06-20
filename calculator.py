from dataclasses import dataclass, field
from typing import Optional

from scraper import Bidder, ConsultationData


@dataclass
class RankedBidder:
    position: int
    name: str
    price: Optional[float]
    distance_to_reference: Optional[float]
    distance_to_estimation: Optional[float]
    estimation_gap_percent: Optional[float]
    side: str
    admin_status: str
    financial_status: str
    is_eligible: bool
    note: str


@dataclass
class LotCalculation:
    lot_id: Optional[str]
    lot_label: Optional[str]
    bidder_count: int
    priced_offer_count: int
    estimated_price: Optional[float]
    estimated_price_currency: str
    average_offer_price: Optional[float]
    reference_price: Optional[float]
    winner_names: list[str] = field(default_factory=list)
    winner_price: Optional[float] = None
    rankings: list[RankedBidder] = field(default_factory=list)


def calculate_consultation(data: ConsultationData) -> list[LotCalculation]:
    lots = data.lots or [data]
    return [calculate_lot(lot, index) for index, lot in enumerate(lots, start=1)]


def calculate_lot(data: ConsultationData, lot_index: int = 1) -> LotCalculation:
    priced = [bidder for bidder in data.bidders if bidder.price is not None]
    no_price = [bidder for bidder in data.bidders if bidder.price is None]

    average_offer_price = None
    reference_price = None
    if priced:
        average_offer_price = sum(bidder.price for bidder in priced) / len(priced)
    if priced and data.estimated_price is not None:
        reference_price = (data.estimated_price + average_offer_price) / 2

    ordered_priced = _order_priced_bidders(priced, reference_price)
    rankings = _build_rankings(ordered_priced, no_price, reference_price, data.estimated_price)

    eligible_rankings = [ranking for ranking in rankings if ranking.is_eligible]
    winner_names: list[str] = []
    winner_price = None
    if eligible_rankings:
        winner_price = eligible_rankings[0].price
        winner_names = [ranking.name for ranking in eligible_rankings if ranking.price == winner_price]

    return LotCalculation(
        lot_id=data.lot_id or str(lot_index),
        lot_label=data.lot_label,
        bidder_count=len(data.bidders),
        priced_offer_count=len(priced),
        estimated_price=data.estimated_price,
        estimated_price_currency=data.estimated_price_currency or "MAD",
        average_offer_price=_round2(average_offer_price),
        reference_price=_round2(reference_price),
        winner_names=winner_names,
        winner_price=winner_price,
        rankings=rankings,
    )


def _order_priced_bidders(priced: list[Bidder], reference_price: Optional[float]) -> list[Bidder]:
    if reference_price is None:
        return sorted(priced, key=lambda bidder: bidder.price)

    below = [bidder for bidder in priced if bidder.price <= reference_price]
    above = [bidder for bidder in priced if bidder.price > reference_price]
    below.sort(key=lambda bidder: bidder.price, reverse=True)
    above.sort(key=lambda bidder: bidder.price)
    return below + above if below else above


def _build_rankings(
    ordered_priced: list[Bidder],
    no_price: list[Bidder],
    reference_price: Optional[float],
    estimated_price: Optional[float],
) -> list[RankedBidder]:
    rankings: list[RankedBidder] = []
    winning_price = ordered_priced[0].price if ordered_priced and reference_price is not None else None

    for position, bidder in enumerate(ordered_priced, start=1):
        note = "Winner" if winning_price is not None and bidder.price == winning_price else ""
        rankings.append(
            RankedBidder(
                position=position,
                name=bidder.name,
                price=bidder.price,
                distance_to_reference=_distance(bidder.price, reference_price),
                distance_to_estimation=_distance(bidder.price, estimated_price),
                estimation_gap_percent=_gap_pct(bidder.price, estimated_price),
                side=_side(bidder.price, reference_price),
                admin_status=bidder.admin_status,
                financial_status=bidder.financial_status,
                is_eligible=reference_price is not None,
                note=note,
            )
        )

    start = len(rankings) + 1
    for offset, bidder in enumerate(no_price):
        rankings.append(
            RankedBidder(
                position=start + offset,
                name=bidder.name,
                price=None,
                distance_to_reference=None,
                distance_to_estimation=None,
                estimation_gap_percent=None,
                side="N/A",
                admin_status=bidder.admin_status,
                financial_status=bidder.financial_status,
                is_eligible=False,
                note="Eliminated - no price",
            )
        )
    return rankings


def _distance(value: Optional[float], target: Optional[float]) -> Optional[float]:
    if value is None or target is None:
        return None
    return _round2(abs(value - target))


def _gap_pct(value: Optional[float], estimated_price: Optional[float]) -> Optional[float]:
    if value is None or estimated_price in (None, 0):
        return None
    return _round2(((value - estimated_price) / estimated_price) * 100)


def _side(value: Optional[float], reference_price: Optional[float]) -> str:
    if value is None or reference_price is None:
        return "N/A"
    return "below" if value <= reference_price else "above"


def _round2(value: Optional[float]) -> Optional[float]:
    return round(value, 2) if value is not None else None

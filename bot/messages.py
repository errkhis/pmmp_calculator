from calculator import LotCalculation
from database import FREE_WINNER_LIMIT, User

MEDALS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


def esc(value) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_number(value):
    return "—" if value is None else f"{value:,.2f}"


def fmt_pct(value):
    if value is None:
        return "—"
    return f"{'+' if value >= 0 else ''}{value:.2f}%"


def fmt_date(value):
    return value.strftime("%Y-%m-%d") if value else "—"


def admin_contact(admin_username: str) -> str:
    return f"@{admin_username.lstrip('@')}" if admin_username else "the administrator"


def welcome_message(user: User | None, admin_username: str) -> str:
    lines = [
        "🏆 <b>Winner Calculation Bot</b>",
        "",
        "Send one <b>marchespublics.gov.ma</b> consultation link.",
        "The bot calculates the winner using the same reference-price method as your existing project.",
        "",
        f"Free plan: <b>{FREE_WINNER_LIMIT}</b> lifetime winner calculations.",
        f"Premium plan: <b>unlimited</b> calculations after admin activation via <b>{esc(admin_contact(admin_username))}</b>.",
    ]
    if user:
        lines.extend(["", account_status_message(user, admin_username)])
    return "\n".join(lines)


def help_message(admin_username: str, is_admin: bool) -> str:
    lines = [
        "📖 <b>Commands</b>",
        "/start - Show welcome message",
        "/help - Show commands",
        "/me - Show your plan and usage",
        "/subscription - Alias of /me",
        "",
        "Send a consultation link directly to calculate the winner.",
        "",
        f"Premium activation contact: <b>{esc(admin_contact(admin_username))}</b>",
    ]
    if is_admin:
        lines.extend(
            [
                "",
                "<b>Admin</b>",
                "/premium TELEGRAM_ID [years]",
                "/free TELEGRAM_ID",
                "/users",
            ]
        )
    return "\n".join(lines)


def account_status_message(user: User, admin_username: str) -> str:
    if user.is_premium:
        return (
            "👤 <b>Your account</b>\n"
            "Plan: <b>Premium</b>\n"
            f"Valid until: <b>{fmt_date(user.premium_expires_at)}</b>\n"
            "Winner calculations: <b>unlimited</b>"
        )
    return (
        "👤 <b>Your account</b>\n"
        "Plan: <b>Free</b>\n"
        f"Used: <b>{user.free_winner_requests_used}/{FREE_WINNER_LIMIT}</b>\n"
        f"Remaining: <b>{user.remaining_free_requests}</b>\n"
        f"To activate Premium, contact <b>{esc(admin_contact(admin_username))}</b>."
    )


def subscription_limit_message(admin_username: str) -> str:
    return (
        "🔒 <b>Free plan limit reached</b>\n\n"
        f"The free plan includes <b>{FREE_WINNER_LIMIT}</b> lifetime winner calculations.\n"
        f"To continue, contact <b>{esc(admin_contact(admin_username))}</b> to activate Premium."
    )


def database_error_message() -> str:
    return (
        "❌ <b>Database is not configured.</b>\n"
        "Add `DATABASE_URL` or `POSTGRES_URL` to your deployment environment."
    )


def build_winner_message(reference: str, lots: list[LotCalculation], consultation_object: str | None = None) -> str:
    if not lots:
        return "❌ No bidder data was found for this consultation."

    lines = [f"Consultation: <b>{esc(reference)}</b>"]
    if consultation_object:
        lines.append(f"Object: <b>{esc(consultation_object)}</b>")
    lines.append("")

    if len(lots) > 1:
        lines.append(f"This consultation contains <b>{len(lots)}</b> lots.")
        lines.append("")

    for index, lot in enumerate(lots, start=1):
        lot_name = lot.lot_id or str(index)
        lines.append(f"<b>Lot {esc(lot_name)}</b>")
        if lot.lot_label:
            lines.append(f"Label: {esc(lot.lot_label)}")
        lines.append(f"Bidders found: <b>{lot.bidder_count}</b>")
        lines.append(f"Priced offers used: <b>{lot.priced_offer_count}</b>")
        lines.append(f"Estimation (E): <b>{fmt_number(lot.estimated_price)}</b> {esc(lot.estimated_price_currency)}")
        lines.append(f"Average offer price: <b>{fmt_number(lot.average_offer_price)}</b>")
        lines.append(f"Reference price (P): <b>{fmt_number(lot.reference_price)}</b>")

        if lot.winner_names:
            if len(lot.winner_names) > 1:
                lines.append(f"Winner price tie: <b>{fmt_number(lot.winner_price)}</b>")
                lines.append("Winners: <b>" + esc(", ".join(lot.winner_names)) + "</b>")
            else:
                lines.append(f"Winner: <b>{esc(lot.winner_names[0])}</b>")
                lines.append(f"Winner price: <b>{fmt_number(lot.winner_price)}</b>")
        else:
            lines.append("Winner: <b>—</b>")

        lines.append("")
        lines.append("<b>Valid ranking:</b>")
        ordered_rankings = _ordered_valid_rankings(lot)
        for i, ranking in enumerate(ordered_rankings, start=1):
            icon = MEDALS[i - 1] if i <= len(MEDALS) else f"{i}."
            lines.append(
                f"{icon} {esc(ranking.name)} - {fmt_number(ranking.price)} ({fmt_pct(ranking.estimation_gap_percent)})"
            )
        lines.append("")

    return "\n".join(lines).strip()


def _ordered_valid_rankings(lot: LotCalculation):
    priced_rankings = [
        ranking for ranking in lot.rankings
        if ranking.price is not None and not ranking.note.startswith("Eliminated")
    ]
    eligible = [ranking for ranking in lot.rankings if ranking.is_eligible]
    return eligible or priced_rankings

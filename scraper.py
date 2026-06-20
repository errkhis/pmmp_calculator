import re
from dataclasses import dataclass, field
from typing import Optional

import httpx
from bs4 import BeautifulSoup


@dataclass
class Bidder:
    rank: int
    name: str
    admin_status: str
    financial_status: str
    price: Optional[float]
    technical_score: Optional[float] = None
    price_before_raw: str = ""
    price_after_raw: str = ""


@dataclass
class ConsultationData:
    reference: str
    object: str
    estimated_price: Optional[float]
    estimated_price_currency: str
    procedure: str
    category: str
    bidders: list[Bidder] = field(default_factory=list)
    technical_weight: Optional[float] = None
    financial_weight: Optional[float] = None
    lot_id: Optional[str] = None
    lot_label: Optional[str] = None
    lots: list["ConsultationData"] = field(default_factory=list)


@dataclass
class _ParsedBidderRow:
    rank: int
    name: str
    admin_status: str
    financial_status: str
    price_before_raw: str
    price_after_raw: str
    price_before: Optional[float]
    price_after: Optional[float]
    generic_price: Optional[float]
    technical_score: Optional[float]


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,ar;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def scrape_consultation(url: str) -> ConsultationData:
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        response = client.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        data = _build_consultation_data(url, soup)

        lot_options = _extract_lot_options(soup)
        lot_estimates = _fetch_lot_estimates(client, url)
        if len(lot_options) > 1:
            lots = []
            for lot_id, lot_label in lot_options:
                lot_soup = _fetch_lot_soup(client, url, soup, lot_id)
                lot_data = _build_consultation_data(url, lot_soup, lot_id, lot_label)
                if lot_id in lot_estimates:
                    lot_data.estimated_price, lot_data.estimated_price_currency = lot_estimates[lot_id]
                lots.append(lot_data)
            data.lots = lots
            if lots:
                data.bidders = [b for lot in lots for b in lot.bidders]
        elif "1" in lot_estimates:
            data.estimated_price, data.estimated_price_currency = lot_estimates["1"]

        return data


def consultation_meta_from_url(url: str) -> tuple[Optional[str], Optional[str]]:
    ref_match = re.search(r"refConsultation=([^&]+)", url)
    org_match = re.search(r"orgAcronyme=([^&]+)", url)
    if not ref_match:
        return None, None
    return ref_match.group(1), org_match.group(1) if org_match else ""


def build_consultation_url(reference: str, org: str) -> str:
    url = (
        "https://www.marchespublics.gov.ma/index.php"
        f"?page=entreprise.SuiviConsultation&refConsultation={reference}"
    )
    if org:
        url += f"&orgAcronyme={org}"
    return url


def _build_consultation_data(
    url: str,
    soup: BeautifulSoup,
    lot_id: Optional[str] = None,
    lot_label: Optional[str] = None,
) -> ConsultationData:
    estimated_price, currency = _extract_estimated_price(soup)
    technical_weight, financial_weight = _extract_weights(soup)
    return ConsultationData(
        reference=_meta_from_url(url),
        object=_extract_object(soup),
        estimated_price=estimated_price,
        estimated_price_currency=currency,
        procedure=_extract_labeled_field(soup, r"proc[eé]dure"),
        category=_extract_labeled_field(soup, r"cat[eé]gorie"),
        bidders=_extract_bidders(soup),
        technical_weight=technical_weight,
        financial_weight=financial_weight,
        lot_id=lot_id,
        lot_label=lot_label,
    )


def _extract_lot_options(soup: BeautifulSoup) -> list[tuple[str, str]]:
    select = soup.find("select", id=re.compile(r"lotsDropDownList", re.I))
    if not select:
        return []
    lots = []
    for opt in select.find_all("option"):
        value = (opt.get("value") or "").strip()
        label = opt.get_text(" ", strip=True)
        if value and label:
            lots.append((value, label))
    return lots


def _fetch_lot_soup(
    client: httpx.Client,
    url: str,
    base_soup: BeautifulSoup,
    lot_id: str,
) -> BeautifulSoup:
    form = base_soup.find("form")
    select = base_soup.find("select", id=re.compile(r"lotsDropDownList", re.I))
    if not form or not select or not select.get("name"):
        return base_soup

    data = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        input_type = (inp.get("type") or "").lower()
        if name and input_type not in ("image", "submit", "button"):
            data[name] = inp.get("value", "")

    select_name = select["name"]
    data[select_name] = lot_id
    data["PRADO_CALLBACK_TARGET"] = select_name
    data["PRADO_CALLBACK_PARAMETER"] = lot_id
    data["PRADO_POSTBACK_TARGET"] = ""
    data["PRADO_POSTBACK_PARAMETER"] = ""

    action = form.get("action") or url
    action_url = str(httpx.URL(url).join(action))
    response = client.post(
        action_url,
        data=data,
        headers={
            **HEADERS,
            "X-Requested-With": "XMLHttpRequest",
            "X-Prototype-Version": "1.7",
            "Accept": "text/javascript, text/html, application/xml, text/xml, */*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
    )
    response.raise_for_status()
    return BeautifulSoup(response.text, "lxml")


def _fetch_lot_estimates(client: httpx.Client, url: str) -> dict[str, tuple[float, str]]:
    reference = _meta_from_url(url)
    org = _meta_from_url_param(url, "orgAcronyme") or _meta_from_url_param(url, "orgAccronyme")
    if not reference or not org:
        return {}

    popup_url = (
        "https://www.marchespublics.gov.ma/index.php"
        f"?page=commun.PopUpDetailLots&orgAccronyme={org}"
        f"&refConsultation={reference}&lang=fr"
    )
    try:
        response = client.get(popup_url)
        response.raise_for_status()
    except httpx.HTTPError:
        return {}

    soup = BeautifulSoup(response.text, "lxml")
    estimates: dict[str, tuple[float, str]] = {}
    for tag in soup.find_all(id=re.compile(r"repeaterLots_ctl(\d+).*panelReferentielZoneText", re.I)):
        text = tag.get_text(" ", strip=True)
        if not re.search(r"estimation", text, re.I):
            continue
        value = _parse_first_price(text)
        if value is None:
            continue
        idx_match = re.search(r"repeaterLots_ctl(\d+)", tag.get("id", ""), re.I)
        if not idx_match:
            continue
        lot_id = str(int(idx_match.group(1)) + 1)
        currency = "MAD TTC" if re.search(r"TTC", text, re.I) else "MAD"
        estimates[lot_id] = (value, currency)
    return estimates


def _extract_object(soup: BeautifulSoup) -> str:
    for tag in soup.find_all("span", id=re.compile(r"labelReferentielZoneText", re.I)):
        container = tag.find_parent()
        if container:
            ctx = container.get_text(separator=" ", strip=True)
            if re.search(r"objet", ctx, re.IGNORECASE):
                return tag.get_text(strip=True)

    for tag in soup.find_all(string=re.compile(r"\bobjet\b", re.IGNORECASE)):
        parent = tag.find_parent()
        if parent:
            nxt = parent.find_next_sibling()
            if nxt:
                return nxt.get_text(strip=True)
    return "N/A"


def _extract_labeled_field(soup: BeautifulSoup, pattern: str) -> str:
    for tag in soup.find_all(string=re.compile(pattern, re.IGNORECASE)):
        parent = tag.find_parent()
        if parent:
            container = parent.find_parent()
            if container:
                value_span = container.find("span", id=re.compile(r"labelReferentielZoneText", re.I))
                if value_span:
                    return value_span.get_text(strip=True)
            nxt = parent.find_next_sibling()
            if nxt:
                value = nxt.get_text(strip=True)
                if value and value != ":":
                    return value
    return "N/A"


def _extract_estimated_price(soup: BeautifulSoup) -> tuple[Optional[float], str]:
    text = soup.get_text(" ", strip=True)
    estimate_patterns = [
        r"estimation\s*[:\-]?\s*([\d\s.\xa0 ]+,\d{2})",
        r"co[uû]t estimatif\s*[:\-]?\s*([\d\s.\xa0 ]+,\d{2})",
    ]
    for pattern in estimate_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = _parse_price_fr(match.group(1))
            if value is not None:
                currency = "MAD TTC" if re.search(r"TTC", match.group(0), re.I) else "MAD"
                return value, currency
    return None, "MAD"


def _extract_weights(soup: BeautifulSoup) -> tuple[Optional[float], Optional[float]]:
    text = soup.get_text(" ", strip=True)
    technical_match = re.search(r"technique\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*%", text, re.I)
    financial_match = re.search(r"financi[eè]re\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*%", text, re.I)
    technical = _parse_percent(technical_match.group(1)) if technical_match else None
    financial = _parse_percent(financial_match.group(1)) if financial_match else None
    return technical, financial


def _extract_bidders(soup: BeautifulSoup) -> list[Bidder]:
    bidders: list[Bidder] = []
    tables = soup.find_all("table")
    for table in tables:
        headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        if not headers:
            continue
        if not any("concurrent" in h or "soumissionnaire" in h or "concurrents" in h for h in headers):
            continue

        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue
            parsed = _parse_bidder_row(cells)
            if not parsed or not parsed.name:
                continue
            price = parsed.price_after or parsed.price_before or parsed.generic_price
            bidders.append(
                Bidder(
                    rank=parsed.rank,
                    name=parsed.name,
                    admin_status=parsed.admin_status,
                    financial_status=parsed.financial_status,
                    price=price,
                    technical_score=parsed.technical_score,
                    price_before_raw=parsed.price_before_raw,
                    price_after_raw=parsed.price_after_raw,
                )
            )
        if bidders:
            break
    return bidders


def _parse_bidder_row(cells) -> Optional[_ParsedBidderRow]:
    texts = [cell.get_text(" ", strip=True) for cell in cells]
    if len(texts) < 2:
        return None

    rank = _parse_rank(texts[0]) or 0
    name = texts[1]
    admin_status = texts[2] if len(texts) > 2 else ""
    financial_status = texts[3] if len(texts) > 3 else ""

    numbers = [_parse_price_fr(text) for text in texts]
    priced_values = [value for value in numbers if value is not None]
    generic_price = priced_values[-1] if priced_values else None

    technical_score = None
    for text in texts:
        if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
            value = float(text.replace(",", "."))
            if 0 <= value <= 100:
                technical_score = value

    return _ParsedBidderRow(
        rank=rank,
        name=name,
        admin_status=admin_status,
        financial_status=financial_status,
        price_before_raw=texts[-2] if len(texts) >= 2 else "",
        price_after_raw=texts[-1] if len(texts) >= 1 else "",
        price_before=numbers[-2] if len(numbers) >= 2 else None,
        price_after=numbers[-1] if len(numbers) >= 1 else None,
        generic_price=generic_price,
        technical_score=technical_score,
    )


def _parse_rank(text: str) -> Optional[int]:
    match = re.search(r"\d+", text or "")
    return int(match.group(0)) if match else None


def _parse_first_price(text: str) -> Optional[float]:
    for match in re.findall(r"\d[\d\s.\xa0 ]*,\d{2}", text):
        value = _parse_price_fr(match)
        if value is not None:
            return value
    return _parse_price_fr(text)


def _parse_price_fr(text: str) -> Optional[float]:
    if not text:
        return None
    value = text.strip().replace("\xa0", " ").replace(" ", " ")
    value = re.sub(r"(MAD|DH|TTC|HT|Dhs?)\s*", "", value, flags=re.IGNORECASE).strip()
    if not value or value in {"-", "—", "N/A"}:
        return None
    value = value.replace(" ", "")
    if "," in value and "." in value:
        value = value.replace(".", "").replace(",", ".")
    elif "," in value:
        value = value.replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return None


def _parse_percent(text: str) -> Optional[float]:
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _meta_from_url(url: str) -> str:
    match = re.search(r"refConsultation=(\w+)", url)
    return match.group(1) if match else "Unknown"


def _meta_from_url_param(url: str, name: str) -> Optional[str]:
    match = re.search(rf"[?&]{re.escape(name)}=([^&]+)", url)
    return match.group(1) if match else None

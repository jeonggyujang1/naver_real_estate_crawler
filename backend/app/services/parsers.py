from datetime import date, datetime


def price_to_manwon(value: str | None) -> int | None:
    if not value:
        return None

    cleaned = value.strip().replace(",", "")
    if not cleaned:
        return None

    if "억" in cleaned:
        front, *tail = cleaned.split("억")
        eok = int(front) if front.isdigit() else 0
        rest = tail[0].strip() if tail else ""
        manwon = int(rest) if rest.isdigit() else 0
        return (eok * 10000) + manwon

    return int(cleaned) if cleaned.isdigit() else None


def parse_confirmed_date(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%y.%m.%d.", "%Y.%m.%d.", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None

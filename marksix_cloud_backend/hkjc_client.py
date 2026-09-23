"""HKJC official public query, verified in tests/marksix_hkjc_test.py.

The full fragment/query and headers below are copied from the successful probe.
Do not simplify the query: HKJC returned WHITELIST_ERROR for altered versions.
No legacy module is imported and there are no network calls at import time.
"""

import re
from datetime import date, datetime

import requests

from .models import validate_draw

PAGE_URL = "https://bet.hkjc.com/ch/marksix/results"
ENDPOINT = "https://info.cld.hkjc.com/graphql/base/"
TIMEOUT = (10, 30)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": PAGE_URL,
    "Origin": "https://bet.hkjc.com",
}

QUERY = """fragment lotteryDrawsFragment on LotteryDraw {
  id
  year
  no
  openDate
  closeDate
  drawDate
  status
  snowballCode
  snowballName_en
  snowballName_ch
  lotteryPool {
    sell
    status
    totalInvestment
    jackpot
    unitBet
    estimatedPrize
    derivedFirstPrizeDiv
    lotteryPrizes {
      type
      winningUnit
      dividend
    }
  }
  drawResult {
    drawnNo
    xDrawnNo
  }
}

query marksixResult($lastNDraw: Int, $startDate: String, $endDate: String, $drawType: LotteryDrawType) {
  lotteryDraws(lastNDraw: $lastNDraw, startDate: $startDate, endDate: $endDate, drawType: $drawType) {
    ...lotteryDrawsFragment
  }
}"""


def safe_message(value: object) -> str:
    """Do not expose credential-shaped strings in unexpected upstream errors."""
    text = re.sub(r"(?i)https?://[^\s/@]+:[^\s/@]+@", "https://[REDACTED]@", str(value))
    text = re.sub(r"(?i)\bBearer\s+[^\s\"'<>]+", "Bearer [REDACTED]", text)
    text = re.sub(
        r"(?i)((?:[\w-]*token|authorization|cookie|password|secret|api[_-]?key)"
        r"[\"']?\s*[:=]\s*[\"']?)[^\s,;\"'<>]+",
        r"\1[REDACTED]", text,
    )
    return re.sub(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+\b", "[REDACTED JWT]", text)


class HkjcError(RuntimeError):
    def __init__(self, kind: str, diagnostics: dict):
        self.kind = kind
        self.diagnostics = {"kind": kind, "endpoint": ENDPOINT, **diagnostics}
        super().__init__(f"HKJC {kind}; inspect diagnostics")


def _integer(value: object, name: str) -> int:
    if type(value) is int:
        result = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        result = int(value)
    else:
        raise ValueError(f"{name}: expected integer or decimal digits")
    if result <= 0:
        raise ValueError(f"{name}: must be positive")
    return result


def normalize_draw(row: object) -> dict:
    if not isinstance(row, dict) or row.get("status") != "Result":
        raise ValueError("expected a completed HKJC Result object")
    year = _integer(row.get("year"), "year")
    number = _integer(row.get("no"), "no")
    if not 1000 <= year <= 9999 or not 1 <= number <= 999:
        raise ValueError("unsupported draw year or draw sequence")
    raw_date = row.get("drawDate")
    # XML-style date, NOT an ISO timestamp: retain HK's calendar date.
    match = re.fullmatch(
        r"([0-9]{4}-[0-9]{2}-[0-9]{2})(?:Z|[+-](?:(?:0[0-9]|1[0-3]):[0-5][0-9]|14:00))?",
        raw_date if isinstance(raw_date, str) else "",
    )
    if not match or int(match.group(1)[:4]) != year:
        raise ValueError("drawDate: invalid date format or year mismatch")
    result = row.get("drawResult")
    if not isinstance(result, dict):
        raise ValueError("drawResult: expected object")
    return validate_draw({
        "draw": f"{year % 100:02d}/{number:03d}",
        "date": match.group(1),
        "numbers": result.get("drawnNo"),
        "special_number": result.get("xDrawnNo"),
    })


def fetch_recent_draws(last_n: int = 20) -> list[dict]:
    if type(last_n) is not int or not 1 <= last_n <= 200:
        raise ValueError("last_n must be an integer in 1..200")
    variables = {"lastNDraw": last_n, "startDate": None, "endDate": None, "drawType": "All"}
    return _fetch_draws(variables, allow_empty=False)


def parse_date(value: str | date) -> date:
    """Accept a calendar date or strict ISO date; never truncate timestamps."""
    if isinstance(value, datetime):
        raise ValueError("expected calendar date, not timestamp")
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("date must be YYYY-MM-DD")
    return date.fromisoformat(value)


def fetch_draws_by_date_range(start_date: str | date, end_date: str | date) -> list[dict]:
    start, end = parse_date(start_date), parse_date(end_date)
    if start > end:
        raise ValueError("start_date must not be after end_date")
    variables = {"lastNDraw": None, "startDate": start.isoformat().replace("-", ""),
                 "endDate": end.isoformat().replace("-", ""), "drawType": "All"}
    draws = _fetch_draws(variables, allow_empty=True)
    if any(not start.isoformat() <= draw["date"] <= end.isoformat() for draw in draws):
        raise HkjcError("validation", {"message": "draw date outside requested interval"})
    return draws


def _fetch_draws(variables: dict, *, allow_empty: bool) -> list[dict]:
    try:
        with requests.Session() as session:
            # Prevent ambient .netrc credentials and proxy authentication from
            # injecting Authorization. This public request uses no saved state.
            session.trust_env = False
            with session.post(
                ENDPOINT, headers=HEADERS, timeout=TIMEOUT, verify=True,
                allow_redirects=False,
                json={"operationName": "marksixResult", "query": QUERY, "variables": variables},
            ) as response:
                diagnostics = {
                    "http_status": response.status_code,
                    "content_type": response.headers.get("Content-Type"),
                    "retry_after": safe_message(response.headers.get("Retry-After", "")),
                }
                try:
                    response.raise_for_status()
                except requests.HTTPError:
                    diagnostics["http_error"] = True
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise HkjcError("json", {**diagnostics, "message": safe_message(exc)}) from None
                if not isinstance(payload, dict):
                    raise HkjcError("schema", {**diagnostics, "message": "expected GraphQL object"})
                if payload.get("errors"):
                    raw_errors = payload["errors"]
                    errors = []
                    for error in raw_errors if isinstance(raw_errors, list) else [raw_errors]:
                        extensions = error.get("extensions") if isinstance(error, dict) else None
                        errors.append({
                            "message": safe_message(error.get("message", "Missing message")
                                                    if isinstance(error, dict) else error),
                            "code": safe_message(extensions.get("code", "")
                                                 if isinstance(extensions, dict) else ""),
                        })
                    diagnostics["errors"] = errors
                    if any("WHITELIST_ERROR" in item["message"] + item["code"] for item in errors):
                        diagnostics["hint"] = (
                            "Compare marksixResult / lotteryDrawsFragment with the current official "
                            "results page JS; preserve fragment-first order and addTypename:false. "
                            "Do not switch to a third-party source."
                        )
                    raise HkjcError("graphql", diagnostics)
                if not 200 <= response.status_code < 300:
                    raise HkjcError("http", diagnostics)
                data = payload.get("data")
                rows = data.get("lotteryDraws") if isinstance(data, dict) else None
                if not isinstance(rows, list) or (not rows and not allow_empty):
                    raise HkjcError("schema", {**diagnostics, "message": "invalid lotteryDraws list"})
    except requests.exceptions.SSLError as exc:
        raise HkjcError("ssl", {"message": safe_message(exc)}) from None
    except requests.exceptions.Timeout as exc:
        raise HkjcError("timeout", {"timeout": TIMEOUT, "message": safe_message(exc)}) from None
    except requests.RequestException as exc:
        raise HkjcError("network", {"type": type(exc).__name__, "message": safe_message(exc)}) from None

    normalized = []
    seen = set()
    for index, row in enumerate(rows):
        try:
            draw = normalize_draw(row)
        except (ValueError, TypeError) as exc:
            # Do not include raw response objects in error logs.
            raise HkjcError("validation", {**diagnostics, "index": index,
                                          "message": safe_message(exc)}) from None
        if draw["draw"] in seen:
            raise HkjcError("validation", {**diagnostics, "message": "duplicate HKJC draw",
                                          "draw": draw["draw"]})
        seen.add(draw["draw"])
        normalized.append(draw)
    return sorted(normalized, key=lambda draw: (draw["date"], draw["draw"]), reverse=True)

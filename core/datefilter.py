"""Date / time-range filtering for Douyin search.

Two complementary mechanisms:

1. Server-side ``publish_time`` — a predefined coarse range that Douyin's Web
   search API understands via the ``filter_selected`` parameter:

       0   不限 (no limit, default)
       1   一天内 (within 1 day)
       7   一周内 (within 1 week)
       182 半年内 (within half a year)

2. Client-side custom range — an arbitrary ``start_date`` / ``end_date`` window
   (the API has no native support for this). Each result carries a
   ``create_time`` epoch; we keep only the posts whose timestamp falls inside
   ``[start 00:00:00, end 23:59:59]`` (both bounds inclusive) and drop the rest.

Both entry points (``main.py`` CLI and ``scrape_all.py`` pipeline, HTTP API
Phase 1 and browser API Phase 2) share this module so the normalization, date
parsing, boundary semantics and ``filter_selected`` construction live in one
place.
"""
import json
import time
from datetime import datetime
from typing import Optional


# Predefined publish_time values accepted by Douyin's search API → human label.
PUBLISH_TIME_CHOICES = {
    0: "不限",
    1: "一天内",
    7: "一周内",
    182: "半年内",
}

DATE_FORMAT = "%Y-%m-%d"


def normalize_publish_time(value) -> int:
    """Coerce ``value`` to one of the allowed publish_time ints.

    Accepts ``None`` / empty (→ 0), ints, or numeric strings. Raises
    ``ValueError`` for anything that is not a recognized predefined range.
    """
    if value is None or value == "":
        return 0
    try:
        pt = int(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"无效的 publish_time: {value!r}（可选值: "
            f"{', '.join(str(k) for k in PUBLISH_TIME_CHOICES)}）"
        )
    if pt not in PUBLISH_TIME_CHOICES:
        raise ValueError(
            f"无效的 publish_time: {pt}（可选值: "
            f"{', '.join(str(k) for k in PUBLISH_TIME_CHOICES)}）"
        )
    return pt


def parse_date(value: str) -> datetime:
    """Parse a ``YYYY-MM-DD`` string into a ``datetime`` at local midnight.

    Raises ``ValueError`` (with a friendly message) on a malformed date.
    """
    if not value:
        raise ValueError("日期不能为空")
    try:
        return datetime.strptime(value.strip(), DATE_FORMAT)
    except ValueError:
        raise ValueError(f"无效的日期格式: {value!r}（应为 YYYY-MM-DD，例如 2025-01-01）")


def _day_start_epoch(d: datetime) -> int:
    return int(time.mktime(d.replace(hour=0, minute=0, second=0).timetuple()))


def _day_end_epoch(d: datetime) -> int:
    return int(time.mktime(d.replace(hour=23, minute=59, second=59).timetuple()))


class DateFilter:
    """Combined server-side + client-side date filter.

    Construct via :meth:`from_inputs`. ``publish_time`` drives the server-side
    coarse filter (emitted through :attr:`filter_selected`); ``start_date`` /
    ``end_date`` drive client-side trimming (:meth:`matches`). The two are
    independent and may be combined — the server narrows coarsely, the client
    enforces the exact window.
    """

    def __init__(self, publish_time: int = 0,
                 start_ts: Optional[int] = None,
                 end_ts: Optional[int] = None):
        self.publish_time = publish_time
        self.start_ts = start_ts
        self.end_ts = end_ts

    @classmethod
    def from_inputs(cls, publish_time=None, start_date=None, end_date=None) -> "DateFilter":
        pt = normalize_publish_time(publish_time)

        start_ts = end_ts = None
        start_dt = parse_date(start_date) if start_date else None
        end_dt = parse_date(end_date) if end_date else None
        if start_dt and end_dt and start_dt > end_dt:
            raise ValueError(
                f"start-date ({start_date}) 不能晚于 end-date ({end_date})"
            )
        if start_dt:
            start_ts = _day_start_epoch(start_dt)   # inclusive: 00:00:00
        if end_dt:
            end_ts = _day_end_epoch(end_dt)         # inclusive: 23:59:59

        return cls(publish_time=pt, start_ts=start_ts, end_ts=end_ts)

    @property
    def has_custom_range(self) -> bool:
        return self.start_ts is not None or self.end_ts is not None

    @property
    def is_active(self) -> bool:
        return self.publish_time != 0 or self.has_custom_range

    @property
    def filter_selected(self) -> Optional[str]:
        """JSON string for the API ``filter_selected`` param, or ``None``.

        Only emitted when a non-default ``publish_time`` is set; the custom
        range is enforced client-side, not by the server.
        """
        if self.publish_time == 0:
            return None
        return json.dumps({"publish_time": str(self.publish_time)})

    def apply_search_params(self, params: dict) -> dict:
        """Mutate a search ``params`` dict in place to add the server filter."""
        fs = self.filter_selected
        if fs is not None:
            params["filter_selected"] = fs
            params["is_filter_search"] = "1"
        return params

    def matches(self, create_ts) -> bool:
        """True if an epoch ``create_ts`` falls inside the custom range.

        No custom range → always True. Posts with a missing/zero timestamp are
        dropped when a custom range is active (can't prove they belong).
        """
        if not self.has_custom_range:
            return True
        try:
            ts = int(create_ts)
        except (TypeError, ValueError):
            return False
        if ts <= 0:
            return False
        if self.start_ts is not None and ts < self.start_ts:
            return False
        if self.end_ts is not None and ts > self.end_ts:
            return False
        return True

    def describe(self) -> str:
        parts = []
        if self.publish_time != 0:
            parts.append(f"publish_time={self.publish_time}({PUBLISH_TIME_CHOICES[self.publish_time]})")
        if self.start_ts is not None:
            parts.append("start=" + time.strftime("%Y-%m-%d", time.localtime(self.start_ts)))
        if self.end_ts is not None:
            parts.append("end=" + time.strftime("%Y-%m-%d", time.localtime(self.end_ts)))
        return ", ".join(parts) if parts else "无日期过滤"

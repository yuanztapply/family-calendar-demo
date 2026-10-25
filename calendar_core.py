"""Small, dependency-free calendar logic for the public demonstration.

All intervals use half-open bounds: start is included, end is excluded.
No calendar data is fetched from a network or saved to disk.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo

UTC = timezone.utc
MAX_ICS_BYTES = 1_000_000


@dataclass(frozen=True)
class Event:
    start: datetime
    end: datetime
    title: str


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime

    @property
    def key(self) -> str:
        return self.start.isoformat()


def local_datetime(value: datetime, zone: ZoneInfo) -> datetime:
    """Attach an IANA zone; reject ambiguous/nonexistent wall-clock inputs."""
    valid = {}
    for fold in (0, 1):
        candidate = value.replace(tzinfo=zone, fold=fold)
        back = candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
        if back == value:
            valid[candidate.utcoffset()] = candidate
    if len(valid) != 1:
        raise ValueError("当地时间不存在或因夏令时重复；请使用带 UTC 时间的事件")
    return next(iter(valid.values()))


def hour_slots(day: date, zone_name: str) -> list[Slot]:
    """Return actual hourly intervals in the local day, including DST days."""
    zone = ZoneInfo(zone_name)
    start = local_datetime(datetime.combine(day, time.min), zone).astimezone(UTC)
    end = local_datetime(datetime.combine(day + timedelta(days=1), time.min), zone)
    end = end.astimezone(UTC)
    result = []
    while start < end:
        finish = min(start + timedelta(hours=1), end)
        result.append(Slot(start, finish))
        start = finish
    return result


def slot_label(slot: Slot, zone_name: str) -> str:
    zone = ZoneInfo(zone_name)
    start = slot.start.astimezone(zone)
    end = slot.end.astimezone(zone)
    return f"{start:%m-%d %H:%M %z} → {end:%m-%d %H:%M %z}"


def overlapping_events(events: list[Event], slot: Slot) -> list[Event]:
    return [event for event in events if event.start < slot.end and event.end > slot.start]


def is_busy(events: list[Event], slot: Slot, manual_busy=(), manual_free=()) -> bool:
    if slot.key in manual_busy:
        return True
    if slot.key in manual_free:
        return False
    return bool(overlapping_events(events, slot))


def _decode_text(value: str) -> str:
    return re.sub(r"\\([nN,;\\])", lambda m: "\n" if m[1] in "nN" else m[1], value)


def _parse_date(value: str, params: dict[str, str], fallback_zone: str):
    is_date = params.get("VALUE") == "DATE" or bool(re.fullmatch(r"\d{8}", value))
    if is_date:
        parsed = datetime.strptime(value, "%Y%m%d")
    else:
        fmt = "%Y%m%dT%H%M%S" if len(value.rstrip("Z")) == 15 else "%Y%m%dT%H%M"
        parsed = datetime.strptime(value.rstrip("Z"), fmt)
    if value.endswith("Z"):
        return parsed.replace(tzinfo=UTC), is_date
    zone = ZoneInfo(params.get("TZID", fallback_zone))
    return local_datetime(parsed, zone), is_date


def _duration_end(start: datetime, value: str, all_day: bool) -> datetime:
    match = re.fullmatch(r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value)
    if not match or not any(match.groups()):
        raise ValueError("不支持的 DURATION")
    weeks, days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    if all_day and (hours or minutes or seconds):
        raise ValueError("全天事件的 DURATION 需使用天或周")
    calendar_days = weeks * 7 + days
    end = start
    if calendar_days:
        wall_end = start.replace(tzinfo=None) + timedelta(days=calendar_days)
        end = local_datetime(wall_end, start.tzinfo)
    return end.astimezone(UTC) + timedelta(hours=hours, minutes=minutes, seconds=seconds)


def parse_ics(data: bytes, fallback_zone: str) -> tuple[list[Event], list[str]]:
    """Read nonrecurring VEVENTs; report unsupported/invalid events explicitly."""
    if len(data) > MAX_ICS_BYTES:
        raise ValueError("ICS 文件超过 1 MB，请导出更小的日期范围")
    ZoneInfo(fallback_zone)
    text = data.decode("utf-8-sig")
    lines = re.sub(r"\r?\n[ \t]", "", text).splitlines()
    if "BEGIN:VCALENDAR" not in lines or "END:VCALENDAR" not in lines:
        raise ValueError("不是完整的 VCALENDAR 文件")
    blocks, current, inside = [], [], False
    for line in lines:
        if line == "BEGIN:VEVENT":
            if inside:
                raise ValueError("VEVENT 结构无效")
            current, inside = [], True
        elif line == "END:VEVENT":
            if not inside:
                raise ValueError("VEVENT 结构无效")
            blocks.append(current)
            inside = False
        elif inside:
            current.append(line)
    if inside:
        raise ValueError("VEVENT 缺少结束标记")
    events, warnings = [], []
    if "BEGIN:VFREEBUSY" in lines:
        warnings.append("VFREEBUSY 忙闲组件未解析，请改用单次 VEVENT")
    if "BEGIN:VTIMEZONE" in lines:
        warnings.append("内嵌 VTIMEZONE 定义未核验；时间仅按本机 IANA 规则解释，请确认时区")
    for number, block in enumerate(blocks, 1):
        props = {}
        try:
            nested_depth = 0
            for line in block:
                if ":" not in line:
                    continue
                head, value = line.split(":", 1)
                if head.upper() == "BEGIN":
                    nested_depth += 1
                    continue
                if head.upper() == "END":
                    nested_depth -= 1
                    continue
                if nested_depth:
                    continue
                segments = head.split(";")
                key = segments[0].upper()
                params = {}
                for segment in segments[1:]:
                    if "=" in segment:
                        name, param = segment.split("=", 1)
                        params[name.upper()] = param.strip('"')
                props[key] = (value, params)
            if any(key in props for key in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID")):
                raise ValueError("循环或例外事件未展开，已跳过；请导出展开后的单次事件")
            if props.get("STATUS", ("", {}))[0].upper() == "CANCELLED":
                continue
            if props.get("TRANSP", ("", {}))[0].upper() == "TRANSPARENT":
                continue
            start, all_day = _parse_date(*props["DTSTART"], fallback_zone)
            if "DTEND" in props:
                end, end_all_day = _parse_date(*props["DTEND"], fallback_zone)
                if all_day != end_all_day:
                    raise ValueError("开始与结束日期类型不一致")
            elif "DURATION" in props:
                end = _duration_end(start, props["DURATION"][0], all_day)
            elif all_day:
                end = local_datetime(start.replace(tzinfo=None) + timedelta(days=1), start.tzinfo)
            else:
                raise ValueError("缺少结束时间，已跳过")
            start, end = start.astimezone(UTC), end.astimezone(UTC)
            if end <= start:
                raise ValueError("结束时间不晚于开始时间")
            title = _decode_text(props.get("SUMMARY", ("未命名事件", {}))[0])[:300]
            events.append(Event(start, end, title))
        except (KeyError, ValueError, UnicodeError) as error:
            warnings.append(f"事件 {number}：{error}")
    return sorted(events, key=lambda event: event.start), warnings

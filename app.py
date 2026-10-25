"""Public, synthetic-data demonstration by Blake Yuan."""

from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from calendar_core import hour_slots, is_busy, overlapping_events, parse_ics, slot_label

st.set_page_config(page_title="Family Calendar Demo", page_icon="🕰️", layout="wide")
st.title("隔着时区，也能找到同一个空档")
st.caption("Family Calendar Demo · Blake Yuan · 公开演示版")
st.info("初始日期和示例日程全部虚构。导入内容仅用于当前会话；没有账号登录、云端同步或消息发送。")

ZONES = ["UTC", "Europe/Berlin", "America/New_York", "Asia/Tokyo", "Asia/Kolkata", "Australia/Sydney",
         "Europe/London", "Asia/Shanghai"]
with st.sidebar:
    st.header("日期与时区")
    selected_day = st.date_input("对照日期", date(2030, 4, 8))
    reference_zone = st.selectbox("按哪个时区的一天对照", ZONES, index=0)
    st.caption("初始日期为虚构示例日期；真实使用时自行选择日期。")
    load_demo = st.checkbox("载入虚构示例（仅成员 A）", value=True)
    st.download_button("下载虚构示例 ICS", (Path(__file__).parent / "demo-fictional.ics").read_bytes(),
                       file_name="demo-fictional.ics", mime="text/calendar")

try:
    slots = hour_slots(selected_day, reference_zone)
except ValueError as error:
    st.error(str(error))
    st.stop()

now = datetime.now(timezone.utc)
members = []
columns = st.columns(3)
for index, column in enumerate(columns):
    with column:
        name = st.text_input("显示名称", f"成员 {chr(65 + index)}", key=f"name-{index}", max_chars=40)
        zone = st.selectbox("当地时区", ZONES, index=index, key=f"zone-{index}")
        st.caption(f"当地现在：{now.astimezone(ZoneInfo(zone)):%m-%d %H:%M %z}")
        upload = st.file_uploader("导入自己的 ICS", type=["ics"], key=f"upload-{index}")
        events, warnings, import_failed = [], [], False
        if upload is not None:
            raw = upload.getvalue()
        elif index == 0 and load_demo:
            raw = (Path(__file__).parent / "demo-fictional.ics").read_bytes()
        else:
            raw = None
        if raw is not None:
            try:
                events, warnings = parse_ics(raw, zone)
                st.caption(f"已读入 {len(events)} 个忙碌事件")
            except (ValueError, UnicodeError) as error:
                st.error(f"导入未完成：{error}")
                import_failed = True
        for warning in warnings:
            st.warning(warning)
        with st.expander("手动调整忙闲与备注"):
            st.caption("下列每项是完整对照时段，显示为该成员当地时间；手动忙碌优先于手动空闲。")
            labels = {slot.key: slot_label(slot, zone) for slot in slots}
            prefix = f"{index}-{selected_day}-{reference_zone}-{zone}"
            manual_busy = st.multiselect("标记忙碌", list(labels), format_func=labels.get, key=f"busy-{prefix}")
            manual_free = st.multiselect("标记空闲（覆盖日历）", list(labels), format_func=labels.get, key=f"free-{prefix}")
            note = st.text_area("本次备注", key=f"note-{prefix}", max_chars=200)
        members.append({"name": name or f"成员 {index + 1}", "zone": zone,
                        "events": events, "busy": manual_busy, "free": manual_free, "note": note,
                        "incomplete": bool(warnings) or import_failed})

rows, shared = [], []
for slot in slots:
    row = {"对照时段": slot_label(slot, reference_zone)}
    free_count = 0
    for index, member in enumerate(members):
        busy = is_busy(member["events"], slot, member["busy"], member["free"])
        hits = overlapping_events(member["events"], slot)
        manual = "手动忙碌" if slot.key in member["busy"] else (
            "手动空闲" if slot.key in member["free"] else ("日历忙碌" if busy else "未记录忙碌"))
        if not busy and member["incomplete"] and slot.key not in member["free"]:
            manual = "日历未完整读取，待确认"
        if not busy:
            free_count += 1
        if slot.key in member["free"] and hits and slot.key not in member["busy"]:
            manual += "（有日历事件）"
        label = f"{index + 1}. {member['name']}"
        row[label] = f"{slot_label(slot, member['zone'])} · {manual}"
        row[f"{label} · 事件"] = "；".join(event.title for event in hits)
    row["可约人数（按已填信息）"] = free_count
    if free_count == len(members):
        shared.append(slot)
    rows.append(row)

st.subheader("共同空档")
if any(member["incomplete"] for member in members):
    st.warning("部分日历未完整读取。下列空档可能漏掉忙碌事件，不能据此确认可约。")
st.metric("共同未记录忙碌的时段", f"{len(shared)} / {len(slots)} 段")
st.caption("按输入信息计算，不等于已经确认空闲。夏令时切换日可能有 23 或 25 小时；偏移量用于区分重复时刻。")
if shared:
    st.write("、".join(slot_label(slot, reference_zone) for slot in shared))
else:
    st.write("这一天没有共同空档，可以调整日期或手动确认忙闲。")
st.subheader("逐小时对照")
st.dataframe(rows, hide_index=True)
for member in members:
    if member["note"]:
        st.write(f"{member['name']} 的本次备注：")
        st.text(member["note"])
with st.expander("导入范围与当前限制"):
    st.write("支持非循环 VEVENT、UTC 或 IANA 时区、浮动时间、全天事件和 DURATION。全天事件的结束日期不包含在内。")
    st.write("循环/例外规则会明确跳过；请先导出展开后的单次事件。缺少结束时间、未知时区或无法消歧的夏令时事件也会提示。")
    st.write("VFREEBUSY 组件不解析；内嵌 VTIMEZONE 定义未核验，仅按运行环境的 IANA 规则解释，并提示未完整读取。")
    st.write("整段内只要与事件有任何重叠，就视为这一段忙碌。浮动时间按该成员所选时区解释。")
    st.write("上传文件只在运行该应用的进程内解析，不写入文件或发送至第三方。部署到他人服务器后，文件会传到该服务器处理。")
    st.write("本演示不保留原项目的固定家庭排班、补觉规则、持久留言板或文学摘录。页面显示的当前时间随页面交互刷新。")

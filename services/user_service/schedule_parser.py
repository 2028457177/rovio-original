"""课表 Excel 解析（上传时预解析用）。

解析规则与 AIRAGAgent/agent/tools/agent_tools.py get_schedule 的兜底逻辑保持一致：
- 单元格按 <br>/换行拆分多门课，行内按 ◇ 分割为 课程信息◇周次节次◇地点
- 周次如 "1-4,6-8,10(周/单周/双周)"，节次如 "[01-02节]"

输出 JSON 可直接存入 user_schedules.parsed_courses，查询方按
parsed[day] 中 weeks 过滤即可，无需再读 Excel。
"""
from __future__ import annotations
import re
from typing import Any, Dict, List

import pandas as pd

_WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期天"]


def _parse_weeks(week_str: str, week_type: str) -> List[int]:
    """解析周次字符串如 "1-4,6-8,10"，按 单周/双周 过滤，返回排序后的周次列表。"""
    weeks_set = set()
    for part in week_str.split(','):
        if '-' in part:
            start, end = map(int, part.split('-'))
            weeks_set.update(range(start, end + 1))
        else:
            weeks_set.add(int(part))

    if week_type == '单周':
        weeks_set = {w for w in weeks_set if w % 2 == 1}
    elif week_type == '双周':
        weeks_set = {w for w in weeks_set if w % 2 == 0}

    return sorted(weeks_set)


def _parse_course_cell(cell_text: str) -> List[Dict[str, Any]]:
    """解析一个单元格内的所有课程（一格可能有多门课，按行拆分）。"""
    courses = []
    for line in cell_text.replace('<br>', '\n').split('\n'):
        line = line.strip()
        if not line:
            continue

        parts = line.split('◇')
        if len(parts) < 3:
            continue  # 格式异常，跳过

        course_info = parts[0].strip()
        week_section = parts[1].strip()
        location = parts[2].strip()

        name = course_info.split('[')[0].strip()
        attributes = re.findall(r'\[(.*?)\]', course_info)

        week_match = re.search(r'([\d,\-]+)\((周|单周|双周)\)', week_section)
        weeks = _parse_weeks(week_match.group(1), week_match.group(2)) if week_match else []

        section_match = re.search(r'\[(\d{2})-(\d{2})节\]', week_section)
        if section_match:
            start_section = int(section_match.group(1))
            end_section = int(section_match.group(2))
        else:
            start_section = end_section = None

        courses.append({
            'name': name,
            'attributes': attributes,
            'weeks': weeks,
            'start_section': start_section,
            'end_section': end_section,
            'location': location,
            'raw': line,
        })

    return courses


def parse_schedule_df(df: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
    """把已校验列名的课表 DataFrame 解析为 {星期: [课程条目]} 结构。

    只保留有课的星期键，条目按时间段顺序排列；条目均可 JSON 序列化。
    """
    df.columns = df.columns.str.strip()
    parsed: Dict[str, List[Dict[str, Any]]] = {}
    for day in _WEEKDAY_CN:
        if day not in df.columns:
            continue
        entries: List[Dict[str, Any]] = []
        for time_slot, cell in df[day].items():
            if pd.isna(cell):
                continue
            for course in _parse_course_cell(str(cell)):
                entry = dict(course)
                entry['time_slot'] = str(time_slot)
                entries.append(entry)
        if entries:
            parsed[day] = entries
    return parsed

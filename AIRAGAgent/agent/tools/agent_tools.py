import os
import re
import random
from contextvars import ContextVar
from datetime import datetime, timedelta

import docx
import requests
from typing import List, Dict, Any, Union
import pandas as pd
from datetime import date, datetime
from langchain_core.tools import tool
from AIRAGAgent.utils.config_handler import rag_conf
from AIRAGAgent.utils.logger_handler import logger
from AIRAGAgent.rag.rag_service import RagSummarizeService
from AIRAGAgent.utils.config_handler import agent_conf
from AIRAGAgent.utils.path_tool import get_abs_path
from AIRAGAgent.utils.paths import UPLOAD_DIR

# 存储当前请求的用户真实 IP，由 FastAPI 接口在调用工具前设置
user_ip_var: ContextVar[str | None] = ContextVar('user_ip', default=None)
# 存储当前请求的用户浏览器经纬度（高精度定位）
user_lat_var: ContextVar[float | None] = ContextVar('user_lat', default=None)
user_lon_var: ContextVar[float | None] = ContextVar('user_lon', default=None)
# 存储当前登录用户的真实 ID
user_id_var: ContextVar[int | None] = ContextVar('user_id', default=None)
# 联网搜索开关（前端可切换；关闭后 Planner 不再选择 search 子代理）
search_enabled_var: ContextVar[bool] = ContextVar('search_enabled', default=True)

_rag_instance = None

def _get_rag():
    """获取 RAG 摘要服务单例，首次调用时惰性创建。"""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = RagSummarizeService()
    return _rag_instance

user_ids = ["1001","1002","1003","1004","1005","1006","1007","1008","1009","1010",]

# month_arr = ["2025-01","2025-02","2025-03","2025-04","2025-05","2025-06","2025-07","2025-08","2025-09","2025-10","2025-11","2025-12"]


external_data = {}

@tool(description="从向量存储中检索参考资料")
def rag_summarize(query: str) -> str:
    """从向量库检索参考资料并生成总结（RAG 查询入口）。"""
    return _get_rag().rag_summarize(query)


@tool(description="传入城市名称，获取指定城市未来天气信息")
def get_weather(city_name: str) -> dict[str, Any]:
    """
    获取未来几天的天气预报（使用 wttr.in 免费服务）
    :param city_name: 纯城市名（如"杭州"），由 get_city_code 处理后的结果
    :return: 天气预报信息列表
    """
    try:
        url = f"https://wttr.in/{city_name}?format=j1&lang=zh"
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            return {'error': f'请求失败，HTTP 状态码：{response.status_code}'}

        data = response.json()
        weather_list = []

        for day_data in data.get('weather', [])[:5]:  # 最多5天
            date_str = day_data.get('date', '')
            hourly = day_data.get('hourly', [])

            if not hourly:
                continue

            # 收集所有温度
            temps = []
            for h in hourly:
                try:
                    temps.append(float(h.get('tempC', 0)))
                except (ValueError, TypeError):
                    pass

            # 取中午时段(约12:00)作为白天天气代表，晚间(约21:00)作为夜晚天气代表
            day_idx = min(4, len(hourly) - 1)   # ~12:00
            night_idx = min(7, len(hourly) - 1)  # ~21:00

            day_h = hourly[day_idx]
            night_h = hourly[night_idx]

            # wttr.in 中文描述在 lang_zh 字段中
            day_desc = (
                day_h.get('lang_zh', [{}])[0].get('value', '') if day_h.get('lang_zh')
                else day_h.get('weatherDesc', [{}])[0].get('value', '')
            )
            night_desc = (
                night_h.get('lang_zh', [{}])[0].get('value', '') if night_h.get('lang_zh')
                else night_h.get('weatherDesc', [{}])[0].get('value', '')
            )

            daily_forecast = {
                '日期': date_str,
                '白天天气': day_desc or '未知',
                '夜晚天气': night_desc or '未知',
                '白天温度': max(temps) if temps else 0.0,
                '夜晚温度': min(temps) if temps else 0.0,
                '白天风向': day_h.get('winddir16Point', ''),
                '夜晚风向': night_h.get('winddir16Point', ''),
                '白天风力': str(day_h.get('windspeedKmph', '')) + 'km/h',
                '夜晚风力': str(night_h.get('windspeedKmph', '')) + 'km/h'
            }
            weather_list.append(daily_forecast)

        return weather_list

    except Exception as e:
        return {'error': f'获取天气失败：{str(e)}'}


@tool(description="获取用户所在城市信息，以纯字符串形式返回")
def get_user_location() -> Any | None:
    """
        通过 IP 地址或浏览器经纬度获取当前位置的省市信息
        优先使用浏览器高精度定位（GPS），回退到 IP 定位
        返回格式：某某省某某市（字符串）
    """
    try:
        lat = user_lat_var.get()
        lon = user_lon_var.get()

        if lat is not None and lon is not None:
            # 使用 Nominatim 逆地理编码（免费无 Key，精度高）
            url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=zh"
            headers = {'User-Agent': 'Rovio/1.0'}
            response = requests.get(url, timeout=5, headers=headers)
            data = response.json()

            address = data.get('address', {})
            province = address.get('state', '') or address.get('province', '')
            city = address.get('city', '') or address.get('town', '') or address.get('county', '')

            if province or city:
                return f"{province}{city}"

        # 回退：通过高德 IP 定位（国内精度远优于 ip-api.com）
        user_ip = user_ip_var.get()
        gaode_key = rag_conf.get("gaode_api_key", "")

        if user_ip:
            url = f"https://restapi.amap.com/v3/ip?key={gaode_key}&ip={user_ip}"
        else:
            url = f"https://restapi.amap.com/v3/ip?key={gaode_key}"

        response = requests.get(url, timeout=5)
        data = response.json()

        if data.get('status') == '1':
            province = data.get('province', '')
            city = data.get('city', '')
            # 对直辖市（北京/上海/天津/重庆），city 可能为空，用 province 作为城市
            if isinstance(city, list):
                city = ''
            if isinstance(province, list):
                province = ''

            if not city and province:
                return province  # 直辖市，province 本身就是城市名（如"北京市"）
            if not province and not city:
                logger.warning(f"高德IP定位返回空省市: {data}")
                return "未知位置"
            return f"{province}{city}"
        else:
            logger.warning(f"高德IP定位失败: {data}")
            return "未知位置"

    except Exception:
        return "获取失败"


@tool(description="处理城市名称，提取纯城市名供天气查询使用")
def get_city_code(city_name: str) -> str:
    """
    从省市字符串中提取纯城市名（如"浙江省杭州市"→"杭州"），供get_weather使用

    Args:
        city_name: get_user_location返回的城市名称，格式如"浙江省杭州市"

    Returns:
        纯城市名字符串，如"杭州"
    """
    try:
        # 去掉"省"前缀，提取城市名
        if '省' in city_name:
            result = city_name.split('省')[1]
        else:
            result = city_name
        # 去掉末尾的"市"字（wttr.in 需要城市名不加"市"）
        if result.endswith('市'):
            result = result[:-1]
        return result
    except Exception as e:
        return city_name


@tool(description="获取用户的ID，以纯字符串形式返回")
def get_user_id() -> str:
    """获取当前登录用户的 ID，以字符串形式返回。"""
    uid = user_id_var.get()
    if uid is not None:
        return str(uid)
    # 兼容旧模式：无用户上下文时随机返回一个 ID
    return random.choice(user_ids)

@tool(description="wantday 作为用户想查询的日期与当前日期相差的天数，如明天是 1 后天是 2，大后天是 3，以此类推，如果是查看当天的日期则为 0")
def get_current_month(wantday:int)-> dict:
    """计算目标日期（当前日期加相差天数）对应的学期周数和星期几，返回日期、周数与星期信息。"""
    now = datetime.now()
    target_date = now + timedelta(days=wantday)
    want_date_str = target_date.strftime("%Y-%m-%d")

    # 从 DB 读取当前用户的开学日期（按用户隔离）
    _, start_date_str, _ = _load_user_schedule_path()
    if not start_date_str:
        return {
            "date": want_date_str,
            "error": "未上传课表",
            "hint": "请前往「设置 → 课表设置」上传你的课表 Excel 并设置开学日期",
            "week": None,
            "day": None,
        }

    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    diff_days = (target_date - start_date).days
    week_number = (diff_days // 7) + 1

    # 获取星期几的中文名
    weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期天"]
    weekday = weekday_cn[target_date.weekday()]  # Monday=0, Sunday=6

    return {
        "date": want_date_str,
        "week": week_number,
        "day": weekday
    }


def _load_user_schedule_path() -> tuple[str | None, str | None, dict | None]:
    """从当前上下文读取用户的课表绝对路径 + 开学日期 + 预解析课表。

    返回 (abs_file_path, start_date_str, parsed)；未上传或读取出错时返回 (None, None, None)。
    parsed 为上传时预解析好的 {星期: [课程条目]} 结构（无则 None，查询时回退读 Excel）。
    内部 lazy import 避免与 database 模块产生循环依赖。
    """
    uid = user_id_var.get()
    if uid is None:
        return None, None, None
    try:
        from AIRAGAgent.database.models import get_schedule_settings
        settings = get_schedule_settings(int(uid))
        if not settings["uploaded"] or not settings["file_path"]:
            return None, None, None
        abs_path = str(UPLOAD_DIR / settings["file_path"])
        return abs_path, settings["start_date"], settings.get("parsed")
    except Exception as e:
        logger.warning(f"[_load_user_schedule_path] 读取用户 {uid} 课表设置失败：{e}")
        return None, None, None

def generate_external_data():
    """
    {
        “user_id":{
            "month":{"特征":XXX，"效率":XXX，...}
            "month":{"特征":XXX，"效率":XXX，...}
            "month":{"特征":XXX，"效率":XXX，...}
            ...
        },
        “user_id":{
            "month":{"特征":XXX，"效率":XXX，...}
            "month":{"特征":XXX，"效率":XXX，...}
            "month":{"特征":XXX，"效率":XXX，...}
            ...
        },
        “user_id":{
            "month":{"特征":XXX，"效率":XXX，...}
            "month":{"特征":XXX，"效率":XXX，...}
            "month":{"特征":XXX，"效率":XXX，...}
            ...
        },
        ...
    }
    :return:
    """
    if not external_data:
        external_data_path = get_abs_path(agent_conf["external_data_path"])
        if not os.path.exists(external_data_path):
            raise FileNotFoundError(f"外部数据文件,{external_data_path}不存在。")

        with open(external_data_path,"r",encoding="utf-8") as f:
            for line in f.readlines()[1:]:
                arr: list[str] = line.strip().split(",")

                user_id: str = arr[0].replace('"',"")
                feature: str = arr[1].replace('"', "")
                efficiency: str = arr[2].replace('"', "")
                consumables: str = arr[3].replace('"', "")
                comparison: str = arr[4].replace('"', "")
                time: str = arr[5].replace('"', "")

                if user_id not in external_data:
                    external_data[user_id] = {}

                external_data[user_id][time] = {
                    "特征":feature,
                    "效率":efficiency,
                    "耗材":consumables,
                    "对比":comparison,
                }


@tool(description="从外部系统中获取用户的使用记录，以春字符串形式返回，如果未检索到返回空字符串")
def fetch_external_data(user_id:str,month:str)->str:
    """从外部系统中获取用户指定月份的使用记录，未检索到返回空字符串。"""
    generate_external_data()

    try:
        return external_data[user_id][month]
    except KeyError:
        logger.warning(f"[fetch_external_data],未能检索到用户:{user_id}在{month}的使用记录数据")
        return  ""


@tool(description="无入参，无返回值，调用后触发中间件自动为报告生成的场景动态注入，为后续提示词切换提供上下文信息")
def fill_context_for_report():
    """触发中间件为报告生成场景动态注入上下文。"""
    return "fill_context_for_report己调用"



@tool(description="week表示学期的周传入1-7，表示周一到周日。day表示星期几传入字符串如“星期一”。")
def get_schedule(week: int, day: str, file_path: str = None) -> List[Dict[str, Any]]:
    """
    从课表Excel文件中查询指定周次和星期几的课程

    Args:
        week: 周次（整数，如1表示第1周）
        day: 星期几（字符串，如"星期一"、"星期二"等）
        file_path: Excel文件路径（可选，默认使用预设路径）

    Returns:
        课程信息列表，每个课程包含：时间段、课程名、节次、地点、属性等
    """
    # 输入验证
    if day not in ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期天"):
        error_msg = f"错误：星期输入应为 星期一~星期天 之一，收到：{day}"
        print(error_msg)
        return []

    # ========== 1. 辅助函数：解析周次字符串 ==========
    def _parse_weeks(week_str: str, week_type: str) -> List[int]:
        """
        解析周次字符串，生成具体的周次列表
        :param week_str: 如 "1-4,6-8,10"
        :param week_type: "周"、"单周" 或 "双周"
        :return: 排序后的周次列表
        """
        weeks_set = set()
        parts = week_str.split(',')
        for part in parts:
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

    # ========== 2. 辅助函数：解析单元格内容 ==========
    def _parse_course_cell(cell_text: str) -> List[Dict[str, Any]]:
        """
        解析一个单元格内的所有课程（可能有多行）
        :param cell_text: 单元格原始文本
        :return: 课程信息列表
        """
        courses = []
        # 将 <br> 替换为换行符，并按行分割
        lines = cell_text.replace('<br>', '\n').split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 按 ◇ 分割，标准格式应有三个部分
            parts = line.split('◇')
            if len(parts) < 3:
                # 格式异常，跳过
                continue

            course_info = parts[0].strip()
            week_section = parts[1].strip()
            location = parts[2].strip()

            # 提取课程名（第一个 '[' 之前的内容）
            name = course_info.split('[')[0].strip()

            # 提取所有属性（中括号内的内容）
            attributes = re.findall(r'\[(.*?)\]', course_info)

            # 解析周次信息
            week_match = re.search(r'([\d,\-]+)\((周|单周|双周)\)', week_section)
            if week_match:
                week_str = week_match.group(1)
                week_type = week_match.group(2)
                weeks = _parse_weeks(week_str, week_type)
            else:
                weeks = []  # 无法解析，可能没有周次信息

            # 解析节次
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
                'raw': line
            })

        return courses

    # ========== 3. 辅助函数：格式化输出 ==========
    def _format_results(results: List[Dict[str, Any]]) -> str:
        """
        将查询结果格式化为易读的字符串
        """
        if not results:
            return "该时间段没有课程。"

        output = []
        output.append(f"找到 {len(results)} 门课程：")
        for i, r in enumerate(results, 1):
            output.append(f"\n--- 课程 {i} ---")
            output.append(f"时间段：{r['时间段']}")
            output.append(f"课程名：{r['课程名']}")
            output.append(f"节次：{r['节次']}")
            output.append(f"地点：{r['地点']}")
            output.append(f"属性：{', '.join(r['属性'])}")

        return '\n'.join(output)

    # ========== 4a. 快速路径：上传时已预解析，直接查 DB 里的课表 JSON ==========
    if file_path is None:
        db_file, _, parsed = _load_user_schedule_path()
        if parsed:
            results = []
            for course in parsed.get(day, []):
                if week in course.get('weeks', []):
                    results.append({
                        '时间段': course.get('time_slot'),
                        '课程名': course.get('name'),
                        '节次': f"{course['start_section']}-{course['end_section']}节" if course.get(
                            'start_section') else '未知',
                        '地点': course.get('location'),
                        '属性': course.get('attributes', []),
                        '原始信息': course.get('raw')
                    })
            if not results:
                print(f"第{week}周{day}没有课程安排")
            return results
        if db_file is None:
            return [{
                "error": "未上传课表",
                "hint": "请前往「设置 → 课表设置」上传你的课表 Excel 文件",
            }]
        file = db_file
    else:
        file = file_path

    # ========== 4b. 兜底路径：旧数据没有预解析结果，现场读 Excel 并解析 ==========

    try:
        # 读取Excel，跳过前两行，第三行作为列名，第一列作为行索引（时间段）
        df = pd.read_excel(file, header=2, index_col=0, sheet_name=0)
    except FileNotFoundError:
        print(f"错误：找不到文件 '{file}'")
        return []
    except Exception as e:
        print(f"读取文件失败：{e}")
        return []

    # 确保列名正确（去除可能的空格）
    df.columns = df.columns.str.strip()
    if day not in df.columns:
        print(f"错误：表格中找不到列 '{day}'")
        return []

    # 获取指定列的数据
    day_series = df[day]
    results = []

    # 遍历每个时间段（行）
    for time_slot, cell in day_series.items():
        if pd.isna(cell):
            continue

        # 解析该单元格中的所有课程
        courses = _parse_course_cell(str(cell))

        # 筛选出当前周有课的课程
        for course in courses:
            if week in course['weeks']:
                results.append({
                    '时间段': time_slot,
                    '课程名': course['name'],
                    '节次': f"{course['start_section']}-{course['end_section']}节" if course[
                        'start_section'] else '未知',
                    '地点': course['location'],
                    '属性': course['attributes'],
                    '原始信息': course['raw']  # 包含原始数据，方便调试
                })

    # 可以选择是否打印结果
    # print(_format_results(results))

    # 如果没有找到课程，返回友好的提示信息
    if not results:
        print(f"第{week}周{day}没有课程安排")
    
    return results
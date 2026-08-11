import re
import json
import uuid
import time
from pathlib import Path
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from langchain_core.tools import tool
from AIRAGAgent.model.factory import chat_model, get_user_chat_model
from AIRAGAgent.utils.logger_handler import logger


def _current_user_id() -> int | None:
    """从请求上下文解析当前用户 ID（非 Web 请求场景返回 None）。"""
    try:
        from AIRAGAgent.agent.tools.agent_tools import user_id_var
        return user_id_var.get()
    except Exception:
        return None

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 文件保留时长（秒），超过后自动清理
FILE_TTL_SECONDS = 24 * 3600  # 24 小时


def _cleanup_old_files():
    """清理 uploads 目录中超过 TTL 的旧文件"""
    now = time.time()
    cleaned = 0
    try:
        for f in UPLOAD_DIR.iterdir():
            if f.is_file() and (now - f.stat().st_mtime) > FILE_TTL_SECONDS:
                f.unlink()
                cleaned += 1
        if cleaned:
            logger.info(f"[文件清理] 已删除 {cleaned} 个过期文件")
    except Exception as e:
        logger.warning(f"[文件清理] 失败: {e}")

# 标签格式：{内容提示|字体|字号}，后两项可选
# 例如：{姓名|楷体|四号}、{日期}、{项目名称|宋体}
TAG_PATTERN = re.compile(r'\{([^{}|]+)(?:\|([^{}]*?))?(?:\|([^{}]*?))?\}')

# 中文字号 → pt 映射
_CHINESE_SIZE_MAP = {
    '初号': 42, '小初': 36,
    '一号': 26, '小一': 24,
    '二号': 22, '小二': 18,
    '三号': 16, '小三': 15,
    '四号': 14, '小四': 12,
    '五号': 10.5, '小五': 9,
    '六号': 7.5, '小六': 6.5,
    '七号': 5.5, '八号': 5,
}

# 默认字体字号
DEFAULT_FONT_NAME = "宋体"
DEFAULT_FONT_SIZE = "小四"


# ═══════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════

def _parse_size_to_pt(size_str: str) -> float | None:
    """将字号字符串转为 pt 值。支持中文字号名和数字（含 pt 后缀）"""
    if not size_str:
        return None
    s = size_str.strip()
    # 中文字号名
    if s in _CHINESE_SIZE_MAP:
        return _CHINESE_SIZE_MAP[s]
    # 数字（可选 pt 后缀）
    num_match = re.match(r'^(\d+(?:\.\d+)?)\s*pt?$', s)
    if num_match:
        return float(num_match.group(1))
    return None


def _apply_font_to_run(run, font_name: str = None, font_size: str = None):
    """对指定 run 应用字体和字号（含东亚字体，确保中文生效）"""
    if font_name:
        run.font.name = font_name
        # 设置东亚字体，否则中文字符不会使用指定字体
        rPr = run._element.get_or_add_rPr()
        rFonts = rPr.find(qn('w:rFonts'))
        if rFonts is None:
            rFonts = OxmlElement('w:rFonts')
            rPr.insert(0, rFonts)
        rFonts.set(qn('w:eastAsia'), font_name)
    if font_size:
        pt = _parse_size_to_pt(font_size)
        if pt is not None:
            run.font.size = Pt(pt)


def _extract_document_context(doc: Document) -> str:
    """提取文档全文作为 AI 上下文（段落 + 表格 + 页眉页脚）"""
    parts = []

    for p in doc.paragraphs:
        text = p.text.strip()
        if text:
            parts.append(text)

    for table in doc.tables:
        for row in table.rows:
            row_parts = [cell.text.strip() for cell in row.cells]
            parts.append(" | ".join(row_parts))

    for section in doc.sections:
        for p in section.header.paragraphs:
            text = p.text.strip()
            if text:
                parts.append(f"[页眉] {text}")
        for p in section.footer.paragraphs:
            text = p.text.strip()
            if text:
                parts.append(f"[页脚] {text}")

    return "\n".join(parts)


def _collect_all_tags(doc: Document) -> set:
    """
    收集文档中所有唯一的内容提示（标签中 | 前的部分）。
    覆盖段落/表格/页眉页脚。
    """
    hints = set()

    def _scan(paragraphs):
        """扫描段落文本，收集所有标签的内容提示。"""
        for p in paragraphs:
            for m in TAG_PATTERN.finditer(p.text):
                hints.add(m.group(1))

    _scan(doc.paragraphs)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                _scan(cell.paragraphs)

    for section in doc.sections:
        _scan(section.header.paragraphs)
        _scan(section.footer.paragraphs)

    return hints


def _generate_tag_contents(hints: set, context: str) -> dict:
    """调用 AI 批量生成标签内容，返回 {content_hint: generated_text} 映射"""
    if not hints:
        return {}

    hints_list = sorted(hints)
    hints_str = "\n".join(f"- {h}" for h in hints_list)

    prompt = f"""你是一个专业的文档撰写助手。请根据以下文档上下文，为每个标签提示生成合适的内容。

## 文档上下文
{context}

## 需要填写的内容提示
{hints_str}

## 要求
1. 根据上下文和提示名称推断应填什么内容
2. 内容要自然、专业、符合文档语境
3. 以 JSON 格式返回，key 为提示名，value 为生成的内容
4. 只返回 JSON，不要其他说明

返回示例：
{{"项目名称": "办公自动化系统升级项目", "开始时间": "2025年1月1日"}}"""

    try:
        # 按当前用户解析对话模型（用户自配 OpenAI 兼容模型优先，否则系统默认）
        response = get_user_chat_model(_current_user_id()).invoke(prompt)
        content = response.content.strip()

        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            content = json_match.group(0)

        result = json.loads(content)

        for hint in hints_list:
            if hint not in result:
                result[hint] = f"[{hint}]"

        return result
    except Exception as e:
        logger.error(f"[Word填充] AI 批量生成失败: {e}")
        return {hint: f"[{hint}]" for hint in hints_list}


def _replace_in_paragraphs(paragraphs, tag_contents: dict) -> int:
    """在段落列表中进行 run 级别的标签替换。返回替换的标签总数。"""
    total = 0
    for p in paragraphs:
        total += _replace_in_single_paragraph(p, tag_contents)
    return total


def _replace_in_single_paragraph(paragraph, tag_contents: dict) -> int:
    """单个段落的标签替换，替换文本并应用字体字号。返回替换次数"""
    if not TAG_PATTERN.search(paragraph.text):
        return 0

    runs = paragraph.runs
    if not runs:
        return 0

    full_text = paragraph.text

    # 构建字符→run 映射，用于判断标签是否跨 run
    char_map = []
    for run_idx, run in enumerate(runs):
        for _ in run.text:
            char_map.append(run_idx)

    if len(char_map) != len(full_text):
        return 0

    # 检查是否存在跨 run 标签
    has_cross_run = False
    for m in TAG_PATTERN.finditer(full_text):
        start_run = char_map[m.start()]
        end_run = char_map[m.end() - 1]
        if start_run != end_run:
            has_cross_run = True
            break

    matches = list(TAG_PATTERN.finditer(full_text))

    if has_cross_run:
        # ── 跨 run 标签：段落级替换 ──
        # 收集第一个有自定义字体的标签格式
        first_font_name = None
        first_font_size = None
        use_custom_font = False
        for m in matches:
            fn = m.group(2) or None
            fs = m.group(3) or None
            if fn or fs:
                first_font_name = fn
                first_font_size = fs
                use_custom_font = True
                break

        # 保存首 run 的原始字体作为回退
        first_run = runs[0]
        first_font = first_run.font

        new_text = full_text
        for m in reversed(matches):
            content_hint = m.group(1)
            if content_hint in tag_contents:
                new_text = new_text[:m.start()] + tag_contents[content_hint] + new_text[m.end():]

        # 清空所有 run，重建
        for run in list(runs):
            run._element.getparent().remove(run._element)

        new_run = paragraph.add_run(new_text)

        if use_custom_font:
            _apply_font_to_run(new_run, first_font_name, first_font_size)
        else:
            # 保留原始格式
            if first_font.bold is not None:
                new_run.bold = first_font.bold
            if first_font.italic is not None:
                new_run.italic = first_font.italic
            if first_font.size is not None:
                new_run.font.size = first_font.size
            if first_font.name is not None:
                new_run.font.name = first_font.name
            if first_font.color and first_font.color.rgb:
                new_run.font.color.rgb = first_font.color.rgb
            if first_font.underline is not None:
                new_run.underline = first_font.underline

        return len(matches)
    else:
        # ── 单 run 标签：run 级替换 + 字体应用 ──
        count = 0
        for run in runs:
            run_matches = list(TAG_PATTERN.finditer(run.text))
            if not run_matches:
                continue

            run_len = len(run.text)

            # 收集此 run 中所有要替换的标签信息
            # (start, end, content_hint, font_name, font_size)
            replacements = []
            for m in run_matches:
                content_hint = m.group(1)
                if content_hint not in tag_contents:
                    continue
                fn = m.group(2) or None
                fs = m.group(3) or None
                replacements.append((m.start(), m.end(), content_hint, fn, fs))

            if not replacements:
                continue

            # 从右往左替换文本
            new_text = run.text
            for start, end, hint, fn, fs in reversed(replacements):
                new_text = new_text[:start] + tag_contents[hint] + new_text[end:]

            run.text = new_text
            count += len(replacements)

            # 应用字体：仅当 run 中只有一个标签且标签占据整个 run 内容时生效
            if len(replacements) == 1:
                start, end, hint, fn, fs = replacements[0]
                if start == 0 and end == run_len and (fn or fs):
                    _apply_font_to_run(run, fn, fs)

        return count


# ═══════════════════════════════════════════════
# 主工具函数
# ═══════════════════════════════════════════════

@tool(description="自动填写Word文件标签。标签格式为{内容提示|字体|字号}，字体和字号可选，不填则使用默认（宋体小四）。填写后的文件可通过返回的下载链接下载。")
def auto_fill_word(template_path: str) -> str:
    """
    接收服务器上已上传的 Word 文件路径，自动查找 {内容提示|字体|字号} 占位标签，
    用 AI 生成内容填充，并应用指定的字体字号。

    标签格式：
        {内容提示}               — 仅内容提示，使用默认字体字号
        {内容提示|字体}           — 指定字体
        {内容提示|字体|字号}      — 指定字体和字号
        {内容提示||字号}          — 仅指定字号（字体用默认）

    Args:
        template_path: 上传到服务器的 Word 文件的绝对路径
    """
    if not Path(template_path).exists():
        return f"处理失败：文件不存在 ({template_path})"
    if not Path(template_path).is_file():
        return f"处理失败：路径不是有效文件 ({template_path})"

    # 处理前先清理过期文件
    _cleanup_old_files()

    try:
        doc = Document(template_path)

        # 1. 提取文档上下文 + 收集唯一内容提示
        context = _extract_document_context(doc)
        all_hints = _collect_all_tags(doc)

        if not all_hints:
            return "文档中没有找到需要填写的占位标签（格式为{内容提示}或{内容提示|字体|字号}），无需处理。"

        # 2. AI 批量生成标签内容
        tag_contents = _generate_tag_contents(all_hints, context)
        logger.info(f"[Word填充] 共 {len(all_hints)} 个内容提示，AI 生成 {len(tag_contents)} 个内容")

        # 3. 替换段落
        para_count = _replace_in_paragraphs(doc.paragraphs, tag_contents)

        # 4. 替换表格
        table_count = 0
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    table_count += _replace_in_paragraphs(cell.paragraphs, tag_contents)

        # 5. 替换页眉页脚
        hf_count = 0
        for section in doc.sections:
            hf_count += _replace_in_paragraphs(section.header.paragraphs, tag_contents)
            hf_count += _replace_in_paragraphs(section.footer.paragraphs, tag_contents)

        # 6. 保存
        output_filename = f"filled_{uuid.uuid4().hex[:8]}.docx"
        output_path = UPLOAD_DIR / output_filename
        doc.save(str(output_path))

        # 7. 删除模板文件
        try:
            Path(template_path).unlink()
            logger.info(f"[Word填充] 已删除模板: {template_path}")
        except Exception as e:
            logger.warning(f"[Word填充] 删除模板失败: {e}")

        total = para_count + table_count + hf_count
        download_url = f"/api/download/{output_filename}"
        return (
            f"文件处理完成！共替换了 {total} 个标签（段落 {para_count} / 表格 {table_count}"
            f"{' / 页眉页脚 ' + str(hf_count) if hf_count else ''}）。\n\n"
            f"[点击下载已填写的文档]({download_url})"
        )

    except Exception as e:
        logger.error(f"[Word填充] 处理失败: {e}")
        return f"处理失败：{str(e)}"

"""WordDoc：美观 Word 文档生成辅助库（wordgen SubAgent 专用）。

封装 python-docx 排版细节，提供高层 API，排版随内容主题自动适配：

    from AIRAGAgent.agent.tools.wordgen_helper import WordDoc

    # theme 由内容决定：modern(调研)/official(正式)/fresh(活泼)/academic(学术)
    doc = WordDoc("关于《王者荣耀世界》博主的生态调研",
                  theme="modern", subtitle="2026 年 8 月", author="AI 调研助手")
    doc.h1("一、调研背景")
    doc.p("《王者荣耀世界》是腾讯天美工作室推出的开放世界 RPG……")
    doc.h2("1.1 博主生态现状")
    doc.bullet("B 站头部博主粉丝量级达数百万")
    doc.table(["博主", "平台", "粉丝数"], [["某甲", "B站", "320万"]])
    path = doc.save("调研报告.docx")   # 相对路径，落到当前计划工作区

内置 4 套主题（配色/字体/封面/表格风格各不同），LLM 只需按内容选 theme，
排版细节由本库保证，不依赖 LLM 写裸 python-docx。

中文字体通过 w:rFonts 的 eastAsia 显式设置到每个 run，确保在 Word/WPS 正确渲染
（python-docx 默认只设 ascii 字体，中文会回退到系统默认导致排版错乱）。
"""
from __future__ import annotations

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_BREAK
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


# ═══════════════════════════════════════════════
# 主题定义
# ═══════════════════════════════════════════════

def _rgb(hex_str: str) -> RGBColor:
    """把十六进制颜色字符串（如 "2C3E50"）转换为 RGBColor 对象。"""
    return RGBColor(int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))


# 每个主题：标题色/H1色/H2色/H3色/正文色/表头底色/表头字色/斑马纹底色/标题字体/正文字体/是否封面
_THEMES = {
    "modern": {
        # 现代简约：莫兰迪蓝灰 + 留白，适合调研报告、行业分析、产品洞察
        "title": _rgb("2C3E50"), "h1": _rgb("2C3E50"), "h2": _rgb("34678F"),
        "h3": _rgb("444444"), "body": _rgb("2D2D2D"), "subtitle": _rgb("7F8C8D"),
        "th_bg": "34678F", "th_fg": _rgb("FFFFFF"), "zebra": "F2F5F8",
        "border": "D5DDE5", "h1_border": "2C3E50",
        "heading_font": "微软雅黑", "body_font": "宋体",
        "cover": True,
    },
    "official": {
        # 正式商务：深蓝 + 封面 + 页码，适合政府/企业年度报告、工作总结、白皮书
        "title": _rgb("1F3864"), "h1": _rgb("1F3864"), "h2": _rgb("2E5395"),
        "h3": _rgb("333333"), "body": _rgb("262626"), "subtitle": _rgb("595959"),
        "th_bg": "1F3864", "th_fg": _rgb("FFFFFF"), "zebra": "EDF1F7",
        "border": "BFBFBF", "h1_border": "1F3864",
        "heading_font": "微软雅黑", "body_font": "宋体",
        "cover": True,
    },
    "fresh": {
        # 清新活泼：蓝绿 + 浅橙点缀，适合活动方案、用户洞察、年轻向内容
        "title": _rgb("0E7C7B"), "h1": _rgb("0E7C7B"), "h2": _rgb("2A9D8F"),
        "h3": _rgb("E76F51"), "body": _rgb("3D3D3D"), "subtitle": _rgb("6B7280"),
        "th_bg": "2A9D8F", "th_fg": _rgb("FFFFFF"), "zebra": "EAF6F4",
        "border": "CFE8E4", "h1_border": "0E7C7B",
        "heading_font": "微软雅黑", "body_font": "宋体",
        "cover": True,
    },
    "academic": {
        # 学术严谨：黑白灰 + 编号风，适合论文、技术研究、技术文档
        "title": _rgb("1A1A1A"), "h1": _rgb("1A1A1A"), "h2": _rgb("333333"),
        "h3": _rgb("333333"), "body": _rgb("1A1A1A"), "subtitle": _rgb("666666"),
        "th_bg": "333333", "th_fg": _rgb("FFFFFF"), "zebra": "F4F4F4",
        "border": "CCCCCC", "h1_border": "333333",
        "heading_font": "黑体", "body_font": "宋体",
        "cover": False,  # 学术文档按惯例不用封面页
    },
}

_DEFAULT_THEME = "modern"


# 字号（pt）—— 各主题统一
_SIZE_TITLE = 24
_SIZE_SUBTITLE = 14
_SIZE_H1 = 16
_SIZE_H2 = 14
_SIZE_H3 = 12
_SIZE_BODY = 12       # 小四
_SIZE_TABLE = 11
_SIZE_CAPTION = 10.5


# ═══════════════════════════════════════════════
# 底层 XML 辅助
# ═══════════════════════════════════════════════

def _set_run_font(run, font_name: str, size_pt: float, bold: bool = False,
                  color: RGBColor | None = None, italic: bool = False):
    """设置 run 字体/字号/粗体/颜色，并通过 eastAsia 保证中文生效。"""
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.insert(0, rFonts)
    rFonts.set(qn('w:eastAsia'), font_name)
    rFonts.set(qn('w:ascii'), font_name)
    rFonts.set(qn('w:hAnsi'), font_name)


def _set_cell_shading(cell, hex_color: str):
    """给 Word 表格单元格设置底色（hex_color 十六进制颜色）。"""
    tcPr = cell._tc.get_or_add_tcPr()
    for old in tcPr.findall(qn('w:shd')):
        tcPr.remove(old)
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)


def _set_table_borders(table, hex_color: str, sz: int = 4):
    """设置 Word 表格的整体边框样式（颜色与粗细）。"""
    tblPr = table._tbl.tblPr
    for old in tblPr.findall(qn('w:tblBorders')):
        tblPr.remove(old)
    borders = OxmlElement('w:tblBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'single')
        el.set(qn('w:sz'), str(sz))
        el.set(qn('w:space'), '0')
        el.set(qn('w:color'), hex_color)
        borders.append(el)
    tblPr.append(borders)


def _add_bottom_border(paragraph, hex_color: str, sz: int = 6):
    """给段落添加下边框线（常用于分隔线效果）。"""
    pPr = paragraph._p.get_or_add_pPr()
    for old in pPr.findall(qn('w:pBdr')):
        pPr.remove(old)
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), str(sz))
    bottom.set(qn('w:space'), '4')
    bottom.set(qn('w:color'), hex_color)
    pBdr.append(bottom)
    pPr.append(pBdr)


def _set_cell_margins(table, top=60, bottom=60, left=100, right=100):
    """设置表格所有单元格的内边距（单位：缇 twips）。"""
    tblPr = table._tbl.tblPr
    for old in tblPr.findall(qn('w:tblCellMar')):
        tblPr.remove(old)
    mar = OxmlElement('w:tblCellMar')
    for side, val in (('top', top), ('bottom', bottom), ('left', left), ('right', right)):
        el = OxmlElement(f'w:{side}')
        el.set(qn('w:w'), str(val))
        el.set(qn('w:type'), 'dxa')
        mar.append(el)
    tblPr.append(mar)


def _add_page_number_footer(section):
    """给 section 的页脚加居中页码（封面后第一页开始计数）。"""
    footer = section.footer
    footer.is_linked_to_previous = False
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    # 清空已有内容
    for r in list(p.runs):
        r._element.getparent().remove(r._element)
    run = p.add_run()
    # PAGE 域：当前页码
    fldBegin = OxmlElement('w:fldChar'); fldBegin.set(qn('w:fldCharType'), 'begin')
    instr = OxmlElement('w:instrText'); instr.set(qn('xml:space'), 'preserve'); instr.text = 'PAGE'
    fldEnd = OxmlElement('w:fldChar'); fldEnd.set(qn('w:fldCharType'), 'end')
    run._element.append(fldBegin)
    run._element.append(instr)
    run._element.append(fldEnd)
    _set_run_font(run, "微软雅黑", 9, color=_rgb("999999"))


# ═══════════════════════════════════════════════
# WordDoc 主体
# ═══════════════════════════════════════════════

class WordDoc:
    """美观 Word 文档构建器，排版随主题自适应。

    Args:
        title: 文档标题
        theme: 排版主题，modern(调研/分析) / official(正式商务) / fresh(活泼) / academic(学术)
        subtitle: 副标题（封面/标题下显示）
        author: 署名（封面/标题下显示）
    """

    def __init__(self, title: str, theme: str = _DEFAULT_THEME,
                 subtitle: str = "", author: str = ""):
        """初始化文档：设置页边距与默认样式，并按主题生成封面或标题块。"""
        self._doc = Document()
        self._theme = _THEMES.get(theme, _THEMES[_DEFAULT_THEME])
        self._has_cover = False

        th = self._theme

        # 页边距
        for section in self._doc.sections:
            section.top_margin = Cm(2.54)
            section.bottom_margin = Cm(2.54)
            section.left_margin = Cm(3.0)
            section.right_margin = Cm(3.0)

        # Normal 默认样式（兜底）
        try:
            normal = self._doc.styles['Normal']
            normal.font.name = th["body_font"]
            normal.font.size = Pt(_SIZE_BODY)
            normal.font.color.rgb = th["body"]
            rPr = normal.element.get_or_add_rPr()
            rFonts = rPr.find(qn('w:rFonts'))
            if rFonts is None:
                rFonts = OxmlElement('w:rFonts')
                rPr.insert(0, rFonts)
            rFonts.set(qn('w:eastAsia'), th["body_font"])
        except Exception:
            pass

        # 封面页（academic 不用）
        if th["cover"]:
            self._build_cover(title, subtitle, author)
            self._has_cover = True
            # 封面后加页脚页码
            for section in self._doc.sections:
                _add_page_number_footer(section)
        else:
            # 无封面：直接在首页顶部放标题块
            self._build_title_block(title, subtitle, author)

    # ── 封面 / 标题块 ──

    def _build_cover(self, title: str, subtitle: str, author: str):
        """生成封面页：标题、装饰横线、副标题、署名与日期，末尾分页。"""
        th = self._theme
        # 顶部留白（约占页面 1/3）
        for _ in range(6):
            sp = self._doc.add_paragraph()
            sp.paragraph_format.space_after = Pt(0)

        # 主标题
        p = self._doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(12)
        r = p.add_run(title)
        _set_run_font(r, th["heading_font"], _SIZE_TITLE, bold=True, color=th["title"])

        # 装饰横线
        line = self._doc.add_paragraph()
        line.alignment = WD_ALIGN_PARAGRAPH.CENTER
        line.paragraph_format.space_after = Pt(16)
        _add_bottom_border(line, th["h1_border"], 12)
        # 横线段落本身不放文字，仅靠底边框呈现

        # 副标题
        if subtitle:
            ps = self._doc.add_paragraph()
            ps.alignment = WD_ALIGN_PARAGRAPH.CENTER
            ps.paragraph_format.space_after = Pt(6)
            rs = ps.add_run(subtitle)
            _set_run_font(rs, th["heading_font"], _SIZE_SUBTITLE, color=th["subtitle"])

        # 署名
        if author:
            pa = self._doc.add_paragraph()
            pa.alignment = WD_ALIGN_PARAGRAPH.CENTER
            pa.paragraph_format.space_after = Pt(6)
            ra = pa.add_run(author)
            _set_run_font(ra, th["heading_font"], _SIZE_SUBTITLE, color=th["subtitle"])

        # 日期（自动）
        import datetime
        pd = self._doc.add_paragraph()
        pd.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pd.paragraph_format.space_after = Pt(6)
        rd = pd.add_run(datetime.date.today().strftime("%Y 年 %m 月"))
        _set_run_font(rd, th["heading_font"], _SIZE_SUBTITLE, color=th["subtitle"])

        # 封面后分页
        self._doc.add_page_break()

    def _build_title_block(self, title: str, subtitle: str, author: str):
        """在首页顶部构建标题块（无封面主题时使用）。"""
        th = self._theme
        p = self._doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)
        r = p.add_run(title)
        _set_run_font(r, th["heading_font"], _SIZE_TITLE, bold=True, color=th["title"])

        if subtitle:
            ps = self._doc.add_paragraph()
            ps.alignment = WD_ALIGN_PARAGRAPH.CENTER
            ps.paragraph_format.space_after = Pt(4)
            rs = ps.add_run(subtitle)
            _set_run_font(rs, th["heading_font"], _SIZE_SUBTITLE, color=th["subtitle"])

        if author:
            pa = self._doc.add_paragraph()
            pa.alignment = WD_ALIGN_PARAGRAPH.CENTER
            pa.paragraph_format.space_after = Pt(14)
            ra = pa.add_run(author)
            _set_run_font(ra, th["heading_font"], _SIZE_SUBTITLE, color=th["subtitle"])

    # ── 标题层级 ──

    def h1(self, text: str):
        """一级标题：主题色加粗，带底部分隔线。"""
        th = self._theme
        p = self._doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(18)
        pf.space_after = Pt(8)
        pf.keep_with_next = True
        r = p.add_run(text)
        _set_run_font(r, th["heading_font"], _SIZE_H1, bold=True, color=th["h1"])
        _add_bottom_border(p, th["h1_border"], 6)
        return p

    def h2(self, text: str):
        """二级标题。"""
        th = self._theme
        p = self._doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(14)
        pf.space_after = Pt(6)
        pf.keep_with_next = True
        r = p.add_run(text)
        _set_run_font(r, th["heading_font"], _SIZE_H2, bold=True, color=th["h2"])
        return p

    def h3(self, text: str):
        """三级标题。"""
        th = self._theme
        p = self._doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(10)
        pf.space_after = Pt(4)
        pf.keep_with_next = True
        r = p.add_run(text)
        _set_run_font(r, th["heading_font"], _SIZE_H3, bold=True, color=th["h3"])
        return p

    # ── 正文 ──

    def p(self, text: str, indent: bool = True):
        """正文段落：1.5 倍行距，首行缩进 2 字符，段后 6pt。"""
        th = self._theme
        para = self._doc.add_paragraph()
        pf = para.paragraph_format
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.line_spacing = 1.5
        pf.space_after = Pt(6)
        if indent:
            pf.first_line_indent = Pt(24)
        r = para.add_run(text)
        _set_run_font(r, th["body_font"], _SIZE_BODY, color=th["body"])
        return para

    def bullet(self, text: str):
        """无序列表项：• 符号 + 悬挂缩进。"""
        th = self._theme
        para = self._doc.add_paragraph()
        pf = para.paragraph_format
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.line_spacing = 1.5
        pf.space_after = Pt(3)
        pf.left_indent = Pt(21)
        pf.first_line_indent = Pt(-21)
        r = para.add_run("• " + text)
        _set_run_font(r, th["body_font"], _SIZE_BODY, color=th["body"])
        return para

    def quote(self, text: str):
        """引用块：左侧竖线 + 灰色字。"""
        th = self._theme
        para = self._doc.add_paragraph()
        pf = para.paragraph_format
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.line_spacing = 1.5
        pf.space_after = Pt(6)
        pf.left_indent = Cm(0.8)
        pPr = para._p.get_or_add_pPr()
        pBdr = OxmlElement('w:pBdr')
        left = OxmlElement('w:left')
        left.set(qn('w:val'), 'single')
        left.set(qn('w:sz'), '18')
        left.set(qn('w:space'), '8')
        left.set(qn('w:color'), th["h1_border"])
        pBdr.append(left)
        pPr.append(pBdr)
        r = para.add_run(text)
        _set_run_font(r, "楷体", _SIZE_BODY, color=th["subtitle"], italic=True)
        return para

    # ── 表格 ──

    def table(self, headers, rows, align: str = "center"):
        """数据表格：表头主题底色 + 白字加粗，正文斑马纹（奇偶行交替底色）。

        Args:
            headers: 列名列表
            rows: 二维数据列表
            align: 单元格对齐 "center" / "left"
        """
        th = self._theme
        ncol = len(headers)
        table = self._doc.add_table(rows=1, cols=ncol)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        _set_table_borders(table, th["border"], 4)
        _set_cell_margins(table)

        align_map = {"center": WD_ALIGN_PARAGRAPH.CENTER, "left": WD_ALIGN_PARAGRAPH.LEFT}
        cell_align = align_map.get(align, WD_ALIGN_PARAGRAPH.CENTER)

        # 表头
        hdr_cells = table.rows[0].cells
        for i, h in enumerate(headers):
            cell = hdr_cells[i]
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(str(h))
            _set_run_font(r, th["heading_font"], _SIZE_TABLE, bold=True, color=th["th_fg"])
            _set_cell_shading(cell, th["th_bg"])

        # 数据行（斑马纹：偶数索引行加底色）
        for row_idx, row in enumerate(rows):
            cells = table.add_row().cells
            is_zebra = (row_idx % 2 == 1)  # 第2、4、6... 行加底色
            for i in range(ncol):
                val = row[i] if i < len(row) else ""
                cell = cells[i]
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                p = cell.paragraphs[0]
                p.alignment = cell_align
                p.paragraph_format.space_after = Pt(0)
                r = p.add_run(str(val))
                _set_run_font(r, th["body_font"], _SIZE_TABLE, color=th["body"])
                if is_zebra:
                    _set_cell_shading(cell, th["zebra"])

        self._doc.add_paragraph().paragraph_format.space_after = Pt(4)
        return table

    # ── 图片 / 分页 ──

    def image(self, path: str, width_cm: float = 14.0, caption: str = ""):
        """在文档中插入一张图片，可选居中并带图注。"""
        th = self._theme
        p = self._doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(2)
        run = p.add_run()
        run.add_picture(path, width=Cm(width_cm))
        if caption:
            cp = self._doc.add_paragraph()
            cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            cp.paragraph_format.space_after = Pt(10)
            r = cp.add_run(caption)
            _set_run_font(r, th["body_font"], _SIZE_CAPTION, color=th["subtitle"])

    def page_break(self):
        """在文档中插入一个分页符。"""
        self._doc.add_page_break()

    def spacer(self, pt: float = 6):
        """插入一个指定段后间距的空行作为留白。"""
        p = self._doc.add_paragraph()
        p.paragraph_format.space_after = Pt(pt)
        return p

    # ── 保存 ──

    def save(self, filename: str) -> str:
        """保存文档，返回绝对路径。自动创建父目录。"""
        import os
        if not filename.lower().endswith(".docx"):
            filename += ".docx"
        parent = os.path.dirname(filename)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._doc.save(filename)
        return os.path.abspath(filename)

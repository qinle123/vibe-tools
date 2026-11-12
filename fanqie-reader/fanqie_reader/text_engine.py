from __future__ import annotations
import re
from typing import List, Tuple

try:
    import wcwidth
    def char_width(c: str) -> int:
        w = wcwidth.wcwidth(c)
        return max(0, w if w >= 0 else 1)
except ImportError:
    def char_width(c: str) -> int:
        # 降级方案：CJK 区域字符宽度为 2，其他为 1
        cp = ord(c)
        if (
            0x4E00 <= cp <= 0x9FFF or
            0x3400 <= cp <= 0x4DBF or
            0x20000 <= cp <= 0x2A6DF or
            0xF900 <= cp <= 0xFAFF or
            0x2F800 <= cp <= 0x2FA1F or
            0x3000 <= cp <= 0x303F or  # CJK 标点
            0xFF00 <= cp <= 0xFFEF     # 全角 ASCII、全角标点
        ):
            return 2
        return 1

def str_visual_width(s: str) -> int:
    """计算字符串在终端中的实际可见列宽"""
    return sum(char_width(c) for c in s)

def sanitize_terminal_text(text: str) -> str:
    """一行只包含可显示文本，控制字符不能移动终端光标。"""
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text.expandtabs(4))

def truncate_to_width(s: str, max_width: int, ellipsis: str = "") -> str:
    """根据真实终端列宽截断字符串，确保总宽度严格 <= max_width，绝不造成终端换行错位"""
    if max_width <= 0:
        return ""
    total_w = str_visual_width(s)
    if total_w <= max_width:
        return s
    
    el_w = str_visual_width(ellipsis)
    target_w = max(0, max_width - el_w) if ellipsis else max_width
    cur_w = 0
    res = []
    for c in s:
        w = char_width(c)
        if cur_w + w > target_w:
            break
        res.append(c)
        cur_w += w
    return "".join(res) + (ellipsis if cur_w > 0 else "")

def pad_to_width(s: str, target_width: int, fillchar: str = " ", align: str = "left") -> str:
    """按照终端真实列宽对齐并填充字符串"""
    cur_w = str_visual_width(s)
    if cur_w >= target_width:
        return truncate_to_width(s, target_width)
    pad = fillchar * (target_width - cur_w)
    if align == "right":
        return pad + s
    elif align == "center":
        left_pad = fillchar * ((target_width - cur_w) // 2)
        right_pad = fillchar * (target_width - cur_w - len(left_pad))
        return left_pad + s + right_pad
    return s + pad

class TextLayoutEngine:
    """针对中英文混排优化的终端排版引擎"""

    def __init__(self, content_width: int = 76):
        self.content_width = max(2, content_width)

    def set_content_width(self, width: int) -> None:
        self.content_width = max(2, width)

    def wrap_paragraph(self, paragraph: str) -> List[str]:
        """将单个自然段根据 content_width 智能折行为终端行"""
        paragraph = sanitize_terminal_text(paragraph)
        if not paragraph.strip():
            return [""]

        # 处理缩进：如果是自然段且未以全角空格开头，加上缩进
        text = paragraph
        lines: List[str] = []
        cur_line = []
        cur_width = 0

        # 不能出现在行首的标点符号（避头）
        no_head_punct = set("，。！？、：；”）》〉】』」…—～")

        for c in text:
            w = char_width(c)
            # 如果当前字符换行会导致超宽
            if cur_width + w > self.content_width:
                # 避头处理：如果超宽换行的首个字符是标点，尝试把前一个字符带到下一行
                if c in no_head_punct and len(cur_line) > 1 and char_width(cur_line[-1]) + w <= self.content_width:
                    prev_c = cur_line.pop()
                    lines.append("".join(cur_line))
                    cur_line = [prev_c, c]
                    cur_width = char_width(prev_c) + w
                else:
                    lines.append("".join(cur_line))
                    cur_line = [c]
                    cur_width = w
            else:
                cur_line.append(c)
                cur_width += w

        if cur_line:
            lines.append("".join(cur_line))

        return lines

    def layout_chapter(self, title: str, content: str) -> List[str]:
        """
        对章节标题和正文进行完整排版
        返回排版后的行列表（lines）
        """
        formatted_lines: List[str] = []

        # 1. 标题居中排版
        if title:
            title = sanitize_terminal_text(title)
            t_width = str_visual_width(title)
            # 标题上下空行
            formatted_lines.append("")
            for line in self.wrap_paragraph(title):
                pad = max(0, (self.content_width - str_visual_width(line)) // 2)
                formatted_lines.append(" " * pad + line)
            # 装饰分割线
            sep_width = min(self.content_width, max(t_width + 4, 16))
            sep_pad = max(0, (self.content_width - sep_width) // 2)
            formatted_lines.append(" " * sep_pad + "─" * (sep_width // 2))
            formatted_lines.append("")

        # 2. 正文段落排版
        paragraphs = content.splitlines()
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            wrapped = self.wrap_paragraph(para)
            formatted_lines.extend(wrapped)
            # 段落间增加一个空行呼吸感
            formatted_lines.append("")

        # 去除末尾多余空行，保留 2 行缓冲
        while formatted_lines and not formatted_lines[-1].strip():
            formatted_lines.pop()
        
        # 章节尾部提示
        formatted_lines.append("")
        end_text = "── 本章完 (按 l 继续下一章) ──"
        for line in self.wrap_paragraph(end_text):
            e_pad = max(0, (self.content_width - str_visual_width(line)) // 2)
            formatted_lines.append(" " * e_pad + line)
        formatted_lines.append("")

        return formatted_lines

    def pad_line_to_center(self, line: str, term_cols: int) -> str:
        """根据终端列宽，将排版好的行居中"""
        margin_left = max(0, (term_cols - self.content_width) // 2)
        return (" " * margin_left) + line

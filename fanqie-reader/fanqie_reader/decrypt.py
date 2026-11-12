from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Dict, Optional

class FontDecryptor:
    """番茄小说字体反爬解密器"""

    def __init__(self, map_path: Optional[str] = None):
        self.mapping: Dict[str, str] = {}
        if not map_path:
            pkg_data = Path(__file__).parent / "data" / "font_map.json"
            if pkg_data.exists():
                map_path = str(pkg_data)
        
        if map_path and Path(map_path).exists():
            try:
                with open(map_path, "r", encoding="utf-8") as f:
                    self.mapping = json.load(f)
            except Exception:
                self.mapping = {}

    def is_pua(self, char: str) -> bool:
        if not char:
            return False
        cp = ord(char[0])
        return 0xE000 <= cp <= 0xF8FF

    def decode_text(self, text: str) -> str:
        """解密含 PUA 字符的文本"""
        if not text:
            return ""
        
        # 逐字符查表替换
        result = []
        for ch in text:
            if self.is_pua(ch):
                real_ch = self.mapping.get(ch)
                if not real_ch:
                    code_key = f"U+{ord(ch):04X}"
                    real_ch = self.mapping.get(code_key, ch)
                result.append(real_ch)
            else:
                result.append(ch)
        return "".join(result)

    def clean_html_content(self, html_content: str) -> str:
        """
        清洗 HTML 段落，替换加密字体，并转换为标准的段落排版文本
        每个自然段前添加两个全角空格缩进，段落间空一行
        """
        if not html_content:
            return ""
        
        # 提取段落
        paragraphs = re.findall(r'<p>(.*?)</p>', html_content, re.DOTALL)
        if not paragraphs:
            # 备选：如果直接是普通带标签文本
            cleaned = re.sub(r'</p>', '\n\n', html_content)
            cleaned = re.sub(r'<p>', '　　', cleaned)
            cleaned = re.sub(r'<[^>]+>', '', cleaned)
            return self.decode_text(cleaned).strip()
        
        decoded_paragraphs = []
        for p in paragraphs:
            # 去除内部标签，如 <span> 等
            p_text = re.sub(r'<[^>]+>', '', p).strip()
            if not p_text:
                continue
            # 解密
            p_dec = self.decode_text(p_text)
            # 首行双全角空格缩进
            if not p_dec.startswith('　　'):
                p_dec = '　　' + p_dec.lstrip()
            decoded_paragraphs.append(p_dec)
        
        return "\n\n".join(decoded_paragraphs)

# 全局单例
_decryptor: Optional[FontDecryptor] = None

def get_decryptor() -> FontDecryptor:
    global _decryptor
    if _decryptor is None:
        _decryptor = FontDecryptor()
    return _decryptor

def decode_chapter(html_content: str) -> str:
    return get_decryptor().clean_html_content(html_content)

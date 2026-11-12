import unittest
from fanqie_reader.text_engine import TextLayoutEngine, str_visual_width, char_width

class TestTextEngine(unittest.TestCase):
    def test_multiline_content_and_long_titles_stay_on_physical_rows(self):
        engine = TextLayoutEngine(content_width=12)
        lines = engine.layout_chapter("超长章节标题" * 5, "第一段\n第二段\r\n第三段\t内容\x1b")
        self.assertTrue(any("第二段" in line for line in lines))
        for line in lines:
            self.assertLessEqual(str_visual_width(line), 12)
            self.assertFalse(any(char in line for char in "\n\r\t\x1b"))

    def test_char_and_string_width(self):
        # 汉字宽度应为 2
        self.assertEqual(char_width("中"), 2)
        self.assertEqual(char_width("国"), 2)
        # 全角标点宽度应为 2
        self.assertEqual(char_width("，"), 2)
        self.assertEqual(char_width("。"), 2)
        # ASCII 字符宽度应为 1
        self.assertEqual(char_width("a"), 1)
        self.assertEqual(char_width("1"), 1)
        self.assertEqual(char_width(" "), 1)

        # "Hello世界" = 5 + 4 = 9
        self.assertEqual(str_visual_width("Hello世界"), 9)

    def test_truncate_to_width(self):
        from fanqie_reader.text_engine import truncate_to_width, pad_to_width
        
        # 汉字截断：每个汉字占 2 列宽
        # "金兵围城？我启动蒸汽机" 10 个字符 = 20 宽
        text = "金兵围城？我启动蒸汽机"
        self.assertEqual(truncate_to_width(text, 10), "金兵围城？")
        self.assertEqual(truncate_to_width(text, 11), "金兵围城？") # 不足以放入第6个汉字
        self.assertEqual(truncate_to_width(text, 12), "金兵围城？我")

        # 带省略号 (4个汉字 8宽 + '..' 2宽 = 10宽)
        res_el = truncate_to_width(text, 10, ellipsis="..")
        self.assertEqual(res_el, "金兵围城..")
        self.assertEqual(str_visual_width(res_el), 10)

        # pad_to_width
        self.assertEqual(pad_to_width("abc", 5), "abc  ")
        self.assertEqual(pad_to_width("中文", 6), "中文  ")

    def test_paragraph_wrapping(self):
        engine = TextLayoutEngine(content_width=20)
        # 10 个汉字刚好 20 宽
        text1 = "一二三四五六七八九十"
        lines1 = engine.wrap_paragraph(text1)
        self.assertEqual(len(lines1), 1)
        self.assertEqual(lines1[0], text1)

        # 11 个汉字应该折为两行
        text2 = "一二三四五六七八九十一"
        lines2 = engine.wrap_paragraph(text2)
        self.assertEqual(len(lines2), 2)
        self.assertEqual(lines2[0], "一二三四五六七八九十")
        self.assertEqual(lines2[1], "一")

    def test_punctuation_no_head(self):
        # 避头测试：第 11 个字符是逗号，避免逗号单独掉到第二行
        engine = TextLayoutEngine(content_width=20)
        text = "一二三四五六七八九十，下一行"
        lines = engine.wrap_paragraph(text)
        # 应该在 '十' 处前移折行，或者将 '十，' 一起放到下一行
        self.assertFalse(lines[1].startswith("，"))

    def test_layout_chapter(self):
        engine = TextLayoutEngine(content_width=40)
        title = "第一章 初始"
        content = "　　第一段话测试。\n\n　　第二段话测试。"
        lines = engine.layout_chapter(title, content)
        self.assertTrue(any("第一章 初始" in l for l in lines))
        self.assertTrue(any("第一段话测试。" in l for l in lines))
        self.assertTrue(any("本章完" in l for l in lines))

if __name__ == "__main__":
    unittest.main()

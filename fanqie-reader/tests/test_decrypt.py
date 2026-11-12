import unittest
from fanqie_reader.decrypt import FontDecryptor, decode_chapter

class TestDecrypt(unittest.TestCase):
    def setUp(self):
        self.dec = FontDecryptor()

    def test_pua_check(self):
        self.assertTrue(self.dec.is_pua(chr(0xE3E8)))
        self.assertTrue(self.dec.is_pua(chr(0xF8FF)))
        self.assertFalse(self.dec.is_pua("中"))
        self.assertFalse(self.dec.is_pua("A"))

    def test_decode_sample_sentence(self):
        # “宗判决？”
        # =门, =的, =下, =来, =了
        sample = "“宗\ue4e3\ue4f3判决\ue531\ue4fa\ue436？”"
        decoded = self.dec.decode_text(sample)
        self.assertEqual(decoded, "“宗门的判决下来了？”")

    def test_html_cleaning(self):
        html = "<p>第一段内容</p><p>第二段内容包含<span>测试</span></p>"
        res = decode_chapter(html)
        expected = "　　第一段内容\n\n　　第二段内容包含测试"
        self.assertEqual(res, expected)

if __name__ == "__main__":
    unittest.main()

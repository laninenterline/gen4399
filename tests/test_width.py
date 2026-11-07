"""终端显示宽度工具测试。"""

import unittest

from gen4399._width import display_width, pad


class TestDisplayWidth(unittest.TestCase):
    def test_ascii(self):
        self.assertEqual(display_width("abc"), 3)

    def test_cjk(self):
        self.assertEqual(display_width("真实姓名"), 8)

    def test_mixed(self):
        self.assertEqual(display_width("QQ号"), 4)


class TestPad(unittest.TestCase):
    def test_left(self):
        self.assertEqual(display_width(pad("QQ", 12)), 12)
        self.assertEqual(pad("QQ", 4), "QQ  ")

    def test_right(self):
        self.assertTrue(pad("QQ", 4, align="right").endswith("QQ"))

    def test_center(self):
        self.assertEqual(display_width(pad("张三", 9, align="center")), 9)

    def test_never_truncates(self):
        self.assertEqual(pad("真实姓名", 2), "真实姓名")


if __name__ == "__main__":
    unittest.main()

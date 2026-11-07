"""身份信息文件（姓名|身份证号[|QQ]）解析与加载测试。"""

import tempfile
import unittest
from pathlib import Path

from gen4399 import load_profiles, parse_profile_line
from gen4399.forms import InvalidProfileError

VALID_ID = "460206194611192084"
VALID_ID_2 = "440106198101010155"


class TestParseProfileLine(unittest.TestCase):
    def test_two_columns(self):
        profile = parse_profile_line("张三|" + VALID_ID)
        self.assertEqual(profile.realname, "张三")
        self.assertEqual(profile.idcard, VALID_ID)
        self.assertIsNone(profile.qq)

    def test_three_columns(self):
        profile = parse_profile_line("张三|" + VALID_ID + "|123456789")
        self.assertEqual(profile.qq, "123456789")

    def test_whitespace_around_fields(self):
        profile = parse_profile_line("  张三 | " + VALID_ID + " | 123456789 ")
        self.assertEqual(profile.realname, "张三")
        self.assertEqual(profile.idcard, VALID_ID)
        self.assertEqual(profile.qq, "123456789")

    def test_fullwidth_pipe(self):
        profile = parse_profile_line("张三｜" + VALID_ID)
        self.assertEqual(profile.realname, "张三")

    def test_empty_third_column_means_no_qq(self):
        self.assertIsNone(parse_profile_line("张三|" + VALID_ID + "|").qq)
        self.assertIsNone(parse_profile_line("张三|" + VALID_ID + "|  ").qq)

    def test_bom_is_tolerated(self):
        profile = parse_profile_line("\ufeff张三|" + VALID_ID)
        self.assertEqual(profile.realname, "张三")

    def test_missing_separator(self):
        with self.assertRaises(InvalidProfileError) as ctx:
            parse_profile_line("张三" + VALID_ID)
        self.assertIn("格式错误", str(ctx.exception))

    def test_too_many_columns(self):
        with self.assertRaises(InvalidProfileError) as ctx:
            parse_profile_line("张三|" + VALID_ID + "|123|extra")
        self.assertIn("字段过多", str(ctx.exception))

    def test_bad_realname(self):
        with self.assertRaises(InvalidProfileError):
            parse_profile_line("张|" + VALID_ID)

    def test_bad_idcard(self):
        with self.assertRaises(InvalidProfileError) as ctx:
            parse_profile_line("张三|110101199001011234")
        self.assertIn("校验码", str(ctx.exception))

    def test_line_number_in_message(self):
        with self.assertRaises(InvalidProfileError) as ctx:
            parse_profile_line("坏行", line_number=7)
        self.assertIn("第 7 行", str(ctx.exception))

    def test_type_error(self):
        with self.assertRaises(TypeError):
            parse_profile_line(None)  # type: ignore[arg-type]


class TestLoadProfiles(unittest.TestCase):
    def _write(self, tmpdir: str, content: str, name: str = "ids.txt") -> Path:
        path = Path(tmpdir) / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_load_with_comments_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                "# 注释\n\n张三|" + VALID_ID + "\n"
                "李四|" + VALID_ID_2 + "|123456789\n\n",
            )
            profiles = load_profiles(path)
        self.assertEqual(len(profiles), 2)
        self.assertEqual(profiles[0].realname, "张三")
        self.assertEqual(profiles[1].qq, "123456789")

    def test_utf8_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ids.txt"
            path.write_bytes(
                b"\xef\xbb\xbf" + ("张三|" + VALID_ID + "\n").encode("utf-8")
            )
            profiles = load_profiles(path)
        self.assertEqual(profiles[0].realname, "张三")

    def test_invalid_line_reports_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp, "张三|" + VALID_ID + "\n坏行\n", name="bad.txt"
            )
            with self.assertRaises(InvalidProfileError) as ctx:
                load_profiles(path)
        self.assertIn("第 2 行", str(ctx.exception))

    def test_empty_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "# 只有注释\n\n", name="empty.txt")
            with self.assertRaises(InvalidProfileError):
                load_profiles(path)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_profiles("/no/such/file/ids.txt")


if __name__ == "__main__":
    unittest.main()

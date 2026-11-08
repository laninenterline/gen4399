"""分层命名空间（gen4399.constants / gen4399.captcha 等）的一致性测试。"""

import unittest

import gen4399
import gen4399.captcha as captcha_ns
import gen4399.constants as constants_ns
import gen4399.forms as forms_ns
import gen4399.identity as identity_ns
import gen4399.remote as remote_ns
import gen4399.submit as submit_ns


class TestTopLevelApi(unittest.TestCase):
    """顶层公共契约：``__all__`` 是核心集，其余名字仍可用但不再对外承诺。"""

    def test_all_resolves(self):
        for name in gen4399.__all__:
            self.assertTrue(hasattr(gen4399, name), name)

    def test_all_has_no_duplicates(self):
        self.assertEqual(len(gen4399.__all__), len(set(gen4399.__all__)))

    def test_core_names_present(self):
        core = {
            "generate", "validate", "validate_username",
            "RegistrationProfile", "prepare_registration",
            "submit_registration", "SubmitResult",
            "check_username", "TransportOptions", "ProxyPool",
            "random_user_agent", "__version__",
        }
        self.assertTrue(core <= set(gen4399.__all__))

    def test_advanced_names_still_importable(self):
        # 不在 __all__ 里，但显式导入照常工作（2.x 兼容）
        from gen4399 import MIN_LENGTH, prompt_captcha_solver  # noqa: F401

        self.assertIsInstance(MIN_LENGTH, int)
        self.assertTrue(callable(prompt_captcha_solver))

    def test_star_import_matches_all(self):
        ns: dict = {}
        exec("from gen4399 import *", ns)  # noqa: S102 - 测试用
        exported = {k for k in ns if not k.startswith("__")}
        self.assertEqual(exported, {n for n in gen4399.__all__ if not n.startswith("__")})


class TestNamespaceModules(unittest.TestCase):
    def test_all_names_resolvable(self):
        for module in (
            constants_ns, captcha_ns, forms_ns, identity_ns,
            remote_ns, submit_ns,
        ):
            for name in getattr(module, "__all__", []):
                self.assertTrue(
                    hasattr(module, name), f"{module.__name__}.{name}"
                )

    def test_constants_match_top_level(self):
        """顶层也导出的常量必须是同一个对象；其余只保证在 constants 里可取。"""
        for name in constants_ns.__all__:
            if hasattr(gen4399, name):
                self.assertIs(
                    getattr(constants_ns, name), getattr(gen4399, name), name
                )
            else:
                self.assertTrue(hasattr(constants_ns, name), name)

    def test_captcha_aliases_private_module(self):
        from gen4399 import _captcha, captcha_web

        for name in captcha_ns.__all__:
            source = (
                captcha_web
                if name in (
                    "learning_captcha_solver", "WebCaptchaBank",
                    "segment_glyphs", "benchmark",
                )
                else _captcha
            )
            self.assertIs(getattr(captcha_ns, name), getattr(source, name))

    def test_submit_result_reachable_from_submit_namespace(self):
        self.assertIs(submit_ns.SubmitResult, gen4399.SubmitResult)
        self.assertIs(
            submit_ns.submit_registration, gen4399.submit_registration
        )

    def test_unified_drop_fields_is_shared(self):
        self.assertIs(
            constants_ns.UNIFIED_DROP_FIELDS, submit_ns.UNIFIED_DROP_FIELDS
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

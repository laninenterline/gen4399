"""gen4399.configure / current_config 的测试。"""

import unittest

import gen4399
from gen4399 import submit as submit_module


class TestConfigure(unittest.TestCase):
    def tearDown(self):
        gen4399.configure(unified_send_realname=True)

    def test_default_is_true(self):
        self.assertTrue(gen4399.current_config()["unified_send_realname"])

    def test_toggle_off(self):
        config = gen4399.configure(unified_send_realname=False)
        self.assertFalse(config["unified_send_realname"])
        self.assertFalse(submit_module.UNIFIED_SEND_REALNAME)

    def test_toggle_back_on(self):
        gen4399.configure(unified_send_realname=False)
        gen4399.configure(unified_send_realname=True)
        self.assertTrue(submit_module.UNIFIED_SEND_REALNAME)

    def test_none_leaves_unchanged(self):
        gen4399.configure(unified_send_realname=False)
        config = gen4399.configure()
        self.assertFalse(config["unified_send_realname"])

    def test_affects_payload(self):
        from gen4399 import RegistrationProfile, prepare_registration
        from gen4399.submit import submit_registration

        profile = RegistrationProfile("王五", "110105198803121893")
        bundle = prepare_registration(profile, path="unified", verify_username=False)

        gen4399.configure(unified_send_realname=False)
        without_realname = submit_registration(bundle, dry_run=True)
        self.assertEqual(len(without_realname.encrypted_fields), 2)

        gen4399.configure(unified_send_realname=True)
        with_realname = submit_registration(bundle, dry_run=True)
        self.assertEqual(len(with_realname.encrypted_fields), 4)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

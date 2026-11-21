"""Deployment choice: single stays loopback; multi will not start without a token."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from ctx import config, ui


class ConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.addCleanup(self._clear_env)

    def _clear_env(self) -> None:
        for key in (config.ENV_DEPLOYMENT, config.ENV_BIND, config.ENV_PORT, config.ENV_TOKEN):
            os.environ.pop(key, None)

    def test_local_ui_stays_single_even_if_the_file_says_multi(self) -> None:
        chosen = config.choose(self.root, "multi")
        self.assertTrue(chosen["access_token"])
        live = config.effective(self.root, deploy=False)
        self.assertEqual(live["deployment"], "single")
        self.assertEqual(live["bind"], "127.0.0.1")

    def test_deploy_requires_a_token_and_binds_open(self) -> None:
        with self.assertRaises(config.ConfigError):
            config.effective(self.root, deploy=True)
        config.choose(self.root, "multi")
        live = config.effective(self.root, deploy=True)
        self.assertEqual(live["deployment"], "multi")
        self.assertEqual(live["bind"], "0.0.0.0")
        self.assertTrue(live["access_token"])

    def test_single_refuses_a_public_bind(self) -> None:
        with self.assertRaises(SystemExit):
            ui.make_server(self.root, "0.0.0.0", 0)

    def test_public_view_hides_the_token(self) -> None:
        config.choose(self.root, "multi")
        view = config.public_view(self.root)
        self.assertNotIn("access_token", view)
        self.assertTrue(view["token_set"])
        self.assertIn("access_token", (self.root / "stead.json").read_text(encoding="utf-8"))

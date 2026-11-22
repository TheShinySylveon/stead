"""Model drafts and eval checks. No live network."""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from ctx import cli, config, db, factory, frontmatter, models


def _root() -> Path:
    base = Path(tempfile.mkdtemp())
    root = base / "repo"
    for sub in ("context/projects", "factories/weekly-project-status/prompts",
                "factories/weekly-project-status/evals"):
        (root / sub).mkdir(parents=True)
    meta = {"id": "project-demo", "type": "project", "title": "Demo",
            "created": "2026-11-21", "updated": "2026-11-21", "status": "active"}
    (root / "context/projects/demo.md").write_text(
        frontmatter.dumps(meta, "# Demo\n"), encoding="utf-8")
    (root / "factories/weekly-project-status/FACTORY.md").write_text("# F\n", encoding="utf-8")
    (root / "factories/weekly-project-status/prompts/v1.md").write_text(
        "Draft a status.\n", encoding="utf-8")
    (root / "factories/weekly-project-status/evals/eval-ok.json").write_text(
        json.dumps({"id": "eval-ok", "factory": "weekly-project-status",
                    "title": "Ok", "input": "a bundle", "pass_criteria": "mentions the project"}),
        encoding="utf-8")
    return root


class ModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.addCleanup(lambda: __import__("os").environ.pop(models.ENV_KEY, None))

    def test_public_view_hides_the_key_and_deployment_keeps_it(self) -> None:
        shown = models.set_model(self.root, provider="openai", name="gpt-test", api_key="sk-secret")
        self.assertNotIn("api_key", shown)
        self.assertTrue(shown["key_set"])
        self.assertNotIn("sk-secret", json.dumps(shown))
        config.choose(self.root, "single")
        raw = (self.root / "stead.json").read_text(encoding="utf-8")
        self.assertIn("sk-secret", raw)
        self.assertNotIn("sk-secret", json.dumps(models.public_model(self.root)))

    def test_model_test_makes_one_live_call(self) -> None:
        models.set_model(self.root, provider="ollama", name="llama3.2")
        calls = []

        def transport(body, settings):
            calls.append(body)
            return {"choices": [{"message": {"content": "ok"}}]}

        result = models.test_model(self.root, transport=transport)
        self.assertTrue(result["ok"])
        self.assertEqual(result["reply"], "ok")
        self.assertEqual(result["name"], "llama3.2")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("api_key", result)

    def test_model_list_reads_ids(self) -> None:
        models.set_model(self.root, provider="ollama", name="llama3.2")

        def transport(url, settings):
            self.assertTrue(url.endswith("/models"))
            return {"data": [{"id": "qwen2.5"}, {"id": "llama3.2"}]}

        result = models.list_models(self.root, transport=transport)
        self.assertEqual(result["models"], ["llama3.2", "qwen2.5"])

    def test_model_test_without_config_fails(self) -> None:
        with self.assertRaises(models.ModelError):
            models.test_model(self.root)

    def test_openai_requires_a_key_and_ollama_does_not(self) -> None:
        models.set_model(self.root, provider="openai", name="gpt-test")
        with self.assertRaises(models.ModelError):
            models.resolve(self.root)
        models.set_model(self.root, provider="ollama", name="llama3.2")
        resolved = models.resolve(self.root)
        self.assertEqual(resolved["base_url"], "http://127.0.0.1:11434/v1")
        self.assertEqual(resolved["api_key"], "")

    def test_changing_the_endpoint_host_drops_the_stored_key(self) -> None:
        models.set_model(self.root, provider="openai", name="gpt-test",
                         api_key="sk-secret")
        # Same host, new model name: the key stays.
        models.set_model(self.root, provider="openai", name="gpt-other")
        self.assertEqual(models.resolve(self.root)["api_key"], "sk-secret")
        # Different host without a new key: the stored key must not ride along.
        models.set_model(self.root, provider="custom", name="elsewhere",
                         base_url="https://attacker.example/v1")
        raw = json.loads((self.root / "stead.json").read_text(encoding="utf-8"))
        self.assertNotIn("sk-secret", json.dumps(raw))
        self.assertNotIn("api_key", raw.get("model", {}))
        # A new key explicitly given for the new host is stored.
        models.set_model(self.root, provider="custom", name="elsewhere",
                         base_url="https://attacker.example/v1", api_key="sk-new")
        self.assertEqual(models.resolve(self.root)["api_key"], "sk-new")

    def test_usage_is_read_from_the_provider(self) -> None:
        models.set_model(self.root, provider="openai", name="gpt-test", api_key="k")
        settings = models.resolve(self.root)
        usage: dict = {}
        models.complete(
            "hello", settings, usage=usage,
            transport=lambda _body, _s: {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3}})
        self.assertEqual(usage["prompt_tokens"], 7)
        self.assertEqual(usage["completion_tokens"], 3)
        self.assertFalse(usage.get("estimated", False))

    def test_missing_usage_is_estimated_from_characters(self) -> None:
        models.set_model(self.root, provider="openai", name="gpt-test", api_key="k")
        settings = models.resolve(self.root)
        usage: dict = {}
        models.complete(
            "x" * 400, settings, usage=usage,
            transport=lambda _body, _s: {"choices": [{"message": {"content": "y" * 40}}]})
        self.assertEqual(usage["prompt_tokens"], 100)
        self.assertEqual(usage["completion_tokens"], 10)
        self.assertTrue(usage["estimated"])

    def test_a_reviewer_model_falls_back_to_the_builder_and_can_be_set(self) -> None:
        models.set_model(self.root, provider="ollama", name="llama3.2")
        self.assertEqual(models.resolve(self.root, "reviewer")["name"], "llama3.2")
        models.set_model(self.root, provider="openai", name="gpt-review",
                         api_key="k", block="reviewer")
        self.assertEqual(models.resolve(self.root, "reviewer")["name"], "gpt-review")
        self.assertEqual(models.resolve(self.root)["name"], "llama3.2")

    def test_call_timeout_defaults_to_300_and_can_be_raised(self) -> None:
        models.set_model(self.root, provider="ollama", name="llama3.2")
        self.assertEqual(models.resolve(self.root)["call_timeout"], 300)
        self.assertEqual(models.public_model(self.root)["call_timeout"], 300)
        models.set_model(self.root, provider="ollama", name="llama3.2",
                         call_timeout=1200)
        self.assertEqual(models.resolve(self.root)["call_timeout"], 1200)
        # Re-saving the model without the option keeps the configured value.
        models.set_model(self.root, provider="ollama", name="qwen")
        self.assertEqual(models.resolve(self.root)["call_timeout"], 1200)

    def test_drafting_uses_the_configured_call_timeout(self) -> None:
        models.set_model(self.root, provider="ollama", name="llama3.2",
                         call_timeout=900)
        seen = []

        def fake_complete(_prompt, _settings, **kwargs):
            seen.append(kwargs.get("timeout"))
            return "a draft"

        with mock.patch("ctx.models.complete", side_effect=fake_complete):
            models.draft(self.root, "draft this")
            models.draft(self.root, "draft this", timeout=45)
        self.assertEqual(seen, [900, 45])

    def test_spec_draft_timeout_is_a_clean_message_not_a_traceback(self) -> None:
        models.set_model(self.root, provider="ollama", name="llama3.2",
                         call_timeout=600)
        with mock.patch("ctx.spec.draft_spec", side_effect=TimeoutError("timed out")):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["--root", str(self.root), "spec", "draft",
                          "--contribution", "contribution-x"])
        message = str(caught.exception.code)
        self.assertIn("did not reply within 600s", message)
        self.assertIn("spec draft stopped", message)
        self.assertIn("--call-timeout", message)

    def test_call_timeout_out_of_range_is_refused(self) -> None:
        for bad in (5, 10_000):
            with self.assertRaises(models.ModelError):
                models.set_model(self.root, provider="ollama", name="llama3.2",
                                 call_timeout=bad)

    def test_build_timeout_is_a_clean_message_not_a_traceback(self) -> None:
        models.set_model(self.root, provider="ollama", name="llama3.2",
                         call_timeout=450)
        with mock.patch("ctx.agent.build", side_effect=TimeoutError("timed out")):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["--root", str(self.root), "build",
                          "--contribution", "contribution-x"])
        message = str(caught.exception.code)
        self.assertIn("did not reply within 450s", message)
        self.assertIn("--call-timeout", message)
        self.assertIn("--retry", message)

    def test_prices_are_stored_for_a_cost_budget(self) -> None:
        models.set_model(self.root, provider="openai", name="gpt-test",
                         api_key="k", input_price=2.5, output_price=10)
        resolved = models.resolve(self.root)
        self.assertEqual(resolved["input_price_per_mtok"], 2.5)
        self.assertEqual(resolved["output_price_per_mtok"], 10.0)

    def test_changing_the_endpoint_port_or_scheme_drops_the_stored_key(self) -> None:
        def stored_key() -> str:
            raw = json.loads((self.root / "stead.json").read_text(encoding="utf-8"))
            return raw.get("model", {}).get("api_key", "")

        models.set_model(self.root, provider="custom", name="m",
                         base_url="https://api.example.com/v1", api_key="sk-secret")
        self.assertEqual(stored_key(), "sk-secret")
        models.set_model(self.root, provider="custom", name="m",
                         base_url="https://api.example.com:8443/v1")
        self.assertEqual(stored_key(), "")
        models.set_model(self.root, provider="custom", name="m",
                         base_url="https://api.example.com/v1", api_key="sk-secret")
        models.set_model(self.root, provider="custom", name="m",
                         base_url="http://api.example.com/v1")
        self.assertEqual(stored_key(), "")

    def test_complete_uses_the_transport_and_hides_the_key_on_failure(self) -> None:
        settings = {"name": "gpt-test", "base_url": "https://example.test/v1", "api_key": "sk-secret"}
        seen = {}

        def transport(body, got):
            seen["model"] = body["model"]
            seen["key"] = got["api_key"]
            return {"choices": [{"message": {"content": [{"type": "text", "text": "hello draft"}]}}]}

        self.assertEqual(models.complete("prompt", settings, transport=transport), "hello draft")
        self.assertEqual(seen["model"], "gpt-test")
        self.assertEqual(seen["key"], "sk-secret")

        def boom(req, timeout=None):
            self.assertEqual(req.get_header("Authorization"), "Bearer sk-secret")
            raise urllib.error.URLError("timed out")

        with mock.patch("urllib.request.urlopen", boom):
            with self.assertRaises(models.ModelError) as caught:
                models.complete("prompt", settings)
        self.assertNotIn("sk-secret", str(caught.exception))

    def test_anthropic_and_grok_use_their_own_endpoints(self) -> None:
        models.set_model(self.root, provider="anthropic", name="claude-test", api_key="sk-ant")
        settings = models.resolve(self.root)
        url, headers, body = models._request(settings, "draft this", 0.2)
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(headers["x-api-key"], "sk-ant")
        self.assertNotIn("Authorization", headers)
        self.assertEqual(body["max_tokens"], models.ANTHROPIC_MAX_TOKENS)
        self.assertEqual(
            models.complete("draft this", settings, transport=lambda _body, _settings: {
                "content": [{"type": "text", "text": "claude draft"}],
            }),
            "claude draft",
        )

        models.set_model(self.root, provider="grok", name="grok-test", api_key="xai-secret")
        settings = models.resolve(self.root)
        url, headers, body = models._request(settings, "draft this", 0.2)
        self.assertEqual(url, "https://api.x.ai/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer xai-secret")
        self.assertEqual(body["model"], "grok-test")
        self.assertNotIn("xai-secret", json.dumps(models.public_model(self.root)))

        def boom(req, timeout=None):
            self.assertEqual(req.get_header("X-api-key"), "sk-ant")
            self.assertIsNone(req.get_header("Authorization"))
            raise urllib.error.URLError("timed out")

        anthropic = {
            "provider": "anthropic", "name": "claude-test",
            "base_url": "https://api.anthropic.com/v1", "api_key": "sk-ant",
        }
        with mock.patch("urllib.request.urlopen", boom):
            with self.assertRaises(models.ModelError) as caught:
                models.complete("draft this", anthropic)
        self.assertNotIn("sk-ant", str(caught.exception))

    def test_structured_output_uses_the_json_schema_form(self) -> None:
        from ctx.agent import _ACTION_RESPONSE_FORMAT
        settings = {"provider": "custom", "name": "lfm3-1.7b",
                    "base_url": "http://localhost:1234/v1", "api_key": ""}
        url, headers, body = models._request(
            settings, "hi", 0.2, response_format=_ACTION_RESPONSE_FORMAT)
        # LM Studio enforces `json_schema`/`text`, not `json_object`.
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertIn("json_schema", body["response_format"])
        # Anthropic gets no response_format (it uses a different API).
        anth = {"provider": "anthropic", "name": "c", "base_url": "https://api.anthropic.com/v1", "api_key": "k"}
        _, _, abody = models._request(anth, "hi", 0.2, response_format=_ACTION_RESPONSE_FORMAT)
        self.assertNotIn("response_format", abody)

    def test_action_schema_declares_every_field_the_loop_reads(self) -> None:
        from ctx.agent import _ACTION_FIELDS, _ACTION_RESPONSE_FORMAT
        schema = _ACTION_RESPONSE_FORMAT["json_schema"]["schema"]
        declared = set(schema["properties"])
        missing = _ACTION_FIELDS - declared
        self.assertFalse(missing, f"undeclared action fields: {missing}")
        # additionalProperties is explicit, so a strict server (llama.cpp
        # defaults it to false) never drops a declared field.
        self.assertIn("additionalProperties", schema)

    def test_custom_url_must_be_http(self) -> None:
        with self.assertRaises(models.ModelError):
            models.set_model(self.root, provider="custom", name="local", base_url="file:///tmp/model")

    def test_generate_writes_a_draft_and_does_not_open_the_network(self) -> None:
        root = _root()
        self.addCleanup(lambda: __import__("shutil").rmtree(root.parent, ignore_errors=True))
        db.init_db(root)
        models.set_model(root, provider="ollama", name="llama3.2")

        def fake_draft(_root, prompt):
            self.assertIn("Draft a status.", prompt)
            return "Status draft.\n"

        with mock.patch("ctx.models.draft", fake_draft), \
             mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            self.assertEqual(cli.cmd_factory_run(root, "weekly-project-status", "demo", generate=True), 0)
        drafts = list((root / "factories/weekly-project-status/runs").glob("*/output.md"))
        self.assertEqual(len(drafts), 1)
        self.assertIn("Status draft.", drafts[0].read_text(encoding="utf-8"))
        run_json = json.loads((drafts[0].parent / "run.json").read_text(encoding="utf-8"))
        self.assertNotIn("api_key", run_json)
        self.assertEqual(run_json["generated"], "model")

    def test_shipped_evals_and_a_judge_result(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        checked = models.check_eval_files(repo)
        self.assertTrue(checked["ok"], checked["problems"])
        self.assertGreaterEqual(checked["cases"], 12)

        root = _root()
        self.addCleanup(lambda: __import__("shutil").rmtree(root.parent, ignore_errors=True))
        models.set_model(root, provider="ollama", name="llama3.2")
        draft = root / "draft.md"
        draft.write_text("The project is fine.\n", encoding="utf-8")

        def transport(_body, settings):
            self.assertNotIn("api_key", json.dumps({k: settings[k] for k in settings if k != "api_key"}))
            return {"choices": [{"message": {"content": "verdict: pass\nreason: it mentions the project"}}]}

        judged = models.judge(root, "weekly-project-status", "eval-ok", str(draft), transport=transport)
        self.assertEqual(judged["verdict"], "pass")
        recorded = (root / judged["path"]).read_text(encoding="utf-8")
        self.assertNotIn("api_key", recorded)
        self.assertIn("pass", recorded)

    def test_write_output_does_not_execute_the_draft(self) -> None:
        root = _root()
        self.addCleanup(lambda: __import__("shutil").rmtree(root.parent, ignore_errors=True))
        db.init_db(root)
        info = factory.assemble(root, "weekly-project-status", "demo")
        updated = factory.write_output(root, info, "rm -rf /\n", source="model")
        self.assertTrue((root / updated["output_path"]).is_file())
        self.assertIn("Draft only", updated["note"])

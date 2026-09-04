"""Repository-level checks that do not require a Home Assistant install."""

from __future__ import annotations

import json
from pathlib import Path
import re
import struct
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "custom_components"
DOMAIN = "australian_fire_watch"
COMPONENT = COMPONENTS / DOMAIN


class _HomeAssistantLoader(yaml.SafeLoader):
    """Parse Home Assistant YAML while rejecting duplicate mapping keys."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False):
        keys = [
            key.value for key, _value in node.value if isinstance(key, yaml.ScalarNode)
        ]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ValueError(f"duplicate YAML keys {duplicates} at {node.start_mark}")
        return super().construct_mapping(node, deep=deep)


_HomeAssistantLoader.add_constructor(
    "!input", lambda loader, node: {"!input": loader.construct_scalar(node)}
)


class PackagingTests(unittest.TestCase):
    """Guard the files HACS and Home Assistant expect in a release."""

    def test_repository_contains_one_integration(self) -> None:
        integrations = sorted(
            path.name
            for path in COMPONENTS.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        )
        self.assertEqual([DOMAIN], integrations)

    def test_legacy_namespace_is_not_published(self) -> None:
        excluded_parts = {".git", ".ruff_cache", "__pycache__"}
        text_suffixes = {
            ".html",
            ".js",
            ".json",
            ".md",
            ".py",
            ".toml",
            ".txt",
            ".yaml",
            ".yml",
        }
        legacy_markers = (
            "nsw" + "_fire_watch",
            "nsw" + "-fire-watch",
            "NSW" + "_FIRE_WATCH",
            "NSW" + " Fire Watch",
        )

        for path in ROOT.rglob("*"):
            if excluded_parts.intersection(path.parts):
                continue
            relative_path = str(path.relative_to(ROOT))
            for marker in legacy_markers:
                with self.subTest(path=relative_path, marker=marker):
                    self.assertNotIn(marker, relative_path)
            if not path.is_file() or path.suffix.lower() not in text_suffixes:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for marker in legacy_markers:
                with self.subTest(path=relative_path, marker=marker):
                    self.assertNotIn(marker, text)

    def test_hacs_manifest(self) -> None:
        manifest = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
        self.assertEqual("Australian Fire Watch", manifest["name"])
        self.assertEqual("AU", manifest["country"])
        self.assertRegex(manifest["homeassistant"], r"^20\d{2}\.\d{1,2}\.\d+$")

    def test_integration_manifest(self) -> None:
        manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
        required = {
            "codeowners",
            "documentation",
            "domain",
            "issue_tracker",
            "name",
            "version",
        }
        self.assertFalse(required - manifest.keys())
        self.assertEqual(DOMAIN, manifest["domain"])
        self.assertTrue(manifest["codeowners"])
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+(?:[-+].+)?$")
        keys = list(manifest)
        self.assertEqual(["domain", "name"], keys[:2])
        self.assertEqual(sorted(keys[2:]), keys[2:])
        if manifest.get("config_flow"):
            self.assertTrue((COMPONENT / "config_flow.py").is_file())

        setup = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("async def async_migrate_entry", setup)

    def test_local_brand_icon(self) -> None:
        icon = COMPONENT / "brand" / "icon.png"
        data = icon.read_bytes()
        self.assertEqual(b"\x89PNG\r\n\x1a\n", data[:8])
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual((256, 256), (width, height))

    def test_native_home_assistant_map_contract(self) -> None:
        frontend = COMPONENT / "frontend"
        vendor = frontend / "vendor"
        assets = (
            "maplibre-gl-csp.js",
            "maplibre-gl-csp-worker.js",
            "maplibre-gl.css",
            "MAPLIBRE-LICENSE.txt",
        )
        for name in assets:
            with self.subTest(asset=name):
                path = vendor / name
                self.assertFalse(path.exists())

        panel = (frontend / "australian-fire-watch-panel.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("maplibre", panel.casefold())
        self.assertNotIn("openfreemap", panel.casefold())
        self.assertRegex(panel, r"\bMAP_DEFAULT_ZOOM\s*=\s*11\b")
        self.assertIn('type: "map"', panel)
        self.assertIn("helpers.createCardElement", panel)
        self.assertIn("window.loadCardHelpers", panel)
        self.assertIn("auto_fit: false", panel)
        self.assertIn("fit_zones: false", panel)
        self.assertIn("focus: true", panel)
        self.assertIn("focus: false", panel)
        self.assertIn("refreshBucket: Math.floor(Date.now() / 300_000)", panel)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Home Assistant's native map card", readme)
        self.assertIn("show_map: false", readme)

    def test_translations_are_valid_json(self) -> None:
        json_files = [COMPONENT / "manifest.json", COMPONENT / "strings.json"]
        translations = COMPONENT / "translations"
        if translations.is_dir():
            json_files.extend(sorted(translations.glob("*.json")))
        for path in json_files:
            with self.subTest(path=path.relative_to(ROOT)):
                json.loads(path.read_text(encoding="utf-8"))

    def test_alert_blueprint_matches_public_contract(self) -> None:
        blueprint = (
            ROOT
            / "blueprints"
            / "automation"
            / "hallyaus"
            / "australian_fire_watch_assigned_alerts.yaml"
        )
        text = blueprint.read_text(encoding="utf-8")
        for marker in (
            "event_type: australian_fire_watch_alert",
            "AUSTRALIAN_FIRE_WATCH_ACK|",
            "AUSTRALIAN_FIRE_WATCH_SNOOZE|",
            "notification_allowed",
            "alert_kind",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_yaml_is_parseable_and_has_no_duplicate_keys(self) -> None:
        yaml_files = sorted(ROOT.rglob("*.yaml")) + sorted(ROOT.rglob("*.yml"))
        self.assertTrue(yaml_files)
        for path in yaml_files:
            with self.subTest(path=path.relative_to(ROOT)):
                yaml.load(path.read_text(encoding="utf-8"), Loader=_HomeAssistantLoader)

    def test_public_docs_contain_safety_and_recovery_guidance(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for heading in (
            "Install with HACS",
            "Safety",
            "Migration from a legacy RFS dashboard",
            "Recovery and rollback",
            "Data sources and attribution",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, readme)
        self.assertIn("emergency app", readme)
        self.assertIn("000", readme)

    def test_repository_does_not_package_home_assistant_private_state(self) -> None:
        forbidden_names = {".storage", "secrets.yaml", "home-assistant_v2.db"}
        packaged = {path.name for path in ROOT.rglob("*")}
        self.assertFalse(forbidden_names & packaged)

        nabu_host = re.compile(r"https://[a-z0-9]+\.ui\.nabu\.casa", re.I)
        text_suffixes = {
            ".cfg",
            ".html",
            ".ini",
            ".js",
            ".json",
            ".md",
            ".py",
            ".toml",
            ".txt",
            ".yaml",
            ".yml",
        }
        public_text = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in ROOT.rglob("*")
            if path.is_file() and path.suffix.lower() in text_suffixes
        )
        self.assertIsNone(nabu_host.search(public_text))
        self.assertNotRegex(public_text, r"notify\.mobile_app_(?!<)")
        self.assertNotRegex(public_text, r"(?m)^\s*HA_TOKEN\s*=")
        self.assertNotRegex(
            public_text,
            r"\b(?:127\.0\.0\.1|10\.\d{1,3}(?:\.\d{1,3}){2}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b",
        )


if __name__ == "__main__":
    unittest.main()

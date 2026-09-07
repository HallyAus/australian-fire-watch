"""Exercise production startup ordering without requiring an HA OS process."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "custom_components/australian_fire_watch/__init__.py"


def functions(*names, **namespace):
    tree = ast.parse(SETUP.read_text(encoding="utf-8"))
    nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    nodes += [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert len(nodes) == len(names) + 1, names
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(SETUP), "exec"), namespace)
    return namespace


class FrontendBootstrapTests(unittest.IsolatedAsyncioTestCase):
    def namespace(self, register):
        return {
            "asyncio": asyncio, "DOMAIN": "australian_fire_watch",
            "DATA_ENTRIES": "entries", "DATA_PANEL": "panel_registered",
            "DATA_FRONTEND_MODULE": "frontend_module_registered",
            "DATA_PANEL_LOCK": "panel_lock", "DATA_MOBILE_LISTENER": "mobile_listener",
            "_async_register_panel": register,
        }

    async def test_frontend_registration_does_not_wait_for_external_feed(self):
        register = AsyncMock()
        namespace = self.namespace(register)

        class FirstRefreshReached(Exception):
            pass

        async def first_refresh():
            # A first refresh can stall or raise ConfigEntryNotReady. The file
            # route and loading metadata must already exist at this point.
            register.assert_awaited()
            raise FirstRefreshReached

        coordinator = SimpleNamespace(async_initialize=AsyncMock(),
                                      async_config_entry_first_refresh=first_refresh)
        namespace["FireWatchCoordinator"] = lambda hass, entry: coordinator
        loaded = functions("async_setup", "async_setup_entry", **namespace)
        hass = SimpleNamespace(data={})
        await loaded["async_setup"](hass, {})
        with self.assertRaises(FirstRefreshReached):
            await loaded["async_setup_entry"](hass, SimpleNamespace())

    async def test_domain_setup_makes_card_loadable_before_yaml_import(self):
        register = AsyncMock()
        loaded = functions("async_setup", **self.namespace(register))
        hass = SimpleNamespace(data={})
        assert await loaded["async_setup"](hass, {})
        register.assert_awaited_once_with(hass)


class ResourceRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def register(self, items, *, storage=True):
        class Storage:
            def __init__(self):
                self.async_get_info = AsyncMock()
                self.async_create_item = AsyncMock()
                self.async_update_item = AsyncMock()
                self.async_delete_item = AsyncMock()

            def async_items(self):
                return items

        resources = Storage() if storage else SimpleNamespace()
        loaded = functions(
            "_async_register_lovelace_resource",
            LOVELACE_DATA="lovelace", ResourceStorageCollection=Storage,
            FRONTEND_URL_PATH="/api/australian_fire_watch/frontend",
            PANEL_JS_FILE="australian-fire-watch-panel.js",
        )
        hass = SimpleNamespace(data={"lovelace": SimpleNamespace(resources=resources)})
        await loaded["_async_register_lovelace_resource"](hass, self.url)
        return resources

    url = "/api/australian_fire_watch/frontend/australian-fire-watch-panel.js?v=1.2.1"

    async def test_creates_module_without_manual_dashboard_edit(self):
        resources = await self.register([])
        resources.async_get_info.assert_awaited_once()
        resources.async_create_item.assert_awaited_once_with({"url": self.url, "res_type": "module"})

    async def test_existing_current_module_is_unchanged(self):
        resources = await self.register([{"id": "one", "url": self.url, "type": "module"}])
        resources.async_create_item.assert_not_awaited()
        resources.async_update_item.assert_not_awaited()
        resources.async_delete_item.assert_not_awaited()

    async def test_updates_own_version_and_removes_only_own_duplicate(self):
        resources = await self.register([
            {"id": "one", "url": self.url.replace("1.2.1", "1.2.0"), "type": "js"},
            {"id": "two", "url": self.url, "type": "module"},
            {"id": "unrelated", "url": "/local/another-card.js", "type": "module"},
        ])
        resources.async_create_item.assert_not_awaited()
        resources.async_update_item.assert_awaited_once_with("one", {"url": self.url, "res_type": "module"})
        resources.async_delete_item.assert_awaited_once_with("two")

    async def test_does_not_take_ownership_of_a_different_path(self):
        resources = await self.register([{"id": "other", "url": "/different" + self.url, "type": "module"}])
        resources.async_create_item.assert_awaited_once()
        resources.async_update_item.assert_not_awaited()
        resources.async_delete_item.assert_not_awaited()

    async def test_yaml_resources_remain_user_owned(self):
        await self.register([], storage=False)

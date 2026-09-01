from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ALLOWED_USERS", "1")

spec = importlib.util.spec_from_file_location(
    "guko_bot_server_sorting_under_test", ROOT / "telegram-bot" / "bot.py"
)
assert spec and spec.loader
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)


def sample_servers():
    return [
        {"id": "alpha", "name": "Alpha", "host": "192.0.2.1"},
        {"id": "bravo", "name": "Bravo", "host": "192.0.2.2"},
        {"id": "charlie", "name": "Charlie", "host": "192.0.2.3"},
    ]


def callback_data(markup):
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]


def callback_update(data: str, user_id: int = 1):
    query = SimpleNamespace(
        data=data,
        message=SimpleNamespace(chat_id=123),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=123),
        effective_message=query.message,
        callback_query=query,
    )
    return update, query


class ServerSortMarkupTest(unittest.TestCase):
    def test_main_server_list_has_sort_entry(self):
        with patch.object(bot, "load_inventory", return_value={"servers": sample_servers()}):
            markup = bot.main_menu_markup()

        entries = {
            (button.text, button.callback_data)
            for row in markup.inline_keyboard
            for button in row
        }
        self.assertIn(("↕️ 调整顺序", "sort:list"), entries)

    def test_sort_page_lists_each_server_in_inventory_order(self):
        markup = bot.server_sort_markup(sample_servers())
        rows = markup.inline_keyboard

        self.assertEqual([row[0].text for row in rows[:-1]], ["1. Alpha", "2. Bravo", "3. Charlie"])
        self.assertEqual([row[0].callback_data for row in rows[:-1]], ["sort:stay"] * 3)
        self.assertTrue(all(len(row) == 3 for row in rows[:-1]))
        self.assertEqual(rows[-1][0].text, "↩️ 返回服务器列表")
        self.assertEqual(rows[-1][0].callback_data, "act:list")
        self.assertFalse(any("保存" in button.text or "取消" in button.text for row in rows for button in row))

    def test_sort_page_boundary_arrows_cannot_request_a_move(self):
        rows = bot.server_sort_markup(sample_servers()).inline_keyboard

        self.assertEqual(rows[0][1].callback_data, "sort:stay")
        self.assertEqual(rows[0][2].callback_data, "sort:down:alpha")
        self.assertEqual(rows[1][1].callback_data, "sort:up:bravo")
        self.assertEqual(rows[1][2].callback_data, "sort:down:bravo")
        self.assertEqual(rows[2][1].callback_data, "sort:up:charlie")
        self.assertEqual(rows[2][2].callback_data, "sort:stay")

    def test_sort_callbacks_reuse_compact_server_id_and_fit_telegram_limit(self):
        long_id_server = {
            "id": "服务器-" + "very-long-identifier-" * 8,
            "name": "Long identifier",
            "host": "192.0.2.10",
        }
        servers = [sample_servers()[0], long_id_server, sample_servers()[2]]
        sid = bot.server_id(long_id_server)
        callbacks = callback_data(bot.server_sort_markup(servers))

        self.assertIn(f"sort:up:{sid}", callbacks)
        self.assertIn(f"sort:down:{sid}", callbacks)
        for data in callbacks:
            self.assertLessEqual(len(data.encode()), 64, data)


class ServerReorderTest(unittest.TestCase):
    def test_reorder_servers_moves_selected_server_up_without_mutating_input(self):
        servers = sample_servers()
        original = copy.deepcopy(servers)

        reordered = bot.reorder_servers(servers, "bravo", "up")

        self.assertEqual([server["id"] for server in reordered], ["bravo", "alpha", "charlie"])
        self.assertEqual(servers, original)

    def test_reorder_servers_moves_selected_server_down_without_mutating_input(self):
        servers = sample_servers()
        original = copy.deepcopy(servers)

        reordered = bot.reorder_servers(servers, "bravo", "down")

        self.assertEqual([server["id"] for server in reordered], ["alpha", "charlie", "bravo"])
        self.assertEqual(servers, original)

    def assert_persisted_move(self, sid: str, direction: str, expected_ids: list[str]):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory_path = root / "servers.json"
            inventory_path.write_text(
                json.dumps(
                    {
                        "updated_at": "2000-01-01T00:00:00+00:00",
                        "source": "test",
                        "servers": sample_servers(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            with patch.object(bot, "DATA_DIR", root), patch.object(bot, "SERVERS_JSON", inventory_path):
                moved = bot.move_server_by_id(sid, direction)

            saved = json.loads(inventory_path.read_text())
            self.assertTrue(moved)
            self.assertEqual([server["id"] for server in saved["servers"]], expected_ids)
            self.assertNotEqual(saved["updated_at"], "2000-01-01T00:00:00+00:00")
            datetime.fromisoformat(saved["updated_at"])

    def test_move_server_up_persists_order_and_updated_at(self):
        self.assert_persisted_move("bravo", "up", ["bravo", "alpha", "charlie"])

    def test_move_server_down_persists_order_and_updated_at(self):
        self.assert_persisted_move("bravo", "down", ["alpha", "charlie", "bravo"])

    def test_missing_server_does_not_write_inventory(self):
        inventory = {
            "updated_at": "unchanged",
            "servers": sample_servers(),
        }
        original = copy.deepcopy(inventory)
        with patch.object(bot, "load_inventory", return_value=inventory), patch.object(
            bot, "save_inventory"
        ) as save:
            moved = bot.move_server_by_id("missing", "up")

        self.assertFalse(moved)
        save.assert_not_called()
        self.assertEqual(inventory, original)

    def test_boundary_moves_do_not_write_inventory(self):
        for sid, direction in (("alpha", "up"), ("charlie", "down")):
            with self.subTest(sid=sid, direction=direction):
                inventory = {
                    "updated_at": "unchanged",
                    "servers": sample_servers(),
                }
                original = copy.deepcopy(inventory)
                with patch.object(bot, "load_inventory", return_value=inventory), patch.object(
                    bot, "save_inventory"
                ) as save:
                    moved = bot.move_server_by_id(sid, direction)

                self.assertFalse(moved)
                save.assert_not_called()
                self.assertEqual(inventory, original)


class ServerSortCallbackTest(unittest.TestCase):
    def test_admin_can_open_sort_page(self):
        async def exercise():
            update, query = callback_update("sort:list")
            servers = sample_servers()
            with patch.object(bot, "ALLOWED_USERS", {"1"}), patch.object(
                bot, "ADMIN_USERS", {"1"}
            ), patch.object(bot, "load_inventory", return_value={"servers": servers}):
                await bot.on_button(update, SimpleNamespace())

            query.edit_message_text.assert_awaited_once()
            call = query.edit_message_text.await_args
            self.assertIn("调整服务器顺序", call.args[0])
            self.assertEqual(
                [row[0].text for row in call.kwargs["reply_markup"].inline_keyboard[:-1]],
                ["1. Alpha", "2. Bravo", "3. Charlie"],
            )

        asyncio.run(exercise())

    def test_admin_move_callbacks_persist_and_refresh_sort_page(self):
        async def exercise(direction: str):
            update, query = callback_update(f"sort:{direction}:bravo")
            moved_servers = sample_servers()[::-1]
            move = MagicMock(return_value=True)
            with patch.object(bot, "ALLOWED_USERS", {"1"}), patch.object(
                bot, "ADMIN_USERS", {"1"}
            ), patch.object(bot, "move_server_by_id", move, create=True), patch.object(
                bot, "load_inventory", return_value={"servers": moved_servers}
            ):
                await bot.on_button(update, SimpleNamespace())

            move.assert_called_once_with("bravo", direction)
            query.edit_message_text.assert_awaited_once()
            rendered = query.edit_message_text.await_args.kwargs["reply_markup"]
            self.assertEqual(
                [row[0].text for row in rendered.inline_keyboard[:-1]],
                ["1. Charlie", "2. Bravo", "3. Alpha"],
            )

        for direction in ("up", "down"):
            with self.subTest(direction=direction):
                asyncio.run(exercise(direction))

    def test_stay_callback_does_not_move_reload_or_edit(self):
        async def exercise():
            update, query = callback_update("sort:stay")
            move = MagicMock()
            load = MagicMock()
            with patch.object(bot, "ALLOWED_USERS", {"1"}), patch.object(
                bot, "ADMIN_USERS", {"1"}
            ), patch.object(bot, "move_server_by_id", move, create=True), patch.object(
                bot, "load_inventory", load
            ):
                await bot.on_button(update, SimpleNamespace())

            move.assert_not_called()
            load.assert_not_called()
            query.edit_message_text.assert_not_awaited()

        asyncio.run(exercise())

    def test_non_admin_cannot_enter_or_operate_sorting(self):
        async def exercise(data: str):
            update, query = callback_update(data, user_id=2)
            move = MagicMock()
            with patch.object(bot, "ALLOWED_USERS", {"1", "2"}), patch.object(
                bot, "ADMIN_USERS", {"1"}
            ), patch.object(bot, "move_server_by_id", move, create=True):
                await bot.on_button(update, SimpleNamespace())

            move.assert_not_called()
            query.edit_message_text.assert_not_awaited()
            alerts = [call.args[0] for call in query.answer.await_args_list if call.args]
            self.assertIn("需要管理员权限", alerts)

        for data in ("sort:list", "sort:up:bravo", "sort:down:bravo", "sort:stay"):
            with self.subTest(data=data):
                asyncio.run(exercise(data))


if __name__ == "__main__":
    unittest.main()

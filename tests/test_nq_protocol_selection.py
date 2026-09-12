"""Protocol selection must not depend on optional inventory IPv6 metadata."""
import asyncio
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_full_features import bot, callbacks


SERVER = {"id": "test-node", "name": "Test", "host": "192.0.2.10", "ipv6_status": {"available": True, "reason": "已记录 IPv6 可用"}}


class NqProtocolSelectionTest(unittest.TestCase):
    def test_verified_menu_offers_both_regardless_of_inventory_metadata(self):
        for ipv6 in (None, "", "-", "None", "2001:db8::10"):
            with self.subTest(ipv6=ipv6):
                server = {**SERVER, "ipv6": ipv6}
                found = callbacks(bot.confirm_nq_markup(server, 15, ipv6_status=(True, 'IPv6 连通性检测通过')))
                self.assertIn("nqproto:test-node:15:4", found)
                self.assertIn("nqproto:test-node:15:46", found)
                self.assertIn("nqrun:test-node:15:4", found)

    def test_dual_stack_command_never_silently_forces_ipv4(self):
        for ipv6 in (None, "", "-", "None", "2001:db8::10"):
            with self.subTest(ipv6=ipv6):
                server = {**SERVER, "ipv6": ipv6}
                self.assertEqual(bot.nq_remote_ipv_arg(server, "46"), "")
                command = bot.nodequality_remote_command(server, 15, "46")
                self.assertTrue(command.rstrip().endswith('bash "$script"'))
                syntax = subprocess.run(["bash", "-n", "-c", command], capture_output=True, text=True)
                self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_ipv4_remains_default_and_is_explicit(self):
        self.assertEqual(bot.nq_remote_ipv_arg(SERVER, "4"), "-4")
        self.assertTrue(bot.nodequality_remote_command(SERVER).rstrip().endswith('bash "$script" -4'))
        buttons = [b for row in bot.confirm_nq_markup(SERVER).inline_keyboard for b in row]
        self.assertTrue(any(b.text == "✅ 仅 IPv4" for b in buttons))

    def test_menu_explains_live_ipv6_detection(self):
        text = bot.nq_menu_text(SERVER, 15, "46", (True, 'IPv6 连通性检测通过'))
        self.assertIn("检测通过", text)
        self.assertIn("IPv6", text)
        self.assertIn("IPv4 + IPv6", text)

    async def invoke(self, data):
        query = SimpleNamespace(data=data, message=SimpleNamespace(chat_id=1),
                                answer=AsyncMock(), edit_message_text=AsyncMock())
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(bot=object())
        with patch.object(bot, "guard", AsyncMock(return_value=True)), \
             patch.object(bot, "find_server_by_id", return_value=SERVER), \
             patch.object(bot, "launch_job", return_value="test-job") as launch, \
             patch.object(bot, "bot_task_started_notice", AsyncMock()):
            await bot.on_button(update, context)
            return query, launch

    def test_protocol_switch_and_item_selection_preserve_dual_stack(self):
        for callback in ("nqproto:test-node:15:46", "nqtoggle:test-node:2:46", "nqsel:test-node:15:46"):
            with self.subTest(callback=callback):
                query, launch = asyncio.run(self.invoke(callback))
                mask = callback.split(":")[2]
                markup = query.edit_message_text.call_args.kwargs["reply_markup"]
                self.assertIn(f"nqrun:test-node:{mask}:46", callbacks(markup))
                launch.assert_not_called()

    def test_start_passes_dual_stack_to_runner_and_history(self):
        query, launch = asyncio.run(self.invoke("nqrun:test-node:15:46"))
        self.assertEqual(launch.call_args.args[-2:], (15, "46"))
        self.assertEqual(launch.call_args.kwargs["ip_mode"], "IPv4 + IPv6")

    def test_legacy_start_still_defaults_ipv4(self):
        query, launch = asyncio.run(self.invoke("nqrun:test-node:15"))
        self.assertEqual(launch.call_args.args[-2:], (15, "4"))

    def test_empty_selection_still_cannot_start(self):
        query, launch = asyncio.run(self.invoke("nqrun:test-node:0:46"))
        launch.assert_not_called()
        self.assertIn("nqrun:test-node:0:46", callbacks(query.edit_message_text.call_args.kwargs["reply_markup"]))


if __name__ == "__main__":
    unittest.main()

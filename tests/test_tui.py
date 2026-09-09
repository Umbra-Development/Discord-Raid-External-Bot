import asyncio
from copy import deepcopy
import logging
import unittest
from typing import Any
from unittest.mock import patch

from textual.containers import Container, VerticalScroll
from textual.theme import BUILTIN_THEMES
from textual.widgets import Button, Input, RichLog, Static, Tab, Tabs, TextArea

from umbra_bot import config
from umbra_tui.app import UmbraTUI, format_log_record


class FakeBot:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.closed = asyncio.Event()
        self.command_prefix = "!"
        self.user = "Umbra Test Bot"
        self.latency = 0.042

    async def start(self, token: str) -> None:
        if token != "test-token":
            raise AssertionError("The TUI passed an unexpected token")
        self.started.set()
        await self.closed.wait()

    async def close(self) -> None:
        self.closed.set()

    def is_closed(self) -> bool:
        return self.closed.is_set()

    def is_ready(self) -> bool:
        return self.started.is_set() and not self.closed.is_set()


class TUITests(unittest.IsolatedAsyncioTestCase):
    async def test_umbra_is_default_without_replacing_builtin_themes(self) -> None:
        app = UmbraTUI(auto_start=False)
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()

            self.assertEqual(app.theme, "umbra")
            self.assertEqual(app.screen.styles.background.hex, "#17131B")
            self.assertIs(app.get_theme("nord"), BUILTIN_THEMES["nord"])
            self.assertIs(
                app.get_theme("textual-light"),
                BUILTIN_THEMES["textual-light"],
            )

            app.theme = "nord"
            await pilot.pause()
            self.assertEqual(app.theme, "nord")
            self.assertEqual(app.screen.styles.background.hex, "#2E3440")
            self.assertIsNotNone(app.get_theme("umbra"))

    async def test_layout_switches_between_mobile_tabs_and_desktop_panes(self) -> None:
        app = UmbraTUI(auto_start=False)
        async with app.run_test(size=(56, 40)) as pilot:
            await pilot.pause()
            console = app.query_one("#console-panel", Container)
            config_panel = app.query_one("#config-panel", VerticalScroll)
            controls = app.query_one("#controls-panel", VerticalScroll)
            tabs = app.query_one("#view-tabs", Tabs)
            controls_tab = app.query_one("#mobile-controls", Tab)

            for scrollable in (
                app.query_one("#console-log", RichLog),
                config_panel,
                controls,
                app.query_one("#config-pm", TextArea),
                app.query_one("#config-pingpm", TextArea),
            ):
                self.assertEqual(
                    scrollable.styles.scrollbar_size_horizontal, 0
                )
                self.assertEqual(scrollable.styles.scrollbar_size_vertical, 0)

            self.assertTrue(app.screen.has_class("-mobile"))
            self.assertTrue(tabs.display)
            self.assertTrue(controls_tab.display)
            self.assertTrue(console.display)
            self.assertFalse(config_panel.display)
            self.assertFalse(controls.display)

            app.action_show_config()
            await pilot.pause()
            self.assertFalse(console.display)
            self.assertTrue(config_panel.display)
            self.assertFalse(controls.display)

            config_panel.scroll_end(animate=False)
            await pilot.pause()
            self.assertGreater(config_panel.scroll_y, 0)

            app.action_show_controls()
            await pilot.pause()
            self.assertFalse(console.display)
            self.assertFalse(config_panel.display)
            self.assertTrue(controls.display)

            await pilot.resize_terminal(120, 40)
            await pilot.pause()
            self.assertTrue(app.screen.has_class("-desktop"))
            self.assertTrue(tabs.display)
            self.assertFalse(controls_tab.display)
            self.assertTrue(console.display)
            self.assertFalse(config_panel.display)
            self.assertTrue(controls.display)

            app.action_show_config()
            await pilot.pause()
            self.assertFalse(console.display)
            self.assertTrue(config_panel.display)
            self.assertTrue(controls.display)

    async def test_config_form_saves_validated_values_and_preserves_extras(self) -> None:
        original = {
            "token": "old-token",
            "basic_config": {
                "prefix": "!",
                "max_uses": 3,
                "wait_seconds": 180,
                "b_seconds": 900,
                "custom_basic_value": True,
            },
            "messages": {
                "pm": "old standard message",
                "pingpm": "old ping message",
            },
            "custom_top_level": {"keep": "me"},
        }
        saved: list[dict[str, Any]] = []

        def save_config(data: dict[str, Any]) -> None:
            saved.append(deepcopy(data))

        def reload_config() -> dict[str, Any]:
            active = saved[-1] if saved else original
            config.prefix = str(active["basic_config"]["prefix"])
            return active

        with (
            patch.object(config, "load_config", lambda: deepcopy(original)),
            patch.object(config, "save_config", save_config),
            patch.object(config, "reload_config", reload_config),
            patch.object(config, "prefix", "!"),
        ):
            app = UmbraTUI(auto_start=False)
            async with app.run_test(size=(120, 48)) as pilot:
                app.action_show_config()
                await pilot.pause()

                token = app.query_one("#config-token", Input)
                self.assertTrue(token.password)
                app.action_toggle_config_token()
                self.assertFalse(token.password)
                self.assertEqual(
                    app.query_one("#config-pm-count", Static).render().plain,
                    f"{len('old standard message')} / 2000",
                )
                self.assertEqual(
                    app.query_one("#config-pingpm-count", Static).render().plain,
                    f"{len('old ping message')} / 2000",
                )

                token.value = "new-token"
                app.query_one("#config-prefix", Input).value = "?"
                app.query_one("#config-max-uses", Input).value = "5"
                app.query_one("#config-wait-seconds", Input).value = "60"
                app.query_one("#config-block-seconds", Input).value = "600"
                app.query_one("#config-pm", TextArea).load_text("new standard")
                app.query_one("#config-pingpm", TextArea).load_text("new ping")

                app.query_one("#config-panel", VerticalScroll).scroll_end(
                    animate=False
                )
                await pilot.pause()
                await pilot.click("#config-save")
                await pilot.pause()

                self.assertEqual(len(saved), 1)
                self.assertEqual(saved[0]["token"], "new-token")
                self.assertEqual(
                    saved[0]["basic_config"],
                    {
                        "prefix": "?",
                        "max_uses": 5,
                        "wait_seconds": 60,
                        "b_seconds": 600,
                        "custom_basic_value": True,
                    },
                )
                self.assertEqual(
                    saved[0]["messages"],
                    {"pm": "new standard", "pingpm": "new ping"},
                )
                self.assertEqual(
                    saved[0]["custom_top_level"], {"keep": "me"}
                )
                status = app.query_one("#config-status", Static).render().plain
                self.assertEqual(status, "Settings saved successfully")

                standard_message = app.query_one("#config-pm", TextArea)
                standard_message.load_text("x" * 2001)
                await pilot.pause()
                self.assertEqual(
                    app.query_one("#config-pm-count", Static).render().plain,
                    "2001 / 2000",
                )
                app.action_save_config()
                self.assertEqual(len(saved), 1)
                status = app.query_one("#config-status", Static).render().plain
                self.assertEqual(
                    status,
                    "Standard message cannot exceed 2000 characters.",
                )

                for editor_id, counter_id in (
                    ("#config-pm", "#config-pm-count"),
                    ("#config-pingpm", "#config-pingpm-count"),
                ):
                    editor = app.query_one(editor_id, TextArea)
                    editor.load_text("")
                    editor.replace("x" * 2001, (0, 0), editor.document.end)
                    await pilot.pause()
                    self.assertEqual(len(editor.text), 2000)
                    self.assertEqual(
                        app.query_one(counter_id, Static).render().plain,
                        "2000 / 2000",
                    )

                standard_message.load_text("new standard")
                app.query_one("#config-pingpm", TextArea).load_text("new ping")
                app.query_one("#config-max-uses", Input).value = "0"
                app.action_save_config()
                self.assertEqual(len(saved), 1)
                status = app.query_one("#config-status", Static).render().plain
                self.assertEqual(status, "Maximum uses must be at least 1.")

    async def test_controls_manage_bot_lifecycle(self) -> None:
        created: list[FakeBot] = []

        def create_bot() -> FakeBot:
            bot = FakeBot()
            created.append(bot)
            return bot

        with (
            patch.object(config, "reload_config", lambda: {}),
            patch.object(config, "token", "test-token"),
        ):
            app = UmbraTUI(bot_factory=create_bot, auto_start=False)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.click("#start-bot")
                await pilot.pause()
                self.assertTrue(created[0].started.is_set())
                app._refresh_connection_status()
                status = app.query_one("#bot-status", Static).render().plain
                self.assertIn("RUNNING", status)
                self.assertTrue(app.query_one("#start-bot", Button).disabled)
                await pilot.pause()

                app.action_toggle_follow()
                self.assertFalse(
                    app.query_one("#console-log", RichLog).auto_scroll
                )
                app.action_toggle_follow()
                self.assertTrue(
                    app.query_one("#console-log", RichLog).auto_scroll
                )

                await pilot.click("#restart-bot")
                await pilot.pause(0.2)
                self.assertTrue(created[0].closed.is_set())
                self.assertEqual(len(created), 2)
                self.assertTrue(created[1].started.is_set())

                await pilot.click("#stop-bot")
                await pilot.pause()
                self.assertTrue(created[1].closed.is_set())
                status = app.query_one("#bot-status", Static).render().plain
                self.assertIn("STOPPED", status)

    async def test_unmount_closes_a_running_bot(self) -> None:
        bot = FakeBot()
        with (
            patch.object(config, "reload_config", lambda: {}),
            patch.object(config, "token", "test-token"),
        ):
            app = UmbraTUI(bot_factory=lambda: bot, auto_start=True)
            async with app.run_test(size=(100, 32)) as pilot:
                await pilot.pause()
                await bot.started.wait()

        self.assertTrue(bot.closed.is_set())

    def test_logging_preserves_ansi_color(self) -> None:
        record = logging.LogRecord(
            "discord.client",
            logging.WARNING,
            "",
            0,
            "\N{ESC}[32mcolored\N{ESC}[0m",
            (),
            None,
        )
        rendered = format_log_record(record)

        self.assertIn("colored", rendered.plain)
        self.assertTrue(
            any(str(span.style) == "color(2)" for span in rendered.spans)
        )


if __name__ == "__main__":
    unittest.main()

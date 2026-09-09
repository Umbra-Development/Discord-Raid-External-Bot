from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from umbra_gui import app as gui


SAMPLE_CONFIG = {
    "token": "test-token",
    "basic_config": {
        "prefix": "!",
        "max_uses": 3,
        "wait_seconds": 180,
        "b_seconds": 900,
    },
    "messages": {
        "pm": "standard",
        "pingpm": "notification",
    },
}


class GUIAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.load_patch = patch.object(
            gui, "load_config", lambda: deepcopy(SAMPLE_CONFIG)
        )
        cls.save_patch = patch.object(gui, "save_config")
        cls.load_patch.start()
        cls.saved_config = cls.save_patch.start()
        try:
            cls.app = gui.SettingsApp()
        except tk.TclError as error:
            cls.load_patch.stop()
            cls.save_patch.stop()
            raise unittest.SkipTest(f"Tk display is unavailable: {error}") from error
        cls.app._dismiss_splash()
        cls.app.update()

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "app") and cls.app.winfo_exists():
            cls.app.destroy()
        cls.save_patch.stop()
        cls.load_patch.stop()

    def setUp(self) -> None:
        self.saved_config.reset_mock()
        self.app._clear_console()
        self.app._append_console(
            "Umbra console ready. Start the bot to stream live output here.\n",
            tag="system",
        )
        self.app.console_state_var.set("Stopped")
        self.app.console_following = True
        self.app.console_follow_button.configure(text="Follow output: On")
        self.app._replace_text(self.app.pm_text, SAMPLE_CONFIG["messages"]["pm"])
        self.app._replace_text(
            self.app.pingpm_text,
            SAMPLE_CONFIG["messages"]["pingpm"],
        )

    def test_console_tab_and_message_limits(self) -> None:
        self.assertEqual(self.app.tabs.get(), "General")
        tab_selector = self.app.tabs._segmented_button
        self.assertEqual(tab_selector.get(), "General")
        self.assertEqual(
            [
                name
                for name, button in tab_selector._buttons_dict.items()
                if button.cget("fg_color") == tab_selector.cget("selected_color")
            ],
            ["General"],
        )
        self.app.tabs.set("Console")
        console_descendants = [self.app.console_host]
        for widget in console_descendants:
            console_descendants.extend(widget.winfo_children())
        self.assertFalse(any(isinstance(widget, tk.Text) for widget in console_descendants))
        self.assertEqual(self.app.general_form._scrollbar.winfo_manager(), "")
        self.assertEqual(self.app.messages_form._scrollbar.winfo_manager(), "")
        self.assertIn(
            "Umbra console ready",
            self.app.console_view.get_text(),
        )

        self.app._append_console("\x1b[31mERROR test output\x1b[0m\n")
        rendered = self.app.console_view.get_text()
        self.assertIn("ERROR test output", rendered)
        self.assertNotIn("\x1b", rendered)
        self.assertEqual(self.app.console_follow_button.cget("text_color"), "#ffffe7")
        self.assertEqual(self.app.console_clear_button.cget("text_color"), "#ffffe7")

        self.app.console_follow_button.invoke()
        self.assertFalse(self.app.console_following)
        self.assertEqual(
            self.app.console_follow_button.cget("text"), "Follow output: Off"
        )
        self.app.console_clear_button.invoke()
        self.assertEqual(self.app.console_view.get_text(), "")

        self.app.tabs.set("Messages")
        self.app.pm_text.replace_contents("")
        self.app.pm_text.insert("1.0", "x" * (gui.MAX_MESSAGE_LENGTH + 1))
        self.app.update()
        self.assertEqual(
            len(self.app.pm_text.get("1.0", "end-1c")),
            gui.MAX_MESSAGE_LENGTH,
        )
        self.assertEqual(self.app.message_count_label.cget("text"), "2000 / 2000")

        self.app._replace_text(
            self.app.pm_text,
            "x" * (gui.MAX_MESSAGE_LENGTH + 1),
        )
        self.app.update()
        self.assertEqual(self.app.message_count_label.cget("text"), "2001 / 2000")
        with patch.object(gui.messagebox, "showwarning") as warning:
            self.assertFalse(self.app.save())
        warning.assert_called_once()
        self.assertIn("cannot exceed 2000", warning.call_args.args[1])
        self.saved_config.assert_not_called()

    def test_high_scale_console_is_clipped_above_clickable_footer(self) -> None:
        self.app._apply_zoom("200%")
        self.app.tabs.set("Console")
        self.app.update()
        try:
            console_canvas = self.app.console_view.canvas
            canvas_bottom = console_canvas.winfo_rooty() + console_canvas.winfo_height()
            host_bottom = (
                self.app.console_host.winfo_rooty()
                + self.app.console_host.winfo_height()
            )
            self.assertLessEqual(canvas_bottom, host_bottom)

            for button in (
                self.app.bot_button,
                self.app.reload_button,
                self.app.save_button,
            ):
                x = button.winfo_rootx() + button.winfo_width() // 2
                y = button.winfo_rooty() + button.winfo_height() // 2
                hit = self.app.winfo_containing(x, y)
                while hit is not None and hit is not button:
                    hit = hit.master
                self.assertIs(hit, button)

            clicked: list[str] = []
            for button, name in (
                (self.app.bot_button, "start"),
                (self.app.reload_button, "reload"),
                (self.app.save_button, "save"),
            ):
                original_command = button._command
                button.configure(command=lambda value=name: clicked.append(value))
                target = button._text_label or button._canvas
                target.event_generate("<Enter>")
                target.event_generate("<Button-1>", x=2, y=2)
                target.event_generate("<ButtonRelease-1>", x=2, y=2)
                self.app.update()
                button.configure(command=original_command)
            self.assertEqual(clicked, ["start", "reload", "save"])

            console_tab_button = self.app.tabs._segmented_button._buttons_dict[
                "Console"
            ]
            self.app.tabs.set("General")
            target = console_tab_button._text_label or console_tab_button._canvas
            target.event_generate("<Enter>")
            target.event_generate("<Button-1>", x=2, y=2)
            target.event_generate("<ButtonRelease-1>", x=2, y=2)
            self.app.update()
            self.assertEqual(self.app.tabs.get(), "Console")
        finally:
            self.app._apply_zoom("100%")
            self.app.update()

    def test_bot_output_is_streamed_and_drained_on_exit(self) -> None:
        class FakeProcess:
            pid = 4242

            def __init__(self) -> None:
                self.exit_code: int | None = None

            def poll(self) -> int | None:
                return self.exit_code

            def terminate(self) -> None:
                self.exit_code = 0

            def kill(self) -> None:
                self.exit_code = -9

        fake_process = FakeProcess()

        def start_process(_command: list[str], **options: object) -> FakeProcess:
            output = options["stdout"]
            output.write("Connected to Discord gateway.\n")
            output.flush()
            return fake_process

        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "bot.log"
            self.app._bot_log_path = log_path
            with (
                patch.object(self.app, "save", return_value=True),
                patch.object(gui.subprocess, "Popen", side_effect=start_process),
            ):
                self.app._start_bot()

            self.assertEqual(self.app.console_state_var.get(), "Running • PID 4242")
            self.app._drain_bot_log()
            self.assertIn(
                "Connected to Discord gateway.",
                self.app.console_view.get_text(),
            )

            if self.app._bot_poll_after_id is not None:
                self.app.after_cancel(self.app._bot_poll_after_id)
                self.app._bot_poll_after_id = None
            fake_process.exit_code = 7
            self.app._poll_bot()

            self.assertIsNone(self.app.bot_process)
            self.assertEqual(self.app.console_state_var.get(), "Exited • code 7")
            self.assertIn(
                "Bot exited with code 7",
                self.app.console_view.get_text(),
            )
            self.assertIn("Connected to Discord gateway.", log_path.read_text())


if __name__ == "__main__":
    unittest.main()

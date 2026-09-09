from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime
from typing import Any

from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Static,
    Tab,
    Tabs,
    TextArea,
)
from textual.widgets.text_area import EditResult, Location

from umbra_bot import config
from umbra_bot.bot import SyraBot
from umbra_tui.theme import UMBRA_THEME


MAX_MESSAGE_LENGTH = 2_000


class LogLine(Message):
    """A thread-safe request to append a Rich log line."""

    def __init__(self, content: Text) -> None:
        self.content = content
        super().__init__()


def format_log_record(
    record: logging.LogRecord,
    *,
    compact: bool = False,
    colors: Mapping[str, str] | None = None,
) -> Text:
    """Render a logging record with the same visual hierarchy as a console."""
    umbra_colors = UMBRA_THEME.to_color_system().generate()
    palette = {
        "primary": umbra_colors["text-primary"],
        "secondary": umbra_colors["text-secondary"],
        "accent": umbra_colors["text-accent"],
        "warning": umbra_colors["text-warning"],
        "error": umbra_colors["text-error"],
        "error-background": umbra_colors["error"],
        "foreground": umbra_colors["foreground"],
    }
    if colors is not None:
        palette.update(colors)
    level_styles = {
        logging.DEBUG: palette["secondary"],
        logging.INFO: f"bold {palette['primary']}",
        logging.WARNING: f"bold {palette['warning']}",
        logging.ERROR: f"bold {palette['error']}",
        logging.CRITICAL: (
            f"bold {palette['foreground']} on {palette['error-background']}"
        ),
    }
    level_style = level_styles.get(
        record.levelno, f"bold {palette['foreground']}"
    )

    line = Text()
    line.append(
        datetime.fromtimestamp(record.created).strftime(
            "%H:%M:%S " if compact else "%Y-%m-%d %H:%M:%S "
        ),
        style=palette["secondary"],
    )
    line.append(f"{record.levelname:<8} ", style=level_style)
    line.append(record.name, style=palette["accent"])
    line.append(
        "\n  " if compact else "  │  ", style=palette["secondary"]
    )
    line.append_text(Text.from_ansi(record.getMessage()))

    if record.exc_info:
        exception = logging.Formatter().formatException(record.exc_info)
        line.append("\n")
        line.append_text(Text.from_ansi(exception, style=palette["error"]))
    if record.stack_info:
        line.append("\n")
        line.append_text(
            Text.from_ansi(record.stack_info, style=palette["foreground"])
        )
    return line


class TUILogHandler(logging.Handler):
    """Forward Python log records into Textual without losing their colors."""

    def __init__(self, app: UmbraTUI) -> None:
        super().__init__(logging.NOTSET)
        self.app = app

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.app.post_message(
                LogLine(
                    format_log_record(
                        record,
                        compact=self.app.size.width < 80,
                        colors=self.app._rich_theme_colors(),
                    )
                )
            )
        except Exception:
            self.handleError(record)


class ConsoleLog(RichLog):
    """A RichLog which also captures ANSI output written with print()."""

    def on_mount(self) -> None:
        self.begin_capture_print(stdout=True, stderr=True)

    def on_unmount(self) -> None:
        self.end_capture_print()

    def on_print(self, event: events.Print) -> None:
        event.stop()
        content = event.text.removesuffix("\n")
        if content:
            self.write(Text.from_ansi(content))


class LimitedTextArea(TextArea):
    """Text editor which refuses edits beyond Discord's message limit."""

    max_length = MAX_MESSAGE_LENGTH

    def replace(
        self,
        insert: str,
        start: Location,
        end: Location,
        *,
        maintain_selection_offset: bool = True,
    ) -> EditResult:
        selected_length = len(self.get_text_range(start, end))
        length_without_selection = len(self.text) - selected_length
        if length_without_selection <= self.max_length:
            allowed_length = self.max_length - length_without_selection
        else:
            # Existing oversized configs may still be edited down, but not
            # made any longer before they return to the valid range.
            allowed_length = selected_length
        return super().replace(
            insert[:allowed_length],
            start,
            end,
            maintain_selection_offset=maintain_selection_offset,
        )


class UmbraTUI(App[None]):
    """Interactive terminal dashboard for running an Umbra bot instance."""

    TITLE = "Umbra Bot"
    SUB_TITLE = "Terminal control center"

    CSS = """
    Screen {
        background: $background;
        color: $foreground;
    }

    * {
        scrollbar-size: 0 0;
        scrollbar-gutter: auto;
    }

    Header {
        background: $panel-lighten-1;
        color: $foreground;
    }

    #workspace {
        width: 100%;
        height: 1fr;
    }

    #view-tabs {
        height: 3;
        margin: 0 1;
        background: $panel;
        color: $foreground;
        border-bottom: solid $secondary;
    }

    #console-panel {
        width: 1fr;
        height: 1fr;
        margin: 1;
        border: round $secondary;
        background: $surface;
    }

    #config-panel {
        display: none;
        width: 1fr;
        height: 1fr;
        margin: 1;
        padding: 1 2;
        border: round $secondary;
        background: $surface;
        scrollbar-color: $scrollbar;
        scrollbar-background: $surface;
    }

    #config-content {
        width: 1fr;
        height: auto;
    }

    #config-title {
        height: auto;
        color: $foreground;
        text-style: bold;
    }

    #config-path,
    #config-status {
        height: auto;
        margin-bottom: 1;
        color: $foreground-muted;
    }

    .config-label {
        height: auto;
        margin-top: 1;
        color: $foreground;
        text-style: bold;
    }

    .config-message-header {
        width: 1fr;
        height: auto;
    }

    .config-message-header .config-label {
        width: 1fr;
    }

    .config-count {
        width: auto;
        height: auto;
        margin-top: 1;
        color: $foreground-muted;
        text-align: right;
    }

    .config-input {
        height: 3;
        border: tall $secondary;
        background: $surface-lighten-1;
        color: $foreground;
    }

    .config-row {
        width: 1fr;
        height: auto;
    }

    .config-field {
        width: 1fr;
        height: auto;
        margin-right: 1;
    }

    #config-block-field {
        margin-right: 0;
    }

    #token-row {
        width: 1fr;
        height: 3;
    }

    #config-token {
        width: 1fr;
    }

    #config-token-toggle {
        width: 10;
        min-width: 10;
        height: 3;
        margin: 0 0 0 1;
    }

    .config-message {
        height: 10;
        border: round $secondary;
        background: $surface-lighten-1;
        color: $foreground;
    }

    #config-actions {
        width: 1fr;
        height: 3;
        margin-top: 1;
    }

    #config-actions Button {
        width: 1fr;
        min-width: 15;
        height: 3;
        margin: 0 1 0 0;
    }

    #config-save {
        background: $success;
    }

    #console-title {
        width: auto;
        height: 1;
        margin-left: 1;
        padding: 0 1;
        color: $foreground;
        text-style: bold;
        background: $panel;
    }

    #console-log {
        height: 1fr;
        padding: 0 1 1 1;
        background: $surface;
        color: $foreground;
        scrollbar-color: $scrollbar;
        scrollbar-color-hover: $scrollbar-hover;
        scrollbar-color-active: $scrollbar-active;
        scrollbar-background: $surface;
        scrollbar-background-hover: $surface;
        scrollbar-background-active: $surface;
        scrollbar-corner-color: $surface;
    }

    #controls-panel {
        width: 32;
        min-width: 28;
        height: 1fr;
        margin: 1 1 1 0;
        padding: 1 2;
        border: round $secondary;
        background: $panel;
        scrollbar-color: $scrollbar;
        scrollbar-color-hover: $scrollbar-hover;
        scrollbar-color-active: $scrollbar-active;
        scrollbar-background: $panel;
        scrollbar-background-hover: $panel;
        scrollbar-background-active: $panel;
        scrollbar-corner-color: $panel;
    }

    #controls-content {
        width: 1fr;
        height: auto;
    }

    #brand {
        height: auto;
        margin-bottom: 1;
        color: $foreground;
        text-style: bold;
    }

    .section-label {
        height: auto;
        margin: 1 0 0 0;
        color: $foreground-muted;
        text-style: bold;
    }

    #status-label {
        margin-top: 0;
    }

    #bot-status {
        height: auto;
        min-height: 3;
        margin: 0 0 1 0;
        padding: 1;
        border: round $secondary;
        background: $surface-lighten-1;
        color: $warning;
    }

    Button {
        width: 100%;
        min-width: 20;
        margin: 0 0 1 0;
        border: none;
        background: $secondary;
        color: $foreground;
        text-style: bold;
    }

    Button:hover {
        background: $secondary-lighten-1;
    }

    Button:focus {
        border: tall $foreground;
    }

    Button:disabled {
        background: $surface-lighten-2;
        color: $foreground-disabled;
    }

    #start-bot {
        background: $success;
    }

    #stop-bot {
        background: $error;
    }

    #restart-bot {
        background: $primary;
    }

    #quit {
        margin-top: 1;
        background: $surface-lighten-1;
        border: tall $secondary;
    }

    Footer {
        background: $footer-background;
        color: $footer-foreground;
    }

    Screen.-desktop #mobile-controls {
        display: none;
    }

    Screen.-mobile #workspace {
        layout: vertical;
    }

    Screen.-mobile #console-panel,
    Screen.-mobile #config-panel,
    Screen.-mobile #controls-panel {
        width: 1fr;
        min-width: 0;
        height: 1fr;
        margin: 0 1 1 1;
    }

    Screen.-mobile #controls-panel {
        padding: 1 2;
    }

    Screen.-mobile .config-row {
        layout: vertical;
    }

    Screen.-mobile .config-field {
        width: 1fr;
        margin-right: 0;
    }

    Screen.-mobile Footer {
        display: none;
    }
    """

    BINDINGS = [
        Binding("s", "start_bot", "Start"),
        Binding("x", "stop_bot", "Stop"),
        Binding("r", "restart_bot", "Restart"),
        Binding("l", "reload_config", "Reload"),
        Binding("f", "toggle_follow", "Follow"),
        Binding("ctrl+l", "clear_log", "Clear"),
        Binding("1", "show_console", "Console"),
        Binding("2", "show_config", "Config"),
        Binding("3", "show_controls", "Controls", show=False),
        Binding("ctrl+s", "save_config", "Save config"),
        Binding("q", "request_quit", "Quit"),
    ]

    HORIZONTAL_BREAKPOINTS = [(0, "-mobile"), (80, "-desktop")]

    def __init__(
        self,
        *,
        bot_factory: Callable[[], Any] = SyraBot,
        auto_start: bool = True,
    ) -> None:
        super().__init__()
        self._bot_factory = bot_factory
        self._auto_start = auto_start
        self._bot: Any | None = None
        self._bot_task: asyncio.Task[None] | None = None
        self._operation_lock = asyncio.Lock()
        self._stop_requested = False
        self._shutting_down = False
        self._main_view = "console"
        self._current_config: dict[str, Any] = {}
        self._state = "stopped"
        self._discord_logger = logging.getLogger("discord")
        self._old_log_handlers: list[logging.Handler] = []
        self._old_log_level = self._discord_logger.level
        self._old_log_propagate = self._discord_logger.propagate
        self._log_handler = TUILogHandler(self)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Tabs(
            Tab("Console", id="mobile-console"),
            Tab("Config", id="mobile-config"),
            Tab("Controls", id="mobile-controls"),
            active="mobile-console",
            id="view-tabs",
        )
        with Horizontal(id="workspace"):
            with Container(id="console-panel"):
                yield Label("LIVE CONSOLE", id="console-title")
                yield ConsoleLog(
                    id="console-log",
                    max_lines=10_000,
                    min_width=40,
                    wrap=True,
                    markup=False,
                    auto_scroll=True,
                )
            with VerticalScroll(id="config-panel"):
                with Vertical(id="config-content"):
                    yield Label("CONFIGURATION", id="config-title")
                    yield Static(str(config.CONFIG_PATH), id="config-path")
                    yield Label("Application token", classes="config-label")
                    with Horizontal(id="token-row"):
                        yield Input(
                            password=True,
                            id="config-token",
                            classes="config-input",
                        )
                        yield Button("Show", id="config-token-toggle")
                    yield Label("Command prefix", classes="config-label")
                    yield Input(id="config-prefix", classes="config-input")
                    with Horizontal(classes="config-row"):
                        with Vertical(classes="config-field"):
                            yield Label("Maximum uses", classes="config-label")
                            yield Input(
                                type="integer",
                                id="config-max-uses",
                                classes="config-input",
                            )
                        with Vertical(classes="config-field"):
                            yield Label("Window seconds", classes="config-label")
                            yield Input(
                                type="integer",
                                id="config-wait-seconds",
                                classes="config-input",
                            )
                        with Vertical(
                            id="config-block-field",
                            classes="config-field",
                        ):
                            yield Label("Block seconds", classes="config-label")
                            yield Input(
                                type="integer",
                                id="config-block-seconds",
                                classes="config-input",
                            )
                    with Horizontal(classes="config-message-header"):
                        yield Label("Standard message", classes="config-label")
                        yield Static(
                            f"0 / {MAX_MESSAGE_LENGTH}",
                            id="config-pm-count",
                            classes="config-count",
                        )
                    yield LimitedTextArea(
                        id="config-pm",
                        classes="config-message",
                        soft_wrap=True,
                        show_line_numbers=False,
                    )
                    with Horizontal(classes="config-message-header"):
                        yield Label("Ping message", classes="config-label")
                        yield Static(
                            f"0 / {MAX_MESSAGE_LENGTH}",
                            id="config-pingpm-count",
                            classes="config-count",
                        )
                    yield LimitedTextArea(
                        id="config-pingpm",
                        classes="config-message",
                        soft_wrap=True,
                        show_line_numbers=False,
                    )
                    with Horizontal(id="config-actions"):
                        yield Button("Reload from disk", id="config-form-reload")
                        yield Button("Save config", id="config-save")
                    yield Static("", id="config-status")
            with VerticalScroll(id="controls-panel"):
                with Vertical(id="controls-content"):
                    yield Label(
                        "STATUS", id="status-label", classes="section-label"
                    )
                    yield Static("Stopped", id="bot-status")
                    yield Label("BOT", classes="section-label")
                    yield Button("Start bot", id="start-bot")
                    yield Button("Stop bot", id="stop-bot", disabled=True)
                    yield Button("Restart bot", id="restart-bot", disabled=True)
                    yield Label("CONSOLE", classes="section-label")
                    yield Button("Reload config", id="reload-config")
                    yield Button("Follow output: On", id="toggle-follow")
                    yield Button("Clear log", id="clear-log")
                    yield Button("Quit", id="quit")
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(UMBRA_THEME)
        self.theme = UMBRA_THEME.name
        self._install_logging()
        self.set_interval(0.5, self._refresh_connection_status)
        self._load_config_form()
        self._apply_responsive_layout(self.size.width)
        self._set_state("stopped", "Ready")
        self._write_system("Umbra terminal control center ready.")
        if self._auto_start:
            self.call_after_refresh(self.action_start_bot)

    def on_resize(self, event: events.Resize) -> None:
        self._apply_responsive_layout(event.size.width)

    def _apply_responsive_layout(self, width: int) -> None:
        mobile = width < 80
        console = self.query_one("#console-panel", Container)
        config_panel = self.query_one("#config-panel", VerticalScroll)
        controls = self.query_one("#controls-panel", VerticalScroll)
        if not mobile and self._main_view == "controls":
            self._main_view = "console"
            self.query_one("#view-tabs", Tabs).active = "mobile-console"
        console.display = self._main_view == "console"
        config_panel.display = self._main_view == "config"
        controls.display = not mobile or self._main_view == "controls"

    @on(Tabs.TabActivated, "#view-tabs")
    def _switch_mobile_tab(self, event: Tabs.TabActivated) -> None:
        selected = (event.tab.id or "mobile-console").removeprefix("mobile-")
        self._main_view = selected
        self._apply_responsive_layout(self.size.width)
        if self._main_view == "console":
            console = self.query_one("#console-log", ConsoleLog)
            if console.auto_scroll:
                console.scroll_end(animate=False)

    async def on_unmount(self) -> None:
        self._shutting_down = True
        try:
            await self._stop_bot(update_ui=False)
        finally:
            self._restore_logging()

    def _install_logging(self) -> None:
        self._old_log_handlers = list(self._discord_logger.handlers)
        self._old_log_level = self._discord_logger.level
        self._old_log_propagate = self._discord_logger.propagate
        self._discord_logger.handlers.clear()
        self._discord_logger.addHandler(self._log_handler)
        self._discord_logger.setLevel(logging.INFO)
        self._discord_logger.propagate = False

    def _restore_logging(self) -> None:
        self._discord_logger.handlers.clear()
        self._discord_logger.handlers.extend(self._old_log_handlers)
        self._discord_logger.setLevel(self._old_log_level)
        self._discord_logger.propagate = self._old_log_propagate

    def _rich_theme_colors(self) -> dict[str, str]:
        """Return the active theme's base colors in Rich-compatible form."""
        generated = self.current_theme.to_color_system().generate()
        colors = {
            name: generated[f"text-{name}"]
            for name in (
                "primary",
                "secondary",
                "accent",
                "warning",
                "error",
                "success",
            )
        }
        colors["error-background"] = generated["error"]
        colors["foreground"] = generated["foreground"]
        return colors

    @on(LogLine)
    def _append_log_line(self, message: LogLine) -> None:
        self.query_one("#console-log", ConsoleLog).write(message.content)

    def _write_system(self, message: str, *, level: int = logging.INFO) -> None:
        if self._shutting_down:
            return
        record = logging.LogRecord(
            name="umbra.tui",
            level=level,
            pathname="",
            lineno=0,
            msg=message,
            args=(),
            exc_info=None,
        )
        self.post_message(
            LogLine(
                format_log_record(
                    record,
                    compact=self.size.width < 80,
                    colors=self._rich_theme_colors(),
                )
            )
        )

    def _set_state(self, state: str, detail: str) -> None:
        self._state = state
        if self._shutting_down:
            return
        theme_colors = self._rich_theme_colors()
        colors = {
            "stopped": theme_colors["secondary"],
            "starting": theme_colors["warning"],
            "running": theme_colors["success"],
            "stopping": theme_colors["warning"],
            "failed": theme_colors["error"],
        }
        labels = {
            "stopped": "STOPPED",
            "starting": "STARTING",
            "running": "RUNNING",
            "stopping": "STOPPING",
            "failed": "FAILED",
        }
        status = Text()
        status.append(labels[state], style=f"bold {colors[state]}")
        if detail:
            status.append(f"\n{detail}", style=theme_colors["foreground"])
        self.query_one("#bot-status", Static).update(status)

        active = state in {"starting", "running", "stopping"}
        self.query_one("#start-bot", Button).disabled = active
        self.query_one("#stop-bot", Button).disabled = not active or state == "stopping"
        self.query_one("#restart-bot", Button).disabled = not active or state == "stopping"

    def _refresh_connection_status(self) -> None:
        bot = self._bot
        task = self._bot_task
        if bot is None or task is None or task.done():
            return
        if getattr(bot, "is_ready", lambda: False)():
            user = getattr(bot, "user", None)
            latency = getattr(bot, "latency", float("nan"))
            detail = str(user) if user is not None else "Connected to Discord"
            if isinstance(latency, (int, float)) and latency >= 0:
                detail += f"\nGateway {latency * 1000:.0f} ms"
            if self._state != "running":
                self._set_state("running", detail)

    async def action_start_bot(self) -> None:
        async with self._operation_lock:
            await self._start_bot()

    async def _start_bot(self) -> None:
        if self._bot_task is not None and not self._bot_task.done():
            return
        try:
            config.reload_config()
        except (KeyError, TypeError, ValueError, OSError) as error:
            self._set_state("failed", "Configuration could not be loaded")
            self._write_system(f"Configuration reload failed: {error}", level=logging.ERROR)
            return
        if not config.token.strip():
            self._set_state("failed", "Add a token in config/config.jsonc")
            self._write_system(
                "Bot not started: config/config.jsonc has no application token.",
                level=logging.ERROR,
            )
            return

        self._bot = self._bot_factory()
        self._stop_requested = False
        self._set_state("starting", "Connecting to Discord…")
        self._write_system("Starting bot…")
        self._bot_task = asyncio.create_task(
            self._run_bot(self._bot, config.token),
            name="umbra-discord-bot",
        )

    async def _run_bot(self, bot: Any, token: str) -> None:
        failed = False
        try:
            await bot.start(token)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failed = True
            record = logging.LogRecord(
                name="discord.umbra",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg="Bot exited with an error: %s",
                args=(error,),
                exc_info=None,
            )
            self.post_message(
                LogLine(
                    format_log_record(
                        record,
                        compact=self.size.width < 80,
                        colors=self._rich_theme_colors(),
                    )
                )
            )
        finally:
            if not getattr(bot, "is_closed", lambda: True)():
                try:
                    await bot.close()
                except Exception as error:
                    self._write_system(f"Bot cleanup failed: {error}", level=logging.ERROR)
            if self._bot is bot:
                self._bot = None
                self._bot_task = None
                if failed:
                    self._set_state("failed", "See the console for details")
                else:
                    detail = "Stopped by user" if self._stop_requested else "Connection closed"
                    self._set_state("stopped", detail)
                self._stop_requested = False

    async def action_stop_bot(self) -> None:
        async with self._operation_lock:
            await self._stop_bot()

    async def _stop_bot(self, *, update_ui: bool = True) -> None:
        bot = self._bot
        task = self._bot_task
        if bot is None or task is None or task.done():
            return
        self._stop_requested = True
        if update_ui:
            self._set_state("stopping", "Closing the Discord connection…")
            self._write_system("Stopping bot…", level=logging.WARNING)
        try:
            await bot.close()
            await asyncio.wait_for(asyncio.shield(task), timeout=10)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if self._bot is bot:
                self._bot = None
                self._bot_task = None
                self._set_state("stopped", "Forced shutdown complete")
        except Exception as error:
            self._write_system(f"Bot shutdown failed: {error}", level=logging.ERROR)

    async def action_restart_bot(self) -> None:
        async with self._operation_lock:
            await self._stop_bot()
            await self._start_bot()

    async def action_reload_config(self) -> None:
        try:
            config.reload_config()
            if self._bot is not None:
                self._bot.command_prefix = config.prefix
        except (KeyError, TypeError, ValueError, OSError) as error:
            self._write_system(f"Configuration reload failed: {error}", level=logging.ERROR)
            return
        self._write_system("Configuration reloaded successfully.")

    def _set_config_status(self, message: str, *, error: bool = False) -> None:
        colors = self._rich_theme_colors()
        status = Text(message, style=colors["error" if error else "success"])
        self.query_one("#config-status", Static).update(status)

    def _update_message_count(self, text_area: TextArea) -> None:
        counter_ids = {
            "config-pm": "#config-pm-count",
            "config-pingpm": "#config-pingpm-count",
        }
        counter_id = counter_ids.get(text_area.id or "")
        if counter_id is None:
            return
        length = len(text_area.text)
        colors = self._rich_theme_colors()
        if length > MAX_MESSAGE_LENGTH:
            color = colors["error"]
        elif length == MAX_MESSAGE_LENGTH:
            color = colors["warning"]
        else:
            color = colors["secondary"]
        self.query_one(counter_id, Static).update(
            Text(f"{length} / {MAX_MESSAGE_LENGTH}", style=color)
        )

    @on(TextArea.Changed, ".config-message")
    def _message_text_changed(self, event: TextArea.Changed) -> None:
        self._update_message_count(event.text_area)

    def _load_config_form(self) -> None:
        try:
            loaded = config.load_config()
            basic = loaded.get("basic_config", {})
            messages = loaded.get("messages", {})
            self._current_config = loaded
            self.query_one("#config-token", Input).value = str(
                loaded.get("token", "")
            )
            self.query_one("#config-prefix", Input).value = str(
                basic.get("prefix", "!")
            )
            self.query_one("#config-max-uses", Input).value = str(
                basic.get("max_uses", 3)
            )
            self.query_one("#config-wait-seconds", Input).value = str(
                basic.get("wait_seconds", 180)
            )
            self.query_one("#config-block-seconds", Input).value = str(
                basic.get("b_seconds", 900)
            )
            standard_message = self.query_one("#config-pm", TextArea)
            standard_message.load_text(str(messages.get("pm", "")))
            self._update_message_count(standard_message)
            ping_message = self.query_one("#config-pingpm", TextArea)
            ping_message.load_text(str(messages.get("pingpm", "")))
            self._update_message_count(ping_message)
        except Exception as error:
            self._set_config_status(f"Could not load config: {error}", error=True)
            return
        self._set_config_status("Loaded from disk")

    @staticmethod
    def _positive_integer(value: str, label: str) -> int:
        try:
            result = int(value)
        except ValueError as error:
            raise ValueError(f"{label} must be a whole number.") from error
        if result < 1:
            raise ValueError(f"{label} must be at least 1.")
        return result

    def action_save_config(self) -> None:
        try:
            prefix = self.query_one("#config-prefix", Input).value.strip()
            if not prefix:
                raise ValueError("Prefix cannot be empty.")
            max_uses = self._positive_integer(
                self.query_one("#config-max-uses", Input).value,
                "Maximum uses",
            )
            wait_seconds = self._positive_integer(
                self.query_one("#config-wait-seconds", Input).value,
                "Window seconds",
            )
            block_seconds = self._positive_integer(
                self.query_one("#config-block-seconds", Input).value,
                "Block seconds",
            )
            standard_message = self.query_one("#config-pm", TextArea).text
            ping_message = self.query_one("#config-pingpm", TextArea).text
            if len(standard_message) > MAX_MESSAGE_LENGTH:
                raise ValueError(
                    f"Standard message cannot exceed {MAX_MESSAGE_LENGTH} characters."
                )
            if len(ping_message) > MAX_MESSAGE_LENGTH:
                raise ValueError(
                    f"Ping message cannot exceed {MAX_MESSAGE_LENGTH} characters."
                )

            updated = deepcopy(self._current_config or config.load_config())
            updated["token"] = self.query_one("#config-token", Input).value.strip()
            updated.setdefault("basic_config", {}).update(
                {
                    "prefix": prefix,
                    "max_uses": max_uses,
                    "wait_seconds": wait_seconds,
                    "b_seconds": block_seconds,
                }
            )
            updated.setdefault("messages", {}).update(
                {
                    "pm": standard_message,
                    "pingpm": ping_message,
                }
            )
            config.save_config(updated)
            config.reload_config()
            self._current_config = updated
            if self._bot is not None:
                self._bot.command_prefix = config.prefix
        except (KeyError, TypeError, ValueError, OSError) as error:
            self._set_config_status(str(error), error=True)
            self._write_system(f"Configuration save failed: {error}", level=logging.ERROR)
            return
        self._set_config_status("Settings saved successfully")
        self._write_system("Configuration saved successfully.")

    def action_toggle_config_token(self) -> None:
        token_input = self.query_one("#config-token", Input)
        token_input.password = not token_input.password
        self.query_one("#config-token-toggle", Button).label = (
            "Show" if token_input.password else "Hide"
        )

    def action_toggle_follow(self) -> None:
        console = self.query_one("#console-log", ConsoleLog)
        console.auto_scroll = not console.auto_scroll
        button = self.query_one("#toggle-follow", Button)
        button.label = f"Follow output: {'On' if console.auto_scroll else 'Off'}"
        if console.auto_scroll:
            console.scroll_end(animate=False)

    def action_clear_log(self) -> None:
        self.query_one("#console-log", ConsoleLog).clear()
        self._write_system("Console cleared.")

    def _show_view(self, view: str) -> None:
        self._main_view = view
        self.query_one("#view-tabs", Tabs).active = f"mobile-{view}"
        self._apply_responsive_layout(self.size.width)
        if view == "console":
            console = self.query_one("#console-log", ConsoleLog)
            if console.auto_scroll:
                console.scroll_end(animate=False)

    def action_show_console(self) -> None:
        self._show_view("console")

    def action_show_config(self) -> None:
        self._show_view("config")

    def action_show_controls(self) -> None:
        if self.size.width < 80:
            self._show_view("controls")

    async def action_request_quit(self) -> None:
        async with self._operation_lock:
            await self._stop_bot()
        self.exit()

    @on(Button.Pressed)
    async def _handle_button(self, event: Button.Pressed) -> None:
        actions: dict[str, Callable[[], Any]] = {
            "start-bot": self.action_start_bot,
            "stop-bot": self.action_stop_bot,
            "restart-bot": self.action_restart_bot,
            "reload-config": self.action_reload_config,
            "toggle-follow": self.action_toggle_follow,
            "clear-log": self.action_clear_log,
            "config-token-toggle": self.action_toggle_config_token,
            "config-form-reload": self._load_config_form,
            "config-save": self.action_save_config,
            "quit": self.action_request_quit,
        }
        action = actions.get(event.button.id or "")
        if action is None:
            return
        result = action()
        if asyncio.iscoroutine(result):
            await result

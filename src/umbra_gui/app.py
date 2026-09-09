import re
import subprocess
import sys
import time
import tkinter as tk
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

from umbra_bot import PACKAGED_BOT_ARGUMENT
from umbra_bot.config import CONFIG_PATH, load_config, save_config
from .discord_preview import DiscordMarkdownView

APP_TITLE = "Umbra"
SPLASH_WORD = "Umbra"
ORGANIZATION_URL = "https://github.com/Umbra-Development"
LOGO_PATH = Path(__file__).with_name("assets") / "umbra-development.png"
THEME_PATH = Path(__file__).with_name("assets") / "umbra-theme.json"
MAX_MESSAGE_LENGTH = 2_000
ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Establish Umbra before the root window or any child widget is drawn. Retain
# the stock palette so the appearance selector can still offer standard modes.
ctk.set_default_color_theme("blue")
STANDARD_THEME = deepcopy(ctk.ThemeManager.theme)
ctk.set_default_color_theme(str(THEME_PATH))
ctk.set_appearance_mode("Dark")


def _scale_preference(value: object, default: int = 100) -> int:
    try:
        return max(50, min(200, int(value)))
    except (TypeError, ValueError):
        return default


class LimitedTextbox(ctk.CTkTextbox):
    """A CTk textbox that caps interactive inserts at Discord's limit."""

    def __init__(self, *args: object, max_length: int, **kwargs: object) -> None:
        kwargs.setdefault("activate_scrollbars", False)
        super().__init__(*args, **kwargs)
        self.max_length = max_length
        self._limit_enabled = True
        self._widget_command = self._textbox._w
        self._original_widget_command = f"{self._widget_command}_original"
        self.tk.call(
            "rename", self._widget_command, self._original_widget_command
        )
        self.tk.createcommand(self._widget_command, self._text_command)

    def _text_command(self, *arguments: object) -> object:
        args = [str(argument) for argument in arguments]
        if self._limit_enabled and args:
            if args[0] == "insert" and len(args) >= 3:
                args = self._limit_insert(args)
                if not args:
                    return ""
            elif args[0] == "replace" and len(args) >= 4:
                args = self._limit_replace(args)

        return self.tk.call(self._original_widget_command, *args)

    def _limit_insert(self, args: list[str]) -> list[str]:
        available = max(0, self.max_length - len(self.get("1.0", "end-1c")))
        return self._limit_text_arguments(args, text_start=2, available=available)

    def _limit_replace(self, args: list[str]) -> list[str]:
        current_length = len(self.get("1.0", "end-1c"))
        replaced = self.get(args[1], args[2])
        available = max(0, self.max_length - current_length + len(replaced))
        limited = self._limit_text_arguments(
            args, text_start=3, available=available
        )
        # Even when no inserted characters fit, replacement must still delete
        # the selected range so an oversized legacy value can be shortened.
        return limited or [*args[:3], ""]

    @staticmethod
    def _limit_text_arguments(
        args: list[str], *, text_start: int, available: int
    ) -> list[str]:
        limited = args[:text_start]
        for index in range(text_start, len(args), 2):
            text = args[index][:available]
            available -= len(text)
            if text:
                limited.append(text)
                if index + 1 < len(args):
                    limited.append(args[index + 1])
        return limited if len(limited) > text_start else []

    def replace_contents(self, value: str, *, enforce_limit: bool = True) -> None:
        previous = self._limit_enabled
        self._limit_enabled = enforce_limit
        try:
            self.delete("1.0", "end")
            self.insert("1.0", value)
        finally:
            self._limit_enabled = previous

    def destroy(self) -> None:
        if self._widget_command:
            self.tk.deletecommand(self._widget_command)
            self.tk.call(
                "rename", self._original_widget_command, self._widget_command
            )
            self._widget_command = ""
        super().destroy()


class ConsoleView(ctk.CTkFrame):
    """Canvas-backed, scrollable output without a native Text input window."""

    max_entries = 5_000

    def __init__(self, master: ctk.CTkBaseClass) -> None:
        super().__init__(master, corner_radius=6, fg_color="#211820")
        self._entries: list[tuple[str, str | None]] = []
        self._colors = {
            "default": "#ffffe7",
            "system": "#8e9b9d",
            "success": "#8bd49c",
            "warning": "#f0c674",
            "error": "#ff8d85",
        }
        self._background = "#211820"
        self._render_after_id: str | None = None
        self.following = True
        self._font = ctk.CTkFont(family="monospace", size=12)

        self.canvas = tk.Canvas(
            self,
            background=self._background,
            borderwidth=0,
            highlightthickness=0,
            takefocus=True,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=3, pady=3)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.canvas.bind("<Configure>", lambda _event: self._schedule_render())
        self.canvas.bind("<Button-1>", self._focus)
        self.canvas.bind("<MouseWheel>", self._scroll)
        self.canvas.bind("<Button-4>", self._scroll)
        self.canvas.bind("<Button-5>", self._scroll)
        self.canvas.bind("<Control-c>", self._copy_all)
        self.canvas.bind("<Command-c>", self._copy_all)

    def append(self, value: str, tag: str | None = None) -> None:
        lines = value.splitlines()
        if not lines and value:
            lines = [value]
        self._entries.extend((line, tag) for line in lines)
        if len(self._entries) > self.max_entries:
            del self._entries[: len(self._entries) - self.max_entries]
        self._schedule_render()

    def clear(self) -> None:
        self._entries.clear()
        self._schedule_render()

    def get_text(self) -> str:
        return "\n".join(text for text, _tag in self._entries)

    def set_following(self, following: bool) -> None:
        self.following = following
        if following:
            self.see_end()

    def see_end(self) -> None:
        self.canvas.yview_moveto(1.0)

    def set_palette(
        self,
        *,
        background: str,
        foreground: str,
        system: str,
        success: str,
        warning: str,
        error: str,
    ) -> None:
        self._background = background
        self._colors = {
            "default": foreground,
            "system": system,
            "success": success,
            "warning": warning,
            "error": error,
        }
        self.configure(fg_color=background)
        self.canvas.configure(background=background)
        self._schedule_render()

    def _schedule_render(self) -> None:
        if self._render_after_id is None and self.winfo_exists():
            self._render_after_id = self.after_idle(self._render)

    def _render(self) -> None:
        self._render_after_id = None
        if not self.winfo_exists():
            return
        canvas = self.canvas
        canvas.delete("all")
        width = max(20, canvas.winfo_width() - 24)
        y = 10
        font = self._apply_font_scaling(self._font)
        for text, tag in self._entries:
            item = canvas.create_text(
                10,
                y,
                anchor="nw",
                width=width,
                text=text or " ",
                fill=self._colors.get(tag or "default", self._colors["default"]),
                font=font,
            )
            bounds = canvas.bbox(item)
            if bounds is not None:
                y = bounds[3] + 3
        content_height = max(canvas.winfo_height(), y + 10)
        canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), content_height))
        if self.following:
            self.see_end()

    def _focus(self, _event: tk.Event) -> None:
        self.canvas.focus_set()

    def _scroll(self, event: tk.Event) -> str:
        delta = getattr(event, "delta", 0)
        if delta:
            direction = -1 if delta > 0 else 1
        else:
            direction = -1 if getattr(event, "num", None) == 4 else 1
        self.canvas.yview_scroll(direction * 3, "units")
        return "break"

    def _copy_all(self, _event: tk.Event | None = None) -> str:
        self.clipboard_clear()
        self.clipboard_append(self.get_text())
        return "break"

    def _set_scaling(
        self, widget_scaling: float, window_scaling: float
    ) -> None:
        super()._set_scaling(widget_scaling, window_scaling)
        self._schedule_render()

    def destroy(self) -> None:
        if self._render_after_id is not None:
            self.after_cancel(self._render_after_id)
            self._render_after_id = None
        super().destroy()


class SettingsApp(ctk.CTk):
    """Desktop editor for the application's JSON5 configuration."""

    def __init__(self) -> None:
        try:
            bootstrap_config = load_config()
        except Exception:
            bootstrap_config = {}
        interface = bootstrap_config.get("interface", {})
        if not isinstance(interface, dict):
            interface = {}
        self.scaling_percent = _scale_preference(
            interface.get("scaling_percent")
        )
        self.preview_scaling_percent = _scale_preference(
            interface.get("preview_scaling_percent")
        )
        # Restore scaling before CTk constructs anything, avoiding a resize
        # and repaint immediately after the first frame is drawn.
        ctk.set_widget_scaling(self.scaling_percent / 100)
        super().__init__()
        # Do not map a partially constructed window before the splash exists.
        self.withdraw()
        self.title(f"{APP_TITLE} Settings")
        self.geometry("860x760")
        self.minsize(720, 620)

        self.umbra_logo_source = Image.open(LOGO_PATH).convert("RGB")
        self.umbra_header_image = ctk.CTkImage(
            light_image=self.umbra_logo_source,
            dark_image=self.umbra_logo_source,
            size=(64, 64),
        )
        avatar_source = self.umbra_logo_source.convert("RGBA")
        avatar_mask = Image.new("L", avatar_source.size, 0)
        ImageDraw.Draw(avatar_mask).ellipse(
            (0, 0, avatar_source.width - 1, avatar_source.height - 1),
            fill=255,
        )
        avatar_source.putalpha(avatar_mask)
        self.umbra_avatar_image = ctk.CTkImage(
            light_image=avatar_source,
            dark_image=avatar_source,
            size=(42, 42),
        )

        self.token_var = ctk.StringVar()
        self.prefix_var = ctk.StringVar()
        self.max_uses_var = ctk.StringVar()
        self.wait_seconds_var = ctk.StringVar()
        self.block_seconds_var = ctk.StringVar()
        self.status_var = ctk.StringVar(value=f"Editing {CONFIG_PATH}")
        self.console_state_var = ctk.StringVar(value="Stopped")
        self.token_visible = False
        self.console_following = True
        self.current_config: dict = bootstrap_config
        self._message_previews: dict[ctk.CTkTextbox, DiscordMarkdownView] = {}
        self.bot_process: subprocess.Popen[bytes] | None = None
        self._bot_log_file = None
        self._bot_log_reader = None
        self._bot_poll_after_id: str | None = None
        self._bot_stop_requested = False
        self._bot_stop_deadline = 0.0
        self._bot_log_path = CONFIG_PATH.parent / "bot.log"

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_form()
        self._build_footer()
        self._theme_baseline: dict[ctk.CTkBaseClass, dict[str, object]] = {}
        self._capture_theme_baseline()
        # The JSON theme supplies widget defaults, while this pass also fixes
        # context-sensitive colors such as transparent toolbar buttons.
        self._apply_theme("Umbra")

        self.bind("<Control-s>", lambda _event: self.save())
        self.bind("<Command-s>", lambda _event: self.save())
        self.bind("<Control-l>", self._clear_console_shortcut)
        self.bind("<Command-l>", self._clear_console_shortcut)
        self._bind_zoom_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.load()
        self.update_idletasks()
        self._show_splash()
        # CustomTkinter withdraws the root once more when its Windows mainloop
        # applies the title-bar theme. Reveal it from the event loop so that
        # Windows does not leave the application running with a hidden window.
        self.after_idle(self._reveal_window)

    def _reveal_window(self) -> None:
        self.deiconify()
        self.lift()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 12))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="",
            image=self.umbra_header_image,
        ).grid(row=0, column=0, rowspan=2, padx=(0, 13))

        ctk.CTkLabel(
            header,
            text=APP_TITLE,
            font=ctk.CTkFont(size=28, weight="bold"),
        ).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(
            header,
            text="Umbra Development • Configuration console",
            text_color=("gray38", "gray68"),
        ).grid(row=1, column=1, sticky="w", pady=(3, 0))

        self.appearance_menu = ctk.CTkOptionMenu(
            header,
            values=["System", "Light", "Dark", "Umbra"],
            width=110,
            command=self._apply_theme,
        )
        self.appearance_menu.set("Umbra")
        self.appearance_menu.grid(
            row=0, column=2, rowspan=2, sticky="e", padx=(12, 8)
        )

        self.scaling_menu = ctk.CTkOptionMenu(
            header,
            values=["50%", "75%", "90%", "100%", "110%", "125%", "150%", "200%"],
            width=90,
            command=self._apply_zoom,
        )
        self.scaling_menu.set(f"{self.scaling_percent}%")
        self.scaling_menu.grid(row=0, column=3, rowspan=2, sticky="e")

    def _capture_theme_baseline(self) -> None:
        for widget in self._walk_widgets(self):
            properties = self._theme_properties(widget)
            if properties:
                self._theme_baseline[widget] = {
                    name: widget.cget(name) for name in properties
                }

    @classmethod
    def _walk_widgets(cls, widget: object):
        yield widget
        for child in widget.winfo_children():
            yield from cls._walk_widgets(child)

    def _theme_properties(self, widget: object) -> tuple[str, ...]:
        if getattr(widget, "_preserve_theme_colors", False):
            return ()
        if isinstance(getattr(widget, "master", None), ctk.CTkSegmentedButton):
            return ()
        if widget is self:
            return ("fg_color",)
        if isinstance(widget, ctk.CTkTabview):
            return (
                "fg_color",
                "border_color",
                "text_color",
            )
        if isinstance(widget, ctk.CTkOptionMenu):
            return (
                "fg_color",
                "button_color",
                "button_hover_color",
                "text_color",
            )
        if isinstance(widget, ctk.CTkSegmentedButton):
            return (
                "fg_color",
                "selected_color",
                "selected_hover_color",
                "unselected_color",
                "unselected_hover_color",
                "text_color",
            )
        if isinstance(widget, ctk.CTkScrollbar):
            return ("fg_color", "button_color", "button_hover_color")
        if isinstance(widget, ctk.CTkTextbox):
            return ("fg_color", "border_color", "text_color")
        if isinstance(widget, ctk.CTkEntry):
            return (
                "fg_color",
                "border_color",
                "text_color",
                "placeholder_text_color",
            )
        if isinstance(widget, ctk.CTkButton):
            return (
                "fg_color",
                "hover_color",
                "border_color",
                "text_color",
            )
        if isinstance(widget, ctk.CTkLabel):
            return ("fg_color", "text_color")
        if isinstance(widget, ctk.CTkScrollableFrame):
            return ("fg_color",)
        if isinstance(widget, ctk.CTkFrame):
            return ("fg_color", "border_color")
        return ()

    def _apply_theme(self, theme_name: str) -> None:
        self.appearance_menu.set(theme_name)
        if theme_name != "Umbra":
            ctk.set_appearance_mode(theme_name)
            self._apply_standard_widget_colors()
            self._configure_console_tags()
            self._refresh_message_counts()
            return

        ctk.set_appearance_mode("Dark")
        palette = {
            "background": "#382837",
            "surface": "#302330",
            "surface_alt": "#291925",
            "input": "#211820",
            "border": "#697477",
            "accent": "#ffffe7",
            "accent_hover": "#d8ddc8",
            "tab_accent": "#697477",
            "text": "#ffffe7",
            "on_accent": "#291925",
            "muted": "#8e9b9d",
        }
        default_label_color = ctk.ThemeManager.theme["CTkLabel"]["text_color"]

        for widget, baseline in self._theme_baseline.items():
            if not widget.winfo_exists():
                continue
            if widget is self:
                widget.configure(fg_color=palette["background"])
            elif isinstance(widget, ctk.CTkTabview):
                widget.configure(
                    fg_color=palette["surface_alt"],
                    border_color=palette["border"],
                    segmented_button_fg_color=palette["surface"],
                    segmented_button_selected_color=palette["tab_accent"],
                    segmented_button_selected_hover_color=palette["border"],
                    segmented_button_unselected_color=palette["surface"],
                    segmented_button_unselected_hover_color=palette["border"],
                    text_color=palette["text"],
                )
            elif isinstance(widget, ctk.CTkOptionMenu):
                widget.configure(
                    fg_color=palette["accent"],
                    button_color=palette["border"],
                    button_hover_color=palette["accent_hover"],
                    text_color=palette["on_accent"],
                    dropdown_fg_color=palette["surface"],
                    dropdown_hover_color=palette["border"],
                    dropdown_text_color=palette["text"],
                )
            elif isinstance(widget, ctk.CTkSegmentedButton):
                widget.configure(
                    fg_color=palette["surface"],
                    selected_color=palette["tab_accent"],
                    selected_hover_color=palette["border"],
                    unselected_color=palette["surface"],
                    unselected_hover_color=palette["surface_alt"],
                    text_color=palette["text"],
                )
            elif isinstance(widget, ctk.CTkScrollbar):
                widget.configure(
                    fg_color="transparent",
                    button_color=palette["border"],
                    button_hover_color=palette["muted"],
                )
            elif isinstance(widget, ctk.CTkTextbox):
                widget.configure(
                    fg_color=palette["input"],
                    border_color=palette["border"],
                    text_color=palette["text"],
                    scrollbar_button_color=palette["border"],
                    scrollbar_button_hover_color=palette["muted"],
                )
            elif isinstance(widget, ctk.CTkEntry):
                widget.configure(
                    fg_color=palette["input"],
                    border_color=palette["border"],
                    text_color=palette["text"],
                    placeholder_text_color=palette["muted"],
                )
            elif isinstance(widget, ctk.CTkButton):
                transparent = baseline.get("fg_color") == "transparent"
                widget.configure(
                    fg_color="transparent" if transparent else palette["accent"],
                    hover_color=palette["border"],
                    border_color=palette["accent"],
                    text_color=(
                        palette["text"] if transparent else palette["on_accent"]
                    ),
                )
            elif isinstance(widget, ctk.CTkLabel):
                muted = baseline.get("text_color") != default_label_color
                widget.configure(
                    fg_color="transparent",
                    text_color=palette["muted"] if muted else palette["text"],
                )
            elif isinstance(widget, ctk.CTkScrollableFrame):
                widget.configure(fg_color="transparent")
            elif isinstance(widget, ctk.CTkFrame):
                transparent = baseline.get("fg_color") == "transparent"
                widget.configure(
                    fg_color="transparent" if transparent else palette["surface"],
                    border_color=palette["border"],
                )
        self._configure_console_tags()
        self._refresh_message_counts()

    def _apply_standard_widget_colors(self) -> None:
        theme = STANDARD_THEME
        default_umbra_label = ctk.ThemeManager.theme["CTkLabel"]["text_color"]

        for widget, baseline in self._theme_baseline.items():
            if not widget.winfo_exists():
                continue
            if widget is self:
                widget.configure(fg_color=theme["CTk"]["fg_color"])
            elif isinstance(widget, ctk.CTkTabview):
                tabs = theme["CTkSegmentedButton"]
                widget.configure(
                    fg_color=theme["CTkFrame"]["fg_color"],
                    border_color=theme["CTkFrame"]["border_color"],
                    segmented_button_fg_color=tabs["fg_color"],
                    segmented_button_selected_color=tabs["selected_color"],
                    segmented_button_selected_hover_color=tabs[
                        "selected_hover_color"
                    ],
                    segmented_button_unselected_color=tabs["unselected_color"],
                    segmented_button_unselected_hover_color=tabs[
                        "unselected_hover_color"
                    ],
                    text_color=tabs["text_color"],
                )
            elif isinstance(widget, ctk.CTkOptionMenu):
                menu = theme["CTkOptionMenu"]
                dropdown = theme["DropdownMenu"]
                widget.configure(
                    fg_color=menu["fg_color"],
                    button_color=menu["button_color"],
                    button_hover_color=menu["button_hover_color"],
                    text_color=menu["text_color"],
                    dropdown_fg_color=dropdown["fg_color"],
                    dropdown_hover_color=dropdown["hover_color"],
                    dropdown_text_color=dropdown["text_color"],
                )
            elif isinstance(widget, ctk.CTkSegmentedButton):
                segmented = theme["CTkSegmentedButton"]
                widget.configure(
                    fg_color=segmented["fg_color"],
                    selected_color=segmented["selected_color"],
                    selected_hover_color=segmented["selected_hover_color"],
                    unselected_color=segmented["unselected_color"],
                    unselected_hover_color=segmented["unselected_hover_color"],
                    text_color=segmented["text_color"],
                )
            elif isinstance(widget, ctk.CTkScrollbar):
                scrollbar = theme["CTkScrollbar"]
                widget.configure(
                    fg_color=scrollbar["fg_color"],
                    button_color=scrollbar["button_color"],
                    button_hover_color=scrollbar["button_hover_color"],
                )
            elif isinstance(widget, ctk.CTkTextbox):
                textbox = theme["CTkTextbox"]
                widget.configure(
                    fg_color=textbox["fg_color"],
                    border_color=textbox["border_color"],
                    text_color=textbox["text_color"],
                    scrollbar_button_color=textbox["scrollbar_button_color"],
                    scrollbar_button_hover_color=textbox[
                        "scrollbar_button_hover_color"
                    ],
                )
            elif isinstance(widget, ctk.CTkEntry):
                entry = theme["CTkEntry"]
                widget.configure(
                    fg_color=entry["fg_color"],
                    border_color=entry["border_color"],
                    text_color=entry["text_color"],
                    placeholder_text_color=entry["placeholder_text_color"],
                )
            elif isinstance(widget, ctk.CTkButton):
                button = theme["CTkButton"]
                transparent = baseline.get("fg_color") == "transparent"
                widget.configure(
                    fg_color="transparent" if transparent else button["fg_color"],
                    hover_color=button["hover_color"],
                    border_color=button["border_color"],
                    text_color=button["text_color"],
                )
            elif isinstance(widget, ctk.CTkLabel):
                muted = baseline.get("text_color") != default_umbra_label
                widget.configure(
                    fg_color="transparent",
                    text_color=(
                        ("gray38", "gray68")
                        if muted
                        else theme["CTkLabel"]["text_color"]
                    ),
                )
            elif isinstance(widget, ctk.CTkScrollableFrame):
                widget.configure(fg_color="transparent")
            elif isinstance(widget, ctk.CTkFrame):
                transparent = baseline.get("fg_color") == "transparent"
                widget.configure(
                    fg_color=(
                        "transparent"
                        if transparent
                        else theme["CTkFrame"]["fg_color"]
                    ),
                    border_color=theme["CTkFrame"]["border_color"],
                )

    def _build_form(self) -> None:
        self.tabs = ctk.CTkTabview(self, corner_radius=14)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 12))

        general_tab = self.tabs.add("General")
        messages_tab = self.tabs.add("Messages")
        console_tab = self.tabs.add("Console")
        about_tab = self.tabs.add("About")
        self.tabs.set("General")

        self._build_general_tab(general_tab)
        self._build_messages_tab(messages_tab)
        self._build_console_tab(console_tab)
        self._build_about_tab(about_tab)

    def _build_console_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 6))
        toolbar.grid_columnconfigure(0, weight=1)

        status = ctk.CTkFrame(toolbar, fg_color="transparent")
        status.grid(row=0, column=0, sticky="w", padx=(8, 12))
        ctk.CTkLabel(
            status,
            text="BOT CONSOLE",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            status,
            text="•",
            text_color=("gray38", "gray68"),
        ).pack(side="left", padx=7)
        ctk.CTkLabel(
            status,
            textvariable=self.console_state_var,
            text_color=("gray38", "gray68"),
        ).pack(side="left")

        self.console_follow_button = ctk.CTkButton(
            toolbar,
            text="Follow output: On",
            width=130,
            fg_color="transparent",
            border_width=1,
            command=self._toggle_console_follow,
        )
        self.console_follow_button.grid(row=0, column=1, padx=(6, 8))
        self.console_clear_button = ctk.CTkButton(
            toolbar,
            text="Clear console",
            width=110,
            fg_color="transparent",
            border_width=1,
            command=self._clear_console,
        )
        self.console_clear_button.grid(row=0, column=2, padx=(0, 8))

        self.console_host = ctk.CTkFrame(tab, fg_color="transparent")
        self.console_host.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=8,
            pady=(0, 8),
        )
        self.console_host.grid_columnconfigure(0, weight=1)
        self.console_host.grid_rowconfigure(0, weight=1)

        self.console_view = ConsoleView(self.console_host)
        self.console_view.grid(
            row=0,
            column=0,
            sticky="nsew",
        )
        self._configure_console_tags()
        self._append_console(
            "Umbra console ready. Start the bot to stream live output here.\n",
            tag="system",
        )

    def _configure_console_tags(self) -> None:
        if not hasattr(self, "console_view"):
            return
        dark = ctk.get_appearance_mode() == "Dark"
        if self.appearance_menu.get() == "Umbra":
            background = "#211820"
            foreground = "#ffffe7"
        else:
            index = 1 if dark else 0
            background = STANDARD_THEME["CTkTextbox"]["fg_color"][index]
            foreground = STANDARD_THEME["CTkTextbox"]["text_color"][index]
        self.console_view.set_palette(
            background=background,
            foreground=foreground,
            system="#8e9b9d" if dark else "#596367",
            success="#8bd49c" if dark else "#177245",
            warning="#f0c674" if dark else "#8a5d00",
            error="#ff8d85" if dark else "#b42318",
        )

    def _append_console(self, value: str, *, tag: str | None = None) -> None:
        if not value or not hasattr(self, "console_view"):
            return
        cleaned = ANSI_ESCAPE.sub("", value).replace("\r\n", "\n")
        for line in cleaned.splitlines(keepends=True):
            line_tag = tag or self._console_line_tag(line)
            self.console_view.append(line, line_tag)

    @staticmethod
    def _console_line_tag(line: str) -> str | None:
        lowered = line.lower()
        if any(word in lowered for word in ("error", "exception", "traceback")):
            return "error"
        if "warning" in lowered or "warn:" in lowered:
            return "warning"
        if any(
            phrase in lowered
            for phrase in ("logged in", "ready", "synced", "connected")
        ):
            return "success"
        return None

    def _clear_console(self) -> None:
        self.console_view.clear()
        self.status_var.set("Console cleared")

    def _clear_console_shortcut(self, _event: object) -> str:
        self._clear_console()
        return "break"

    def _toggle_console_follow(self) -> None:
        self.console_following = not self.console_following
        state = "On" if self.console_following else "Off"
        self.console_follow_button.configure(text=f"Follow output: {state}")
        self.console_view.set_following(self.console_following)

    def _build_general_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        form = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        form.grid(row=0, column=0, sticky="nsew")
        form._scrollbar.grid_remove()
        form.grid_columnconfigure(0, weight=1)
        self.general_form = form

        account = self._section(
            form,
            0,
            "Connection",
            "The token is stored locally in config/config.jsonc.",
        )
        account.grid_columnconfigure(0, weight=1)
        self._field_label(account, "Application token", 2)
        token_row = ctk.CTkFrame(account, fg_color="transparent")
        token_row.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 18))
        token_row.grid_columnconfigure(0, weight=1)
        self.token_entry = ctk.CTkEntry(
            token_row,
            textvariable=self.token_var,
            show="•",
            placeholder_text="Paste the application token",
            height=38,
        )
        self.token_entry.grid(row=0, column=0, sticky="ew")
        self.token_button = ctk.CTkButton(
            token_row,
            text="Show",
            width=78,
            height=38,
            command=self._toggle_token,
        )
        self.token_button.grid(row=0, column=1, padx=(10, 0))

        behavior = self._section(
            form,
            1,
            "Command behavior",
            "Use whole seconds for both cooldown durations.",
        )
        for column in range(4):
            behavior.grid_columnconfigure(column, weight=1)

        fields = (
            ("Prefix", self.prefix_var, "!"),
            ("Maximum uses", self.max_uses_var, "3"),
            ("Window (seconds)", self.wait_seconds_var, "180"),
            ("Block (seconds)", self.block_seconds_var, "900"),
        )
        for column, (label, variable, placeholder) in enumerate(fields):
            ctk.CTkLabel(behavior, text=label, font=ctk.CTkFont(weight="bold")).grid(
                row=2, column=column, sticky="w", padx=(20 if column == 0 else 8, 8)
            )
            ctk.CTkEntry(
                behavior,
                textvariable=variable,
                placeholder_text=placeholder,
                height=38,
            ).grid(
                row=3,
                column=column,
                sticky="ew",
                padx=(20 if column == 0 else 8, 20 if column == 3 else 8),
                pady=(5, 18),
            )

    def _build_messages_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        form = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        form.grid(row=0, column=0, sticky="nsew")
        form._scrollbar.grid_remove()
        form.grid_columnconfigure(0, weight=1)
        self.messages_form = form

        messages = self._section(
            form,
            0,
            "Message templates",
            "Plain text and Discord markdown are supported • 2,000 character maximum.",
        )
        messages.grid_columnconfigure(0, weight=1)
        chooser = ctk.CTkFrame(messages, fg_color="transparent")
        chooser.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 7))
        chooser.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            chooser,
            text="Message being edited",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        self.message_count_label = ctk.CTkLabel(
            chooser,
            text=f"0 / {MAX_MESSAGE_LENGTH}",
            font=ctk.CTkFont(size=11),
            text_color=("gray38", "gray68"),
        )
        self.message_count_label.grid(row=1, column=1, sticky="e", pady=(4, 0))
        self.message_editor_selector = ctk.CTkSegmentedButton(
            chooser,
            width=320,
            height=40,
            corner_radius=10,
            border_width=1,
            values=["Standard", "Notification"],
            dynamic_resizing=False,
            fg_color="#211820",
            selected_color="#697477",
            selected_hover_color="#819093",
            unselected_color="#302330",
            unselected_hover_color="#291925",
            text_color="#ffffe7",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._select_message_editor,
        )
        self.message_editor_selector.grid(row=0, column=1, sticky="e")
        self.message_editor_selector.set("Standard")

        editor_host = ctk.CTkFrame(messages, fg_color="transparent")
        editor_host.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 18))
        editor_host.grid_columnconfigure(0, weight=1)
        self.pm_text = LimitedTextbox(
            editor_host,
            height=300,
            wrap="word",
            max_length=MAX_MESSAGE_LENGTH,
        )
        self.pingpm_text = LimitedTextbox(
            editor_host,
            height=300,
            wrap="word",
            max_length=MAX_MESSAGE_LENGTH,
        )
        self.pm_text.grid(row=0, column=0, sticky="ew")
        self.pingpm_text.grid(row=0, column=0, sticky="ew")
        self.pingpm_text.grid_remove()
        self.active_message_textbox = self.pm_text

        self._discord_preview(messages, row=4)

    def _discord_preview(
        self,
        parent: ctk.CTkFrame,
        row: int,
    ) -> None:
        preview_controls = ctk.CTkFrame(parent, fg_color="transparent")
        preview_controls.grid(
            row=row,
            column=0,
            sticky="ew",
            padx=20,
            pady=(2, 6),
        )
        preview_controls.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            preview_controls,
            text="DISCORD PREVIEW",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray38", "gray68"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            preview_controls,
            text="Render size",
            text_color=("gray38", "gray68"),
        ).grid(row=0, column=1, sticky="e", padx=(12, 7))
        self.preview_scaling_menu = ctk.CTkOptionMenu(
            preview_controls,
            values=["50%", "75%", "90%", "100%", "110%", "125%", "150%", "200%"],
            width=86,
            command=self._apply_preview_zoom,
        )
        self.preview_scaling_menu.set(f"{self.preview_scaling_percent}%")
        self.preview_scaling_menu.grid(row=0, column=2, sticky="e")

        preview = ctk.CTkFrame(
            parent,
            corner_radius=8,
            fg_color="#313338",
            border_width=1,
            border_color="#3f4147",
        )
        preview.grid(
            row=row + 1,
            column=0,
            sticky="nsew",
            padx=20,
            pady=(0, 20),
        )
        preview.grid_columnconfigure(1, weight=1)

        avatar = ctk.CTkLabel(
            preview,
            text="",
            image=self.umbra_avatar_image,
            fg_color="transparent",
        )
        avatar.grid(row=0, column=0, rowspan=2, sticky="n", padx=(12, 10), pady=12)

        header = ctk.CTkFrame(preview, fg_color="transparent")
        header.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=(12, 1))
        ctk.CTkLabel(
            header,
            text="Umbra",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#f2f3f5",
        ).pack(side="left")
        ctk.CTkLabel(
            header,
            text="APP",
            width=30,
            height=16,
            corner_radius=3,
            fg_color="#5865f2",
            text_color="#ffffff",
            font=ctk.CTkFont(size=9, weight="bold"),
        ).pack(side="left", padx=(5, 6))
        ctk.CTkLabel(
            header,
            text=f"Today at {datetime.now().strftime('%I:%M %p').lstrip('0')}",
            text_color="#949ba4",
            font=ctk.CTkFont(size=10),
        ).pack(side="left")

        message = DiscordMarkdownView(
            preview,
        )
        message.set_scaling(self.preview_scaling_percent)
        message.grid(row=1, column=1, sticky="nsew", padx=(0, 12), pady=(0, 12))
        self.discord_preview = message

        for widget in (preview, avatar, header, *header.winfo_children(), message):
            widget._preserve_theme_colors = True

        for textbox in (self.pm_text, self.pingpm_text):
            self._message_previews[textbox] = message
            textbox._textbox.bind(
                "<<Modified>>",
                lambda _event, field=textbox: self._message_text_changed(field),
                add="+",
            )
            textbox._textbox.edit_modified(False)

    def _select_message_editor(self, selection: str) -> None:
        selected = self.pm_text if selection == "Standard" else self.pingpm_text
        self.pm_text.grid_remove()
        self.pingpm_text.grid_remove()
        selected.grid(row=0, column=0, sticky="ew")
        self.active_message_textbox = selected
        self.message_editor_selector.set(selection)
        self._update_message_count(selected)
        self._update_message_preview(selected)

    def _apply_preview_zoom(self, value: str) -> None:
        try:
            percent = int(value.removesuffix("%"))
        except ValueError:
            return
        self.preview_scaling_percent = max(50, min(200, percent))
        self.preview_scaling_menu.set(f"{self.preview_scaling_percent}%")
        self.discord_preview.set_scaling(self.preview_scaling_percent)
        self._persist_scale_preferences()
        self.status_var.set(f"Discord preview scaling: {self.preview_scaling_percent}%")

    def _persist_scale_preferences(self) -> None:
        try:
            updated = deepcopy(self.current_config or load_config())
            updated.setdefault("interface", {}).update(
                {
                    "scaling_percent": self.scaling_percent,
                    "preview_scaling_percent": self.preview_scaling_percent,
                }
            )
            save_config(updated)
            self.current_config = updated
        except Exception:
            # A later explicit Save still gets another chance to persist these
            # values and will report any filesystem error to the user.
            return

    def _message_text_changed(self, textbox: ctk.CTkTextbox) -> None:
        if not textbox._textbox.edit_modified():
            return
        textbox._textbox.edit_modified(False)
        self._update_message_count(textbox)
        self._update_message_preview(textbox)

    def _update_message_count(self, textbox: ctk.CTkTextbox) -> None:
        if textbox is not self.active_message_textbox:
            return
        length = len(textbox.get("1.0", "end-1c"))
        if length > MAX_MESSAGE_LENGTH:
            color = ("#b42318", "#ff8d85")
        elif length == MAX_MESSAGE_LENGTH:
            color = ("#9a6700", "#f0c674")
        else:
            color = ("gray38", "gray68")
        self.message_count_label.configure(
            text=f"{length} / {MAX_MESSAGE_LENGTH}",
            text_color=color,
        )

    def _refresh_message_counts(self) -> None:
        if hasattr(self, "active_message_textbox"):
            self._update_message_count(self.active_message_textbox)

    def _update_message_preview(self, textbox: ctk.CTkTextbox) -> None:
        if textbox is not self.active_message_textbox:
            return
        value = textbox.get("1.0", "end-1c")
        preview = self._message_previews.get(textbox)
        if preview is None:
            return
        preview.set_message(value)

    def _build_about_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        card = ctk.CTkFrame(tab, corner_radius=14)
        card.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            card,
            text=APP_TITLE,
            font=ctk.CTkFont(size=26, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=24, pady=(24, 2))
        ctk.CTkLabel(
            card,
            text="Umbra Development desktop configuration utility.",
            text_color=("gray38", "gray68"),
        ).grid(row=1, column=0, sticky="w", padx=24)
        ctk.CTkLabel(
            card,
            text=ORGANIZATION_URL,
            text_color=("#697477", "#8e9b9d"),
        ).grid(row=2, column=0, sticky="w", padx=24, pady=(6, 0))
        ctk.CTkLabel(
            card,
            text=f"Configuration\n{CONFIG_PATH}",
            justify="left",
            anchor="w",
        ).grid(row=3, column=0, sticky="ew", padx=24, pady=(28, 0))
        ctk.CTkLabel(
            card,
            text=(
                "Shortcuts\n"
                "Ctrl/Cmd + S    Save settings\n"
                "Ctrl/Cmd + +/-  Adjust interface scale\n"
                "Ctrl/Cmd + 0    Reset interface scale\n"
                "Ctrl/Cmd + wheel  Adjust interface scale"
            ),
            justify="left",
            anchor="w",
        ).grid(row=4, column=0, sticky="ew", padx=24, pady=(28, 24))

    def _show_splash(self) -> None:
        splash_background = "#382837"
        self.splash = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color=splash_background,
        )
        self.splash.place(x=0, y=0, relwidth=1, relheight=1)
        self.splash.lift()
        self.splash.grid_columnconfigure(0, weight=1)
        self.splash.grid_rowconfigure(0, weight=1)

        self.splash_canvas = tk.Canvas(
            self.splash,
            background=splash_background,
            highlightthickness=0,
            borderwidth=0,
        )
        self.splash_canvas.grid(row=0, column=0, sticky="nsew")
        self.splash_canvas.bind(
            "<Button-1>", lambda _event: self._dismiss_splash()
        )

        self._splash_started = time.perf_counter()
        self._splash_after_id: str | None = None
        self._animate_splash()

    def _animate_splash(self) -> None:
        if not self.splash.winfo_exists():
            return
        self._splash_after_id = None

        elapsed = time.perf_counter() - self._splash_started
        duration = 2.95
        if elapsed >= duration:
            self._dismiss_splash()
            return

        canvas = self.splash_canvas
        width = max(canvas.winfo_width(), self.winfo_width())
        height = max(canvas.winfo_height(), self.winfo_height())
        center_x = width / 2
        center_y = height / 2 - 12
        canvas.delete("all")

        background = "#382837"
        accent = "#ffffe7"
        muted = "#8e9b9d"
        wave = "#697477"
        fade = min(1.0, max(0.0, (elapsed - 2.25) / 0.65))
        text_visibility = 1.0 - fade
        logo_visibility = 1.0 - fade

        logo_reveal = min(1.0, max(0.0, (elapsed - 0.08) / 0.62))
        # Ease-out-back gives the logo a quick overshoot before settling.
        overshoot = 1.70158
        shifted = logo_reveal - 1
        logo_eased = 1 + (overshoot + 1) * shifted**3 + overshoot * shifted**2
        mark_size = max(1, round(92 + 128 * logo_eased))

        resized_logo = self.umbra_logo_source.resize(
            (mark_size, mark_size),
            Image.Resampling.LANCZOS,
        )
        if logo_visibility < 1:
            fade_layer = Image.new("RGB", resized_logo.size, background)
            resized_logo = Image.blend(
                fade_layer,
                resized_logo,
                logo_visibility,
            )
        self._splash_logo_image = ImageTk.PhotoImage(resized_logo)
        logo_center_y = center_y - 45
        canvas.create_image(
            center_x,
            logo_center_y,
            image=self._splash_logo_image,
        )

        ring_reveal = min(1.0, elapsed / 0.9)
        ring_radius = 118
        ring_box = (
            center_x - ring_radius,
            logo_center_y - ring_radius,
            center_x + ring_radius,
            logo_center_y + ring_radius,
        )
        canvas.create_arc(
            ring_box,
            start=-90 + elapsed * 24,
            extent=325 * ring_reveal,
            style="arc",
            outline=self._mix_color(
                background,
                wave,
                0.72 * logo_visibility,
            ),
            width=3,
        )

        word_y = center_y + 125
        text_reveal = min(1.0, max(0.0, (elapsed - 0.9) / 0.5))
        text_eased = 1 - (1 - text_reveal) ** 3
        word = SPLASH_WORD

        glow_color = self._mix_color(
            background,
            wave,
            0.34 * text_reveal * text_visibility,
        )
        word_size = max(1, round(38 + 28 * text_eased))
        for offset in (4, 2):
            canvas.create_text(
                center_x,
                word_y + offset,
                text=word,
                fill=glow_color,
                font=("TkDefaultFont", word_size + offset, "bold"),
            )
        canvas.create_text(
            center_x,
            word_y,
            text=word,
            fill=self._mix_color(
                background,
                accent,
                text_reveal * text_visibility,
            ),
            font=("TkDefaultFont", word_size, "bold"),
        )

        subtitle_reveal = min(1.0, max(0.0, (elapsed - 1.35) / 0.35))
        canvas.create_text(
            center_x,
            center_y + 209,
            text="UMBRA DEVELOPMENT",
            fill=self._mix_color(
                background,
                muted,
                subtitle_reveal * text_visibility,
            ),
            font=("TkDefaultFont", 13, "bold"),
        )
        line_half_width = 68 * subtitle_reveal
        canvas.create_line(
            center_x - line_half_width,
            center_y + 180,
            center_x + line_half_width,
            center_y + 180,
            fill=self._mix_color(
                background,
                accent,
                subtitle_reveal * text_visibility,
            ),
            width=2,
        )

        self._splash_after_id = self.after(16, self._animate_splash)

    @staticmethod
    def _mix_color(first: str, second: str, amount: float) -> str:
        amount = max(0.0, min(1.0, amount))
        first_rgb = tuple(int(first[index : index + 2], 16) for index in (1, 3, 5))
        second_rgb = tuple(int(second[index : index + 2], 16) for index in (1, 3, 5))
        mixed = tuple(
            round(start + (end - start) * amount)
            for start, end in zip(first_rgb, second_rgb, strict=True)
        )
        return f"#{mixed[0]:02x}{mixed[1]:02x}{mixed[2]:02x}"

    def _dismiss_splash(self) -> None:
        if getattr(self, "_splash_after_id", None) is not None:
            self.after_cancel(self._splash_after_id)
            self._splash_after_id = None
        if hasattr(self, "splash") and self.splash.winfo_exists():
            self.splash.destroy()

    @staticmethod
    def _section(
        parent: ctk.CTkBaseClass,
        row: int,
        title: str,
        description: str,
    ) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, corner_radius=14)
        frame.grid(row=row, column=0, sticky="ew", padx=8, pady=8)
        ctk.CTkLabel(
            frame,
            text=title,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=20, pady=(17, 0))
        ctk.CTkLabel(
            frame,
            text=description,
            text_color=("gray38", "gray68"),
        ).grid(row=1, column=0, columnspan=4, sticky="w", padx=20, pady=(2, 14))
        return frame

    @staticmethod
    def _field_label(parent: ctk.CTkFrame, text: str, row: int) -> None:
        ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(weight="bold")).grid(
            row=row, column=0, sticky="w", padx=20, pady=(0, 5)
        )

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, corner_radius=0)
        footer.grid(row=2, column=0, sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            footer,
            textvariable=self.status_var,
            anchor="w",
            text_color=("gray35", "gray72"),
        ).grid(row=0, column=0, sticky="ew", padx=28, pady=18)
        self.bot_button = ctk.CTkButton(
            footer,
            text="Start bot",
            width=110,
            command=self._toggle_bot,
        )
        self.bot_button.grid(row=0, column=1, padx=(8, 8), pady=14)
        self.reload_button = ctk.CTkButton(
            footer,
            text="Reload",
            width=100,
            fg_color="transparent",
            hover_color="#697477",
            border_color="#ffffe7",
            border_width=1,
            text_color="#ffffe7",
            command=self.load,
        )
        self.reload_button.grid(row=0, column=2, padx=(0, 8), pady=14)
        self.save_button = ctk.CTkButton(
            footer,
            text="Save settings",
            width=130,
            command=self.save,
        )
        self.save_button.grid(row=0, column=3, padx=(0, 28), pady=14)

    def _toggle_bot(self) -> None:
        if self.bot_process is not None and self.bot_process.poll() is None:
            self._stop_bot()
        else:
            self._start_bot()

    def _bot_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, PACKAGED_BOT_ARGUMENT]
        return [sys.executable, "-m", "umbra_bot"]

    def _start_bot(self) -> None:
        if not self.save():
            return

        try:
            command = self._bot_command()
            self._bot_log_path.parent.mkdir(parents=True, exist_ok=True)
            self._bot_log_file = self._bot_log_path.open(
                "a", encoding="utf-8", buffering=1
            )
            started_line = (
                "\n--- Umbra bot started "
                f"{datetime.now().isoformat(timespec='seconds')} ---\n"
            )
            self._bot_log_file.write(started_line)
            self._bot_log_file.flush()
            self._bot_log_reader = self._bot_log_path.open(
                "r", encoding="utf-8", errors="replace"
            )
            self._bot_log_reader.seek(0, 2)
            self._append_console(started_line, tag="system")
            options: dict[str, object] = {
                "cwd": CONFIG_PATH.parent.parent,
                "stdout": self._bot_log_file,
                "stderr": subprocess.STDOUT,
            }
            if sys.platform == "win32":
                options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                options["start_new_session"] = True
            self.bot_process = subprocess.Popen(command, **options)
        except (OSError, ValueError) as error:
            self._close_bot_log()
            self._append_console(
                f"Could not start the bot: {error}\n", tag="error"
            )
            messagebox.showerror("Could not start bot", str(error), parent=self)
            self.status_var.set("Could not start the bot")
            self.console_state_var.set("Failed to start")
            return

        self._bot_stop_requested = False
        self.bot_button.configure(text="Stop bot", state="normal")
        self.status_var.set(f"Bot running (PID {self.bot_process.pid})")
        self.console_state_var.set(f"Running • PID {self.bot_process.pid}")
        self._append_console(
            f"Bot process started with PID {self.bot_process.pid}.\n",
            tag="success",
        )
        self._schedule_bot_poll()

    def _stop_bot(self) -> None:
        process = self.bot_process
        if process is None or process.poll() is not None:
            return
        self._bot_stop_requested = True
        self._bot_stop_deadline = time.monotonic() + 3
        self.bot_button.configure(text="Stopping…", state="disabled")
        self.status_var.set("Stopping bot…")
        self.console_state_var.set("Stopping…")
        self._append_console("Stopping bot…\n", tag="warning")
        try:
            process.terminate()
        except OSError:
            pass
        self._schedule_bot_poll()

    def _schedule_bot_poll(self) -> None:
        if self._bot_poll_after_id is None:
            self._bot_poll_after_id = self.after(250, self._poll_bot)

    def _poll_bot(self) -> None:
        self._bot_poll_after_id = None
        process = self.bot_process
        if process is None:
            return

        exit_code = process.poll()
        self._drain_bot_log()
        if exit_code is None:
            if (
                self._bot_stop_requested
                and time.monotonic() >= self._bot_stop_deadline
            ):
                try:
                    process.kill()
                except OSError:
                    pass
            self._schedule_bot_poll()
            return

        self._drain_bot_log()
        stopped_by_user = self._bot_stop_requested
        self.bot_process = None
        self._bot_stop_requested = False
        self._close_bot_log()
        self.bot_button.configure(text="Start bot", state="normal")
        if stopped_by_user:
            self.status_var.set("Bot stopped")
            self.console_state_var.set("Stopped")
            self._append_console("Bot stopped.\n", tag="system")
        elif exit_code == 0:
            self.status_var.set("Bot stopped")
            self.console_state_var.set("Stopped")
            self._append_console("Bot process exited normally.\n", tag="system")
        else:
            self.status_var.set(
                f"Bot exited with code {exit_code}; see {self._bot_log_path}"
            )
            self.console_state_var.set(f"Exited • code {exit_code}")
            self._append_console(
                f"Bot exited with code {exit_code}. Full log: "
                f"{self._bot_log_path}\n",
                tag="error",
            )

    def _drain_bot_log(self) -> None:
        if self._bot_log_reader is None:
            return
        try:
            output = self._bot_log_reader.read()
        except (OSError, ValueError) as error:
            self._append_console(f"Could not read bot output: {error}\n", tag="error")
            return
        if output:
            self._append_console(output)

    def _close_bot_log(self) -> None:
        if self._bot_log_file is not None:
            try:
                self._bot_log_file.flush()
            except (OSError, ValueError):
                pass
            self._bot_log_file.close()
            self._bot_log_file = None
        self._drain_bot_log()
        if self._bot_log_reader is not None:
            self._bot_log_reader.close()
            self._bot_log_reader = None

    def _on_close(self) -> None:
        if self._bot_poll_after_id is not None:
            self.after_cancel(self._bot_poll_after_id)
            self._bot_poll_after_id = None
        process = self.bot_process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            except OSError:
                pass
        self._drain_bot_log()
        self._close_bot_log()
        self.destroy()

    def _toggle_token(self) -> None:
        self.token_visible = not self.token_visible
        self.token_entry.configure(show="" if self.token_visible else "•")
        self.token_button.configure(text="Hide" if self.token_visible else "Show")

    def _bind_zoom_shortcuts(self) -> None:
        for sequence in (
            "<Control-plus>",
            "<Control-equal>",
            "<Control-KP_Add>",
            "<Command-plus>",
            "<Command-equal>",
        ):
            self.bind(sequence, lambda _event: self._zoom_by(10))
        for sequence in (
            "<Control-minus>",
            "<Control-KP_Subtract>",
            "<Command-minus>",
        ):
            self.bind(sequence, lambda _event: self._zoom_by(-10))
        self.bind("<Control-0>", lambda _event: self._apply_zoom("100%"))
        self.bind("<Command-0>", lambda _event: self._apply_zoom("100%"))

        # Windows and macOS report wheel movement through MouseWheel. Linux/X11
        # reports the wheel as buttons 4 and 5 instead.
        self.bind_all("<Control-MouseWheel>", self._handle_zoom_wheel)
        self.bind_all("<Command-MouseWheel>", self._handle_zoom_wheel)
        self.bind_all("<Control-Button-4>", self._handle_zoom_wheel)
        self.bind_all("<Control-Button-5>", self._handle_zoom_wheel)

    def _zoom_by(self, change: int) -> str:
        new_percent = max(50, min(200, self.scaling_percent + change))
        if new_percent == self.scaling_percent:
            return "break"
        self._apply_zoom(f"{new_percent}%")
        return "break"

    def _handle_zoom_wheel(self, event: object) -> str:
        wheel_button = getattr(event, "num", None)
        wheel_delta = getattr(event, "delta", 0)
        if wheel_button == 4 or wheel_delta > 0:
            return self._zoom_by(10)
        if wheel_button == 5 or wheel_delta < 0:
            return self._zoom_by(-10)
        return "break"

    def _apply_zoom(self, value: str) -> str:
        try:
            percent = int(value.removesuffix("%"))
        except ValueError:
            return "break"

        new_percent = max(50, min(200, percent))
        if new_percent == self.scaling_percent:
            return "break"

        self.scaling_percent = new_percent
        ctk.set_widget_scaling(new_percent / 100)
        self.scaling_menu.set(f"{new_percent}%")
        self._persist_scale_preferences()
        self.status_var.set(f"Interface scaling: {new_percent}%")
        return "break"

    def load(self) -> None:
        try:
            self.current_config = load_config()
            basic = self.current_config.get("basic_config", {})
            messages = self.current_config.get("messages", {})

            self.token_var.set(str(self.current_config.get("token", "")))
            self.prefix_var.set(str(basic.get("prefix", "!")))
            self.max_uses_var.set(str(basic.get("max_uses", 3)))
            self.wait_seconds_var.set(str(basic.get("wait_seconds", 180)))
            self.block_seconds_var.set(str(basic.get("b_seconds", 900)))
            self._replace_text(self.pm_text, str(messages.get("pm", "")))
            self._replace_text(
                self.pingpm_text, str(messages.get("pingpm", ""))
            )
            self.status_var.set(f"Loaded {CONFIG_PATH}")
        except Exception as error:
            messagebox.showerror("Could not load settings", str(error), parent=self)
            self.status_var.set("Could not load the configuration")

    def _replace_text(self, textbox: ctk.CTkTextbox, value: str) -> None:
        if isinstance(textbox, LimitedTextbox):
            # Load legacy oversized values intact so the counter can flag them
            # and the user can decide how to shorten them before saving.
            textbox.replace_contents(value, enforce_limit=False)
        else:
            textbox.delete("1.0", "end")
            textbox.insert("1.0", value)
        self._update_message_count(textbox)
        self._update_message_preview(textbox)

    def save(self) -> bool:
        try:
            prefix = self.prefix_var.get().strip()
            if not prefix:
                raise ValueError("Prefix cannot be empty.")

            max_uses = self._positive_integer(
                self.max_uses_var.get(), "Maximum uses"
            )
            wait_seconds = self._positive_integer(
                self.wait_seconds_var.get(), "Window seconds"
            )
            block_seconds = self._positive_integer(
                self.block_seconds_var.get(), "Block seconds"
            )

            standard_message = self.pm_text.get("1.0", "end-1c")
            notification_message = self.pingpm_text.get("1.0", "end-1c")
            if len(standard_message) > MAX_MESSAGE_LENGTH:
                raise ValueError(
                    f"Standard message cannot exceed {MAX_MESSAGE_LENGTH} characters."
                )
            if len(notification_message) > MAX_MESSAGE_LENGTH:
                raise ValueError(
                    "Notification message cannot exceed "
                    f"{MAX_MESSAGE_LENGTH} characters."
                )

            updated = deepcopy(self.current_config)
            updated["token"] = self.token_var.get().strip()
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
                    "pingpm": notification_message,
                }
            )
            updated.setdefault("interface", {}).update(
                {
                    "scaling_percent": self.scaling_percent,
                    "preview_scaling_percent": self.preview_scaling_percent,
                }
            )
            save_config(updated)
            self.current_config = updated
            self.status_var.set("Settings saved successfully")
            return True
        except ValueError as error:
            messagebox.showwarning("Check your settings", str(error), parent=self)
            return False
        except Exception as error:
            messagebox.showerror("Could not save settings", str(error), parent=self)
            self.status_var.set("Could not save the configuration")
            return False

    @staticmethod
    def _positive_integer(value: str, label: str) -> int:
        try:
            result = int(value)
        except ValueError as error:
            raise ValueError(f"{label} must be a whole number.") from error
        if result < 1:
            raise ValueError(f"{label} must be at least 1.")
        return result


def main() -> None:
    SettingsApp().mainloop()


if __name__ == "__main__":
    main()

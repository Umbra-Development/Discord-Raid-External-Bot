"""A small native-Tk renderer for Discord's documented message markup."""

from __future__ import annotations

import re
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from datetime import datetime


DISCORD_BACKGROUND = "#313338"
DISCORD_TEXT = "#dbdee1"
DISCORD_MUTED = "#949ba4"
DISCORD_LINK = "#00a8fc"
DISCORD_MENTION = "#c9cdfb"
DISCORD_MENTION_BACKGROUND = "#3c4270"
DISCORD_CODE_BACKGROUND = "#2b2d31"
DISCORD_QUOTE = "#4e5058"
DISCORD_SPOILER = "#1e1f22"


@dataclass(frozen=True)
class TextRun:
    text: str
    styles: tuple[str, ...] = ()


_SPECIAL_TOKEN = re.compile(
    r"<@!?\d+>|<@&\d+>|<#\d+>|</[^:>]+:\d+>|"
    r"<a?:[A-Za-z0-9_]+:\d+>|<t:\d+(?::[tTdDfFsSR])?>|"
    r"https?://[^\s<>]+|@(?:everyone|here)"
)
_LIST_ITEM = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")
_CODE_LANGUAGE = re.compile(r"[A-Za-z0-9_+.-]+")


def _unescaped_index(value: str, delimiter: str, start: int) -> int:
    position = value.find(delimiter, start)
    while position >= 0:
        backslashes = 0
        cursor = position - 1
        while cursor >= 0 and value[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return position
        position = value.find(delimiter, position + len(delimiter))
    return -1


def _timestamp_display(token: str) -> str:
    match = re.fullmatch(r"<t:(\d+)(?::([tTdDfFsSR]))?>", token)
    if match is None:
        return token
    moment = datetime.fromtimestamp(int(match.group(1)))
    style = match.group(2) or "f"
    if style == "t":
        return moment.strftime("%I:%M %p").lstrip("0")
    if style == "T":
        return moment.strftime("%I:%M:%S %p").lstrip("0")
    if style == "d":
        return moment.strftime("%m/%d/%Y")
    if style == "D":
        return moment.strftime("%B %d, %Y").replace(" 0", " ")
    if style == "s":
        return moment.strftime("%m/%d/%Y %I:%M %p").replace(" 0", " ")
    if style == "S":
        return moment.strftime("%m/%d/%Y %I:%M:%S %p").replace(" 0", " ")
    if style == "F":
        return moment.strftime("%A, %B %d, %Y %I:%M %p").replace(" 0", " ")
    if style == "R":
        seconds = round((moment - datetime.now()).total_seconds())
        future = seconds > 0
        seconds = abs(seconds)
        if seconds < 60:
            quantity, unit = seconds, "second"
        elif seconds < 3600:
            quantity, unit = round(seconds / 60), "minute"
        elif seconds < 86400:
            quantity, unit = round(seconds / 3600), "hour"
        elif seconds < 2_592_000:
            quantity, unit = round(seconds / 86400), "day"
        elif seconds < 31_536_000:
            quantity, unit = round(seconds / 2_592_000), "month"
        else:
            quantity, unit = round(seconds / 31_536_000), "year"
        suffix = "" if quantity == 1 else "s"
        return f"in {quantity} {unit}{suffix}" if future else f"{quantity} {unit}{suffix} ago"
    return moment.strftime("%B %d, %Y at %I:%M %p").replace(" 0", " ")


def _discord_token_display(token: str) -> tuple[str, tuple[str, ...]]:
    if token.startswith("<t:"):
        return _timestamp_display(token), ("timestamp",)
    if token.startswith("<@&"):
        return "@role", ("mention",)
    if token.startswith("<@"):
        return "@user", ("mention",)
    if token.startswith("<#"):
        return "#channel", ("mention",)
    if token.startswith("</"):
        return f"/{token[2:token.rfind(':')]}", ("mention",)
    if token.startswith("<:") or token.startswith("<a:"):
        parts = token.split(":")
        return f":{parts[1]}:", ("emoji",)
    if token.startswith("http"):
        return token, ("link",)
    return token, ("mention",)


def parse_inline(value: str, inherited: tuple[str, ...] = ()) -> list[TextRun]:
    runs: list[TextRun] = []
    plain: list[str] = []

    def flush() -> None:
        if plain:
            runs.append(TextRun("".join(plain), inherited))
            plain.clear()

    index = 0
    delimiters = (
        ("||", "spoiler"),
        ("***", "bold_italic"),
        ("___", "underline_italic"),
        ("**", "bold"),
        ("__", "underline"),
        ("~~", "strike"),
        ("*", "italic"),
        ("_", "italic"),
    )
    while index < len(value):
        if value[index] == "\\" and index + 1 < len(value):
            plain.append(value[index + 1])
            index += 2
            continue

        if value[index] == "`":
            closing = _unescaped_index(value, "`", index + 1)
            if closing >= 0:
                flush()
                runs.append(TextRun(value[index + 1 : closing], (*inherited, "code")))
                index = closing + 1
                continue

        if value[index] == "[":
            label_end = _unescaped_index(value, "]", index + 1)
            if label_end >= 0 and label_end + 1 < len(value) and value[label_end + 1] == "(":
                url_end = _unescaped_index(value, ")", label_end + 2)
                url = value[label_end + 2 : url_end] if url_end >= 0 else ""
                if url.startswith(("http://", "https://")):
                    flush()
                    runs.extend(
                        parse_inline(value[index + 1 : label_end], (*inherited, "link"))
                    )
                    index = url_end + 1
                    continue

        matched_delimiter = False
        for delimiter, style in delimiters:
            if not value.startswith(delimiter, index):
                continue
            closing = _unescaped_index(value, delimiter, index + len(delimiter))
            if closing < 0 or closing == index + len(delimiter):
                continue
            flush()
            runs.extend(
                parse_inline(
                    value[index + len(delimiter) : closing],
                    (*inherited, style),
                )
            )
            index = closing + len(delimiter)
            matched_delimiter = True
            break
        if matched_delimiter:
            continue

        token = _SPECIAL_TOKEN.match(value, index)
        if token is not None:
            flush()
            displayed, styles = _discord_token_display(token.group())
            runs.append(TextRun(displayed, (*inherited, *styles)))
            index = token.end()
            continue

        plain.append(value[index])
        index += 1

    flush()
    return runs


def parse_message(value: str) -> list[TextRun]:
    runs: list[TextRun] = []
    lines = value.splitlines()
    in_code_block = False
    quote_remainder = False

    for line_number, original_line in enumerate(lines):
        line = original_line
        block_styles: tuple[str, ...] = ()

        if line.startswith("```"):
            if in_code_block:
                in_code_block = False
            else:
                opening_content = line[3:]
                if opening_content.endswith("```"):
                    runs.append(TextRun(opening_content[:-3], ("code_block",)))
                    continue
                in_code_block = True
                if opening_content and _CODE_LANGUAGE.fullmatch(opening_content) is None:
                    runs.append(TextRun(opening_content, ("code_block",)))
                    if line_number < len(lines) - 1:
                        runs.append(TextRun("\n", ("code_block",)))
            continue
        if in_code_block:
            runs.append(TextRun(line, ("code_block",)))
        else:
            if line.startswith(">>> "):
                quote_remainder = True
                line = line[4:]
            elif quote_remainder:
                pass
            elif line.startswith("> "):
                line = line[2:]
                block_styles = ("quote",)
            elif line.startswith("-# "):
                line = line[3:]
                block_styles = ("subtext",)
            elif line.startswith("### "):
                line = line[4:]
                block_styles = ("heading3",)
            elif line.startswith("## "):
                line = line[3:]
                block_styles = ("heading2",)
            elif line.startswith("# "):
                line = line[2:]
                block_styles = ("heading1",)
            else:
                list_item = _LIST_ITEM.match(line)
                if list_item is not None:
                    indent, marker, line = list_item.groups()
                    bullet = marker if marker[-1] == "." else "•"
                    line = f"{indent}{bullet} {line}"
                    block_styles = ("list",)
            if quote_remainder:
                block_styles = ("quote",)
            if "quote" in block_styles:
                runs.append(TextRun("▌ ", ("quote_bar",)))
            runs.extend(parse_inline(line, block_styles))

        if line_number < len(lines) - 1:
            runs.append(TextRun("\n", block_styles))
    return runs


def split_message_blocks(value: str) -> list[tuple[str, str]]:
    """Split rich text and fenced code while preserving code whitespace."""
    blocks: list[tuple[str, str]] = []
    normal_lines: list[str] = []
    code_lines: list[str] = []
    in_code = False

    def flush(kind: str, lines: list[str]) -> None:
        if lines:
            blocks.append((kind, "\n".join(lines)))
            lines.clear()

    for line in value.splitlines():
        if line.startswith("```"):
            remainder = line[3:]
            if in_code:
                flush("code", code_lines)
                in_code = False
                if remainder:
                    normal_lines.append(remainder)
            else:
                flush("rich", normal_lines)
                if remainder.endswith("```"):
                    blocks.append(("code", remainder[:-3]))
                    continue
                in_code = True
                # A plain ASCII identifier is Discord's optional language hint.
                # Anything else after the fence is content, including LRM marks.
                if remainder and _CODE_LANGUAGE.fullmatch(remainder) is None:
                    code_lines.append(remainder)
            continue
        (code_lines if in_code else normal_lines).append(line)

    if in_code:
        flush("code", code_lines)
    else:
        flush("rich", normal_lines)
    return blocks


class DiscordMarkdownView(tk.Text):
    """Read-only rich text with distinct inline-code and code-block rendering."""

    def __init__(self, master: tk.Misc, **kwargs: object) -> None:
        super().__init__(
            master,
            height=10,
            wrap="word",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            background=DISCORD_BACKGROUND,
            foreground=DISCORD_TEXT,
            insertbackground=DISCORD_TEXT,
            cursor="arrow",
            padx=0,
            pady=0,
            takefocus=False,
            **kwargs,
        )
        self._value = ""
        self._scale = 1.0
        self._spoilers_revealed = False
        self._style_combinations: dict[str, frozenset[str]] = {}
        self._fonts: dict[str, tkfont.Font] = {}
        self._code_blocks: list[tuple[tk.Frame, tk.Text, tkfont.Font]] = []
        self.bind("<Button-1>", self._handle_click)
        self.bind("<Configure>", lambda _event: self._resize_code_blocks())
        self.set_message("")

    def set_scaling(self, percent: int) -> None:
        self._scale = percent / 100
        self._render()

    def set_message(self, value: str) -> None:
        self._value = value
        self._spoilers_revealed = False
        self._render()

    def _handle_click(self, event: tk.Event) -> str | None:
        index = self.index(f"@{event.x},{event.y}")
        if any(
            "spoiler" in self._style_combinations.get(tag, frozenset())
            for tag in self.tag_names(index)
        ):
            self._spoilers_revealed = not self._spoilers_revealed
            self._render()
            return "break"
        return None

    def _font_for(self, styles: frozenset[str]) -> tkfont.Font:
        default = tkfont.nametofont("TkDefaultFont").actual()
        fixed = tkfont.nametofont("TkFixedFont").actual()
        size = round(14 * self._scale)
        family = str(default["family"])
        weight = "normal"
        slant = "roman"
        underline = 0
        overstrike = 0

        if "code" in styles:
            family = str(fixed["family"])
            size = round(13 * self._scale)
        if "heading1" in styles:
            size, weight = round(22 * self._scale), "bold"
        elif "heading2" in styles:
            size, weight = round(20 * self._scale), "bold"
        elif "heading3" in styles:
            size, weight = round(17 * self._scale), "bold"
        elif "subtext" in styles:
            size = round(11 * self._scale)
        if "bold" in styles or "bold_italic" in styles:
            weight = "bold"
        if any(style in styles for style in ("italic", "bold_italic", "underline_italic")):
            slant = "italic"
        if "underline" in styles or "underline_italic" in styles:
            underline = 1
        if "strike" in styles:
            overstrike = 1
        return tkfont.Font(
            family=family,
            size=max(1, size),
            weight=weight,
            slant=slant,
            underline=underline,
            overstrike=overstrike,
        )

    def _configure_style(self, tag: str, styles: frozenset[str]) -> None:
        foreground = DISCORD_TEXT
        background = DISCORD_BACKGROUND
        if "subtext" in styles or "timestamp" in styles:
            foreground = DISCORD_MUTED
        if "quote_bar" in styles:
            foreground = DISCORD_QUOTE
        if "link" in styles:
            foreground = DISCORD_LINK
        if "mention" in styles:
            foreground = DISCORD_MENTION
            background = DISCORD_MENTION_BACKGROUND
        # Single-backtick code is intentionally an inline background chip.
        if "code" in styles:
            background = DISCORD_CODE_BACKGROUND
        if "spoiler" in styles and not self._spoilers_revealed:
            foreground = DISCORD_SPOILER
            background = DISCORD_SPOILER

        font = self._font_for(styles)
        self._fonts[tag] = font
        self.tag_configure(
            tag,
            foreground=foreground,
            background=background,
            font=font,
            lmargin1=10 if "quote" in styles else 0,
            lmargin2=10 if "quote" in styles else 0,
            spacing1=2 if any(style.startswith("heading") for style in styles) else 0,
        )

    def _insert_rich_text(self, value: str) -> None:
        for run in parse_message(value):
            styles = frozenset(run.styles)
            tag = "style_" + "_".join(sorted(styles)) if styles else "style_plain"
            if tag not in self._style_combinations:
                self._style_combinations[tag] = styles
                self._configure_style(tag, styles)
            self.insert("end", run.text, tag)

    def _insert_code_block(self, value: str) -> None:
        font = tkfont.Font(
            family=str(tkfont.nametofont("TkFixedFont").actual()["family"]),
            size=max(1, round(13 * self._scale)),
        )
        frame = tk.Frame(
            self,
            background=DISCORD_CODE_BACKGROUND,
            highlightbackground="#41434a",
            highlightcolor="#41434a",
            highlightthickness=1,
            borderwidth=0,
        )
        code = tk.Text(
            frame,
            height=max(1, min(20, value.count("\n") + 1)),
            width=20,
            wrap="none",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            background=DISCORD_CODE_BACKGROUND,
            foreground=DISCORD_TEXT,
            insertbackground=DISCORD_TEXT,
            font=font,
            padx=10,
            pady=8,
            cursor="arrow",
            takefocus=False,
        )
        code.insert("1.0", value)
        code.configure(state="disabled")
        code.pack(fill="x", expand=True)
        code.bind(
            "<Shift-MouseWheel>",
            lambda event, field=code: self._scroll_code_block(field, event),
        )
        code.bind(
            "<Shift-Button-4>",
            lambda event, field=code: self._scroll_code_block(field, event),
        )
        code.bind(
            "<Shift-Button-5>",
            lambda event, field=code: self._scroll_code_block(field, event),
        )

        self.window_create("end", window=frame, padx=1, pady=5)
        self._code_blocks.append((frame, code, font))
        self.after_idle(self._resize_code_blocks)

    @staticmethod
    def _scroll_code_block(code: tk.Text, event: tk.Event) -> str:
        direction = -1 if getattr(event, "num", None) == 4 else 1
        delta = getattr(event, "delta", 0)
        if delta:
            direction = -1 if delta > 0 else 1
        code.xview_scroll(direction, "units")
        return "break"

    def _resize_code_blocks(self) -> None:
        available_width = max(140, self.winfo_width() - 18)
        for frame, code, font in self._code_blocks:
            if not frame.winfo_exists():
                continue
            character_width = max(1, font.measure("0"))
            code.configure(width=max(10, available_width // character_width))

    def _render(self) -> None:
        for frame, _code, _font in self._code_blocks:
            if frame.winfo_exists():
                frame.destroy()
        self._code_blocks.clear()

        base_font = self._font_for(frozenset())
        self._fonts["base"] = base_font
        self.configure(state="normal", font=base_font)
        self.delete("1.0", "end")
        self._style_combinations.clear()

        if not self._value:
            tag = "style_empty"
            styles = frozenset({"subtext"})
            self._style_combinations[tag] = styles
            self._configure_style(tag, styles)
            self.insert("end", "Your message preview will appear here.", tag)
            self.configure(height=6)
        else:
            blocks = split_message_blocks(self._value)
            line_count = 0
            for index, (kind, value) in enumerate(blocks):
                if kind == "code":
                    self._insert_code_block(value)
                else:
                    self._insert_rich_text(value)
                line_count += value.count("\n") + 1
                if index < len(blocks) - 1:
                    self.insert("end", "\n")
                    line_count += 1
            self.configure(height=max(10, min(24, line_count)))

        self.configure(state="disabled")

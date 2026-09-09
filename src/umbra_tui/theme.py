"""Umbra's Textual theme definition."""

from textual.theme import Theme


UMBRA_THEME = Theme(
    name="umbra",
    primary="#66558d",
    secondary="#697477",
    accent="#c792ea",
    warning="#f2cf5b",
    error="#934955",
    success="#50765b",
    foreground="#ffffe7",
    background="#17131b",
    surface="#211820",
    panel="#302330",
    dark=True,
    variables={
        "border": "#697477",
        "border-blurred": "#697477",
        "block-cursor-background": "#66558d",
        "button-color-foreground": "#ffffe7",
        "button-foreground": "#ffffe7",
        "footer-background": "#382837",
        "footer-key-foreground": "#f2cf5b",
        "input-selection-background": "#66558d 50%",
        "scrollbar": "#697477",
        "scrollbar-hover": "#8e9b9d",
        "scrollbar-active": "#ffffe7",
        "scrollbar-background": "#211820",
        "scrollbar-background-hover": "#211820",
        "scrollbar-background-active": "#211820",
        "scrollbar-corner-color": "#211820",
    },
)


__all__ = ["UMBRA_THEME"]

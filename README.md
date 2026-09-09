<div align="center">
  <img
    src="./src/umbra_gui/assets/umbra-development.png"
    alt="Umbra Development logo"
    width="190"
  />

  <h1>Umbra</h1>

  <p>Cross-platform desktop and terminal interfaces for configuring and running Umbra.</p>

  <p>
    <a href="https://github.com/Umbra-Development/Discord-Raid-External-Bot/releases/latest"><strong>Download</strong></a>
    ·
    <a href="https://github.com/Umbra-Development/Discord-Raid-External-Bot/wiki"><strong>Wiki</strong></a>
    ·
    <a href="https://github.com/Umbra-Development/Discord-Raid-External-Bot/issues"><strong>Report an issue</strong></a>
  </p>
</div>

---

## Get started

Download the latest build for Windows or Linux from
[GitHub Releases](https://github.com/Umbra-Development/Discord-Raid-External-Bot/releases/latest).
Choose the executable for your operating system and architecture (`x86_64` or
`ARM64`), then open `Umbra`. Archive copies are also provided. Configure your
application, then use the built-in control to start or stop the bot.

The desktop app opens on **General**. Its **Console** tab streams bot output
live, with follow and clear controls; scrollbars stay hidden while wheel and
trackpad scrolling remain available.

For setup instructions, configuration help, troubleshooting, and frequently
asked questions, visit the **[Umbra Wiki](https://github.com/Umbra-Development/Discord-Raid-External-Bot/wiki)**.

<details>
  <summary><strong>Developer quick start</strong></summary>

```bash
uv sync
uv run gui
```

Use the responsive terminal dashboard for a colored live log, bot controls,
and configuration editing:

```bash
uv run cli
```

Umbra is the default terminal theme. Press `Ctrl+P` to switch to any of
Textual's built-in themes.

The plain standalone bot command remains available for development and
automation:

```bash
uv run bot
```

</details>

## Disclaimer

Umbra Development is not responsible for how this software is used. Use it
responsibly and follow Discord's terms and applicable rules.

## Community and support

Join the [Umbra Development Discord](https://discord.gg/cMtCZx5YPn) for help
and more tools.

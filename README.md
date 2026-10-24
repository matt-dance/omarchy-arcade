# Omarchy Arcade

A controller-first game library for [Omarchy](https://omarchy.org), in the spirit of Steam Big Picture, built as a native Omarchy shell plugin. It follows your Omarchy theme, finds every installed game (Steam, Heroic, Lutris, Bottles, itch, Flatpak, GeForce NOW, emulators), and adds Guide-button chords that work like Omarchy's keyboard binds.

**Status: planning.** No code yet. Read these first:

- [`PLAN.md`](PLAN.md): scope, stack, default bindings, milestones, risks and open questions
- [`ARCHITECTURE.md`](ARCHITECTURE.md): processes, wire protocol, game model, scanners, session tracking, theming, install files
- [`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md): existing Omarchy and Linux projects, and why we build instead of wrap

Planned install, once built:

```bash
omarchy plugin add https://github.com/matt-dance/omarchy-arcade.git --enable
bash ~/.config/omarchy/plugins/matt-dance.arcade/scripts/install.sh   # adds Super+Ctrl+G and the Gaming › Arcade menu rows
```

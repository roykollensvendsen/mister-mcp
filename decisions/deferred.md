# What is deliberately not done yet

A thing left undone with no trigger is a thing forgotten. Each row names what
would make it worth doing, so the question comes back on its own rather than
depending on someone remembering it. Nothing enforces a trigger; the list is
read whenever a decision record is written and when a phase ends.

| Not done | The trigger | Why not now |
|---|---|---|
| A coverage threshold in CI | Two months of measured coverage to set it below | A number picked before there is data is a guess with a gate on it |
| A code of conduct and issue templates | A second contributor, or the first outside issue | Boilerplate answering questions nobody has asked |
| A release workflow and publishing | The first release someone outside will install | A published name is claimed and a published version cannot be reused |
| `CODEOWNERS` | A second person who reviews | It would name one person as the owner of everything |
| `pre-commit` as a requirement rather than an option | A second contributor | The gates run in CI, and a hook one person installs is a hook one person maintains |
| Switching the MiSTer on and off through a smart plug, after a clean shutdown over SSH | The owner names the plug and says yes to the request-and-confirm design | The owner chose to start with games; power is the one risky action and needs its own record. When it comes, the shutdown runs with `mister_mcp.ssh`'s options, never asks for a password, and says how to put the key back if update_all lost it |
| Pairing with Zaparoo as a member client, or with an API key | The first use against the real MiSTer | It is a change on the MiSTer, the owner's to make; until then the plugin's own allow-list is the guard |
| Blocking `execute`, `mister.script` and `mister.ini` in Zaparoo's `block_commands` on the MiSTer | The first use against the real MiSTer | A settings change on the MiSTer, the owner's to make; `unsafe: true` and the plugin's text check already refuse them |
| A layer order among the modules, refused by a test as in tv-mcp | A module that both talks to a device and shapes what the voice hears, or a tenth module | Eight small modules with one direction of import; a rule now would guard nothing |
| Asking the bridge to call `tv_input` instead of starting tv-mcp over stdio | The bridge lets one plugin call another plugin's tool | Plugins cannot reach the bridge today; `TvSwitch` keeps the swap to one class |

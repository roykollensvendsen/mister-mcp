# Decision records

A decision that costs more to reverse than to take is written down here before
the code that rests on it. A decision that only implements one already taken
is not; it is a commit message.

## The form

Every record is `ADR-MM-NNN-a-short-title.md`, with these sections in
this order:

| Section | Holds |
|---|---|
| Status | Accepted or Proposed, who decided, when; an objection returns it to Proposed |
| Context | what was true when the question arose, with sources where the facts are checkable |
| Options considered | every option weighed, including doing nothing, each with why it was not taken |
| Decision | what was chosen, in one paragraph |
| Consequences | what this costs, what it forecloses, and at least one thing that gets worse |
| Related | the pages it shapes |

Numbers are one sequence and never reused. A record is superseded by a later
one, never edited into a different decision.

Record the process choices too, not only the artefact ones. How a change is
made, and why, is what costs time on every future contribution, and it is the
decision nobody writes down.

## The records

| Id | Decides | Status |
|---|---|---|
| [ADR-MM-001](ADR-MM-001-build-on-zaparoo-core.md) | Build on Zaparoo Core's API, with a fixed allow-list of calls | Accepted |
| [ADR-MM-002](ADR-MM-002-switch-the-tv-through-tv-mcps-own-tools.md) | Switch the TV through the TV plugin's own tools, only when it is on | Accepted |
| [ADR-MM-003](ADR-MM-003-main-keeps-the-quality-levels.md) | Main keeps the quality levels, so a pull request never records them | Accepted |
| [ADR-MM-004](ADR-MM-004-run-update-all-over-ssh-from-a-fixed-list.md) | Run update_all over SSH, by key, from a fixed list of commands | Accepted |

What is deliberately left undone, and what would make each worth doing, is
[`deferred.md`](deferred.md). A thing left undone with no trigger is a thing
forgotten.

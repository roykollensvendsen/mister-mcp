# One row per rule

A rule nothing catches is a rule nothing protects. `scripts/mutate.py` turns
each rule off in turn and runs the suite; a rule whose removal breaks no test
has no test. `tests/test_rules_have_evidence.py` counts the rules in the source
against the rows here, so this folder cannot fall behind.

Each row is a file of its own, named after the rule, in a folder that is the
whole path of the file it switches off, the same layout as the other plugins.
`# RULE: a launch needs a yes` in `src/mister_mcp/service.py` goes in
`src/mister_mcp/service.py/a-launch-needs-a-yes.toml` here:

```toml
[[rule]]
name = "a launch needs a yes"
file = "src/mister_mcp/service.py"
find = 'if not confirmed:'
replace = 'if False:'
```

`find` is a regular expression matching the single line to replace; `replace`
is what replaces it, keeping the file valid. The line's own indentation is
kept, so `replace` needs none. A row in the wrong folder, under another name,
or a second row for one rule, is refused by the tests.

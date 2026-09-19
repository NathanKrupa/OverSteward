Closes #428

## Summary
A change with two non-blocking findings.

## Adversarial review

```reviewer-verdict
verdict: PASS-WITH-FINDINGS
findings: 2
tokens: 51100
```

1. `src/pkg/thing.py:88` — the docstring asserts an invariant no test pins.
   proof: deleted the caller's guard; the suite stayed green.
2. `tests/test_thing.py:12` — passes against the unfixed tree.
   proof: `git stash && pytest tests/test_thing.py -k new` → green.

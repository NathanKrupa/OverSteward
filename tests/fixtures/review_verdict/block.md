Closes #428

## Summary
A change that removed a production refusal.

## Adversarial review

```reviewer-verdict
verdict: BLOCK
findings: 1
tokens: 44900
```

1. `apps/docs/services/screenshot_seed.py:160` — `require_home_org` lost its
   `_assert_seed_allowed(email)` call, so the production refusal is gone from
   the function whose docstring still claims it cannot be forgotten.
   proof: called `require_home_org()` with `SMOKE_PRODUCTION=1`; it returned the
   org instead of raising.

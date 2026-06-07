## Summary

<!-- What does this PR do and why? One short paragraph. -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor (no behaviour change)
- [ ] Dataset change (required: full pipeline re-run)
- [ ] Docs / config only

## Checklist

**Engine changes:**
- [ ] `python -m engine.match` completes without `[FAIL]` or `AssertionError`
- [ ] `python -m engine.state --test-flow` completes with `ALL ASSERTS PASSED`
- [ ] `python -m engine.routing --self-test` passes
- [ ] No `\x` escape sequences introduced in any ID field
- [ ] No hand-typed counts or statistics in report output (numbers regenerated from live dataframes)

**Dataset changes (if applicable):**
- [ ] `build_datasets.py` → `build_jitter.py` → `build_map.py` pipeline re-run with `RANDOM_SEED=42`
- [ ] `REPORT.md` in `data/build/` regenerated and committed

**Frontend changes (if applicable):**
- [ ] Manually tested in browser: golden path (select patient → view tiers → issue unit → check log → reset)
- [ ] `npm run build` completes without TypeScript errors

**General:**
- [ ] `data/working_sim.db` is NOT included in this PR (it is gitignored)
- [ ] No secrets, API keys, or `.env` files included

## Testing done

<!-- Describe what you tested manually. Screenshots welcome for UI changes. -->

## Breaking changes

<!-- Does this change any API response shape, CSV schema, or invariant?
     If yes, describe the impact and migration path. -->

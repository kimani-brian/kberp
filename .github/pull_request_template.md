## Summary

What changed, and why. Link the issue, phase or requirement.

## Type

- [ ] Bug fix
- [ ] Feature
- [ ] Refactor
- [ ] Documentation or build
- [ ] Security

## Verification

Commands run and their results. Include the test names that cover the change.

```text
make check
...
```

## Checklist

- [ ] The change is scoped to one problem and has a regression test.
- [ ] `make check` passes.
- [ ] Module boundaries and service rules in `rules.md` are respected.
- [ ] Metadata changes are in addon XML, not ad-hoc Python.
- [ ] The client bundle was rebuilt if `client/src/` changed.
- [ ] No `.env`, credentials, customer data or runtime files are included.
- [ ] UI changes include a screenshot and pass the relevant smoke suite.

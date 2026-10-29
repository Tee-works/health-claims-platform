## What changes

## Who is affected

Run `python -m claims.lineage impact <model>` for each changed model and paste the output:

```
```

## Checklist

- [ ] New or changed models have tests (unique / not null / relationships / accepted values)
- [ ] Marts that feed dashboards keep their enforced contract, or the contract change is intended
- [ ] No personal data added outside `restricted` (the build checks this, but say so)
- [ ] Incremental models: a schema change comes with a `--full-refresh` plan
- [ ] Terraform: `terraform plan` output attached for access changes

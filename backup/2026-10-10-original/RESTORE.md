# Backup — original TenderRadar (10 Oct 2026)

An exact copy of every file on `main` as of commit `c4b1da6`
("chore: update tenders [2026-10-10 20:36]"), taken before the redesign.

This folder is inert: nothing in it runs. The workflow files here are
copies and are ignored by GitHub Actions because they are not in the
repo's top-level `.github/workflows/`.

## Restore everything

From the repo root:

```bash
cp -r backup/2026-10-10-original/{README.md,.github,scraper,docs,data} .
git add -A && git commit -m "Restore original TenderRadar" && git push
```

## Restore a single file

```bash
cp backup/2026-10-10-original/docs/index.html docs/index.html
```

Git history also has every version: `git show c4b1da6:docs/index.html`.

# Releasing obiobi

Maintainer notes. Users never need this — `pip install obiobi` is all they do.

## Steps

1. **Bump the version** in `pyproject.toml`. PyPI refuses to overwrite a version
   that already exists, so every release needs a new number.
2. **Build and check.**
   ```bash
   python -m build                 # -> dist/*.whl and dist/*.tar.gz
   python -m twine check dist/*    # must say PASSED for both
   ```
3. **Tag and push** (tag matches the version):
   ```bash
   git tag -a v1.2.3 -m "obiobi 1.2.3"
   git push origin main
   git push origin v1.2.3
   ```
4. **Upload to PyPI:**
   ```bash
   python -m twine upload dist/*   # username: __token__, password: pypi-...
   ```
5. **Cut the GitHub Release** from the tag, and drag the two `dist/` files in as
   assets.

## Tokens

Get one from <https://pypi.org/manage/account/token/> and **scope it to the
`obiobi` project** — the project exists now, so you never need an account-wide
token again. Revoke any token that has been pasted into a chat, terminal history,
or CI log; a leaked PyPI token can publish or yank your releases.

## Dry run

Rehearse against TestPyPI first if a release feels risky:

```bash
python -m twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ obiobi
```

## Sanity check after publishing

```bash
python -m venv /tmp/verify && /tmp/verify/bin/pip install --no-cache-dir obiobi
/tmp/verify/bin/obiobi --help
```

release:
    rm -rf build/ dist/ *.egg-info
    python -m build
    python -m twine upload dist/*


test:
    ruff check . --fix
    mypy . --config=pyproject.toml
    pytest --maxfail=1
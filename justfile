release:
    rm -rf build/ dist/ *.egg-info
    python -m build
    python -m twine upload dist/*


test:
    pytest --maxfail=1
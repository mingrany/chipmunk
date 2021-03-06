# Chipmunk

[![Build status](https://ci.appveyor.com/api/projects/status/060fwhaq3vfvt22n/branch/master?svg=true)](https://ci.appveyor.com/project/anirudhSK/chipmunk-hhg5f/branch/master)

## Installation
- Install [sketch](https://people.csail.mit.edu/asolar/sketch-1.7.5.tar.gz)
- Install Java. This repo uses [antlr](https://www.antlr.org/) to generate
  parser and lexer.
- `pip3 install -r requirements-dev.txt -e . && pre-commit install` (if you want to make changes to
  this repo),
- `pip3 install .` (if you want to simply use chipmunk.).
- Add sudo if you want to install system wide.

## How to

### Develop

If you have installed it as above, first re-install via following command.

```shell
pip3 install -r requirements-dev.txt -e .
pre-commit install
```
Note that there is `-e` in install command. It will install this package in
development mode, and simply link actual chipc directory to your Python's
site-packages directory.

1. Make changes to python code
2. Consider implementing tests and run tests `python3 -m unittest`
3. Run your desired binary like `python chipc/chipmunk.py ...`

This way you don't have to keep installing and uninstalling whenever you make a
change and test. However, still you have to run via `python3 chipc/chipmunk.py`
instead of using the installed binary.

Also consider using [venv](https://docs.python.org/3/library/venv.html),
[virtualenv](https://virtualenv.pypa.io/en/latest/) or
[pipenv](https://pipenv.readthedocs.io/en/latest/) to create an isolated Python
development environment.

### Iterative solver
```shell
iterative_solver example_specs/simple.sk example_alus/stateful_alus/raw.alu example_alus/stateless_alus/stateless_alu.alu 2 2 "0,1,2,3" 10 --hole-elimination
```

```shell
iterative_solver example_specs/simple.sk example_alus/stateful_alus/raw.alu example_alus/stateless_alus/stateless_alu.alu 2 2 "0,1,2,3" 10 --parallel --parallel-sketch --hole-elimination
```

### Test

Run:

You need to run setup in editable mode (with -e) to generate lexer and parser
in this directory.
```shell
pip3 install -r requirements-dev.txt -e .
python3 -m unittest
```

If you want to add a test, add a new file in [tests](tests/) directory or add
test cases in existing `test_*.py` file.

"""Test suite for the ctx package (stdlib unittest only).

Run from the repo root:  python3 -m unittest
"""


def strip_git_hygiene(argv):
    """Remove the `-c core.hooksPath=...` / `-c core.fsmonitor=false` pairs
    Stead injects into every git call, so fake runners can assert on the git
    command itself."""
    out = []
    i = 0
    while i < len(argv):
        if (argv[i] == "-c" and i + 1 < len(argv)
                and (argv[i + 1].startswith("core.hooksPath=")
                     or argv[i + 1] == "core.fsmonitor=false")):
            i += 2
            continue
        out.append(argv[i])
        i += 1
    return out

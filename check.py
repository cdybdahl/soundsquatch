#!/usr/bin/env python3
"""Checks the app's script before it is installed (install.sh runs this and stops if it fails): it must parse in
JavaScriptCore, the engine Safari uses, and use nothing older Safari lacks; one such line stops the whole page.
A check whose tool is missing on this machine is skipped, and says so."""
import glob
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
HAZARDS = [(r"\(\?<[=!]", "a regex lookbehind"), (r"\.findLast(Index)?\(", "findLast"), (r"\.toSorted\(|\.toReversed\(|\.toSpliced\(", "toSorted and its kin"),
           (r"\.at\(-?\d", "Array.at"), (r"\bstructuredClone\(", "structuredClone"), (r"Object\.groupBy\(", "Object.groupBy"), (r"\.replaceAll\(", "replaceAll")]


def main():
    problems = []
    for path in sorted(glob.glob(os.path.join(HERE, "app", "*.js"))):
        name = os.path.relpath(path, HERE)
        code = open(path).read()
        for pattern, what in HAZARDS:
            for m in re.finditer(pattern, code):
                problems.append(f"{name}:{code[:m.start()].count(chr(10)) + 1}: {what}, which older Safari cannot handle")
        if os.path.exists(JSC):
            out = subprocess.run([JSC, "-e", f'try {{ checkSyntax("{path}"); }} catch (e) {{ print(String(e)); }}'], capture_output=True, text=True, timeout=60).stdout.strip()
            if out:
                problems.append(f"{name}: does not parse in Safari's engine: {out[:160]}")
    if not os.path.exists(JSC):
        print("  syntax check skipped: JavaScriptCore's jsc is not on this machine")
    if problems:
        print("error: the app did not pass its checks:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        sys.exit(1)
    print("  the app parses in Safari's engine and uses nothing older Safari lacks")


if __name__ == "__main__":
    main()

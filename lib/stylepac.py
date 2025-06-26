#!/bin/python3

lines = open("/etc/pacman.conf").readlines()
new = []
has_candy = any("ILoveCandy" in l for l in lines)

for l in lines:
    s = l.strip()

    if s == "#Color":
        new.append("Color\n")
        continue

    if s == "# Misc options" and not has_candy:
        new += [l, "ILoveCandy\n"]
        continue

    new.append(l)

open("/etc/pacman.conf", "w").writelines(new)

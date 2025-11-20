#!/bin/python3

lines = open("/etc/pacman.conf").readlines()
new = []
has_candy = any("ILoveCandy" in line for line in lines)

for line in lines:
    s = line.strip()

    if s == "#Color":
        new.append("Color\n")
        continue

    if s == "# Misc options" and not has_candy:
        new += [line, "ILoveCandy\n"]
        continue

    new.append(line)

open("/etc/pacman.conf", "w").writelines(new)

import os
import sys
import subprocess
import re

def check_pacman_contrib():
    """Check if pacman-contrib is installed (provides pactree for dependency analysis)"""
    try:
        result = subprocess.run(['pacman', '-Q', 'pacman-contrib'],
                              capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
        return False

def get_package_deps_count(package_name):
    """
    Get the number of dependencies for a package using pactree.
    Returns -1 if pacman-contrib is not available or error occurs.
    """
    if not check_pacman_contrib():
        return -1

    try:
        # Use pactree to get dependency tree (-u for unique, -d 1 for depth 1 only)
        result = subprocess.run(['pactree', '-u', package_name],
                              capture_output=True, text=True, check=True)
        # Count lines (excluding the package itself)
        deps = result.stdout.strip().split('\n')
        return max(0, len(deps) - 1)
    except subprocess.CalledProcessError:
        return -1

def is_in_ignorepkg(package_name):
    """Check if a package is in IgnorePkg in /etc/pacman.conf"""
    try:
        with open('/etc/pacman.conf', 'r') as f:
            content = f.read()

        # Look for IgnorePkg lines (commented or uncommented)
        for line in content.split('\n'):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            if stripped.startswith('IgnorePkg'):
                # Extract packages after = sign
                if '=' in stripped:
                    packages = stripped.split('=', 1)[1].strip()
                    pkg_list = [p.strip() for p in packages.split()]
                    if package_name in pkg_list:
                        return True
        return False
    except Exception:
        return False

def add_to_ignorepkg(package_name):
    """Add a package to IgnorePkg in /etc/pacman.conf"""
    try:
        with open('/etc/pacman.conf', 'r') as f:
            lines = f.readlines()

        new_lines = []
        found_ignorepkg = False

        for line in lines:
            stripped = line.strip()

            # Skip commented IgnorePkg lines
            if stripped.startswith('#IgnorePkg'):
                new_lines.append(line)
                continue

            # If we find an active IgnorePkg line, append to it
            if stripped.startswith('IgnorePkg') and '=' in stripped:
                found_ignorepkg = True
                # Check if package already in line
                if package_name not in stripped:
                    line = line.rstrip() + f" {package_name}\n"
                new_lines.append(line)
            else:
                new_lines.append(line)

        # If no IgnorePkg line found, add one in the [options] section
        if not found_ignorepkg:
            new_lines_with_ignorepkg = []
            in_options = False
            added = False

            for line in new_lines:
                stripped = line.strip()
                if stripped == '[options]':
                    in_options = True
                    new_lines_with_ignorepkg.append(line)
                elif in_options and not added and (stripped.startswith('[') or not stripped or stripped.startswith('#')):
                    # Add IgnorePkg before the next section or end of [options]
                    if not stripped.startswith('['):
                        new_lines_with_ignorepkg.append(f"IgnorePkg = {package_name}\n")
                        added = True
                    new_lines_with_ignorepkg.append(line)
                    if stripped.startswith('['):
                        in_options = False
                else:
                    new_lines_with_ignorepkg.append(line)

            new_lines = new_lines_with_ignorepkg

        # Write back
        with open('/etc/pacman.conf', 'w') as f:
            f.writelines(new_lines)

        return True
    except Exception as e:
        print(f"Error adding to IgnorePkg: {e}")
        return False

def remove_from_ignorepkg(package_name):
    """Remove a package from IgnorePkg in /etc/pacman.conf"""
    try:
        with open('/etc/pacman.conf', 'r') as f:
            lines = f.readlines()

        new_lines = []

        for line in lines:
            stripped = line.strip()

            # Skip commented lines
            if stripped.startswith('#'):
                new_lines.append(line)
                continue

            # Process IgnorePkg lines
            if stripped.startswith('IgnorePkg') and '=' in stripped:
                parts = stripped.split('=', 1)
                packages = parts[1].strip().split()

                # Remove the target package
                packages = [p for p in packages if p != package_name]

                # Only keep the line if there are remaining packages
                if packages:
                    new_lines.append(f"IgnorePkg = {' '.join(packages)}\n")
                # else: skip the line entirely (remove empty IgnorePkg)
            else:
                new_lines.append(line)

        # Write back
        with open('/etc/pacman.conf', 'w') as f:
            f.writelines(new_lines)

        return True
    except Exception as e:
        print(f"Error removing from IgnorePkg: {e}")
        return False

def get_packages_with_many_deps(threshold=50):
    """
    Get list of installed packages with more than threshold dependencies.
    Returns list of tuples: (package_name, dep_count)
    Returns empty list if pacman-contrib not installed.
    """
    if not check_pacman_contrib():
        return []

    try:
        # Get list of explicitly installed packages
        result = subprocess.run(['pacman', '-Qe'],
                              capture_output=True, text=True, check=True)
        packages = [line.split()[0] for line in result.stdout.strip().split('\n') if line]

        heavy_packages = []
        for pkg in packages:
            dep_count = get_package_deps_count(pkg)
            if dep_count >= threshold:
                heavy_packages.append((pkg, dep_count))

        # Sort by dependency count (descending)
        heavy_packages.sort(key=lambda x: x[1], reverse=True)
        return heavy_packages
    except Exception:
        return []


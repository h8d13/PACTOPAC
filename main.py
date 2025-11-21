#!/usr/bin/env python3
import subprocess
import threading
import os
import sys
import re
import signal
from difflib import SequenceMatcher
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Vte', '3.91')

from gi.repository import Gtk, Adw, GLib, Vte, Gdk, Pango  # noqa: E402

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
        with open('/etc/pacman.conf') as f:
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
        with open('/etc/pacman.conf') as f:
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
        with open('/etc/pacman.conf') as f:
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

def is_pacman_running():
    """
    Check for running pacman processes.
    Returns True if pacman is running, False otherwise.
    """
    try:
        # pgrep -f matches the full command line, -x matches exact process name
        subprocess.check_output(['pgrep', '-x', 'pacman'], text=True)
        print('Pacman pid found!!')
        return True
    except subprocess.CalledProcessError:
        # pgrep returns non-zero exit code when no processes found
        print('No pacman pid found')
        return False
    except Exception as e:
        print(f"Error checking pacman process: {e}")
        return False

def detect_distro():
    """
    Detect if running on Arch or Artix Linux.
    Returns 'arch', 'artix', or 'unknown'
    """
    try:
        with open('/etc/os-release') as f:
            content = f.read()
            for line in content.split('\n'):
                if line.startswith('ID='):
                    distro_id = line.split('=', 1)[1].strip().strip('"')
                    if distro_id == 'arch':
                        return 'arch'
                    elif distro_id == 'artix':
                        return 'artix'
    except (FileNotFoundError, PermissionError, IndexError, OSError):
        pass
    return 'unknown'

class PkgMan(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("PacToPac")
        self.set_default_size(800, 600)


        if os.geteuid() != 0:
            print("Error: This application must be run with sudo", file=sys.stderr)
            print("Usage: sudo python3 main.py", file=sys.stderr)
            app.quit()
            sys.exit(1)

        # Get SUDO_USER - guaranteed to exist when run with sudo
        sudo_user = os.environ.get('SUDO_USER')
        if not sudo_user:
            print("Error: SUDO_USER environment variable not found", file=sys.stderr)
            print("Please run with: sudo python3 main.py", file=sys.stderr)
            app.quit()
            sys.exit(1)

        self.sudo_user: str = sudo_user  # Type annotation: always a string

        self.packages = []
        self.filtered_packages = []
        self.selected = None
        self.page_size = 100
        self.current_page = 0
        self.current_tab = "installed"  # Default to installed tab
        self.running_processes = []  # Track running pacman/flatpak processes
        self.installed_aur = set()  # Track installed AUR packages
        self.aur_search_cache = {}  # Cache AUR search results
        self.aur_total_count = None  # Cache total AUR package count
        self.aur_count_loading = False  # Flag to prevent duplicate count requests
        self.fuzzy_threshold = self.get_fuzzy_threshold()  # Fuzzy match threshold
        self.terminal_font_size = self.get_terminal_font_size()  # VTE terminal font size
        self.setup_ui()
        self.load_packages()
    

    def monitor_processes_and_close(self, window):
        """Monitor processes and close window when all complete"""
        def check_processes():
            active_processes = [proc for proc in self.running_processes if proc.poll() is None]
            if not active_processes:
                # All processes done, safe to close
                GLib.idle_add(lambda: window.destroy())
                return False  # Stop monitoring
            return True  # Continue monitoring
        
        # Check every 1 second
        GLib.timeout_add(1000, check_processes)
    
    def setup_ui(self):
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)
        
        header = Adw.HeaderBar()
        settings_btn = Gtk.Button(icon_name="preferences-system-symbolic", tooltip_text="Settings")
        settings_btn.connect("clicked", self.show_settings)
        header.pack_start(settings_btn)
        toolbar_view.add_top_bar(header)
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        toolbar_view.set_content(box)
        
        self.search = Gtk.SearchEntry(placeholder_text="Search packages...")
        self.search.connect("search-changed", self.on_search_changed)

        # Add escape key handler to refocus list
        search_key_controller = Gtk.EventControllerKey()
        search_key_controller.connect("key-pressed", self.on_search_key_pressed)
        self.search.add_controller(search_key_controller)

        box.append(self.search)

        # Add view stack for Installed/Available tabs
        self.view_stack = Adw.ViewStack()

        # Create Installed tab
        installed_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.installed_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.installed_scroll.add_css_class("card")
        
        # Container for list and load more button
        installed_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.installed_list = Gtk.ListBox()
        self.installed_list.add_css_class("boxed-list")
        self.installed_list.connect("row-selected", self.on_select)

        # Enable keyboard navigation
        self.installed_list.set_can_focus(True)
        self.installed_list.set_selection_mode(Gtk.SelectionMode.BROWSE)

        # Add keyboard event controller for arrow keys
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self.on_list_key_pressed, self.installed_list)
        self.installed_list.add_controller(key_controller)

        installed_container.append(self.installed_list)

        # Load More button with consistent styling
        self.installed_load_more = Gtk.Button(label="Load More", sensitive=False)
        self.installed_load_more.connect("clicked", self.load_more_packages)
        self.installed_load_more.set_margin_top(6)
        self.installed_load_more.set_margin_bottom(6)
        self.installed_load_more.set_margin_start(6)
        self.installed_load_more.set_margin_end(6)
        installed_container.append(self.installed_load_more)
        
        self.installed_scroll.set_child(installed_container)
        installed_page.append(self.installed_scroll)
        
        self.view_stack.add_titled_with_icon(installed_page, "installed", "Installed", "object-select-symbolic")
        
        # Create Flatpak tab
        flatpak_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.flatpak_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.flatpak_scroll.add_css_class("card")

        # Container for list and load more button
        flatpak_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.flatpak_list = Gtk.ListBox()
        self.flatpak_list.add_css_class("boxed-list")
        self.flatpak_list.connect("row-selected", self.on_select)

        # Enable keyboard navigation but skip in tab order
        self.flatpak_list.set_can_focus(True)
        self.flatpak_list.set_focus_on_click(False)
        self.flatpak_list.set_selection_mode(Gtk.SelectionMode.BROWSE)

        # Add keyboard event controller for arrow keys
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self.on_list_key_pressed, self.flatpak_list)
        self.flatpak_list.add_controller(key_controller)

        flatpak_container.append(self.flatpak_list)

        # Load More button with consistent styling
        self.flatpak_load_more = Gtk.Button(label="Load More", sensitive=False)
        self.flatpak_load_more.connect("clicked", self.load_more_packages)
        self.flatpak_load_more.set_margin_top(6)
        self.flatpak_load_more.set_margin_bottom(6)
        self.flatpak_load_more.set_margin_start(6)
        self.flatpak_load_more.set_margin_end(6)
        flatpak_container.append(self.flatpak_load_more)

        self.flatpak_scroll.set_child(flatpak_container)
        flatpak_page.append(self.flatpak_scroll)

        self.view_stack.add_titled_with_icon(flatpak_page, "flatpak", "Flatpak", "application-x-addon-symbolic")

        # Create AUR tab
        aur_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.aur_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.aur_scroll.add_css_class("card")

        # Container for list and load more button
        aur_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.aur_list = Gtk.ListBox()
        self.aur_list.add_css_class("boxed-list")
        self.aur_list.connect("row-selected", self.on_select)

        # Enable keyboard navigation but skip in tab order
        self.aur_list.set_can_focus(True)
        self.aur_list.set_focus_on_click(False)
        self.aur_list.set_selection_mode(Gtk.SelectionMode.BROWSE)

        # Add keyboard event controller for arrow keys
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self.on_list_key_pressed, self.aur_list)
        self.aur_list.add_controller(key_controller)

        aur_container.append(self.aur_list)

        # Load More button with consistent styling
        self.aur_load_more = Gtk.Button(label="Load More", sensitive=False)
        self.aur_load_more.connect("clicked", self.load_more_packages)
        self.aur_load_more.set_margin_top(6)
        self.aur_load_more.set_margin_bottom(6)
        self.aur_load_more.set_margin_start(6)
        self.aur_load_more.set_margin_end(6)
        aur_container.append(self.aur_load_more)

        self.aur_scroll.set_child(aur_container)
        aur_page.append(self.aur_scroll)

        self.view_stack.add_titled_with_icon(aur_page, "aur", "AUR", "software-properties-symbolic")
        
        # Create Available tab
        available_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.available_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.available_scroll.add_css_class("card")
        
        # Container for list and load more button
        available_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.available_list = Gtk.ListBox()
        self.available_list.add_css_class("boxed-list")
        self.available_list.connect("row-selected", self.on_select)

        # Enable keyboard navigation but skip in tab order
        self.available_list.set_can_focus(True)
        self.available_list.set_focus_on_click(False)
        self.available_list.set_selection_mode(Gtk.SelectionMode.BROWSE)

        # Add keyboard event controller for arrow keys
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self.on_list_key_pressed, self.available_list)
        self.available_list.add_controller(key_controller)

        available_container.append(self.available_list)
        
        # Load More button with consistent styling
        self.available_load_more = Gtk.Button(label="Load More", sensitive=False)
        self.available_load_more.connect("clicked", self.load_more_packages)
        self.available_load_more.set_margin_top(6)
        self.available_load_more.set_margin_bottom(6)
        self.available_load_more.set_margin_start(6)
        self.available_load_more.set_margin_end(6)
        available_container.append(self.available_load_more)
        
        self.available_scroll.set_child(available_container)
        available_page.append(self.available_scroll)
        
        self.view_stack.add_titled_with_icon(available_page, "available", "Available", "folder-download-symbolic")
        
        # Create All tab
        all_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.all_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.all_scroll.add_css_class("card")
        
        # Container for list and load more button
        all_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.all_list = Gtk.ListBox()
        self.all_list.add_css_class("boxed-list")
        self.all_list.connect("row-selected", self.on_select)

        # Enable keyboard navigation but skip in tab order
        self.all_list.set_can_focus(True)
        self.all_list.set_focus_on_click(False)
        self.all_list.set_selection_mode(Gtk.SelectionMode.BROWSE)

        # Add keyboard event controller for arrow keys
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self.on_list_key_pressed, self.all_list)
        self.all_list.add_controller(key_controller)

        all_container.append(self.all_list)
        
        # Load More button with consistent styling
        self.all_load_more = Gtk.Button(label="Load More", sensitive=False)
        self.all_load_more.connect("clicked", self.load_more_packages)
        self.all_load_more.set_margin_top(6)
        self.all_load_more.set_margin_bottom(6)
        self.all_load_more.set_margin_start(6)
        self.all_load_more.set_margin_end(6)
        all_container.append(self.all_load_more)
        
        self.all_scroll.set_child(all_container)
        all_page.append(self.all_scroll)
        
        self.view_stack.add_titled_with_icon(all_page, "all", "All", "view-list-symbolic")
        
        # Set default to installed
        self.view_stack.set_visible_child_name("installed")
        
        # Connect stack change signal
        self.view_stack.connect("notify::visible-child-name", self.on_stack_changed)
        
        box.append(self.view_stack)

        # Create compact filter button with popover (below the list)
        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        filter_box.set_margin_start(12)
        filter_box.set_margin_end(12)
        filter_box.set_margin_top(6)

        self.filter_label = Gtk.Label(label="Filter: Installed", halign=Gtk.Align.START, hexpand=True)
        self.filter_label.add_css_class("dim-label")
        filter_box.append(self.filter_label)

        self.filter_button = Gtk.MenuButton(icon_name="view-more-symbolic")
        self.filter_button.set_tooltip_text("Change filter")
        self.filter_button.set_direction(Gtk.ArrowType.LEFT)  # Open to the left

        # Create popover with filter options
        popover = Gtk.Popover()
        popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        popover_box.set_margin_top(6)
        popover_box.set_margin_bottom(6)
        popover_box.set_margin_start(6)
        popover_box.set_margin_end(6)

        # Create filter buttons
        installed_btn = Gtk.Button(label="Installed", halign=Gtk.Align.FILL)
        installed_btn.connect("clicked", lambda b: self.change_filter("installed", popover))
        popover_box.append(installed_btn)

        flatpak_btn = Gtk.Button(label="Flatpak", halign=Gtk.Align.FILL)
        flatpak_btn.connect("clicked", lambda b: self.change_filter("flatpak", popover))
        popover_box.append(flatpak_btn)

        aur_btn = Gtk.Button(label="AUR", halign=Gtk.Align.FILL)
        aur_btn.connect("clicked", lambda b: self.change_filter("aur", popover))
        popover_box.append(aur_btn)

        available_btn = Gtk.Button(label="Available", halign=Gtk.Align.FILL)
        available_btn.connect("clicked", lambda b: self.change_filter("available", popover))
        popover_box.append(available_btn)

        all_btn = Gtk.Button(label="All", halign=Gtk.Align.FILL)
        all_btn.connect("clicked", lambda b: self.change_filter("all", popover))
        popover_box.append(all_btn)

        popover.set_child(popover_box)
        self.filter_button.set_popover(popover)
        filter_box.append(self.filter_button)

        box.append(filter_box)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, homogeneous=True)
        
        self.info_btn = Gtk.Button(label="Info", sensitive=False)
        self.info_btn.connect("clicked", self.show_package_info)
        
        self.action_btn = Gtk.Button(label="Install", sensitive=False)
        self.action_btn.add_css_class("suggested-action")
        self.action_btn.connect("clicked", self.handle_package_action)

        self.update_btn = Gtk.Button(label="Update", sensitive=True)
        self.update_btn.connect("clicked", self.handle_update)
        
        clean_orphans_btn = Gtk.Button(label="Clean", sensitive=True)
        clean_orphans_btn.connect("clicked", self.handle_clean_orphans)
        clean_orphans_btn.add_css_class("destructive-action")

        for btn in [self.info_btn, self.action_btn, self.update_btn, clean_orphans_btn]:
            btn_box.append(btn)
        box.append(btn_box)
        
        # Status area with process indicator
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        self.status = Gtk.Label(label="Loading packages...")
        self.status.add_css_class("dim-label")
        self.status.set_hexpand(True)
        status_box.append(self.status)
        
        self.process_indicator = Gtk.Label(label="")
        self.process_indicator.add_css_class("dim-label")
        status_box.append(self.process_indicator)
        
        box.append(status_box)

        # Load and apply saved theme preference
        saved_is_light = self.load_theme_pref()
        style_manager = Adw.StyleManager.get_default()
        if saved_is_light:
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        else:
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    
    def on_stack_changed(self, view_stack, param):
        """Handle view stack change to update current filter"""
        visible_child_name = view_stack.get_visible_child_name()
        if visible_child_name:
            self.current_tab = visible_child_name
            self.current_page = 0
            self.refresh_list()

    def change_filter(self, filter_name, popover):
        """Change the active filter and update label"""
        self.view_stack.set_visible_child_name(filter_name)

        # Update filter label
        filter_names = {
            "installed": "Installed",
            "flatpak": "Flatpak",
            "aur": "AUR",
            "available": "Available",
            "all": "All"
        }
        self.filter_label.set_label(f"Filter: {filter_names.get(filter_name, filter_name)}")

        # Close popover
        popover.popdown()

    def show_settings(self, button):
        dialog = Adw.PreferencesDialog()
        dialog.set_title("Settings")
        dialog.set_search_enabled(True)
        dialog.set_content_width(800)
        dialog.set_content_height(600)

        # Repository Settings Page
        repo_page = Adw.PreferencesPage(title="General", icon_name="folder-symbolic")
        dialog.add(repo_page)
        
        # Pacman repositories
        pacman_group = Adw.PreferencesGroup(title="Pacman Repositories", description="Configure official Arch/Artix Linux repositories")
        repo_page.add(pacman_group)
        
        # Detect distro for proper repo naming
        distro = detect_distro()
        repo_name = "lib32" if distro == "artix" else "multilib"
        repo_title = f"{repo_name.capitalize()} Repository"

        multilib_row = Adw.SwitchRow(
            title=repo_title,
            subtitle="Enable 32-bit package support for games and legacy software\nHint: lib32-vulkan-intel or lib32-vulkan-radeon or lib32-nvidia-utils"
        )
        multilib_row.set_active(self.check_multilib_enabled())
        multilib_row.connect("notify::active", self.on_multilib_toggle)
        pacman_group.add(multilib_row)

        dep_group = Adw.PreferencesGroup(
            title="Dependency Management",
            description="Analyze and manage packages with many dependencies using IgnorePkg"
        )
        repo_page.add(dep_group)

        # Check if pacman-contrib is installed
        has_contrib = check_pacman_contrib()

        if not has_contrib:
            contrib_row = Adw.ActionRow(
                title="pacman-contrib Required",
                subtitle="Install pacman-contrib to enable dependency analysis (provides pactree)"
            )
            install_contrib_btn = Gtk.Button(label="Install")
            install_contrib_btn.add_css_class("suggested-action")
            install_contrib_btn.set_valign(Gtk.Align.CENTER)
            install_contrib_btn.connect("clicked", lambda b: self.install_pacman_contrib(dialog))
            contrib_row.add_suffix(install_contrib_btn)
            dep_group.add(contrib_row)
        else:
            # Show button to analyze packages
            analyze_row = Adw.ActionRow(
                title="Analyze Heavy Packages",
                subtitle="Find packages with many dependencies and manage IgnorePkg"
            )
            analyze_btn = Gtk.Button(label="Analyze")
            analyze_btn.add_css_class("suggested-action")
            analyze_btn.set_valign(Gtk.Align.CENTER)
            analyze_btn.connect("clicked", self.show_dependency_analysis)
            analyze_row.add_suffix(analyze_btn)
            dep_group.add(analyze_row)

        # UI Settings
        ui_group = Adw.PreferencesGroup(title="Interface", description="Customize search and terminal appearance")
        repo_page.add(ui_group)

        # Fuzzy search threshold
        fuzzy_row = Adw.SpinRow.new_with_range(0.0, 1.0, 0.05)
        fuzzy_row.set_title("Fuzzy Search Threshold")
        fuzzy_row.set_subtitle("Lower = more results (0.0-1.0, default: 0.4)")
        fuzzy_row.set_digits(2)
        fuzzy_row.set_value(self.fuzzy_threshold)
        fuzzy_row.connect("changed", self.on_fuzzy_threshold_changed)
        ui_group.add(fuzzy_row)

        # Terminal font size
        font_size_row = Adw.SpinRow.new_with_range(8, 24, 1)
        font_size_row.set_title("Terminal Font Size")
        font_size_row.set_subtitle("Font size for command output terminal (default: 12)")
        font_size_row.set_value(self.terminal_font_size)
        font_size_row.connect("changed", self.on_terminal_font_size_changed)
        ui_group.add(font_size_row)

        # Package Operations Settings
        operations_group = Adw.PreferencesGroup(title="Package Operations", description="Configure how package operations behave")
        repo_page.add(operations_group)

        # Noconfirm toggle
        noconfirm_row = Adw.SwitchRow(
            title="Skip Confirmation Prompts",
            subtitle="Automatically proceed with package operations without asking for confirmation"
        )
        noconfirm_row.set_active(self.get_noconfirm_enabled())
        noconfirm_row.connect("notify::active", self.on_noconfirm_toggle)
        operations_group.add(noconfirm_row)

        # Flatpak Settings Page
        flatpak_page = Adw.PreferencesPage(title="Flatpak", icon_name="application-x-executable-symbolic")
        dialog.add(flatpak_page)
        
        flatpak_group = Adw.PreferencesGroup(title="Flatpak Configuration", description="Universal application packages")
        flatpak_page.add(flatpak_group)
        
        if self.check_fp():
            flathub_row = Adw.SwitchRow(
                title="Flathub Repository", 
                subtitle="Enable access to thousands of applications via Flatpak"
            )
            flathub_row.set_active(self.check_fh())
            flathub_row.connect("notify::active", self.on_fh_toggle)
            flatpak_group.add(flathub_row)
        else:
            unavailable_row = Adw.ActionRow(
                title="Flatpak Not Available",
                subtitle="Install flatpak package to enable universal app support"
            )
            install_btn = Gtk.Button(label="Install")
            install_btn.add_css_class("suggested-action") 
            install_btn.set_valign(Gtk.Align.CENTER)
            # Modified this line to include refresh after installation
            install_btn.connect("clicked", lambda b: self.install_fp_and_refresh(dialog))
            unavailable_row.add_suffix(install_btn)
            flatpak_group.add(unavailable_row)
        
        update_flatpak_row = Adw.ActionRow(
            title="Update Flatpak Apps",
            subtitle="Update all installed Flatpak applications"
        )

        update_flatpak_btn = Gtk.Button(label="Update")
        update_flatpak_btn.add_css_class("suggested-action")
        update_flatpak_btn.set_valign(Gtk.Align.CENTER)
        update_flatpak_btn.connect("clicked", self.handle_flatpak_update)
        update_flatpak_row.add_suffix(update_flatpak_btn)

        flatpak_group.add(update_flatpak_row)

        clean_flatpak_row = Adw.ActionRow(
            title="Clean Flatpak Cache",
            subtitle="Remove unused Flatpak runtimes and clear cache"
        )

        clean_flatpak_btn = Gtk.Button(label="Clean")
        clean_flatpak_btn.add_css_class("destructive-action")
        clean_flatpak_btn.set_valign(Gtk.Align.CENTER)
        clean_flatpak_btn.connect("clicked", self.handle_flatpak_cleanup)
        clean_flatpak_row.add_suffix(clean_flatpak_btn)

        flatpak_group.add(clean_flatpak_row)

        # AUR Settings Page
        aur_page = Adw.PreferencesPage(title="AUR", icon_name="package-x-generic-symbolic")
        dialog.add(aur_page)

        aur_group = Adw.PreferencesGroup(title="AUR Configuration", description="Arch User Repository package support using Grimaur-too")
        aur_page.add(aur_group)

        aur_enable_row = Adw.SwitchRow(
            title="Enable AUR Support",
            subtitle="Enable AUR package installation and management using ryk4rd/grimaur"
        )
        aur_enable_row.set_active(self.get_grimaur_enabled())
        aur_enable_row.connect("notify::active", self.on_aur_toggle)
        aur_group.add(aur_enable_row)

        # Git mirror toggle
        git_mirror_row = Adw.SwitchRow(
            title="Use Git Mirror",
            subtitle="Use git mirrors if or when AUR is down"
        )
        git_mirror_row.set_active(self.get_git_mirror_enabled())
        git_mirror_row.connect("notify::active", self.on_git_mirror_toggle)
        aur_group.add(git_mirror_row)

        # Remove cache toggle
        remove_cache_row = Adw.SwitchRow(
            title="Remove Cache on Uninstall",
            subtitle="Delete cached build files when removing AUR packages"
        )
        remove_cache_row.set_active(self.get_remove_cache_enabled())
        remove_cache_row.connect("notify::active", self.on_remove_cache_toggle)
        aur_group.add(remove_cache_row)

        # Add info about requirements
        requirements_row = Adw.ActionRow(
            title="Requirements",
            subtitle="AUR packages need base-devel and git installed to build\nIt is your responsability to check PKGBUILD and use reputable pkgs.\nhttps://aur.archlinux.org/packages"
        )
        aur_group.add(requirements_row)

        # About Page
        about_page = Adw.PreferencesPage(title="Misc", icon_name="help-about-symbolic")
        dialog.add(about_page)
        
        # App info group
        about_group = Adw.PreferencesGroup()
        about_page.add(about_group)
        
        app_row = Adw.ActionRow(title="PacToPac // Grimaur2", subtitle="Suckless Arch/Artix Linux package manager")
        about_group.add(app_row)
        
        version_row = Adw.ActionRow(title="Version", subtitle="1.0.8")
        about_group.add(version_row)
        
        # Appearance group with theme toggle
        appearance_group = Adw.PreferencesGroup(title="Appearance", description="Customize look and feel")
        about_page.add(appearance_group)
        
        # Get current theme state
        style_manager = Adw.StyleManager.get_default()
        is_light = style_manager.get_color_scheme() == Adw.ColorScheme.FORCE_LIGHT
        
        theme_row = Adw.SwitchRow(
            title="Theme Preference",
            subtitle="Switch between light and dark appearance"
        )
        theme_row.set_active(is_light)
        theme_row.connect("notify::active", self.on_theme_toggle)
        appearance_group.add(theme_row)

        # Pacman styling toggle
        style_row = Adw.SwitchRow(
            title="Pacman Styling",
            subtitle="Enable color output and ILoveCandy progress animation"
        )
        style_row.set_active(self.check_pacman_styling_enabled())
        style_row.connect("notify::active", self.on_style_toggle)
        appearance_group.add(style_row)

        dialog.present(self)

    def copy_url_to_clipboard(self, button, url):
        """Copy URL to clipboard"""
        clipboard = self.get_clipboard()
        clipboard.set(url)

        # Optional: show a brief confirmation
        button.set_icon_name("object-select-symbolic")
        GLib.timeout_add(1000, lambda: button.set_icon_name("edit-copy-symbolic"))

    def handle_flatpak_update(self, button):
        """Update all Flatpak applications"""
        if self.check_fp():
            cmd = ['sudo', '-u', self.sudo_user, 'flatpak', 'update']
            if self.get_noconfirm_enabled():
                cmd.append('-y')
            self.run_cmd(cmd)
        else:
            self.show_error("Flatpak is not installed")

    def handle_flatpak_cleanup(self, button):
        """Clean Flatpak cache and unused runtimes"""
        if self.check_fp():
            # This removes unused runtimes and clears cache
            cmd = ['sudo', '-u', self.sudo_user, 'flatpak', 'uninstall', '--unused']
            if self.get_noconfirm_enabled():
                cmd.append('-y')
            self.run_cmd(cmd)
            # flatpak uninstall --delete-data
            # flatpak repair --user
        else:
            self.show_error("Flatpak is not installed")

    def handle_clean_orphans(self, button):
        def check_and_clean():
            try:
                # Check if there are orphaned packages
                result = subprocess.run(['pacman', '-Qtdq'], capture_output=True, text=True)
                orphaned_packages = result.stdout.strip()
                
                if orphaned_packages:
                    # Remove orphaned packages
                    cmd = ['pacman', '-Rns'] + orphaned_packages.split('\n')
                    if self.get_noconfirm_enabled():
                        cmd.append('--noconfirm')
                    GLib.idle_add(lambda: self.run_cmd(cmd))
                else:
                    # No orphans found, clean cache instead
                    GLib.idle_add(lambda: self.show_cache_clean_dialog())
                
            except subprocess.CalledProcessError:
                # No orphans found, clean cache instead
                GLib.idle_add(lambda: self.show_cache_clean_dialog())
        
        threading.Thread(target=check_and_clean, daemon=True).start()

    def show_cache_clean_dialog(self):
        dialog = Adw.AlertDialog(
            heading="No Orphaned Packages",
            body="No orphaned packages found. Would you like to clean the package cache instead?"
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("partial", "Clean Old Versions")
        dialog.add_response("full", "Clean All Cache")
        dialog.set_response_appearance("full", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("partial", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self.on_cache_clean_response)
        dialog.present(self)

    def on_cache_clean_response(self, dialog, response):
        if response == "partial":
            # paccache -r: removes old versions, keeps last 3 of each package
            cmd = ['paccache', '-r']
            self.run_cmd(cmd)
        elif response == "full":
            # pacman -Scc: removes all cached packages
            cmd = ['pacman', '-Scc']
            if self.get_noconfirm_enabled():
                cmd.append('--noconfirm')
            self.run_cmd(cmd)

    def check_fp(self):
        try:
            cmd = (['sudo', '-u', self.sudo_user, 'flatpak', '--version'])
            subprocess.run(cmd, capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return False

    def check_grimaur(self):
        """Check if grimaur is available"""
        try:
            grimaur_path = os.path.join(os.path.dirname(__file__), 'grimaur-too/grimaur.py')
            if os.path.exists(grimaur_path):

                result = subprocess.run(['sudo', '-u', self.sudo_user, 'python3', grimaur_path, '--help'], capture_output=True, timeout=5)

                return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError, OSError, TimeoutError):
            pass
        return False

    def get_grimaur_enabled(self):
        """Check if AUR support is enabled in config"""
        try:
            config_file = f"/home/{self.sudo_user}/.config/pactopac/aur_enabled"
            with open(config_file) as f:
                return f.read().strip() == "1"
        except (FileNotFoundError, PermissionError, OSError):
            return False  # Default to disabled

    def set_grimaur_enabled(self, enabled):
        """Save AUR enable state to config"""
        config_dir = f"/home/{self.sudo_user}/.config/pactopac"
        os.makedirs(config_dir, exist_ok=True)
        config_file = os.path.join(config_dir, "aur_enabled")
        with open(config_file, 'w') as f:
            f.write("1" if enabled else "0")

    def get_git_mirror_enabled(self):
        """Check if git mirror is enabled in config"""
        try:
            config_file = f"/home/{self.sudo_user}/.config/pactopac/git_mirror_enabled"
            with open(config_file) as f:
                return f.read().strip() == "1"
        except (FileNotFoundError, PermissionError, OSError):
            return False

    def set_git_mirror_enabled(self, enabled):
        """Save git mirror enable state to config"""
        config_dir = f"/home/{self.sudo_user}/.config/pactopac"
        os.makedirs(config_dir, exist_ok=True)
        config_file = os.path.join(config_dir, "git_mirror_enabled")
        with open(config_file, 'w') as f:
            f.write("1" if enabled else "0")

    def get_remove_cache_enabled(self):
        """Check if remove cache is enabled in config"""
        try:
            config_file = f"/home/{self.sudo_user}/.config/pactopac/remove_cache_enabled"
            with open(config_file) as f:
                return f.read().strip() == "1"
        except (FileNotFoundError, PermissionError, OSError):
            return False

    def set_remove_cache_enabled(self, enabled):
        """Save remove cache enable state to config"""
        config_dir = f"/home/{self.sudo_user}/.config/pactopac"
        os.makedirs(config_dir, exist_ok=True)
        config_file = os.path.join(config_dir, "remove_cache_enabled")
        with open(config_file, 'w') as f:
            f.write("1" if enabled else "0")

    def get_noconfirm_enabled(self):
        """Check if noconfirm is enabled in config"""
        try:
            config_file = f"/home/{self.sudo_user}/.config/pactopac/noconfirm_enabled"
            with open(config_file) as f:
                return f.read().strip() == "1"
        except (FileNotFoundError, PermissionError, OSError):
            return False  # Default to disabled (ask for confirmation)

    def set_noconfirm_enabled(self, enabled):
        """Save noconfirm enable state to config"""
        config_dir = f"/home/{self.sudo_user}/.config/pactopac"
        os.makedirs(config_dir, exist_ok=True)
        config_file = os.path.join(config_dir, "noconfirm_enabled")
        with open(config_file, 'w') as f:
            f.write("1" if enabled else "0")

    def get_fuzzy_threshold(self):
        """Get fuzzy match threshold from config"""
        try:
            config_file = f"/home/{self.sudo_user}/.config/pactopac/fuzzy_threshold"
            with open(config_file) as f:
                return float(f.read().strip())
        except (FileNotFoundError, PermissionError, OSError, ValueError):
            return 0.4  # Default to 40%

    def set_fuzzy_threshold(self, threshold):
        """Save fuzzy match threshold to config"""
        config_dir = f"/home/{self.sudo_user}/.config/pactopac"
        os.makedirs(config_dir, exist_ok=True)
        config_file = os.path.join(config_dir, "fuzzy_threshold")
        with open(config_file, 'w') as f:
            f.write(str(threshold))

    def get_terminal_font_size(self):
        """Get terminal font size from config"""
        try:
            config_file = f"/home/{self.sudo_user}/.config/pactopac/terminal_font_size"
            with open(config_file) as f:
                return int(f.read().strip())
        except (FileNotFoundError, PermissionError, OSError, ValueError):
            return 12  # Default to 12pt

    def set_terminal_font_size(self, size):
        """Save terminal font size to config"""
        config_dir = f"/home/{self.sudo_user}/.config/pactopac"
        os.makedirs(config_dir, exist_ok=True)
        config_file = os.path.join(config_dir, "terminal_font_size")
        with open(config_file, 'w') as f:
            f.write(str(int(size)))

    def check_fh(self):
        try:
            result = subprocess.run(['sudo', '-u', self.sudo_user, 'flatpak', 'remotes'], capture_output=True, text=True, check=True)

            for line in result.stdout.split('\n'):
                if 'flathub' in line.lower():
                    return 'disabled' not in line.lower()
            return False
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return False
    
    def check_multilib_enabled(self):
        """Check if multilib is enabled (works for both Arch and Artix)"""
        try:
            with open('/etc/pacman.conf') as f:
                content = f.read()
                distro = detect_distro()

                if distro == 'artix':
                    # Artix uses [lib32]
                    return bool(re.search(r'^\[lib32\]', content, re.MULTILINE))
                else:
                    # Arch uses [multilib]
                    return bool(re.search(r'^\[multilib\]', content, re.MULTILINE))
        except (FileNotFoundError, PermissionError, OSError):
            return False

    def get_multilib_repo_name(self):
        """Get the appropriate multilib repository name based on distro"""
        distro = detect_distro()
        if distro == 'artix':
            return 'lib32'
        else:
            return 'multilib'
        
    def install_fp_and_refresh(self, dialog):
        """Install flatpak package"""
        dialog.close()
        # Always use --noconfirm for utility installs like this
        self.run_cmd(['pacman', '-S', '--noconfirm', '--needed', 'flatpak'])

    def show_info(self, message):
        """Show info dialog"""
        dialog = Adw.AlertDialog(heading="Info", body=message)
        dialog.add_response("ok", "OK")
        dialog.present(self)

    def save_theme_pref(self, is_light_theme):
        config_dir = f"/home/{self.sudo_user}/.config/pactopac"
        os.makedirs(config_dir, exist_ok=True)

        config_file = os.path.join(config_dir, "theme")
        with open(config_file, 'w') as f:
            f.write("1" if is_light_theme else "0")

    def load_theme_pref(self):
        try:
            config_file = f"/home/{self.sudo_user}/.config/pactopac/theme"
            with open(config_file) as f:
                return f.read().strip() == "1"
        except (FileNotFoundError, PermissionError, OSError):
            return False  # Default to dark theme

    def is_first_run(self):
        """Check if this is the first run by checking if theme config exists"""
        config_file = f"/home/{self.sudo_user}/.config/pactopac/theme"
        return not os.path.exists(config_file)

    def on_theme_toggle(self, switch_row, param):
        style_manager = Adw.StyleManager.get_default()
        is_light = switch_row.get_active()
        
        if is_light:
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        else:
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        
        self.save_theme_pref(is_light)

    def show_error(self, message):
        dialog = Adw.AlertDialog(heading="Error", body=message)
        dialog.add_response("ok", "OK")
        dialog.present(self)
    
    def run_toggle(self, enabled, enable_cmd, disable_cmd):
        # threaded utilities to not block UI
        def run():
            try:
                subprocess.run(enable_cmd if enabled else disable_cmd, check=True)
                GLib.idle_add(self.load_packages)
            except subprocess.CalledProcessError as e:
                print(f"Toggle error: {e}")
        threading.Thread(target=run, daemon=True).start()
    
    def on_multilib_toggle(self, switch_row, param):
        enabled = switch_row.get_active()
        repo_name = self.get_multilib_repo_name()

        if enabled:
            # Enable the multilib/lib32 repo by uncommenting
            self.run_toggle(True, ['sed', '-i', f'/^#\\[{repo_name}\\]/{{s/^#//;n;s/^#//}}', '/etc/pacman.conf'], None)
            subprocess.run(['pacman', '-Sy'], check=True)
        else:
            # Disable the multilib/lib32 repo by commenting out
            self.run_toggle(False, None, ['sed', '-i', f'/^\\[{repo_name}\\]/{{s/^/#/;n;s/^/#/}}', '/etc/pacman.conf'])
    
    def on_fh_toggle(self, switch_row, param):
        enabled = switch_row.get_active()
        if enabled:
            # Always try to add first (handles both missing and disabled cases)
            self.run_toggle(True, ['sudo', '-u', self.sudo_user, 'flatpak', 'remote-add', '--if-not-exists', 'flathub', 'https://dl.flathub.org/repo/flathub.flatpakrepo'], None)
            # Then make sure it's enabled
            subprocess.run(['sudo', '-u', self.sudo_user, 'flatpak', 'remote-modify', '--enable', 'flathub'], check=False)
        else:
            self.show_error("SUDO_USER not found")

        GLib.idle_add(self.load_packages)

    def on_aur_toggle(self, switch_row, param):
        """Handle AUR support toggle"""
        enabled = switch_row.get_active()
        self.set_grimaur_enabled(enabled)
        # Reload packages to reflect changes
        GLib.idle_add(self.load_packages)

    def on_git_mirror_toggle(self, switch_row, param):
        """Handle git mirror toggle"""
        enabled = switch_row.get_active()
        self.set_git_mirror_enabled(enabled)

    def on_remove_cache_toggle(self, switch_row, param):
        """Handle remove cache toggle"""
        enabled = switch_row.get_active()
        self.set_remove_cache_enabled(enabled)

    def on_noconfirm_toggle(self, switch_row, param):
        """Handle noconfirm toggle"""
        enabled = switch_row.get_active()
        self.set_noconfirm_enabled(enabled)

    def get_aur_count(self):
        """Get total AUR package count using grimaur count command"""
        if self.aur_total_count is not None:
            return self.aur_total_count

        if self.aur_count_loading:
            return None

        self.aur_count_loading = True

        def fetch_count():
            try:
                grimaur_path = os.path.join(os.path.dirname(__file__), 'grimaur-too/grimaur.py')
                result = subprocess.run(
                    ['sudo', '-u', self.sudo_user, 'python3', grimaur_path, 'count'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    count = int(result.stdout.strip())
                    self.aur_total_count = count
                    GLib.idle_add(self.refresh_list)
            except (subprocess.SubprocessError, ValueError, OSError):
                pass
            finally:
                self.aur_count_loading = False

        threading.Thread(target=fetch_count, daemon=True).start()
        return None

    def check_pacman_styling_enabled(self):
        """Check if pacman styling (Color and ILoveCandy) is enabled"""
        try:
            with open('/etc/pacman.conf') as f:
                content = f.read()
                # Check for uncommented Color and ILoveCandy
                has_color = 'Color\n' in content and '#Color' not in content
                has_candy = 'ILoveCandy' in content
                return has_color and has_candy
        except (FileNotFoundError, PermissionError, OSError):
            return False
    
    def on_style_toggle(self, switch_row, param):
        """Handle pacman styling toggle"""
        enabled = switch_row.get_active()
        if enabled:
            self.enable_pacman_styling()
        else:
            self.disable_pacman_styling()

    def on_fuzzy_threshold_changed(self, spin_row):
        """Handle fuzzy threshold change"""
        threshold = spin_row.get_value()
        self.fuzzy_threshold = threshold
        self.set_fuzzy_threshold(threshold)
        # Refresh the current search
        self.refresh_list()

    def on_terminal_font_size_changed(self, spin_row):
        """Handle terminal font size change"""
        size = int(spin_row.get_value())
        self.terminal_font_size = size
        self.set_terminal_font_size(size)

    def enable_pacman_styling(self):
        """Enable pacman styling using the existing script"""
        script_path = os.path.join(os.path.dirname(__file__), 'lib/stylepac.py')
        if os.path.exists(script_path):
            try:
                subprocess.run(['python3', script_path], check=True)
            except subprocess.CalledProcessError:
                self.show_error("Failed to enable pacman styling")
        else:
            self.show_error("Stylepac script (stylepac.py) not found")
    
    def disable_pacman_styling(self):
        """Disable pacman styling by reverting changes"""
        try:
            with open('/etc/pacman.conf') as f:
                lines = f.readlines()
            
            new_lines = []
            for line in lines:
                stripped = line.strip()
                # Comment out Color
                if stripped == "Color":
                    new_lines.append("#Color\n")
                # Remove ILoveCandy
                elif stripped == "ILoveCandy":
                    continue
                else:
                    new_lines.append(line)
            
            with open('/etc/pacman.conf', 'w') as f:
                f.writelines(new_lines)
                
        except Exception as e:
            self.show_error(f"Failed to disable pacman styling: {e}")
    
    def update_package_status(self):
        """Update package installation status without reloading the entire list"""
        def update():
            try:
                # Get current installed packages
                result = subprocess.run(['pacman', '-Q'], capture_output=True, text=True, check=True)
                installed_pacman = {line.split()[0] for line in result.stdout.strip().split('\n') if line}

                # Get installed flatpak packages
                installed_flatpak = set()
                try:
                    result = subprocess.run(['flatpak', 'list', '--app', '--columns=application'],
                                          capture_output=True, text=True, check=True)
                    for line in result.stdout.strip().split('\n'):
                        if line and not line.startswith('Application'):
                            installed_flatpak.add(line.strip())
                except Exception:
                    pass

                # Get installed AUR packages
                self.refresh_installed_aur()

                # Update package list with new installed status
                updated_packages = []
                for pkg in self.packages:
                    pkg_name = pkg[0]
                    pkg_repo = pkg[1]
                    pkg_type = pkg[3] if len(pkg) > 3 else "pacman"
                    
                    # Determine new installed status
                    if pkg_type == "aur":
                        is_installed = pkg_name in self.installed_aur
                    elif pkg_type == "flatpak":
                        # For flatpaks, check using the application ID (index 4), not the display name
                        pkg_app_id = pkg[4] if len(pkg) > 4 else None
                        is_installed = pkg_app_id in installed_flatpak if pkg_app_id else False
                    else:  # pacman
                        is_installed = pkg_name in installed_pacman

                    # Create updated package tuple
                    if len(pkg) > 4:
                        updated_pkg = (pkg_name, pkg_repo, is_installed, pkg_type, pkg[4])
                    else:
                        updated_pkg = (pkg_name, pkg_repo, is_installed, pkg_type)
                    updated_packages.append(updated_pkg)

                # Update packages list and refresh display
                self.packages = updated_packages
                GLib.idle_add(self.refresh_list)

            except Exception as e:
                print(f"Error updating package status: {e}")
                # Fall back to full reload on error
                GLib.idle_add(self.load_packages)

        threading.Thread(target=update, daemon=True).start()
        return False

    def load_packages(self):
        def load():
            try:
                packages = []

                # Load pacman packages
                all_pkgs = subprocess.run(['pacman', '-Sl'], capture_output=True, text=True, check=True)
                installed = {line.split()[0] for line in subprocess.run(['pacman', '-Q'], capture_output=True, text=True).stdout.split('\n') if line}

                for line in all_pkgs.stdout.split('\n'):
                    if line:
                        parts = line.split(' ', 2)
                        if len(parts) >= 2:
                            packages.append((parts[1], parts[0], parts[1] in installed, "pacman"))

                # Load flatpak packages
                if self.check_fp() and self.check_fh():
                    try:
                        available = subprocess.run(['sudo', '-u', self.sudo_user, 'flatpak', 'remote-ls', '--app', 'flathub'], capture_output=True, text=True, check=True)
                        installed_fps = subprocess.run(['sudo', '-u', self.sudo_user, 'flatpak', 'list', '--app'], capture_output=True, text=True, check=True)

                        installed_ids = {line.split('\t')[1] for line in installed_fps.stdout.split('\n') if line.strip() and len(line.split('\t')) > 1}

                        for line in available.stdout.split('\n'):
                            if line.strip():
                                parts = line.split('\t')
                                if len(parts) >= 3:
                                    packages.append((parts[0], "flathub", parts[1] in installed_ids, "flatpak", parts[1]))
                    except subprocess.CalledProcessError:
                        pass

                # Load AUR packages
                if self.check_grimaur() and self.get_grimaur_enabled():
                    try:
                        grimaur_path = os.path.join(os.path.dirname(__file__), 'grimaur-too/grimaur.py')
                        # Get installed AUR packages (foreign packages)

                        result = subprocess.run(['sudo', '-u', self.sudo_user, 'python3', grimaur_path, 'list'], capture_output=True, text=True, timeout=30)

                        installed_aur = set()
                        if result.returncode == 0:
                            for line in result.stdout.strip().split('\n'):
                                # Strip leading whitespace and color codes
                                line = line.strip()

                                # Skip empty lines
                                if not line:
                                    continue

                                # Skip header line (starts with "Installed foreign packages" or ends with colon)
                                if line.lower().startswith('installed') or line.endswith(':'):
                                    continue

                                # Parse "package-name version" format
                                parts = line.split()
                                if len(parts) >= 1:  # Changed from >= 2 to handle packages without versions
                                    pkg_name = parts[0]

                                    # Validate package name format (alphanumeric, hyphens, underscores, dots, plus)
                                    import re
                                    if re.match(r'^[a-zA-Z0-9._+-]+$', pkg_name):
                                        installed_aur.add(pkg_name)
                                        packages.append((pkg_name, "aur", True, "aur"))

                        # Store installed AUR packages for search functionality
                        self.installed_aur = installed_aur
                    except Exception as e:
                        print(f"Error loading AUR packages: {e}")
                        self.installed_aur = set()

                GLib.idle_add(self.update_list, packages)
            except Exception as e:
                GLib.idle_add(self.status.set_text, f"Error: {e}")

        threading.Thread(target=load, daemon=True).start()

    def refresh_installed_aur(self):
        """Refresh the list of installed AUR packages by calling grimaur list"""
        try:
            grimaur_path = os.path.join(os.path.dirname(__file__), 'grimaur-too/grimaur.py')
            result = subprocess.run(['sudo', '-u', self.sudo_user, 'python3', grimaur_path, 'list'],
                                    capture_output=True, text=True, timeout=10)

            installed_aur = set()
            if result.returncode == 0:
                import re
                for line in result.stdout.strip().split('\n'):
                    line = line.strip()

                    # Skip empty lines
                    if not line:
                        continue

                    # Skip header lines (e.g., "Installed foreign packages (1):")
                    if line.lower().startswith('installed') or line.endswith(':'):
                        continue

                    # Parse "package-name version" format
                    parts = line.split()
                    if len(parts) >= 1:  # Changed from >= 2 to >= 1 to handle packages without versions
                        pkg_name = parts[0]
                        # Validate package name format
                        if re.match(r'^[a-zA-Z0-9._+-]+$', pkg_name):
                            installed_aur.add(pkg_name)

            self.installed_aur = installed_aur
        except Exception as e:
            print(f"Error refreshing installed AUR list: {e}")

    def search_aur_packages(self, search_term):
        """Search AUR packages using grimaur search"""
        if not self.check_grimaur() or not self.get_grimaur_enabled():
            return []
        
        # Refresh installed AUR packages list before searching
        self.refresh_installed_aur()
        
        # Check cache for search results
        if search_term in self.aur_search_cache:
            cached_results = self.aur_search_cache[search_term]
            # Update installed status for cached results
            updated_results = []
            for pkg_name, repo, _, pkg_type in cached_results:
                is_installed = pkg_name in self.installed_aur
                updated_results.append((pkg_name, repo, is_installed, pkg_type))
            self.aur_search_cache[search_term] = updated_results
            return updated_results
        
        try:
            grimaur_path = os.path.join(os.path.dirname(__file__), 'grimaur-too/grimaur.py')
            cmd = ['sudo', '-u', self.sudo_user, 'python3', grimaur_path, '--no-color', 'search', search_term]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            aur_packages = []
            if result.returncode == 0 and result.stdout.strip():
                import re
                
                for line in result.stdout.split('\n'):
                    # Skip empty lines
                    if not line:
                        continue
                    
                    # Description lines have 4+ spaces of indentation
                    # Package lines have 0-1 spaces (for alignment of single-digit numbers)
                    # Check if line starts with 2+ spaces or tab (description line)
                    if line.startswith('  ') or line.startswith('\t'):
                        continue
                    
                    # Now strip for processing
                    line = line.strip()
                    
                    # Skip empty lines after stripping
                    if not line:
                        continue
                    
                    # Skip header lines
                    if 'search results' in line.lower():
                        continue
                    
                    # Match lines with numbering format: "NUMBER) package-name"
                    match = re.match(r'^(\d+)\)\s+(\S+)', line)
                    if not match:
                        continue
                    
                    # Extract package name (second capture group)
                    pkg_name = match.group(2)
                    
                    # Validate package name format
                    if not re.match(r'^[a-zA-Z0-9._+-]{2,}$', pkg_name):
                        continue
                    
                    # Check if it's installed
                    is_installed = pkg_name in self.installed_aur
                    aur_packages.append((pkg_name, "aur", is_installed, "aur"))
            
            # match how grimoir works
            aur_packages.reverse()
            # Cache the results
            self.aur_search_cache[search_term] = aur_packages
            return aur_packages
        
        except Exception as e:
            print(f"Error searching AUR: {e}")
            return []

    def update_list(self, packages):
        self.packages = packages
        self.current_page = 0
        self.refresh_list()
        return False
    
    def on_search_changed(self, search_entry):
        self.current_page = 0
        search_text = search_entry.get_text().strip()

        # When searching, automatically switch to All tab
        if search_text:
            self.view_stack.set_visible_child_name("all")
            self.filter_label.set_label("Filter: All")

            # Trigger async AUR search if enabled
            if self.check_grimaur() and self.get_grimaur_enabled():
                def search_and_update():
                    aur_results = self.search_aur_packages(search_text)
                    # Add AUR search results to packages list
                    # Remove old AUR search results first
                    GLib.idle_add(self.merge_aur_search_results, aur_results)

                threading.Thread(target=search_and_update, daemon=True).start()
        else:
            # Clear search cache when search is cleared
            self.aur_search_cache.clear()

        self.refresh_list()

    def merge_aur_search_results(self, aur_results):
        """Merge AUR search results into the main package list"""
        # Remove existing AUR packages that are not installed
        self.packages = [p for p in self.packages if not (len(p) > 3 and p[3] == "aur" and not p[2])]

        # Create a set of existing package names to avoid duplicates
        existing_names = {p[0] for p in self.packages}

        # Add new AUR search results only if not already in the list
        for aur_pkg in aur_results:
            if aur_pkg[0] not in existing_names:
                self.packages.append(aur_pkg)

        # Refresh the display
        self.refresh_list()
        return False

    def on_search_key_pressed(self, controller, keyval, keycode, state):
        """Handle key presses in search entry"""
        
        # Down arrow: focus the current list
        if keyval == Gdk.KEY_Down:
            current_list = self.get_current_list()
            if current_list:
                selected_row = current_list.get_selected_row()
                if not selected_row:
                    # Select first row if nothing selected
                    first_row = current_list.get_row_at_index(0)
                    if first_row:
                        current_list.select_row(first_row)
                        selected_row = first_row

                if selected_row:
                    current_list.grab_focus()
                    return True

        return False

    def get_current_list(self):
        """Get the ListBox for the current tab"""
        if self.current_tab == "installed":
            return self.installed_list
        elif self.current_tab == "available":
            return self.available_list
        elif self.current_tab == "flatpak":
            return self.flatpak_list
        elif self.current_tab == "aur":
            return self.aur_list
        else:  # all tab
            return self.all_list
    
    def fuzzy_match(self, search_text, package_name):
        """Check if search_text fuzzy matches package_name"""
        if not search_text:
            return True, 1.0

        search_lower = search_text.lower()
        name_lower = package_name.lower()

        # Exact substring match gets priority
        if search_lower in name_lower:
            return True, 1.0

        # Fuzzy match using SequenceMatcher
        similarity = SequenceMatcher(None, search_lower, name_lower).ratio()

        # Match if similarity is above user-configured threshold
        return similarity >= self.fuzzy_threshold, similarity

    def refresh_list(self):
        # Determine which list and button to use based on current tab
        if self.current_tab == "installed":
            current_list = self.installed_list
            load_more_btn = self.installed_load_more
        elif self.current_tab == "available":
            current_list = self.available_list
            load_more_btn = self.available_load_more
        elif self.current_tab == "flatpak":
            current_list = self.flatpak_list
            load_more_btn = self.flatpak_load_more
        elif self.current_tab == "aur":
            current_list = self.aur_list
            load_more_btn = self.aur_load_more
        else:  # all tab
            current_list = self.all_list
            load_more_btn = self.all_load_more

        # Clear the current list if starting from page 0
        if self.current_page == 0:
            while child := current_list.get_first_child():
                current_list.remove(child)

        search_text = self.search.get_text()

        # Filter packages based on search and tab with fuzzy matching
        matches_with_scores = []

        if self.current_tab == "installed":
            # Show installed pacman packages only
            for p in self.packages:
                if p[2] and len(p) > 3 and p[3] == "pacman":
                    matches, score = self.fuzzy_match(search_text, p[0])
                    if matches:
                        matches_with_scores.append((p, score))
        elif self.current_tab == "available":
            # Show available packages (not installed)
            for p in self.packages:
                if not p[2]:
                    matches, score = self.fuzzy_match(search_text, p[0])
                    if matches:
                        matches_with_scores.append((p, score))
        elif self.current_tab == "flatpak":
            # Show installed flatpak packages only
            for p in self.packages:
                if p[2] and len(p) > 3 and p[3] == "flatpak":
                    matches, score = self.fuzzy_match(search_text, p[0])
                    if matches:
                        matches_with_scores.append((p, score))
        elif self.current_tab == "aur":
            # Show all AUR packages (installed and available from search)
            for p in self.packages:
                if len(p) > 3 and p[3] == "aur":
                    matches, score = self.fuzzy_match(search_text, p[0])
                    if matches:
                        matches_with_scores.append((p, score))
        else:  # all tab
            # Show all packages (installed and available)
            for p in self.packages:
                matches, score = self.fuzzy_match(search_text, p[0])
                if matches:
                    matches_with_scores.append((p, score))

        # Sort by score (highest first) to show best matches at the top
        matches_with_scores.sort(key=lambda x: x[1], reverse=True)
        self.filtered_packages = [p for p, score in matches_with_scores]
        
        total_filtered = len(self.filtered_packages)
        start_idx = self.current_page * self.page_size
        end_idx = min((self.current_page + 1) * self.page_size, total_filtered)
        
        packages_to_show = self.filtered_packages[start_idx:end_idx] if self.current_page > 0 else self.filtered_packages[0:end_idx]
        
        # Add packages to the appropriate list
        for pkg_data in packages_to_show:
            self.add_package_row(pkg_data, current_list)
        
        # Handle empty states
        if total_filtered == 0:
            self.add_empty_state_message(current_list)
        
        # Update UI
        has_more = end_idx < total_filtered
        load_more_btn.set_sensitive(has_more)
        load_more_btn.set_label("More..." if has_more else "All packages loaded")

        total_showing = min((self.current_page + 1) * self.page_size, total_filtered)
        if search_text:
            self.status.set_text(f"Showing {total_showing} of {total_filtered} filtered packages")
        else:
            total_installed_pacman = sum(1 for pkg in self.packages if pkg[2] and len(pkg) > 3 and pkg[3] == "pacman")
            total_installed_flatpak = sum(1 for pkg in self.packages if pkg[2] and len(pkg) > 3 and pkg[3] == "flatpak")
            total_installed_aur = sum(1 for pkg in self.packages if pkg[2] and len(pkg) > 3 and pkg[3] == "aur")
            total_installed = total_installed_pacman + total_installed_flatpak + total_installed_aur

            if self.current_tab == "installed":
                # Get total size for pacman packages only
                total_size = self.get_total_package_sizes()
                self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_installed_pacman} pacman installed • {total_size}")
            elif self.current_tab == "flatpak":
                self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_installed_flatpak} flatpak installed")
            elif self.current_tab == "aur":
                # Get total AUR count
                aur_count = self.get_aur_count()
                if search_text:
                    # When searching, show search result count
                    total_aur_available = sum(1 for pkg in self.packages if not pkg[2] and len(pkg) > 3 and pkg[3] == "aur")
                    self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_installed_aur} installed, {total_aur_available} in results")
                else:
                    # When not searching, show total AUR size
                    if aur_count is not None:
                        self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_installed_aur} installed, {aur_count:,} available in AUR")
                    else:
                        self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_installed_aur} installed, loading count...")
            elif self.current_tab == "available":
                total_available = len(self.packages) - total_installed
                self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_available} available packages")
            else:  # all tab
                total_available = len(self.packages) - total_installed
                # Add AUR total count if enabled
                if self.check_grimaur() and self.get_grimaur_enabled():
                    aur_count = self.get_aur_count()
                    if aur_count is not None:
                        # Add AUR total minus already counted installed AUR packages
                        total_available = total_available + aur_count - total_installed_aur
                        self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_installed} installed, {total_available:,} available")
                    else:
                        self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_installed} installed, {total_available:,}+ available (loading AUR count...)")
                else:
                    self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_installed} installed, {total_available} available")

        # Auto-select first package (but don't auto-focus to allow mouse scrolling)
        if self.current_page == 0 and total_filtered > 0:
            first_row = current_list.get_row_at_index(0)
            if first_row:
                current_list.select_row(first_row)
    
    def add_package_row(self, pkg_data, target_list):
        """Add a package row to the specified list"""
        name, repo, installed, pkg_type = pkg_data[:4]

        row = Gtk.ListBoxRow()
        box = Gtk.Box(spacing=12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)

        icon = Gtk.Label(label="●" if installed else "○", width_request=20)
        if installed:
            icon.add_css_class("success")
        box.append(icon)

        name_label = Gtk.Label(label=name, halign=Gtk.Align.START, hexpand=True)
        box.append(name_label)

        repo_label = Gtk.Label(label=repo)
        repo_label.add_css_class("dim-label")
        if pkg_type == "flatpak":
            repo_label.add_css_class("accent")
        elif pkg_type == "aur":
            repo_label.add_css_class("warning")
        box.append(repo_label)

        row.set_child(box)
        row.pkg_data = pkg_data
        target_list.append(row)
    
    def add_empty_state_message(self, target_list):
        """Add an empty state message to the specified list"""
        row = Gtk.ListBoxRow(selectable=False, activatable=False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        box.set_margin_top(60)
        box.set_margin_bottom(60)
        box.set_margin_start(24)
        box.set_margin_end(24)
        
        if self.current_tab == "installed":
            icon = Gtk.Image.new_from_icon_name("package-x-generic-symbolic")
            icon.set_pixel_size(64)
            icon.add_css_class("dim-label")
            title = "No Packages Installed"
            subtitle = "Install packages from the Available tab to see them here."
        elif self.current_tab == "flatpak":
            icon = Gtk.Image.new_from_icon_name("application-x-addon-symbolic")
            icon.set_pixel_size(64)
            icon.add_css_class("dim-label")
            if not self.check_fp():
                title = "Flatpak Not Available"
                subtitle = "Install Flatpak from Settings to use universal applications."
            elif not self.check_fh():
                title = "Flathub Not Enabled"
                subtitle = "Enable Flathub repository in Settings to install Flatpak apps."
            else:
                title = "No Flatpak Apps Installed"
                subtitle = "Install Flatpak applications to see them here."
        elif self.current_tab == "aur":
            icon = Gtk.Image.new_from_icon_name("software-properties-symbolic")
            icon.set_pixel_size(64)
            icon.add_css_class("dim-label")
            if not self.check_grimaur():
                title = "Grimaur Not Available"
                subtitle = "Grimaur is required for AUR support."
            elif not self.get_grimaur_enabled():
                title = "AUR Support Disabled"
                subtitle = "Enable AUR support in Settings to install AUR packages."
            else:
                title = "No AUR Packages Found"
                subtitle = "Search for AUR packages to install, or view installed ones here."
        elif self.current_tab == "available":
            icon = Gtk.Image.new_from_icon_name("system-search-symbolic")
            icon.set_pixel_size(64)
            icon.add_css_class("dim-label")
            title = "No Packages Found"
            subtitle = "Try adjusting your search terms or check your internet connection."
        else:  # all tab
            icon = Gtk.Image.new_from_icon_name("view-list-symbolic")
            icon.set_pixel_size(64)
            icon.add_css_class("dim-label")
            title = "No Matching Packages"
            subtitle = "Try different search terms to find packages."
        
        box.append(icon)
        
        title_label = Gtk.Label(label=title, halign=Gtk.Align.CENTER)
        title_label.add_css_class("title-2")
        box.append(title_label)
        
        subtitle_label = Gtk.Label(label=subtitle, halign=Gtk.Align.CENTER, wrap=True)
        subtitle_label.add_css_class("dim-label")
        box.append(subtitle_label)
        
        row.set_child(box)
        target_list.append(row)

    def load_more_packages(self, button):
        self.current_page += 1
        self.refresh_list()
    
    def on_select(self, listbox, row):
        if row:
            self.selected = row.pkg_data
            installed = self.selected[2]

            self.info_btn.set_sensitive(True)
            self.action_btn.set_sensitive(True)

            if installed:
                self.action_btn.set_label("Remove")
                self.action_btn.remove_css_class("suggested-action")
                self.action_btn.add_css_class("destructive-action")
            else:
                self.action_btn.set_label("Install")
                self.action_btn.remove_css_class("destructive-action")
                self.action_btn.add_css_class("suggested-action")
        else:
            self.selected = None
            self.info_btn.set_sensitive(False)
            self.action_btn.set_sensitive(False)

    def on_list_key_pressed(self, controller, keyval, keycode, state, listbox):
        """Handle arrow key navigation in package lists"""

        # Tab: Skip list and go to next major section (buttons)
        if keyval == Gdk.KEY_Tab:
            # Move focus to the first button (info button)
            self.info_btn.grab_focus()
            return True

        # Shift+Tab: Go back to filter button
        if keyval == Gdk.KEY_ISO_Left_Tab:
            # Move focus back to filter button
            self.filter_button.grab_focus()
            return True

        # Enter: install/remove selected package
        if keyval == Gdk.KEY_Return or keyval == Gdk.KEY_KP_Enter:
            if self.selected and self.action_btn.get_sensitive():
                self.handle_package_action(self.action_btn)
                return True

        # Backspace or Space: return to search
        if keyval == Gdk.KEY_BackSpace or keyval == Gdk.KEY_space:
            self.search.grab_focus()
            # Let the search handle the key
            return False

        # Any regular typing key (letters, numbers, etc): return to search
        if keyval >= 32 and keyval <= 126:  # Printable ASCII characters
            self.search.grab_focus()
            # Let the search handle the key
            return False

        selected_row = listbox.get_selected_row()
        if not selected_row:
            # If nothing selected, select first row
            first_row = listbox.get_row_at_index(0)
            if first_row:
                listbox.select_row(first_row)
                self.scroll_to_row(listbox, first_row)
            return False

        current_index = selected_row.get_index()

        if keyval == Gdk.KEY_Down:
            # Move down
            next_row = listbox.get_row_at_index(current_index + 1)
            if next_row:
                listbox.select_row(next_row)
                # Scroll to make it visible
                self.scroll_to_row(listbox, next_row)
                return True
        elif keyval == Gdk.KEY_Up:
            # Move up
            if current_index > 0:
                prev_row = listbox.get_row_at_index(current_index - 1)
                if prev_row:
                    listbox.select_row(prev_row)
                    # Scroll to make it visible
                    self.scroll_to_row(listbox, prev_row)
                    return True

        return False

    def on_terminal_escape_pressed(self, controller, keyval, keycode, state, dialog):
        """Handle escape key press in terminal dialog"""
        if keyval == Gdk.KEY_Escape:
            # If process already finished, just close without confirmation
            if dialog.process_finished:
                dialog.close()
                return True

            # Show confirmation dialog only if process is still running
            confirm_dialog = Adw.AlertDialog(
                heading="Exit Terminal?",
                body="Are you sure you want to close this terminal? The running process will be terminated."
            )
            confirm_dialog.add_response("cancel", "Cancel")
            confirm_dialog.add_response("exit", "Exit")
            confirm_dialog.set_response_appearance("exit", Adw.ResponseAppearance.DESTRUCTIVE)
            confirm_dialog.set_default_response("cancel")

            def on_confirm_response(d, response):
                if response == "exit":
                    # Send 'n' to answer any pending prompt, then close
                    if hasattr(dialog, 'terminal') and dialog.terminal:
                        try:
                            dialog.terminal.feed_child()
                        except (OSError, AttributeError):
                            pass
                    # Set flag to allow close without re-showing confirmation
                    dialog.confirmed_close = True
                    dialog.close()

            confirm_dialog.connect("response", on_confirm_response)
            confirm_dialog.present(dialog)
            return True
        return False

    def scroll_to_row(self, listbox, row):
        """Scroll the list to make the row visible"""
        if not row:
            return

        # Get the parent ScrolledWindow - need to traverse up through containers
        parent = listbox.get_parent()
        scroll_window = None

        # Traverse up to find ScrolledWindow (it's wrapped in Box containers)
        while parent:
            if isinstance(parent, Gtk.ScrolledWindow):
                scroll_window = parent
                break
            parent = parent.get_parent()

        if not scroll_window:
            return

        # Use GTK4's proper method - compute bounds relative to listbox
        success, bounds = row.compute_bounds(listbox)
        if not success:
            return

        # Get the vertical adjustment
        vadj = scroll_window.get_vadjustment()
        if not vadj:
            return

        # Get bounds values
        row_y = bounds.get_y()
        row_height = bounds.get_height()

        # Get visible area
        page_size = vadj.get_page_size()
        current_value = vadj.get_value()

        # Add some padding for better UX (20px margin)
        padding = 20

        # Calculate if row is outside visible area
        if row_y < current_value + padding:
            # Row is above visible area, scroll up
            new_value = max(0, row_y - padding)
            vadj.set_value(new_value)
        elif row_y + row_height > current_value + page_size - padding:
            # Row is below visible area, scroll down
            new_value = min(vadj.get_upper() - page_size, row_y + row_height - page_size + padding)
            vadj.set_value(new_value)

    def handle_package_action(self, button):
        if not self.selected or len(self.selected) < 4:
            return

        installed = self.selected[2]
        pkg_type = self.selected[3]

        if pkg_type == "flatpak":
            if len(self.selected) < 5:
                self.show_error("Invalid flatpak package data")
                return

            app_id = self.selected[4]
            if installed:
                cmd = ['sudo', '-u', self.sudo_user, 'flatpak', 'uninstall', app_id]
                if self.get_noconfirm_enabled():
                    cmd.insert(4, '-y')  # Insert -y before app_id
            else:
                cmd = ['sudo', '-u', self.sudo_user, 'flatpak', 'install', 'flathub', app_id]
                if self.get_noconfirm_enabled():
                    cmd.insert(4, '-y')  # Insert -y before flathub

        elif pkg_type == "aur":
            grimaur_path = os.path.join(os.path.dirname(__file__), 'grimaur-too/grimaur.py')

            # Check if grimaur exists
            if not os.path.exists(grimaur_path):
                self.show_error(f"Grimaur not found at: {grimaur_path}")
                return

            pkg_name = self.selected[0]
            if installed:
                # Remove AUR package
                cmd = ['sudo', '-u', self.sudo_user, 'python3', grimaur_path, 'remove', pkg_name]
                if self.get_remove_cache_enabled():
                    cmd.append('--remove-cache')
                if self.get_noconfirm_enabled():
                    cmd.append('--noconfirm')
            else:
                # Install AUR package
                cmd = ['sudo', '-u', self.sudo_user, 'python3', grimaur_path, 'install', pkg_name]
                # TODO: Add this to config
                #dest_root = "/tmp/pactopac/aur"
                #cmd.extend(['--dest-root', dest_root])
                
                if self.get_noconfirm_enabled():
                    cmd.append('--noconfirm')
                if self.get_git_mirror_enabled():
                    cmd.pop(5)
                    cmd.append('--git-mirror')

            # Print debug info
            print(f"Running AUR command: {' '.join(cmd)}")
        else:
            pkg_name = self.selected[0]
            if installed:
                cmd = ['pacman', '-R', pkg_name]
                if self.get_noconfirm_enabled():
                    cmd.append('--noconfirm')
            else:
                cmd = ['pacman', '-S', pkg_name]
                if self.get_noconfirm_enabled():
                    cmd.append('--noconfirm')

        self.run_cmd(cmd)
    
    def handle_update(self, button):
        """Handle system update - use grimaur if AUR is enabled, otherwise use pacman"""
        if self.check_grimaur() and self.get_grimaur_enabled():
            # Use grimaur update --global (updates system first, then AUR packages)
            grimaur_path = os.path.join(os.path.dirname(__file__), 'grimaur-too/grimaur.py')
            cmd = ['sudo', '-u', self.sudo_user, 'python3', grimaur_path, 'update', '--global']
            if self.get_noconfirm_enabled():
                cmd.append('--noconfirm')
            self.run_cmd(cmd)
        else:
            # Standard pacman update
            cmd = ['pacman', '-Syu']
            if self.get_noconfirm_enabled():
                cmd.append('--noconfirm')
            self.run_cmd(cmd)
    
    def get_total_package_sizes(self):

        # Get pacman package sizes
        result = subprocess.run(['pacman', '-Qi'], capture_output=True, text=True, check=True)
        total_size = 0
        
        for line in result.stdout.split('\n'):
            if line.startswith('Installed Size'):
                size_str = line.split(':', 1)[1].strip()
                # Parse size (handles KiB, MiB, GiB)
                if 'KiB' in size_str:
                    size = float(size_str.replace('KiB', '').strip()) * 1024
                elif 'MiB' in size_str:
                    size = float(size_str.replace('MiB', '').strip()) * 1024 * 1024
                elif 'GiB' in size_str:
                    size = float(size_str.replace('GiB', '').strip()) * 1024 * 1024 * 1024
                else:
                    continue
                total_size += size
        
        # Format the total size nicely
        if total_size > 1024**3:
            return f"{total_size / (1024**3):.1f} GiB"
        elif total_size > 1024**2:
            return f"{total_size / (1024**2):.1f} MiB"
        else:
            return f"{total_size / 1024:.1f} KiB"
                
    def show_package_info(self, button):
        if not self.selected or len(self.selected) < 4:
            return

        # Store package info in local variables for thread safety
        pkg_name = self.selected[0]
        pkg_type = self.selected[3]
        pkg_installed = self.selected[2] if len(self.selected) > 2 else False
        pkg_app_id = self.selected[4] if len(self.selected) > 4 else None

        dialog = Adw.Window(title=f"Info: {pkg_name}", transient_for=self, modal=True)
        dialog.set_default_size(600, 400)

        # Add escape key handler to close dialog
        info_key_controller = Gtk.EventControllerKey()
        info_key_controller.connect("key-pressed", lambda c, k, kc, s: dialog.close() if k == Gdk.KEY_Escape else False)
        dialog.add_controller(info_key_controller)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        dialog.set_content(toolbar_view)

        spinner = Gtk.Spinner(spinning=True)
        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        loading_box.append(spinner)
        loading_box.append(Gtk.Label(label="Loading..."))
        toolbar_view.set_content(loading_box)
        dialog.present()

        def load_info():
            try:
                if pkg_type == "flatpak":
                    # For flatpak, we need the full application ID
                    if pkg_app_id:
                        if pkg_installed:
                            # For installed apps, use 'flatpak info'
                            result = subprocess.run(['sudo', '-u', self.sudo_user, 'flatpak', 'info', pkg_app_id], capture_output=True, text=True, check=True)
                        else:
                            # For uninstalled apps, use 'flatpak remote-info' with the remote name
                            result = subprocess.run(['sudo', '-u', self.sudo_user, 'flatpak', 'remote-info', 'flathub', pkg_app_id], capture_output=True, text=True, check=True)
                    else:
                        print("Error - flatpak package missing app ID")
                        GLib.idle_add(self.display_info, toolbar_view, "Error: Flatpak package data incomplete")
                        return
                elif pkg_type == "aur":
                    # For AUR packages, use grimaur inspect
                    grimaur_path = os.path.join(os.path.dirname(__file__), 'grimaur-too/grimaur.py')
                    cmd = ['sudo', '-u', self.sudo_user, 'python3', grimaur_path, 'inspect', pkg_name, '--full']
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)

                else:
                    result = subprocess.run(['pacman', '-Si', pkg_name], capture_output=True, text=True, check=True)
                    if not result.stdout.strip():
                        result = subprocess.run(['pacman', '-Qi', pkg_name], capture_output=True, text=True, check=True)

                GLib.idle_add(self.display_info, toolbar_view, result.stdout)

            except subprocess.CalledProcessError as e:
                error_msg = f"Failed to get info for {pkg_name}"
                if pkg_type == "flatpak":
                    cmd_used = f"flatpak {'info' if pkg_installed else 'remote-info flathub'} {pkg_app_id if pkg_app_id else 'unknown'}"
                    error_msg += f"\nCommand: {cmd_used}"
                    error_msg += f"\nError: {e.stderr if e.stderr else 'Unknown error'}"
                elif pkg_type == "aur":
                    error_msg += f"\nError: {e.stderr if e.stderr else 'Unknown error'}"
                print(f"Debug - command failed: {error_msg}")
                GLib.idle_add(self.display_info, toolbar_view, error_msg)

        threading.Thread(target=load_info, daemon=True).start()
    
    def display_info(self, toolbar_view, info_text):
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_margin_top(12)
        scroll.set_margin_bottom(12)
        scroll.set_margin_start(12)
        scroll.set_margin_end(12)

        # Enable keyboard navigation
        scroll.set_can_focus(True)
        scroll.set_focus_on_click(True)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # Add freeze button for installed pacman packages
        if self.selected and self.selected[2] and self.selected[3] == "pacman":
            pkg_name = self.selected[0]
            is_frozen = is_in_ignorepkg(pkg_name)

            freeze_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            freeze_box.set_margin_bottom(12)

            freeze_label = Gtk.Label(label="Package Update Status:", halign=Gtk.Align.START)
            freeze_label.set_markup("<b>Package Update Status:</b>")
            freeze_box.append(freeze_label)

            freeze_btn = Gtk.Button(label="Unfreeze" if is_frozen else "Freeze")
            freeze_btn.set_tooltip_text("Remove from IgnorePkg" if is_frozen else "Add to IgnorePkg to prevent updates")
            if not is_frozen:
                freeze_btn.add_css_class("suggested-action")
            else:
                freeze_btn.add_css_class("destructive-action")
            freeze_btn.connect("clicked", lambda b: self.toggle_package_freeze(b, pkg_name))
            freeze_box.append(freeze_btn)

            status_label = Gtk.Label(label="[Frozen]" if is_frozen else "[Updates enabled]", halign=Gtk.Align.START, hexpand=True)
            status_label.add_css_class("dim-label")
            freeze_box.append(status_label)

            content_box.append(freeze_box)

            # Add separator
            separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            separator.set_margin_top(6)
            separator.set_margin_bottom(12)
            content_box.append(separator)
        
        lines = info_text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Handle both pacman format (Key : Value) and flatpak format (Key: Value)
            if ':' in line and not line.startswith(' ') and not line.startswith('\t'):
                # Split only on the first colon to handle values that contain colons
                parts = line.split(':', 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip()
                    
                    row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                    
                    key_label = Gtk.Label(label=key, halign=Gtk.Align.START, valign=Gtk.Align.START)
                    key_label.set_markup(f"<b>{key}</b>")
                    key_label.set_size_request(120, -1)
                    key_label.set_xalign(0.0)  # Left align within allocated space
                    
                    value_label = Gtk.Label(
                        label=value, 
                        halign=Gtk.Align.START, 
                        valign=Gtk.Align.START, 
                        hexpand=True, 
                        wrap=True, 
                        selectable=True
                    )
                    value_label.set_xalign(0.0)  # Left align within allocated space
                    
                    row_box.append(key_label)
                    row_box.append(value_label)
                    content_box.append(row_box)
            else:
                # Handle continuation lines or lines without colons
                if line.startswith(' ') or line.startswith('\t'):
                    # This is likely a continuation of the previous field
                    continue_label = Gtk.Label(
                        label=line.strip(), 
                        halign=Gtk.Align.START, 
                        hexpand=True, 
                        wrap=True, 
                        selectable=True
                    )
                    continue_label.set_xalign(0.0)
                    continue_label.set_margin_start(132)  # Indent to align with values
                    content_box.append(continue_label)
                else:
                    # Lines without colons (like section headers)
                    section_label = Gtk.Label(label=line, halign=Gtk.Align.START, wrap=True, selectable=True)
                    section_label.set_markup(f"<b>{line}</b>")
                    section_label.set_xalign(0.0)
                    content_box.append(section_label)
        
        # If no structured content was found, show the raw text
        if not content_box.get_first_child():
            raw_label = Gtk.Label(
                label=info_text, 
                halign=Gtk.Align.START, 
                valign=Gtk.Align.START,
                wrap=True, 
                selectable=True
            )
            raw_label.set_xalign(0.0)
            content_box.append(raw_label)
        
        scroll.set_child(content_box)
        toolbar_view.set_content(scroll)
        return False

    def toggle_package_freeze(self, button, package_name):
        """Toggle package freeze status (add/remove from IgnorePkg)"""

        is_frozen = is_in_ignorepkg(package_name)

        if is_frozen:
            # Unfreeze
            if remove_from_ignorepkg(package_name):
                button.set_label("Freeze")
                button.remove_css_class("destructive-action")
                button.add_css_class("suggested-action")
                button.set_tooltip_text("Add to IgnorePkg to prevent updates")
                # Update status label if it exists
                parent = button.get_parent()
                if parent:
                    status_label = parent.get_last_child()
                    if status_label and isinstance(status_label, Gtk.Label):
                        status_label.set_label("[Updates enabled]")
            else:
                self.show_error(f"Failed to unfreeze {package_name}")
        else:
            # Freeze
            if add_to_ignorepkg(package_name):
                button.set_label("Unfreeze")
                button.remove_css_class("suggested-action")
                button.add_css_class("destructive-action")
                button.set_tooltip_text("Remove from IgnorePkg")
                # Update status label if it exists
                parent = button.get_parent()
                if parent:
                    status_label = parent.get_last_child()
                    if status_label and isinstance(status_label, Gtk.Label):
                        status_label.set_label("[Frozen]")
            else:
                self.show_error(f"Failed to freeze {package_name}")

    def run_cmd(self, cmd):
        dialog = Adw.Window(title="Terminal", transient_for=self, modal=True)
        dialog.set_default_size(800, 600)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)
        dialog.set_content(toolbar_view)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Create VTE terminal widget
        terminal = Vte.Terminal()
        terminal.set_scroll_on_output(True)
        terminal.set_scrollback_lines(10000)
        terminal.set_mouse_autohide(True)

        # Apply terminal styling
        terminal.set_cursor_blink_mode(Vte.CursorBlinkMode.ON)

        # Apply font size
        font_desc = Pango.FontDescription(f"Monospace {self.terminal_font_size}")
        terminal.set_font(font_desc)

        # Store terminal reference on dialog for cleanup
        dialog.terminal = terminal
        dialog.confirmed_close = False  # Flag to prevent close confirmation loop
        dialog.process_finished = False  # Flag to track if process has exited

        # Add escape key handler to terminal widget
        terminal_key_controller = Gtk.EventControllerKey()
        terminal_key_controller.connect("key-pressed", self.on_terminal_escape_pressed, dialog)
        terminal.add_controller(terminal_key_controller)

        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_child(terminal)
        content_box.append(scroll)

        # Progress bar with accelerating pulse effect (full width)
        progress = Gtk.ProgressBar(show_text=False)
        progress.set_valign(Gtk.Align.CENTER)
        content_box.append(progress)

        # Status bar at bottom
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        status_box.set_margin_top(12)
        status_box.set_margin_bottom(12)
        status_box.set_margin_start(12)
        status_box.set_margin_end(12)

        status_label = Gtk.Label(label="Running command...", halign=Gtk.Align.START)
        status_label.add_css_class("dim-label")
        status_box.append(status_label)

        content_box.append(status_box)

        toolbar_view.set_content(content_box)

        # Handle close button (X) with same confirmation as escape
        def on_close_request(window):
            # If process finished or already confirmed, allow close
            if dialog.process_finished or dialog.confirmed_close:
                return False  # Allow close
            # Otherwise show confirmation
            self.on_terminal_escape_pressed(None, Gdk.KEY_Escape, 0, 0, dialog)
            return True  # Prevent default close

        dialog.connect("close-request", on_close_request)
        dialog.present()

        # Start progress bar with accelerating pulse effect
        pulse_position = [0.0]  # Current position (0.0 to 1.0)
        pulse_speed = [0.01]    # Current speed, will accelerate

        def accelerating_pulse():
            # Update position
            pulse_position[0] += pulse_speed[0]

            # Accelerate as it moves
            pulse_speed[0] += 0.0005

            # Reset when reaching the end
            if pulse_position[0] >= 1.0:
                pulse_position[0] = 0.0
                pulse_speed[0] = 0.01  # Reset to initial speed

            progress.set_fraction(pulse_position[0])
            return True  # Continue animation

        pulse_id = GLib.timeout_add(16, accelerating_pulse)  # ~60fps

        # Track terminal PID for cleanup
        terminal_pid = None

        def on_child_exited(term, status):
            nonlocal terminal_pid

            # Mark process as finished
            dialog.process_finished = True

            # Stop progress bar pulsing and set to full
            GLib.source_remove(pulse_id)
            GLib.idle_add(lambda: progress.set_fraction(1.0))

            # Update status and progress bar color
            if status == 0:
                GLib.idle_add(lambda: progress.add_css_class("success"))
                GLib.idle_add(lambda: status_label.set_text("✓ Success"))
                GLib.timeout_add(500, self.update_package_status)
            else:
                GLib.idle_add(lambda: progress.add_css_class("error"))
                GLib.idle_add(lambda: status_label.set_text(f"✗ Error (exit code: {status})"))

        terminal.connect("child-exited", on_child_exited)

        # Spawn command in terminal
        try:
            terminal.spawn_async(
                Vte.PtyFlags.DEFAULT,
                None,  # working directory (None = inherit)
                cmd,   # command and args
                None,  # environment (None = inherit)
                GLib.SpawnFlags.DEFAULT,
                None,  # child setup
                None,  # child setup data
                -1,    # timeout (-1 = no timeout)
                None,  # cancellable
                self.on_terminal_spawn_callback,  # callback
                (terminal, status_label, pulse_id, progress)  # user data
            )
        except Exception as e:
            GLib.source_remove(pulse_id)
            progress.set_fraction(1.0)
            progress.add_css_class("error")
            status_label.set_text(f"✗ Failed to spawn command: {e}")

    def on_terminal_spawn_callback(self, terminal, pid, error, user_data):
        """Callback when terminal spawn completes"""
        term, status_label, pulse_id, progress = user_data

        if error:
            GLib.source_remove(pulse_id)
            GLib.idle_add(lambda: progress.set_fraction(1.0))
            GLib.idle_add(lambda: progress.add_css_class("error"))
            GLib.idle_add(lambda: status_label.set_text(f"✗ Error: {error}"))
            return

        # Create a pseudo-process object for tracking
        class TerminalProcess:
            def __init__(self, pid):
                self.pid = pid

            def poll(self):
                # Check if process is still running
                try:
                    os.kill(self.pid, 0)
                    return None  # Still running
                except OSError:
                    return 0  # Process finished

            def terminate(self):
                try:
                    os.kill(self.pid, signal.SIGTERM)
                except OSError:
                    pass

            def kill(self):
                try:
                    os.kill(self.pid, signal.SIGKILL)
                except OSError:
                    pass

            def wait(self, timeout=None):
                # Simple wait implementation
                import time
                start = time.time()
                while self.poll() is None:
                    if timeout and (time.time() - start) > timeout:
                        raise subprocess.TimeoutExpired(self.pid, timeout)
                    time.sleep(0.1)

        # Track the process
        proc_obj = TerminalProcess(pid)
        self.running_processes.append(proc_obj)

    def install_pacman_contrib(self, dialog):
        """Install pacman-contrib and refresh settings dialog"""
        dialog.close()

        def check_and_reopen():
            """Poll for installation completion and reopen settings"""
            def check_installation_complete():
                if check_pacman_contrib():
                    # pacman-contrib is now installed
                    self.show_settings(None)
                    return False  # Stop the timeout
                else:
                    return True  # Continue checking

            # Start polling every 500ms for installation completion
            GLib.timeout_add(500, check_installation_complete)

        # Install pacman-contrib
        self.run_cmd(['pacman', '-S', '--noconfirm', 'pacman-contrib'])
        GLib.timeout_add(100, lambda: check_and_reopen() or False)

    def show_dependency_analysis(self, button):
        """Show dialog with packages that have many dependencies"""
        # Create a new dialog window
        dialog = Adw.Window(title="Dependency Analysis", transient_for=self, modal=True)
        dialog.set_default_size(800, 600)

        toolbar_view = Adw.ToolbarView()
        dialog.set_content(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        # Show loading spinner initially
        spinner = Gtk.Spinner(spinning=True)
        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                             halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        loading_box.append(spinner)
        loading_box.append(Gtk.Label(label="Analyzing dependencies..."))
        toolbar_view.set_content(loading_box)
        dialog.present()

        def analyze():
            # Get packages with 5+
            heavy_packages = get_packages_with_many_deps(threshold=5)

            GLib.idle_add(self.display_dependency_results, toolbar_view, heavy_packages)

        threading.Thread(target=analyze, daemon=True).start()

    def display_dependency_results(self, toolbar_view, heavy_packages):
        """Display the dependency analysis results"""
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_box.set_margin_top(12)
        main_box.set_margin_bottom(12)
        main_box.set_margin_start(12)
        main_box.set_margin_end(12)

        if not heavy_packages:
            # No heavy packages found
            empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                               halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
            icon.set_pixel_size(64)
            icon.add_css_class("success")
            empty_box.append(icon)

            title = Gtk.Label(label="No Heavy Packages Found")
            title.add_css_class("title-2")
            empty_box.append(title)

            subtitle = Gtk.Label(label="All packages have fewer than 50 dependencies")
            subtitle.add_css_class("dim-label")
            empty_box.append(subtitle)

            main_box.append(empty_box)
            toolbar_view.set_content(main_box)
        else:
            # Show list of heavy packages
            info_label = Gtk.Label(
                label=f"Found {len(heavy_packages)} packages with 50+ dependencies",
                halign=Gtk.Align.START
            )
            info_label.add_css_class("heading")
            main_box.append(info_label)

            scroll = Gtk.ScrolledWindow(vexpand=True)
            scroll.add_css_class("card")

            # Enable keyboard navigation
            scroll.set_can_focus(True)
            scroll.set_focus_on_click(True)

            listbox = Gtk.ListBox()
            listbox.add_css_class("boxed-list")

            # Enable keyboard navigation for listbox
            listbox.set_can_focus(True)
            listbox.set_selection_mode(Gtk.SelectionMode.BROWSE)

            # Add keyboard event controller for arrow keys
            key_controller = Gtk.EventControllerKey()
            key_controller.connect("key-pressed", self.on_list_key_pressed, listbox)
            listbox.add_controller(key_controller)

            for pkg_name, dep_count in heavy_packages:
                row = Adw.ActionRow(
                    title=pkg_name,
                    subtitle=f"{dep_count} dependencies"
                )

                # Check if already in IgnorePkg
                if is_in_ignorepkg(pkg_name):
                    # Show remove button
                    remove_btn = Gtk.Button(label="Remove from IgnorePkg")
                    remove_btn.set_valign(Gtk.Align.CENTER)
                    remove_btn.connect("clicked", lambda b, pkg=pkg_name: self.handle_remove_ignorepkg(b, pkg))
                    row.add_suffix(remove_btn)

                    # Add indicator
                    indicator = Gtk.Label(label="[FROZEN]")
                    indicator.set_tooltip_text("In IgnorePkg")
                    indicator.add_css_class("dim-label")
                    row.add_suffix(indicator)
                else:
                    # Show add button
                    add_btn = Gtk.Button(label="Add to IgnorePkg")
                    add_btn.add_css_class("suggested-action")
                    add_btn.set_valign(Gtk.Align.CENTER)
                    add_btn.connect("clicked", lambda b, pkg=pkg_name: self.handle_add_ignorepkg(b, pkg))
                    row.add_suffix(add_btn)

                listbox.append(row)

            scroll.set_child(listbox)
            main_box.append(scroll)

            toolbar_view.set_content(main_box)

        return False

    def handle_add_ignorepkg(self, button, package_name):
        """Add package to IgnorePkg"""
        if add_to_ignorepkg(package_name):
            button.set_label("Added")
            button.set_sensitive(False)
            # Update button after 1 second
            GLib.timeout_add(1000, lambda: self.update_ignorepkg_button(button, package_name, True))
        else:
            self.show_error(f"Failed to add {package_name} to IgnorePkg")

    def handle_remove_ignorepkg(self, button, package_name):
        """Remove package from IgnorePkg"""
        if remove_from_ignorepkg(package_name):
            button.set_label("Removed")
            button.set_sensitive(False)
            # Update button after 1 second
            GLib.timeout_add(1000, lambda: self.update_ignorepkg_button(button, package_name, False))
        else:
            self.show_error(f"Failed to remove {package_name} from IgnorePkg")

    def update_ignorepkg_button(self, button, package_name, was_added):
        """Update button state after add/remove operation"""
        if was_added:
            button.set_label("Remove from IgnorePkg")
            button.remove_css_class("suggested-action")
        else:
            button.set_label("Add to IgnorePkg")
            button.add_css_class("suggested-action")
        button.set_sensitive(True)
        return False

class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.suckless.pacman")
        self.window = None

    def do_activate(self):
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)

        # --- PRE-OPEN PACMAN CHECK ---
        if is_pacman_running():
            # Show a quick info dialog and quit after user closes it
            dialog = Adw.AlertDialog(
                heading="Pacman is Already Running",
                body="A pacman operation is already running on your system."
            )
            dialog.add_response("ok", "OK")
            # Create a temporary window just to host the dialog
            temp_win = Adw.ApplicationWindow(application=self)
            dialog.present(temp_win)
            def exit_app(dialog, _):
                self.quit()
            dialog.connect("response", exit_app)
            temp_win.present()
            return

        self.window = PkgMan(self)
        self.window.set_icon_name("package-x-generic")
        self.window.connect("destroy", lambda w: self.quit())
        self.window.present()

        # Open settings on first run
        if self.window.is_first_run():
            # Create the theme file so this only happens once
            self.window.save_theme_pref(False)  # Save dark as default
            # Schedule settings to open after window is shown
            def open_settings():
                if self.window:
                    self.window.show_settings(None)
                return False
            GLib.idle_add(open_settings)


if __name__ == "__main__":
    try:
        Adw.init()
        App().run(sys.argv)
    except KeyboardInterrupt:
        sys.exit(0)

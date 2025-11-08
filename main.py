#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Vte', '3.91')
from gi.repository import Gtk, Adw, GLib, Vte, Gdk
import subprocess
import threading
import os
import sys
import re
import signal

# Import lazy package functions
try:
    from lazy import (check_pacman_contrib, get_package_deps_count,
                     is_in_ignorepkg, add_to_ignorepkg, remove_from_ignorepkg,
                     get_packages_with_many_deps)
    LAZY_AVAILABLE = True
except ImportError:
    LAZY_AVAILABLE = False
    print("Warning: lazy.py not found - dependency analysis features disabled")

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
        with open('/etc/os-release', 'r') as f:
            content = f.read()
            for line in content.split('\n'):
                if line.startswith('ID='):
                    distro_id = line.split('=', 1)[1].strip().strip('"')
                    if distro_id == 'arch':
                        return 'arch'
                    elif distro_id == 'artix':
                        return 'artix'
    except:
        pass
    return 'unknown'

class PkgMan(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("PacToPac")
        self.set_default_size(800, 600)

        if os.geteuid() != 0:
            print("Error: Run with sudo", file=sys.stderr)
            app.quit()
            return

        # Get SUDO_USER once at initialization
        self.sudo_user = os.environ.get('SUDO_USER')

        self.packages = []
        self.filtered_packages = []
        self.selected = None
        self.page_size = 100
        self.current_page = 0
        self.current_tab = "installed"  # Default to installed tab
        self.running_processes = []  # Track running pacman/flatpak processes
        self._cleanup_done = False  # Flag to prevent duplicate cleanup
        self.setup_ui()
        self.load_packages()
    
    def signal_handler(self, signum, frame):
        """Handle termination signals gracefully"""
        print(f"\nReceived signal {signum}, cleaning up...")
        sys.exit(0)
        
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
 
        # Update every 1 second
        GLib.timeout_add(1000, update_process_indicator)
    
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
        self.view_switcher = Adw.ViewSwitcher()
        self.view_switcher.set_stack(self.view_stack)

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

        # Enable keyboard navigation
        self.flatpak_list.set_can_focus(True)
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
        
        # Create Available tab
        available_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.available_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.available_scroll.add_css_class("card")
        
        # Container for list and load more button
        available_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.available_list = Gtk.ListBox()
        self.available_list.add_css_class("boxed-list")
        self.available_list.connect("row-selected", self.on_select)

        # Enable keyboard navigation
        self.available_list.set_can_focus(True)
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

        # Enable keyboard navigation
        self.all_list.set_can_focus(True)
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

        # Add view switcher below the list
        box.append(self.view_switcher)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, homogeneous=True)
        
        self.info_btn = Gtk.Button(label="Info", sensitive=False)
        self.info_btn.connect("clicked", self.show_package_info)
        
        self.action_btn = Gtk.Button(label="Install", sensitive=False)
        self.action_btn.add_css_class("suggested-action")
        self.action_btn.connect("clicked", self.handle_package_action)
        
        update_btn = Gtk.Button(label="Update", sensitive=True)
        update_btn.connect("clicked", self.handle_update)
        
        clean_orphans_btn = Gtk.Button(label="Clean", sensitive=True)
        clean_orphans_btn.connect("clicked", self.handle_clean_orphans)
        clean_orphans_btn.add_css_class("destructive-action")

        for btn in [update_btn, self.info_btn, self.action_btn, clean_orphans_btn]:
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
    
    def show_settings(self, button):
        dialog = Adw.PreferencesWindow(transient_for=self, modal=True)
        dialog.set_title("Settings")
        dialog.set_default_size(800, 600)

        # Repository Settings Page
        repo_page = Adw.PreferencesPage(title="General", icon_name="folder-symbolic")
        dialog.add(repo_page)
        
        # Pacman repositories
        pacman_group = Adw.PreferencesGroup(title="Pacman Repositories", description="Configure official Arch Linux repositories")
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

        # Dependency Management Group
        if LAZY_AVAILABLE:
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

        # Flatpak Settings Page
        flatpak_page = Adw.PreferencesPage(title="Flatpak", icon_name="application-x-addon-symbolic")
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

        # About Page
        about_page = Adw.PreferencesPage(title="Misc", icon_name="help-about-symbolic")
        dialog.add(about_page)
        
        # App info group
        about_group = Adw.PreferencesGroup()
        about_page.add(about_group)
        
        app_row = Adw.ActionRow(title="PacToPac", subtitle="Suckless Arch Linux package manager")
        about_group.add(app_row)
        
        version_row = Adw.ActionRow(title="Version", subtitle="1.0.6")
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

        resources_group = Adw.PreferencesGroup(title="Resources")
        about_page.add(resources_group)

        arch_news_row = Adw.ActionRow(
            title="Arch Linux News",
            subtitle="https://archlinux.org/news/"
        )

        clipboard_btn = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copy to clipboard")
        clipboard_btn.set_valign(Gtk.Align.CENTER)
        clipboard_btn.connect("clicked", self.copy_arch_news_url)
        arch_news_row.add_suffix(clipboard_btn)

        resources_group.add(arch_news_row)

        dialog.present()

    def copy_arch_news_url(self, button):
        """Copy Arch Linux news URL to clipboard"""
        clipboard = self.get_clipboard()
        clipboard.set("https://archlinux.org/news/")
        
        # Optional: show a brief confirmation
        button.set_icon_name("object-select-symbolic")
        GLib.timeout_add(1000, lambda: button.set_icon_name("edit-copy-symbolic"))

    def handle_flatpak_update(self, button):
        """Update all Flatpak applications"""
        if self.check_fp():
            ## Needs to be ran in user session
            if self.sudo_user:
                self.run_cmd(['sudo', '-u', self.sudo_user, 'flatpak', 'update', '-y'])
            else:
                self.show_error("SUDO_USER not found")
        else:
            self.show_error("Flatpak is not installed")

    def handle_flatpak_cleanup(self, button):
        """Clean Flatpak cache and unused runtimes"""
        if self.check_fp():
            # This removes unused runtimes and clears cache
            if self.sudo_user:
                self.run_cmd(['sudo', '-u', self.sudo_user, 'flatpak', 'uninstall', '--unused', '-y'])
            else:
                self.show_error("SUDO_USER not found")
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
            self.run_cmd(['paccache', '-r'])
        elif response == "full":
            # pacman -Scc: removes all cached packages
            self.run_cmd(['pacman', '-Scc'])

    def check_fp(self):
        try:
            if self.sudo_user:
                cmd = (['sudo', '-u', self.sudo_user, 'flatpak', '--version'])
            else:
                cmd = (['flatpak', '--version'])
            subprocess.run(cmd, capture_output=True, check=True)
            return True
        except:
            return False
    
    def check_fh(self):
        try:
            if self.sudo_user:
                result = subprocess.run(['sudo', '-u', self.sudo_user, 'flatpak', 'remotes'], capture_output=True, text=True, check=True)
            else:
                result = subprocess.run(['flatpak', 'remotes'], capture_output=True, text=True, check=True)
            # Check if flathub exists and is not disabled
            for line in result.stdout.split('\n'):
                if 'flathub' in line.lower():
                    return 'disabled' not in line.lower()
            return False
        except:
            return False
    
    def check_multilib_enabled(self):
        """Check if multilib is enabled (works for both Arch and Artix)"""
        try:
            with open('/etc/pacman.conf', 'r') as f:
                content = f.read()
                distro = detect_distro()

                if distro == 'artix':
                    # Artix uses [lib32]
                    return bool(re.search(r'^\[lib32\]', content, re.MULTILINE))
                else:
                    # Arch uses [multilib]
                    return bool(re.search(r'^\[multilib\]', content, re.MULTILINE))
        except:
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
        self.run_cmd(['pacman', '-S', '--noconfirm', '--needed', 'flatpak'])

    def show_info(self, message):
        """Show info dialog"""
        dialog = Adw.AlertDialog(heading="Info", body=message)
        dialog.add_response("ok", "OK")
        dialog.present(self)

    def save_theme_pref(self, is_light_theme):
        config_dir = os.path.expanduser("~/.config/pactopac")
        os.makedirs(config_dir, exist_ok=True)
        
        config_file = os.path.join(config_dir, "theme")
        with open(config_file, 'w') as f:
            f.write("1" if is_light_theme else "0")

    def load_theme_pref(self):
        try:
            config_file = os.path.expanduser("~/.config/pactopac/theme")
            with open(config_file, 'r') as f:
                return f.read().strip() == "1"
        except:
            return False  # Default to dark theme

    def is_first_run(self):
        """Check if this is the first run by checking if theme config exists"""
        config_file = os.path.expanduser("~/.config/pactopac/theme")
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
        if self.sudo_user:
            if enabled:
                # Always try to add first (handles both missing and disabled cases)
                self.run_toggle(True, ['sudo', '-u', self.sudo_user, 'flatpak', 'remote-add', '--if-not-exists', 'flathub', 'https://dl.flathub.org/repo/flathub.flatpakrepo'], None)
                # Then make sure it's enabled
                subprocess.run(['sudo', '-u', self.sudo_user, 'flatpak', 'remote-modify', '--enable', 'flathub'], check=False)
            else:
                self.run_toggle(False, None, ['sudo', '-u', self.sudo_user, 'flatpak', 'remote-modify', '--disable', 'flathub'])
        else:
            self.show_error("SUDO_USER not found")

        GLib.idle_add(self.load_packages)

    def check_pacman_styling_enabled(self):
        """Check if pacman styling (Color and ILoveCandy) is enabled"""
        try:
            with open('/etc/pacman.conf', 'r') as f:
                content = f.read()
                # Check for uncommented Color and ILoveCandy
                has_color = 'Color\n' in content and '#Color' not in content
                has_candy = 'ILoveCandy' in content
                return has_color and has_candy
        except:
            return False
    
    def on_style_toggle(self, switch_row, param):
        """Handle pacman styling toggle"""
        enabled = switch_row.get_active()
        if enabled:
            self.enable_pacman_styling()
        else:
            self.disable_pacman_styling()
    
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
            with open('/etc/pacman.conf', 'r') as f:
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
                        if self.sudo_user:
                            available = subprocess.run(['sudo', '-u', self.sudo_user, 'flatpak', 'remote-ls', '--app', 'flathub'], capture_output=True, text=True, check=True)
                            installed_fps = subprocess.run(['sudo', '-u', self.sudo_user, 'flatpak', 'list', '--app'], capture_output=True, text=True, check=True)
                        else:
                            available = subprocess.run(['flatpak', 'remote-ls', '--app', 'flathub'], capture_output=True, text=True, check=True)
                            installed_fps = subprocess.run(['flatpak', 'list', '--app'], capture_output=True, text=True, check=True)

                        installed_ids = {line.split('\t')[1] for line in installed_fps.stdout.split('\n') if line.strip() and len(line.split('\t')) > 1}

                        for line in available.stdout.split('\n'):
                            if line.strip():
                                parts = line.split('\t')
                                if len(parts) >= 3:
                                    packages.append((parts[0], "flathub", parts[1] in installed_ids, "flatpak", parts[1]))
                    except subprocess.CalledProcessError:
                        pass
                
                GLib.idle_add(self.update_list, packages)
            except Exception as e:
                GLib.idle_add(self.status.set_text, f"Error: {e}")
        
        threading.Thread(target=load, daemon=True).start()
    
    def update_list(self, packages):
        self.packages = packages
        self.current_page = 0
        self.refresh_list()
        return False
    
    def on_search_changed(self, search_entry):
        self.current_page = 0
        # When searching, automatically switch to All tab
        search_text = search_entry.get_text()
        if search_text.strip():
            self.view_stack.set_visible_child_name("all")
        self.refresh_list()

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
        else:  # all tab
            return self.all_list
    
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
        else:  # all tab
            current_list = self.all_list
            load_more_btn = self.all_load_more
        
        # Clear the current list if starting from page 0
        if self.current_page == 0:
            while child := current_list.get_first_child():
                current_list.remove(child)
        
        search_text = self.search.get_text().lower()
        
        # Filter packages based on search and tab
        if self.current_tab == "installed":
            # Show installed pacman packages only
            self.filtered_packages = [p for p in self.packages if p[2] and len(p) > 3 and p[3] == "pacman" and (search_text in p[0].lower() or not search_text)]
        elif self.current_tab == "available":
            # Show available packages (not installed)
            self.filtered_packages = [p for p in self.packages if not p[2] and (search_text in p[0].lower() or not search_text)]
        elif self.current_tab == "flatpak":
            # Show installed flatpak packages only
            self.filtered_packages = [p for p in self.packages if p[2] and len(p) > 3 and p[3] == "flatpak" and (search_text in p[0].lower() or not search_text)]
        else:  # all tab
            # Show all packages (installed and available)
            self.filtered_packages = [p for p in self.packages if (search_text in p[0].lower() or not search_text)]
        
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
            total_installed = total_installed_pacman + total_installed_flatpak

            if self.current_tab == "installed":
                # Get total size for pacman packages only
                total_size = self.get_total_package_sizes()
                self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_installed_pacman} pacman installed • {total_size}")
            elif self.current_tab == "flatpak":
                self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_installed_flatpak} flatpak installed")
            elif self.current_tab == "available":
                total_available = len(self.packages) - total_installed
                self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_available} available packages")
            else:  # all tab
                self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_installed} installed, {len(self.packages) - total_installed} available")

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
        from gi.repository import Gdk

        # Tab/Shift+Tab: allow normal focus traversal between sections
        if keyval == Gdk.KEY_Tab or keyval == Gdk.KEY_ISO_Left_Tab:
            return False

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
            # Show confirmation dialog
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
                            dialog.terminal.feed_child('n\n'.encode('utf-8'))
                        except:
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
        if not self.selected:
            return

        installed, pkg_type = self.selected[2], self.selected[3]

        if pkg_type == "flatpak":
            if self.sudo_user:
                if installed:
                    cmd = ['sudo', '-u', self.sudo_user, 'flatpak', 'uninstall', '-y', self.selected[4]]
                else:
                    cmd = ['sudo', '-u', self.sudo_user, 'flatpak', 'install', '-y', 'flathub', self.selected[4]]
            else:
                self.show_error("SUDO_USER not found")
                return
        else:
            if installed:
                cmd = ['pacman', '-R', self.selected[0]]
            else:
                cmd = ['pacman', '-S', self.selected[0]]

        self.run_cmd(cmd)
    
    def handle_update(self, button):
        self.run_cmd(['pacman', '-Syu'])
    
    def get_total_package_sizes(self):
        try:
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
                
        except:
            return "Unknown"

    def show_package_info(self, button):
        if not self.selected:
            return
        
        pkg_name, pkg_type = self.selected[0], self.selected[3]
        
        dialog = Adw.Window(title=f"Info: {pkg_name}", transient_for=self, modal=True)
        dialog.set_default_size(600, 400)
        
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
                    if len(self.selected) > 4:
                        app_id = self.selected[4]  # Should be the full com.app.Name ID
                        installed = self.selected[2]  # Whether it's installed

                        if self.sudo_user:
                            if installed:
                                # For installed apps, use 'flatpak info'
                                result = subprocess.run(['sudo', '-u', self.sudo_user, 'flatpak', 'info', app_id], capture_output=True, text=True, check=True)
                            else:
                                # For uninstalled apps, use 'flatpak remote-info' with the remote name
                                result = subprocess.run(['sudo', '-u', self.sudo_user, 'flatpak', 'remote-info', 'flathub', app_id], capture_output=True, text=True, check=True)
                        else:
                            if installed:
                                # For installed apps, use 'flatpak info'
                                result = subprocess.run(['flatpak', 'info', app_id], capture_output=True, text=True, check=True)
                            else:
                                # For uninstalled apps, use 'flatpak remote-info' with the remote name
                                result = subprocess.run(['flatpak', 'remote-info', 'flathub', app_id], capture_output=True, text=True, check=True)
                    else:
                        print("Error - flatpak package missing app ID")
                        GLib.idle_add(self.display_info, toolbar_view, f"Error: Flatpak package data incomplete")
                        return
                else:
                    result = subprocess.run(['pacman', '-Si', pkg_name], capture_output=True, text=True, check=True)
                    if not result.stdout.strip():
                        result = subprocess.run(['pacman', '-Qi', pkg_name], capture_output=True, text=True, check=True)

                GLib.idle_add(self.display_info, toolbar_view, result.stdout)
            except subprocess.CalledProcessError as e:
                error_msg = f"Failed to get info for {pkg_name}"
                if pkg_type == "flatpak":
                    cmd_used = f"flatpak {'info' if self.selected[2] else 'remote-info flathub'} {app_id if 'app_id' in locals() else 'unknown'}"
                    error_msg += f"\nCommand: {cmd_used}"
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
        if self.selected and self.selected[2] and self.selected[3] == "pacman" and LAZY_AVAILABLE:
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
        if not LAZY_AVAILABLE:
            return

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
        dialog = Adw.Window(title=f"Running: {' '.join(cmd[:2])}", transient_for=self, modal=True)
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

        # Store terminal reference on dialog for cleanup
        dialog.terminal = terminal
        dialog.confirmed_close = False  # Flag to prevent close confirmation loop

        # Add escape key handler to terminal widget
        terminal_key_controller = Gtk.EventControllerKey()
        terminal_key_controller.connect("key-pressed", self.on_terminal_escape_pressed, dialog)
        terminal.add_controller(terminal_key_controller)

        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_child(terminal)
        content_box.append(scroll)

        # Status bar at bottom
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        status_box.set_margin_top(12)
        status_box.set_margin_bottom(12)
        status_box.set_margin_start(12)
        status_box.set_margin_end(12)

        progress = Gtk.ProgressBar(show_text=False)
        progress.set_size_request(120, -1)
        progress.set_valign(Gtk.Align.CENTER)
        status_box.append(progress)

        status_label = Gtk.Label(label="Running command...", halign=Gtk.Align.START, hexpand=True)
        status_label.add_css_class("dim-label")
        status_box.append(status_label)

        content_box.append(status_box)

        toolbar_view.set_content(content_box)

        # Handle close button (X) with same confirmation as escape
        def on_close_request(window):
            # If already confirmed, allow close
            if dialog.confirmed_close:
                return False  # Allow close
            # Otherwise show confirmation
            self.on_terminal_escape_pressed(None, Gdk.KEY_Escape, 0, 0, dialog)
            return True  # Prevent default close

        dialog.connect("close-request", on_close_request)
        dialog.present()

        # Start progress bar pulsing
        pulse_id = GLib.timeout_add(100, lambda: progress.pulse() or True)

        # Track terminal PID for cleanup
        terminal_pid = None

        def on_child_exited(term, status):
            nonlocal terminal_pid

            # Stop progress bar pulsing and set to full
            GLib.source_remove(pulse_id)
            GLib.idle_add(lambda: progress.set_fraction(1.0))

            # Update status and progress bar color
            if status == 0:
                GLib.idle_add(lambda: progress.add_css_class("success"))
                GLib.idle_add(lambda: status_label.set_text("✓ Success"))
                GLib.idle_add(self.load_packages)
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
                if LAZY_AVAILABLE and check_pacman_contrib():
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
        dialog.set_default_size(700, 500)

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
            """Run analysis in background thread"""
            if not LAZY_AVAILABLE:
                GLib.idle_add(self.show_error, "Lazy module not available")
                GLib.idle_add(dialog.close)
                return

            # Get packages with 50+ dependencies
            heavy_packages = get_packages_with_many_deps(threshold=50)

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
        if LAZY_AVAILABLE and add_to_ignorepkg(package_name):
            button.set_label("Added")
            button.set_sensitive(False)
            # Update button after 1 second
            GLib.timeout_add(1000, lambda: self.update_ignorepkg_button(button, package_name, True))
        else:
            self.show_error(f"Failed to add {package_name} to IgnorePkg")

    def handle_remove_ignorepkg(self, button, package_name):
        """Remove package from IgnorePkg"""
        if LAZY_AVAILABLE and remove_from_ignorepkg(package_name):
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
        self.window.present()

        # Open settings on first run
        if self.window.is_first_run():
            # Create the theme file so this only happens once
            self.window.save_theme_pref(False)  # Save dark as default
            GLib.idle_add(lambda: self.window.show_settings(None) or False)

    def do_shutdown(self):
        sys.exit()

if __name__ == "__main__":
    Adw.init()
    App().run(sys.argv)
    Adw.Application.do_shutdown(self)
#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib
import subprocess
import threading
import os
import sys
import re
import urllib.request

countries = [
    ("All Countries", "all"),
    ("Australia", "AU"),
    ("Austria", "AT"),
    ("Bangladesh", "BD"),
    ("Belarus", "BY"),
    ("Belgium", "BE"),
    ("Bosnia and Herzegovina", "BA"),
    ("Brazil", "BR"),
    ("Bulgaria", "BG"),
    ("Canada", "CA"),
    ("Chile", "CL"),
    ("China", "CN"),
    ("Colombia", "CO"),
    ("Croatia", "HR"),
    ("Czech Republic", "CZ"),
    ("Denmark", "DK"),
    ("Ecuador", "EC"),
    ("Estonia", "EE"),
    ("Finland", "FI"),
    ("France", "FR"),
    ("Georgia", "GE"),
    ("Germany", "DE"),
    ("Greece", "GR"),
    ("Hong Kong", "HK"),
    ("Hungary", "HU"),
    ("Iceland", "IS"),
    ("India", "IN"),
    ("Indonesia", "ID"),
    ("Iran", "IR"),
    ("Ireland", "IE"),
    ("Israel", "IL"),
    ("Italy", "IT"),
    ("Japan", "JP"),
    ("Kazakhstan", "KZ"),
    ("Kenya", "KE"),
    ("Latvia", "LV"),
    ("Lithuania", "LT"),
    ("Luxembourg", "LU"),
    ("Mexico", "MX"),
    ("Moldova", "MD"),
    ("Netherlands", "NL"),
    ("New Caledonia", "NC"),
    ("New Zealand", "NZ"),
    ("North Macedonia", "MK"),
    ("Norway", "NO"),
    ("Pakistan", "PK"),
    ("Paraguay", "PY"),
    ("Poland", "PL"),
    ("Portugal", "PT"),
    ("Romania", "RO"),
    ("Russia", "RU"),
    ("Serbia", "RS"),
    ("Singapore", "SG"),
    ("Slovakia", "SK"),
    ("Slovenia", "SI"),
    ("South Africa", "ZA"),
    ("South Korea", "KR"),
    ("Spain", "ES"),
    ("Sweden", "SE"),
    ("Switzerland", "CH"),
    ("Taiwan", "TW"),
    ("Thailand", "TH"),
    ("Turkey", "TR"),
    ("Ukraine", "UA"),
    ("United Kingdom", "GB"),
    ("United States", "US"),
    ("Vietnam", "VN")
]

class PkgMan(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("PacToPac")
        self.set_default_size(800, 600)
        
        if os.geteuid() != 0:
            print("Error: Run with sudo", file=sys.stderr)
            app.quit()
            return
            
        self.packages = []
        self.filtered_packages = []
        self.selected = None
        self.page_size = 100
        self.current_page = 0
        self.current_tab = "installed"  # Default to installed tab
        self.setup_ui()
        self.load_packages()
    
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
        box.append(self.search)
        
        # Add view stack for Installed/Available tabs
        self.view_stack = Adw.ViewStack()
        self.view_switcher = Adw.ViewSwitcher()
        self.view_switcher.set_stack(self.view_stack)
        box.append(self.view_switcher)
        
        # Create Installed tab
        installed_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.installed_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.installed_scroll.add_css_class("card")
        self.installed_list = Gtk.ListBox()
        self.installed_list.add_css_class("boxed-list")
        self.installed_list.connect("row-selected", self.on_select)
        self.installed_scroll.set_child(self.installed_list)
        installed_page.append(self.installed_scroll)
        
        self.installed_load_more = Gtk.Button(label="Load More", sensitive=False)
        self.installed_load_more.connect("clicked", self.load_more_packages)
        self.installed_load_more.add_css_class("pill")
        self.installed_load_more.set_halign(Gtk.Align.CENTER)
        self.installed_load_more.set_size_request(120, -1)
        installed_page.append(self.installed_load_more)
        
        self.view_stack.add_titled_with_icon(installed_page, "installed", "Installed", "object-select-symbolic")
        
        # Create Flatpak tab
        flatpak_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.flatpak_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.flatpak_scroll.add_css_class("card")
        self.flatpak_list = Gtk.ListBox()
        self.flatpak_list.add_css_class("boxed-list")
        self.flatpak_list.connect("row-selected", self.on_select)
        self.flatpak_scroll.set_child(self.flatpak_list)
        flatpak_page.append(self.flatpak_scroll)
        
        self.flatpak_load_more = Gtk.Button(label="Load More", sensitive=False)
        self.flatpak_load_more.connect("clicked", self.load_more_packages)
        self.flatpak_load_more.add_css_class("pill")
        self.flatpak_load_more.set_halign(Gtk.Align.CENTER)
        self.flatpak_load_more.set_size_request(120, -1)
        flatpak_page.append(self.flatpak_load_more)
        
        self.view_stack.add_titled_with_icon(flatpak_page, "flatpak", "Flatpak", "application-x-addon-symbolic")
        
        # Create Available tab
        available_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.available_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.available_scroll.add_css_class("card")
        self.available_list = Gtk.ListBox()
        self.available_list.add_css_class("boxed-list")
        self.available_list.connect("row-selected", self.on_select)
        self.available_scroll.set_child(self.available_list)
        available_page.append(self.available_scroll)
        
        self.available_load_more = Gtk.Button(label="Load More", sensitive=False)
        self.available_load_more.connect("clicked", self.load_more_packages)
        self.available_load_more.add_css_class("pill")
        self.available_load_more.set_halign(Gtk.Align.CENTER)
        self.available_load_more.set_size_request(120, -1)
        available_page.append(self.available_load_more)
        
        self.view_stack.add_titled_with_icon(available_page, "available", "Available", "folder-download-symbolic")
        
        # Create All tab
        all_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.all_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.all_scroll.add_css_class("card")
        self.all_list = Gtk.ListBox()
        self.all_list.add_css_class("boxed-list")
        self.all_list.connect("row-selected", self.on_select)
        self.all_scroll.set_child(self.all_list)
        all_page.append(self.all_scroll)
        
        self.all_load_more = Gtk.Button(label="Load More", sensitive=False)
        self.all_load_more.connect("clicked", self.load_more_packages)
        self.all_load_more.add_css_class("pill")
        self.all_load_more.set_halign(Gtk.Align.CENTER)
        self.all_load_more.set_size_request(120, -1)
        all_page.append(self.all_load_more)
        
        self.view_stack.add_titled_with_icon(all_page, "all", "All", "view-list-symbolic")
        
        # Set default to installed
        self.view_stack.set_visible_child_name("installed")
        
        # Connect stack change signal
        self.view_stack.connect("notify::visible-child-name", self.on_stack_changed)
        
        box.append(self.view_stack)
        
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
        
        self.status = Gtk.Label(label="Loading packages...")
        self.status.add_css_class("dim-label")
        box.append(self.status)

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
        dialog = Adw.PreferencesDialog()
        dialog.set_title("Settings")
        
        # Repository Settings Page
        repo_page = Adw.PreferencesPage(title="General", icon_name="folder-symbolic")
        dialog.add(repo_page)
        
        # Pacman repositories
        pacman_group = Adw.PreferencesGroup(title="Pacman Repositories", description="Configure official Arch Linux repositories")
        repo_page.add(pacman_group)
        
        multilib_row = Adw.SwitchRow(
            title="Multilib Repository", 
            subtitle="Enable 32-bit package support for games and legacy software"
        )
        multilib_row.set_active(self.check_multilib_enabled())
        multilib_row.connect("notify::active", self.on_multilib_toggle)
        pacman_group.add(multilib_row)
        
        # Mirror settings
        mirror_group = Adw.PreferencesGroup(title="Mirror Configuration", description="Optimize package download speeds by location")
        repo_page.add(mirror_group)
        
        # Country selection
        country_row = Adw.ComboRow(
            title="Mirror Country",
            subtitle="Select your country or region, HTTPS/IPv4 default"
        )
        country_model = Gtk.StringList()
    
        for name, code in countries:
            country_model.append(name)
        country_row.set_model(country_model)
    
        # Set the current selection based on mirrorlist
        current_country = self.get_current_mirror(countries)
        for i, (name, code) in enumerate(countries):
            if name == current_country:
                country_row.set_selected(i)
                break
    
        mirror_group.add(country_row)
    
        # Generate button
        generate_row = Adw.ActionRow(
            title="Update Mirrorlist",
            subtitle="Generate and apply new mirrorlist for selected country"
        )
    
        generate_btn = Gtk.Button(label="Generate")
        generate_btn.add_css_class("suggested-action")
        generate_btn.set_valign(Gtk.Align.CENTER)
        generate_btn.connect("clicked", lambda b: self.generate_mirrorlist(countries[country_row.get_selected()][1]))
        generate_row.add_suffix(generate_btn)
        
        mirror_group.add(generate_row)

        # Hardware Detection Group
        hardware_group = Adw.PreferencesGroup(
            title="Hardware Detection", 
            description="Analyze system hardware and check driver installation"
        )
        repo_page.add(hardware_group)

        # Hardware detection row
        hw_detect_row = Adw.ActionRow(
            title="Detect Hardware",
            subtitle="Scan CPU, GPU, and form factor; check microcode and driver status"
        )

        hw_detect_btn = Gtk.Button(label="Detect")
        hw_detect_btn.add_css_class("suggested-action")
        hw_detect_btn.set_valign(Gtk.Align.CENTER)
        hw_detect_btn.connect("clicked", self.on_hardware_detection)
        hw_detect_row.add_suffix(hw_detect_btn)

        hardware_group.add(hw_detect_row)
        
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
        about_page = Adw.PreferencesPage(title="About", icon_name="help-about-symbolic")
        dialog.add(about_page)
        
        # App info group
        about_group = Adw.PreferencesGroup()
        about_page.add(about_group)
        
        app_row = Adw.ActionRow(title="PacToPac", subtitle="Suckless Arch Linux package manager")
        about_group.add(app_row)
        
        version_row = Adw.ActionRow(title="Version", subtitle="1.0.5")
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

        # Update Notifications Group
        updates_group = Adw.PreferencesGroup(
            title="Update Notifications", 
            description="Automatic notifications when system updates are available"
        )
        about_page.add(updates_group)
        
        # Update checker toggle
        update_checker_row = Adw.SwitchRow(
            title="Enable Update Checker",
            subtitle="Show desktop notifications when updates are available (works on next login/logout)"
        )
        # Set initial state without triggering the handler
        is_enabled = self.check_update_checker_enabled()
        # Connect handler BEFORE setting state to avoid false triggers
        update_checker_row.connect("notify::active", self.on_update_checker_toggle)
        # Block the signal temporarily while setting initial state
        update_checker_row.handler_block_by_func(self.on_update_checker_toggle)
        update_checker_row.set_active(is_enabled)
        update_checker_row.handler_unblock_by_func(self.on_update_checker_toggle)
        updates_group.add(update_checker_row)
        
        # Time interval selection
        interval_row = Adw.ComboRow(
            title="Check Interval",
            subtitle="How often to check for updates"
        )
        
        interval_model = Gtk.StringList()
        intervals = [
            ("1 minute", "60"),
            ("5 minutes", "300"),
            ("15 minutes", "900"),
            ("30 minutes", "1800"),
            ("1 hour", "3600"), 
            ("2 hours", "7200"),
            ("6 hours", "21600"),
            ("12 hours", "43200"),
            ("24 hours", "86400")
        ]
        
        for name, _ in intervals:
            interval_model.append(name)
        interval_row.set_model(interval_model)
        
        # Set current selection based on current interval
        current_interval = self.get_current_update_interval()
        for i, (_, seconds) in enumerate(intervals):
            if seconds == current_interval:
                interval_row.set_selected(i)
                break
        
        # Only enable interval selection if update checker is enabled
        interval_row.set_sensitive(is_enabled)
        
        interval_row.connect("notify::selected", lambda row, _: self.on_interval_changed(row, intervals))
        updates_group.add(interval_row)
        
        # Store reference to interval row for enabling/disabling
        update_checker_row.interval_row = interval_row

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

        dialog.present(self)

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
            self.run_cmd(['flatpak', 'update', '-y'])
        else:
            self.show_error("Flatpak is not installed")

    def handle_flatpak_cleanup(self, button):
        """Clean Flatpak cache and unused runtimes"""
        if self.check_fp():
            # This removes unused runtimes and clears cache
            self.run_cmd(['flatpak', 'uninstall', '--unused', '-y'])
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
                    cmd = ['pacman', '-Rns'] + ['--noconfirm'] + orphaned_packages.split('\n')
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
            # pacman -Sc: removes old versions, keeps current
            self.run_cmd(['pacman', '-Sc', '--noconfirm'])
        elif response == "full":
            # pacman -Scc: removes all cached packages
            self.run_cmd(['pacman', '-Scc', '--noconfirm'])

    def check_fp(self):
        try:
            cmd = (['flatpak', '--version'])
            subprocess.run(cmd, capture_output=True, check=True)
            return True
        except:
            return False
    
    def check_fh(self):
        try:
            result = subprocess.run(['flatpak', 'remotes'], capture_output=True, text=True, check=True)
            # Check if flathub exists and is not disabled
            for line in result.stdout.split('\n'):
                if 'flathub' in line.lower():
                    return 'disabled' not in line.lower()
            return False
        except:
            return False
    
    def check_multilib_enabled(self):
        try:
            with open('/etc/pacman.conf', 'r') as f:
                return bool(re.search(r'^\[multilib\]', f.read(), re.MULTILINE))
        except:
            return False
        
    def install_fp_and_refresh(self, dialog):
        # Close the current settings dialog
        dialog.close()
        
        # Use the existing run_cmd method to install flatpak
        self.run_cmd(['pacman', '-S', '--noconfirm', 'flatpak'])
        
        # Schedule opening a new settings dialog after a short delay
        # This gives time for the installation to complete
        GLib.timeout_add(1000, lambda: self.show_settings(None))

    def show_info(self, message):
        """Show info dialog"""
        dialog = Adw.AlertDialog(heading="Info", body=message)
        dialog.add_response("ok", "OK")
        dialog.present(self)

    def get_current_mirror(self, countries):
        try:
            with open('/etc/pacman.d/mirrorlist', 'r') as f:
                content = f.read().lower()
            
            for name, code in countries:
                if name.lower() in content:
                    return name
            
            return 'All Countries'  # Default fallback
            
        except (FileNotFoundError, IOError):
            return 'All Countries'
    
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

    def on_theme_toggle(self, switch_row, param):
        style_manager = Adw.StyleManager.get_default()
        is_light = switch_row.get_active()
        
        if is_light:
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        else:
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        
        self.save_theme_pref(is_light)

    def generate_mirrorlist(self, country_code):
        def generate():
            try:
                url = f"https://archlinux.org/mirrorlist/?country={country_code}&protocol=https&ip_version=4"
                
                with urllib.request.urlopen(url) as response:
                    mirrorlist_data = response.read().decode('utf-8')
                
                # Uncomment all servers
                uncommented_data = re.sub(r'^#(Server = )', r'\1', mirrorlist_data, flags=re.MULTILINE)
                
                # Backup current mirrorlist
                subprocess.run(['cp', '/etc/pacman.d/mirrorlist', '/etc/pacman.d/mirrorlist.backup'], check=True)
                
                # Write new mirrorlist
                with open('/etc/pacman.d/mirrorlist', 'w') as f:
                    f.write(uncommented_data)
                
                # Refresh pacman
                GLib.idle_add(lambda: self.run_cmd(['pacman', '-Sy']))
                
            except Exception as e:
                GLib.idle_add(lambda: self.show_error(f"Failed to generate mirrorlist: {e}"))
        
        threading.Thread(target=generate, daemon=True).start()
    
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
        if enabled:
            self.run_toggle(True, ['sed', '-i', '/^#\\[multilib\\]/{s/^#//;n;s/^#//}', '/etc/pacman.conf'], None)
            subprocess.run(['pacman', '-Sy'], check=True)
        else:
            self.run_toggle(False, None, ['sed', '-i', '/^\\[multilib\\]/{s/^/#/;n;s/^/#/}', '/etc/pacman.conf'])
    
    def on_fh_toggle(self, switch_row, param):
        enabled = switch_row.get_active()
        if enabled:
            # Always try to add first (handles both missing and disabled cases)
            self.run_toggle(True, ['flatpak', 'remote-add', '--if-not-exists', 'flathub', 'https://dl.flathub.org/repo/flathub.flatpakrepo'], None)
            # Then make sure it's enabled
            subprocess.run(['flatpak', 'remote-modify', '--enable', 'flathub'], check=False)
        else:
            self.run_toggle(False, None, ['flatpak', 'remote-modify', '--disable', 'flathub'])
        
        GLib.idle_add(self.load_packages)

    def on_hardware_detection(self, button):
        script_path = os.path.join(os.path.dirname(__file__), 'lib/newhw.py')
        if os.path.exists(script_path):
            self.run_cmd(['python3', script_path])
        else:
            self.show_error("Hardware detection script (newhw.py) not found")

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
    
    def check_update_checker_enabled(self):
        """Check if update checker is currently enabled"""
        # Get the actual user (not root)
        actual_user = os.environ.get('SUDO_USER')
        if actual_user:
            autostart_file = f"/home/{actual_user}/.config/autostart/update-checker.desktop"
        else:
            autostart_file = os.path.expanduser("~/.config/autostart/update-checker.desktop")
        return os.path.exists(autostart_file)
    
    def get_current_update_interval(self):
        """Get current update check interval from script"""
        # Get the actual user (not root)
        actual_user = os.environ.get('SUDO_USER')
        if actual_user:
            script_file = f"/home/{actual_user}/.local/bin/update-checker"
        else:
            script_file = os.path.expanduser("~/.local/bin/update-checker")
            
        if not os.path.exists(script_file):
            return "7200"  # Default 2 hours
        
        try:
            with open(script_file, 'r') as f:
                content = f.read()
                # Look for sleep command with interval
                import re
                match = re.search(r'sleep (\d+)', content)
                if match:
                    return match.group(1)
        except:
            pass
        return "7200"
    
    def on_update_checker_toggle(self, switch_row, param):
        """Handle update checker enable/disable"""
        enabled = switch_row.get_active()
        
        # Enable/disable the interval dropdown
        if hasattr(switch_row, 'interval_row'):
            switch_row.interval_row.set_sensitive(enabled)
        
        if enabled:
            self.enable_update_checker()
        else:
            self.disable_update_checker()
    
    def on_interval_changed(self, combo_row, intervals):
        """Handle update interval change"""
        selected = combo_row.get_selected()
        if selected < len(intervals):
            _, seconds = intervals[selected]
            self.update_checker_interval(seconds)
    
    def enable_update_checker(self):
        """Enable the update checker with current interval"""
        script_path = os.path.join(os.path.dirname(__file__), 'lib/update-checker.sh')
        if os.path.exists(script_path):
            # Run the installer script as the actual user (not root)
            actual_user = os.environ.get('SUDO_USER')
            if actual_user:
                result = subprocess.run(['sudo', '-u', actual_user, 'bash', script_path], 
                                      capture_output=True, text=True, check=False)
                if result.returncode == 0:
                    # Give the script a moment to create the files
                    import time
                    time.sleep(0.5)
                    # Send an immediate test notification for instant feedback
                    self.send_test_notification(actual_user)
            else:
                result = subprocess.run(['bash', script_path], 
                                      capture_output=True, text=True, check=False)
                if result.returncode == 0:
                    import time
                    time.sleep(0.5)
                    self.send_test_notification()
        else:
            self.show_error("Update checker script not found")
    
    def disable_update_checker(self):
        """Disable the update checker"""
        actual_user = os.environ.get('SUDO_USER')
        
        try:
            # 1. Stop the update checker processes properly as the user
            if actual_user:
                subprocess.run(['sudo', '-u', actual_user, 'pkill', '-f', 'update-checker'], 
                             capture_output=True, check=False)
            else:
                subprocess.run(['pkill', '-f', 'update-checker'], capture_output=True, check=False)
            
            # 2. Remove the files manually instead of using the script
            if actual_user:
                script_file = f"/home/{actual_user}/.local/bin/update-checker"
                desktop_file = f"/home/{actual_user}/.config/autostart/update-checker.desktop"
            else:
                script_file = os.path.expanduser("~/.local/bin/update-checker")
                desktop_file = os.path.expanduser("~/.config/autostart/update-checker.desktop")
            
            # Remove files if they exist
            for file_path in [script_file, desktop_file]:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"Removed: {file_path}")
            
            print("Update checker disabled successfully")
            
        except Exception as e:
            print(f"Error disabling update checker: {e}")
            # Fallback to the original script method
            script_path = os.path.join(os.path.dirname(__file__), 'lib/update-checker-uninstall.sh')
            if os.path.exists(script_path):
                if actual_user:
                    subprocess.run(['sudo', '-u', actual_user, 'bash', script_path], check=False)
                else:
                    subprocess.run(['bash', script_path], check=False)
            else:
                self.show_error("Update checker uninstall script not found")
    
    def send_test_notification(self, actual_user=None):
        """Send an immediate test notification for instant feedback"""
        try:
            # First check if notify-send exists
            if actual_user:
                # Check if notify-send is available as the user
                result = subprocess.run(['sudo', '-u', actual_user, 'which', 'notify-send'], 
                                      capture_output=True, check=False)
                if result.returncode == 0:
                    # Get the user's actual display and session info
                    try:
                        # Get user's DISPLAY from their process
                        display_result = subprocess.run(['sudo', '-u', actual_user, 'bash', '-c', 'echo $DISPLAY'], 
                                                      capture_output=True, text=True, check=False)
                        user_display = display_result.stdout.strip()
                        
                        # Use runuser instead of sudo for better session handling
                        subprocess.run(['runuser', '-l', actual_user, '-c', 
                                      f'DISPLAY={user_display or ":0"} notify-send "Update Checker Enabled" "Notifications are now active! Checking for updates..."'], 
                                     check=False)
                        print(f"Test notification sent to display: {user_display or ':0'}")
                    except:
                        # Fallback to original method
                        env = os.environ.copy()
                        env['DISPLAY'] = ':0'
                        subprocess.run(['sudo', '-u', actual_user, 'notify-send', 
                                      'Update Checker Enabled', 
                                      'Notifications are now active! Checking for updates...'], 
                                     env=env, check=False)
                        print("Test notification sent (fallback method)")
                else:
                    print("notify-send not found - notifications may not work")
            else:
                result = subprocess.run(['which', 'notify-send'], capture_output=True, check=False)
                if result.returncode == 0:
                    subprocess.run(['notify-send', 
                                  'Update Checker Enabled', 
                                  'Notifications are now active! Checking for updates...'], 
                                 check=False)
                    print("Test notification sent")
                else:
                    print("notify-send not found - install libnotify for desktop notifications")
        except Exception as e:
            print(f"Test notification failed: {e}")
            print("Update checker will still work, but may only show console messages")
    
    
    def update_checker_interval(self, seconds):
        """Update the check interval if update checker is enabled"""
        if self.check_update_checker_enabled():
            # Just restart the process with new interval - no need for full reinstall
            self.restart_update_checker_with_interval(seconds)
    
    def restart_update_checker_with_interval(self, seconds):
        """Restart update checker with new interval without full reinstall"""
        actual_user = os.environ.get('SUDO_USER')
        
        try:
            # 1. Stop the current update checker process
            if actual_user:
                subprocess.run(['sudo', '-u', actual_user, 'pkill', '-f', 'update-checker'], 
                             capture_output=True, check=False)
            else:
                subprocess.run(['pkill', '-f', 'update-checker'], capture_output=True, check=False)
            
            # 2. Update the interval in the source script for future installs
            self.modify_update_script_interval(seconds)
            
            # 3. Update the installed script with new interval
            if actual_user:
                script_path = f"/home/{actual_user}/.local/bin/update-checker"
            else:
                script_path = os.path.expanduser("~/.local/bin/update-checker")
                
            if os.path.exists(script_path):
                with open(script_path, 'r') as f:
                    content = f.read()
                
                import re
                content = re.sub(r'sleep \d+', f'sleep {seconds}', content)
                
                with open(script_path, 'w') as f:
                    f.write(content)
            
            # Update complete - checker will use new interval on next run
            
        except Exception as e:
            print(f"Failed to update interval: {e}")
    
    def modify_update_script_interval(self, seconds):
        """Modify the update checker script with new interval"""
        script_path = os.path.join(os.path.dirname(__file__), 'lib/update-checker.sh')
        if not os.path.exists(script_path):
            return
            
        try:
            with open(script_path, 'r') as f:
                content = f.read()
            
            # Replace the CHECK_INTERVAL line
            import re
            content = re.sub(r'CHECK_INTERVAL=\d+', f'CHECK_INTERVAL={seconds}', content)
            
            with open(script_path, 'w') as f:
                f.write(content)
        except Exception as e:
            self.show_error(f"Failed to update interval: {e}")

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
    
    def handle_package_action(self, button):
        if not self.selected:
            return
        
        installed, pkg_type = self.selected[2], self.selected[3]
        
        if installed:
            cmd = ['flatpak', 'uninstall', '-y', self.selected[4]] if pkg_type == "flatpak" else ['pacman', '-R', '--noconfirm', self.selected[0]]
        else:
            cmd = ['flatpak', 'install', '-y', 'flathub', self.selected[4]] if pkg_type == "flatpak" else ['pacman', '-S', '--noconfirm', self.selected[0]]
        
        self.run_cmd(cmd)
    
    def handle_update(self, button):
        self.run_cmd(['pacman', '-Syu', '--noconfirm'])
    
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
        
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
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

    def run_cmd(self, cmd):
        dialog = Adw.Window(title=f"Running: {' '.join(cmd[:2])}", transient_for=self, modal=True)
        dialog.set_default_size(800, 600)
        
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        dialog.set_content(toolbar_view)
        
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        
        progress = Gtk.ProgressBar(show_text=True, text="Starting...")
        content_box.append(progress)
        
        scroll = Gtk.ScrolledWindow(vexpand=True)
        text = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        text.set_left_margin(6)
        text.set_right_margin(6)
        scroll.set_child(text)
        content_box.append(scroll)
        
        toolbar_view.set_content(content_box)
        dialog.present()
        
        def run():
            try:
                pulse_id = GLib.timeout_add(100, lambda: progress.pulse() or True)
                
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
                buf = text.get_buffer()
                
                GLib.idle_add(lambda: progress.set_text("Running, please wait..."))
                
                def insert_and_scroll(line):
                    buf.insert(buf.get_end_iter(), line)
                    # Auto-scroll to the end
                    mark = buf.get_insert()
                    text.scroll_mark_onscreen(mark)
                
                for line in iter(proc.stdout.readline, ''):
                    GLib.idle_add(lambda l=line: insert_and_scroll(l))
                
                proc.wait()
                GLib.source_remove(pulse_id)
                
                success = proc.returncode == 0
                result = "✓ Success" if success else f"✗ Failed ({proc.returncode})"
                
                GLib.idle_add(lambda: progress.set_fraction(1.0))
                GLib.idle_add(lambda: progress.set_text(result))
                GLib.idle_add(lambda: progress.add_css_class("success" if success else "error"))
                GLib.idle_add(lambda: insert_and_scroll(f"\n{result}"))
                
                if success:
                    GLib.idle_add(self.load_packages)
                    
            except Exception as e:
                if 'pulse_id' in locals():
                    GLib.source_remove(pulse_id)
                GLib.idle_add(lambda: progress.set_text("Error"))
                GLib.idle_add(lambda: progress.add_css_class("error"))
        
        threading.Thread(target=run, daemon=True).start()

class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.suckless.pacman")
        
    def do_activate(self):
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        window = PkgMan(self)
        window.set_icon_name("package-x-generic")
        window.present()

if __name__ == "__main__":
    Adw.init()
    App().run(sys.argv)

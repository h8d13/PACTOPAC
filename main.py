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
        
        self.scroll = Gtk.ScrolledWindow(vexpand=True)
        self.scroll.add_css_class("card")
        self.list = Gtk.ListBox()
        self.list.add_css_class("boxed-list")
        self.list.connect("row-selected", self.on_select)
        self.scroll.set_child(self.list)
        box.append(self.scroll)
        
        self.load_more_btn = Gtk.Button(label="Load More", sensitive=False)
        self.load_more_btn.connect("clicked", self.load_more_packages)
        self.load_more_btn.add_css_class("pill")
        box.append(self.load_more_btn)
        
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

        integration_row = Adw.ActionRow(
            title="Fix KDE Integration",
            subtitle="Configure system-wide desktop integration for KDE launcher icons"
        )

        # Check if already configured and set button accordingly
        if self.check_flatpak_integration():
            integration_btn = Gtk.Button(label="Configured")
            integration_btn.set_sensitive(False)
            integration_btn.add_css_class("success")
        else:
            integration_btn = Gtk.Button(label="Fix")
            integration_btn.add_css_class("suggested-action")
            integration_btn.connect("clicked", self.fix_flatpak_integration)

        integration_btn.set_valign(Gtk.Align.CENTER)
        integration_row.add_suffix(integration_btn)

        flatpak_group.add(integration_row)

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
        
        version_row = Adw.ActionRow(title="Version", subtitle="1.0.4")
        about_group.add(version_row)
        
        # Appearance group with theme toggle
        appearance_group = Adw.PreferencesGroup(title="Appearance", description="Customize the look and feel")
        about_page.add(appearance_group)
        
        # Get current theme state
        style_manager = Adw.StyleManager.get_default()
        is_light = style_manager.get_color_scheme() == Adw.ColorScheme.FORCE_LIGHT
        
        theme_row = Adw.SwitchRow(
            title="Light Theme",
            subtitle="Switch between light and dark appearance"
        )
        theme_row.set_active(is_light)
        theme_row.connect("notify::active", self.on_theme_toggle)
        appearance_group.add(theme_row)

        dialog.present(self)

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

    def check_flatpak_integration(self):
        """Check if Flatpak desktop integration is configured"""
        try:
            with open('/etc/environment', 'r') as f:
                content = f.read()
                return '/var/lib/flatpak/exports/share' in content
        except:
            return False

    def fix_flatpak_integration(self, button):
        """Apply system-wide Flatpak desktop integration fix"""
        try:
            # Read current environment file
            try:
                with open('/etc/environment', 'r') as f:
                    content = f.read()
            except FileNotFoundError:
                content = ""
            
            # Check if already configured
            if '/var/lib/flatpak/exports/share' in content:
                self.show_info("Flatpak integration is already configured!")
                return
            
            # Add or update XDG_DATA_DIRS
            lines = content.split('\n')
            xdg_line_found = False
            
            for i, line in enumerate(lines):
                if line.startswith('XDG_DATA_DIRS='):
                    # Update existing line
                    if '/var/lib/flatpak/exports/share' not in line:
                        lines[i] = 'XDG_DATA_DIRS="/var/lib/flatpak/exports/share:/usr/local/share:/usr/share"'
                    xdg_line_found = True
                    break
            
            if not xdg_line_found:
                # Add new line
                lines.append('XDG_DATA_DIRS="/var/lib/flatpak/exports/share:/usr/local/share:/usr/share"')
            
            # Write back to file
            new_content = '\n'.join(lines)
            with open('/etc/environment', 'w') as f:
                f.write(new_content)
            
            self.show_info("Flatpak integration configured! Please restart your session for KDE launcher icons to appear.")
            
        except PermissionError:
            self.show_error("Permission denied. Make sure you're running with sudo.")
        except Exception as e:
            self.show_error(f"Failed to configure Flatpak integration: {e}")

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
        script_path = os.path.join(os.path.dirname(__file__), 'newhw.py')
        if os.path.exists(script_path):
            self.run_cmd(['python3', script_path])
        else:
            self.show_error("Hardware detection script (newhw.py) not found")
    
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
        self.refresh_list()
    
    def refresh_list(self):
        if self.current_page == 0:
            while child := self.list.get_first_child():
                self.list.remove(child)
        
        search_text = self.search.get_text().lower()
        self.filtered_packages = [p for p in self.packages if search_text in p[0].lower() or not search_text]
        
        total_filtered = len(self.filtered_packages)
        start_idx = self.current_page * self.page_size
        end_idx = min((self.current_page + 1) * self.page_size, total_filtered)
        
        packages_to_show = self.filtered_packages[start_idx:end_idx] if self.current_page > 0 else self.filtered_packages[0:end_idx]
        
        for pkg_data in packages_to_show:
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
            self.list.append(row)
        
        # Update UI
        has_more = end_idx < total_filtered
        self.load_more_btn.set_sensitive(has_more)
        self.load_more_btn.set_label("More..." if has_more else "All packages loaded")
    
        total_showing = min((self.current_page + 1) * self.page_size, total_filtered)
        if search_text:
            self.status.set_text(f"Showing {total_showing} of {total_filtered} filtered packages")
        else:
            total_installed = sum(1 for pkg in self.packages if pkg[2])
            flatpak_installed = sum(1 for pkg in self.packages if pkg[2] and len(pkg) > 3 and pkg[3] == "flatpak")
            
            # Get total size
            total_size = self.get_total_package_sizes()
            
            if flatpak_installed > 0:
                self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_installed} installed ({flatpak_installed} flatpak) • {total_size}")
            else:
                self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_installed} installed • {total_size}")

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
        self.run_cmd(['pacman', '-Syuu', '--noconfirm'])
    
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

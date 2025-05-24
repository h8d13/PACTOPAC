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
        
        for btn in [update_btn, self.info_btn, self.action_btn]:
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
    
    def check_cmd(self, cmd):
        try:
            subprocess.run(cmd, capture_output=True, check=True)
            return True
        except:
            return False
    
    def check_fp(self):
        return self.check_cmd(['flatpak', '--version'])
    
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
    
    def get_current_mirror_country(self, countries):
        """Parse /etc/pacman.d/mirrorlist and match against countries list"""
        try:
            with open('/etc/pacman.d/mirrorlist', 'r') as f:
                content = f.read().lower()
            
            # Check each country name from the JSON list
            for name, code in countries:
                if name.lower() in content:
                    return name
            
            return 'All Countries'  # Default fallback
            
        except (FileNotFoundError, IOError):
            return 'All Countries'
    
    def on_theme_toggle(self, switch_row, param):
        """Handle theme toggle switch"""
        style_manager = Adw.StyleManager.get_default()
        if switch_row.get_active():
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        else:
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    
    def show_settings(self, button):
        dialog = Adw.PreferencesDialog()
        dialog.set_title("Settings")
        dialog.set_content_width(600)
        dialog.set_content_height(700)
        
        # Repository Settings Page
        repo_page = Adw.PreferencesPage(title="Repositories", icon_name="folder-symbolic")
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
            subtitle="Select your country or region for faster downloads"
        )
        country_model = Gtk.StringList()

        # Load countries from JSON
        import json
        try:
            with open("countries.json", "r") as f:
                countries_data = json.load(f)
                countries = [(country["name"], country["code"]) for country in countries_data["countries"]]
        except FileNotFoundError:
            print("Missing json file")
            countries = [("All Countries", "all")]

        for name, code in countries:
            country_model.append(name)
        country_row.set_model(country_model)

        # Set the current selection based on mirrorlist
        current_country = self.get_current_mirror_country(countries)
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
            install_btn.connect("clicked", lambda b: self.run_cmd(['pacman', '-S', '--noconfirm', 'flatpak']))
            unavailable_row.add_suffix(install_btn)
            flatpak_group.add(unavailable_row)
        
        # About Page
        about_page = Adw.PreferencesPage(title="About", icon_name="help-about-symbolic")
        dialog.add(about_page)
        
        # App info group
        about_group = Adw.PreferencesGroup()
        about_page.add(about_group)
        
        app_row = Adw.ActionRow(title="PacToPac", subtitle="Suckless Arch Linux package manager")
        about_group.add(app_row)
        
        version_row = Adw.ActionRow(title="Version", subtitle="1.0.1")
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
            
            if flatpak_installed > 0:
                self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_installed} installed ({flatpak_installed} flatpak)")
            else:
                self.status.set_text(f"Showing {total_showing} of {total_filtered} • {total_installed} installed")
    
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
    
    def show_package_info(self, button):
        if not self.selected:
            return
        
        pkg_name, pkg_type = self.selected[0], self.selected[3]
        
        dialog = Adw.Window(title=f"Info: {pkg_name}", transient_for=self, modal=True)
        dialog.set_default_size(600, 500)
        
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
                    result = subprocess.run(['flatpak', 'info', self.selected[4]], capture_output=True, text=True, check=True)
                else:
                    result = subprocess.run(['pacman', '-Si', pkg_name], capture_output=True, text=True, check=True)
                    if not result.stdout.strip():
                        result = subprocess.run(['pacman', '-Qi', pkg_name], capture_output=True, text=True, check=True)
                
                GLib.idle_add(self.display_info, toolbar_view, result.stdout)
            except subprocess.CalledProcessError:
                GLib.idle_add(self.display_info, toolbar_view, f"No info available for {pkg_name}")
        
        threading.Thread(target=load_info, daemon=True).start()
    
    def display_info(self, toolbar_view, info_text):
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_margin_top(12)
        scroll.set_margin_bottom(12)
        scroll.set_margin_start(12)
        scroll.set_margin_end(12)
        
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        for line in info_text.strip().split('\n'):
            if ':' in line and not line.startswith(' '):
                key, value = line.split(':', 1)
                
                row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                key_label = Gtk.Label(label=key.strip(), halign=Gtk.Align.START)
                key_label.set_markup(f"<b>{key.strip()}</b>")
                key_label.set_size_request(100, -1)
                
                value_label = Gtk.Label(label=value.strip(), halign=Gtk.Align.START, hexpand=True, wrap=True, selectable=True)
                
                row_box.append(key_label)
                row_box.append(value_label)
                content_box.append(row_box)
        
        scroll.set_child(content_box)
        toolbar_view.set_content(scroll)
        return False
    
    def run_cmd(self, cmd):
        dialog = Adw.Window(title=f"Running: {' '.join(cmd[:2])}", transient_for=self, modal=True)
        dialog.set_default_size(600, 500)
        
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
        text = Gtk.TextView(editable=False, monospace=True)
        scroll.set_child(text)
        content_box.append(scroll)
        
        toolbar_view.set_content(content_box)
        dialog.present()
        
        def run():
            try:
                pulse_id = GLib.timeout_add(100, lambda: progress.pulse() or True)
                
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
                buf = text.get_buffer()
                
                GLib.idle_add(lambda: progress.set_text("Running..."))
                
                for line in iter(proc.stdout.readline, ''):
                    GLib.idle_add(lambda l=line: buf.insert(buf.get_end_iter(), l))
                
                proc.wait()
                GLib.source_remove(pulse_id)
                
                success = proc.returncode == 0
                result = "✓ Success" if success else f"✗ Failed ({proc.returncode})"
                
                GLib.idle_add(lambda: progress.set_fraction(1.0))
                GLib.idle_add(lambda: progress.set_text(result))
                GLib.idle_add(lambda: progress.add_css_class("success" if success else "error"))
                GLib.idle_add(lambda: buf.insert(buf.get_end_iter(), f"\n{result}"))
                
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

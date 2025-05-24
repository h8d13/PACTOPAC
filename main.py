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

class PackageManager(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("PacToPac")
        self.set_default_size(800, 600)
        
        if os.geteuid() != 0:
            print("Error: Run with sudo", file=sys.stderr)
            app.quit()
            return
            
        self.packages = []
        self.selected = None
        self.setup_ui()
        self.load_packages()
    
    def setup_ui(self):
        # Main layout
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)
        
        # Header with settings
        header = Adw.HeaderBar()
        settings_btn = Gtk.Button(icon_name="preferences-system-symbolic", tooltip_text="Settings")
        settings_btn.connect("clicked", self.show_settings)
        header.pack_start(settings_btn)
        toolbar_view.add_top_bar(header)
        
        # Content box
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        toolbar_view.set_content(box)
        
        # Search
        self.search = Gtk.SearchEntry(placeholder_text="Search packages...")
        self.search.connect("search-changed", lambda _: self.refresh_list())
        box.append(self.search)
        
        # Action buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, homogeneous=True)
        
        self.info_btn = self.create_button("Info", False, self.show_package_info)
        self.install_btn = self.create_button("Install", False, self.handle_install, "suggested-action")
        self.remove_btn = self.create_button("Remove", False, self.handle_remove, "destructive-action")
        update_btn = self.create_button("Update", True, self.handle_update)
        
        for btn in [self.info_btn, self.install_btn, self.remove_btn, update_btn]:
            btn_box.append(btn)
        box.append(btn_box)
        
        # Package list
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.add_css_class("card")
        self.list = Gtk.ListBox()
        self.list.add_css_class("boxed-list")
        self.list.connect("row-selected", self.on_select)
        scroll.set_child(self.list)
        box.append(scroll)
        
        # Status
        self.status = Gtk.Label(label="Loading packages...")
        self.status.add_css_class("dim-label")
        box.append(self.status)
    
    def create_button(self, label, sensitive, callback, css_class=None):
        btn = Gtk.Button(label=label, sensitive=sensitive)
        btn.connect("clicked", callback)
        if css_class:
            btn.add_css_class(css_class)
        return btn
    
    def check_flatpak_available(self):
        try:
            subprocess.run(['flatpak', '--version'], capture_output=True, check=True)
            return True
        except:
            return False
    
    def check_flathub_enabled(self):
        try:
            result = subprocess.run(['flatpak', 'remotes'], capture_output=True, text=True, check=True)
            return 'flathub' in result.stdout.lower()
        except:
            return False
    
    def check_multilib_enabled(self):
        try:
            with open('/etc/pacman.conf', 'r') as f:
                return bool(re.search(r'^\[multilib\]', f.read(), re.MULTILINE))
        except:
            return False
    
    def show_settings(self, button):
        dialog = Adw.PreferencesWindow(title="Settings", transient_for=self, modal=True)
        dialog.set_default_size(500, 400)
        
        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")
        dialog.add(page)
        
        # Repository settings
        repo_group = Adw.PreferencesGroup(title="Repository Settings")
        page.add(repo_group)
        
        # Multilib
        multilib_row = Adw.SwitchRow(
            title="Enable multilib repository", 
            subtitle="Access to 32-bit packages"
        )
        multilib_row.set_active(self.check_multilib_enabled())
        multilib_row.connect("notify::active", self.on_multilib_toggle)
        repo_group.add(multilib_row)
        
        # Flatpak
        flatpak_group = Adw.PreferencesGroup(title="Flatpak Settings")
        page.add(flatpak_group)
        
        if self.check_flatpak_available():
            flathub_row = Adw.SwitchRow(
                title="Enable Flathub repository", 
                subtitle="Access to Flatpak applications"
            )
            flathub_row.set_active(self.check_flathub_enabled())
            flathub_row.connect("notify::active", self.on_flathub_toggle)
            flatpak_group.add(flathub_row)
        else:
            info_row = Adw.ActionRow(
                title="Flatpak not available", 
                subtitle="Install flatpak to enable support"
            )
            flatpak_group.add(info_row)
        
        dialog.present()
    
    def toggle_setting(self, enabled, enable_cmd, disable_cmd, reload=True):
        def run():
            try:
                subprocess.run(enable_cmd if enabled else disable_cmd, check=True)
                if reload:
                    GLib.idle_add(self.load_packages)
            except subprocess.CalledProcessError as e:
                print(f"Toggle error: {e}")
        threading.Thread(target=run, daemon=True).start()
    
    def on_multilib_toggle(self, switch_row, param):
        enabled = switch_row.get_active()
        if enabled:
            self.toggle_setting(True, 
                ['sed', '-i', '/^#\\[multilib\\]/{s/^#//;n;s/^#//}', '/etc/pacman.conf'],
                None)
            subprocess.run(['pacman', '-Sy'], check=True)
        else:
            self.toggle_setting(False, None,
                ['sed', '-i', '/^\\[multilib\\]/{s/^/#/;n;s/^/#/}', '/etc/pacman.conf'])
    
    def on_flathub_toggle(self, switch_row, param):
        enabled = switch_row.get_active()
        if enabled:
            self.toggle_setting(True,
                ['flatpak', 'remote-add', '--if-not-exists', 'flathub',
                 'https://dl.flathub.org/repo/flathub.flatpakrepo'],
                None)
        else:
            GLib.idle_add(self.load_packages)  # Just reload without flathub
    
    def load_packages(self):
        def load():
            try:
                packages = []
                
                # Pacman packages
                all_pkgs = subprocess.run(['pacman', '-Sl'], capture_output=True, text=True, check=True)
                installed = {line.split()[0] for line in 
                           subprocess.run(['pacman', '-Q'], capture_output=True, text=True).stdout.split('\n') if line}
                
                for line in all_pkgs.stdout.split('\n'):
                    if line:
                        parts = line.split(' ', 2)
                        if len(parts) >= 2:
                            packages.append((parts[1], f"{parts[0]}", parts[1] in installed, "pacman"))
                
                # Flatpak packages
                if self.check_flatpak_available() and self.check_flathub_enabled():
                    try:
                        available = subprocess.run(['flatpak', 'remote-ls', '--app', 'flathub'], 
                                                 capture_output=True, text=True, check=True)
                        installed_fps = subprocess.run(['flatpak', 'list', '--app'], 
                                                     capture_output=True, text=True, check=True)
                        
                        installed_ids = {line.split('\t')[1] for line in installed_fps.stdout.split('\n') 
                                       if line.strip() and len(line.split('\t')) > 1}
                        
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
        self.refresh_list()
        
        # Count packages
        total_installed = sum(1 for pkg in packages if pkg[2])
        flatpak_installed = sum(1 for pkg in packages if pkg[2] and len(pkg) > 3 and pkg[3] == "flatpak")
        
        if flatpak_installed > 0:
            self.status.set_text(f"{total_installed} installed ({flatpak_installed} flatpak) / {len(packages)} available")
        else:
            self.status.set_text(f"{total_installed} installed / {len(packages)} packages")
        
        return False
    
    def refresh_list(self):
        # Clear list
        while child := self.list.get_first_child():
            self.list.remove(child)
        
        # Filter and add packages
        search_text = self.search.get_text().lower()
        filtered = [p for p in self.packages if search_text in p[0].lower()][:500]
        
        for pkg_data in filtered:
            name, repo, installed, pkg_type = pkg_data[0], pkg_data[1], pkg_data[2], pkg_data[3]
            
            row = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=12)
            box.set_margin_top(6)
            box.set_margin_bottom(6)
            box.set_margin_start(12)
            box.set_margin_end(12)
            
            # Status icon
            icon = Gtk.Label(label="●" if installed else "○", width_request=20)
            if installed:
                icon.add_css_class("success")
            box.append(icon)
            
            # Package name
            name_label = Gtk.Label(label=name, halign=Gtk.Align.START, hexpand=True)
            box.append(name_label)
            
            # Repository
            repo_label = Gtk.Label(label=repo)
            repo_label.add_css_class("dim-label")
            if pkg_type == "flatpak":
                repo_label.add_css_class("accent")
            box.append(repo_label)
            
            row.set_child(box)
            row.pkg_data = pkg_data
            self.list.append(row)
    
    def on_select(self, listbox, row):
        if row:
            self.selected = row.pkg_data
            installed = self.selected[2]
            self.info_btn.set_sensitive(True)
            self.install_btn.set_sensitive(not installed)
            self.remove_btn.set_sensitive(installed)
        else:
            self.selected = None
            for btn in [self.info_btn, self.install_btn, self.remove_btn]:
                btn.set_sensitive(False)
    
    def handle_install(self, button):
        if not self.selected:
            return
        
        pkg_type = self.selected[3]
        if pkg_type == "flatpak":
            self.run_cmd(['flatpak', 'install', '-y', 'flathub', self.selected[4]])
        else:
            self.run_cmd(['pacman', '-S', '--noconfirm', self.selected[0]])
    
    def handle_remove(self, button):
        if not self.selected:
            return
        
        pkg_type = self.selected[3]
        if pkg_type == "flatpak":
            self.run_cmd(['flatpak', 'uninstall', '-y', self.selected[4]])
        else:
            self.run_cmd(['pacman', '-R', '--noconfirm', self.selected[0]])
    
    def handle_update(self, button):
        self.run_cmd(['pacman', '-Syuu', '--noconfirm'])
    
    def show_package_info(self, button):
        if not self.selected:
            return
        
        pkg_name, pkg_type = self.selected[0], self.selected[3]
        
        dialog = Adw.Window(title=f"Info: {pkg_name}", transient_for=self, modal=True)
        dialog.set_default_size(600, 500)
        
        # Setup dialog
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        dialog.set_content(toolbar_view)
        
        # Loading spinner
        spinner = Gtk.Spinner(spinning=True)
        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                             halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        loading_box.append(spinner)
        loading_box.append(Gtk.Label(label="Loading..."))
        toolbar_view.set_content(loading_box)
        dialog.present()
        
        def load_info():
            try:
                if pkg_type == "flatpak":
                    result = subprocess.run(['flatpak', 'info', self.selected[4]], 
                                          capture_output=True, text=True, check=True)
                else:
                    result = subprocess.run(['pacman', '-Si', pkg_name], 
                                          capture_output=True, text=True, check=True)
                    if not result.stdout.strip():
                        result = subprocess.run(['pacman', '-Qi', pkg_name], 
                                              capture_output=True, text=True, check=True)
                
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
        
        # Parse info
        for line in info_text.strip().split('\n'):
            if ':' in line and not line.startswith(' '):
                key, value = line.split(':', 1)
                
                row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                key_label = Gtk.Label(label=key.strip(), halign=Gtk.Align.START)
                key_label.set_markup(f"<b>{key.strip()}</b>")
                key_label.set_size_request(100, -1)
                
                value_label = Gtk.Label(label=value.strip(), halign=Gtk.Align.START, 
                                      hexpand=True, wrap=True, selectable=True)
                
                row_box.append(key_label)
                row_box.append(value_label)
                content_box.append(row_box)
        
        scroll.set_child(content_box)
        toolbar_view.set_content(scroll)
        return False
    
    def run_cmd(self, cmd):
        dialog = Adw.Window(title=f"Running: {' '.join(cmd[:2])}", transient_for=self, modal=True)
        dialog.set_default_size(600, 400)
        
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
                
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      universal_newlines=True, bufsize=1)
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
        PackageManager(self).present()

if __name__ == "__main__":
    Adw.init()
    App().run(sys.argv)

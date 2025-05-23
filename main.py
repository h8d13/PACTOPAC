#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib
import subprocess
import threading
import os
import sys

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
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)
        toolbar_view.add_top_bar(Adw.HeaderBar())
        
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
        
        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, homogeneous=True)
        
        self.info_btn = self.create_button("Info", False, self.show_package_info)
        self.install_btn = self.create_button("Install", False, lambda _: self.run_cmd(['pacman', '-S', '--noconfirm', self.selected]), "suggested-action")
        self.remove_btn = self.create_button("Remove", False, lambda _: self.run_cmd(['pacman', '-R', '--noconfirm', self.selected]), "destructive-action")
        update_btn = self.create_button("Update System", True, lambda _: self.run_cmd(['pacman', '-Syu']))
        
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
        
        self.status = Gtk.Label(label="Loading packages...")
        self.status.add_css_class("dim-label")
        box.append(self.status)
    
    def create_button(self, label, sensitive, callback, css_class=None):
        btn = Gtk.Button(label=label, sensitive=sensitive)
        btn.connect("clicked", callback)
        if css_class:
            btn.add_css_class(css_class)
        return btn
    
    def load_packages(self):
        def load():
            try:
                all_pkgs = subprocess.run(['pacman', '-Sl'], capture_output=True, text=True, check=True)
                installed = {line.split()[0] for line in 
                           subprocess.run(['pacman', '-Q'], capture_output=True, text=True, check=True).stdout.split('\n') if line}
                
                packages = []
                for line in all_pkgs.stdout.split('\n'):
                    if line:
                        parts = line.split(' ', 2)
                        if len(parts) >= 2:
                            packages.append((parts[1], parts[0], parts[1] in installed))
                
                GLib.idle_add(self.update_list, packages)
            except Exception as e:
                GLib.idle_add(self.status.set_text, f"Error: {e}")
        
        threading.Thread(target=load, daemon=True).start()
    
    def update_list(self, packages):
        self.packages = packages
        self.refresh_list()
        self.status.set_text(f"{len(packages)} packages")
        return False
    
    def refresh_list(self):
        while child := self.list.get_first_child():
            self.list.remove(child)
        
        search_text = self.search.get_text().lower()
        filtered = [p for p in self.packages if search_text in p[0].lower()][:500]
        
        for name, repo, installed in filtered:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=12)
            box.set_margin_top(6)
            box.set_margin_bottom(6)
            box.set_margin_start(12)
            box.set_margin_end(12)
            
            status_icon = Gtk.Label(label="●" if installed else "○", width_request=20)
            if installed:
                status_icon.add_css_class("success")
            
            name_label = Gtk.Label(label=name, halign=Gtk.Align.START, hexpand=True)
            repo_label = Gtk.Label(label=repo)
            repo_label.add_css_class("dim-label")
            
            for widget in [status_icon, name_label, repo_label]:
                box.append(widget)
            
            row.set_child(box)
            row.pkg_data = (name, installed)
            self.list.append(row)
    
    def on_select(self, listbox, row):
        if row:
            name, installed = row.pkg_data
            self.selected = name
            self.info_btn.set_sensitive(True)
            self.install_btn.set_sensitive(not installed)
            self.remove_btn.set_sensitive(installed)
        else:
            for btn in [self.info_btn, self.install_btn, self.remove_btn]:
                btn.set_sensitive(False)
    
    def show_package_info(self, button):
        if not self.selected:
            return
            
        dialog = Adw.Window(title=f"Package Info: {self.selected}", 
                           transient_for=self, modal=True)
        dialog.set_default_size(600, 500)
        
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        dialog.set_content(toolbar_view)
        
        # Loading state
        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, 
                             halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        loading_box.append(Gtk.Spinner(spinning=True))
        loading_box.append(Gtk.Label(label="Loading package information..."))
        toolbar_view.set_content(loading_box)
        dialog.present()
        
        def load_info():
            try:
                for cmd in [['pacman', '-Si', self.selected], ['pacman', '-Qi', self.selected]]:
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.stdout.strip():
                        GLib.idle_add(self.display_package_info, toolbar_view, result.stdout)
                        return
                GLib.idle_add(self.display_package_info, toolbar_view, f"Could not retrieve information for package '{self.selected}'")
            except Exception:
                GLib.idle_add(self.display_package_info, toolbar_view, f"Error retrieving package info")
        
        threading.Thread(target=load_info, daemon=True).start()
    
    def display_package_info(self, toolbar_view, info_text):
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_margin_top(12)
        scroll.set_margin_bottom(12)
        scroll.set_margin_start(12)
        scroll.set_margin_end(12)
        
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        if "Could not retrieve" in info_text or "Error" in info_text:
            error_label = Gtk.Label(label=info_text, halign=Gtk.Align.CENTER)
            error_label.add_css_class("dim-label")
            content_box.append(error_label)
        else:
            for line in info_text.strip().split('\n'):
                if ':' in line and not line.startswith(' '):
                    key, value = line.split(':', 1)
                    key, value = key.strip(), value.strip()
                    
                    row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                    
                    key_label = Gtk.Label(label=key, halign=Gtk.Align.START)
                    key_label.set_markup(f"<b>{key}</b>")
                    key_label.set_size_request(120, -1)
                    
                    value_label = Gtk.Label(label=value, halign=Gtk.Align.START, 
                                          hexpand=True, wrap=True, selectable=True)
                    
                    row_box.append(key_label)
                    row_box.append(value_label)
                    content_box.append(row_box)
        
        scroll.set_child(content_box)
        toolbar_view.set_content(scroll)
        return False
    
    def run_cmd(self, cmd):
        dialog = Adw.Window(title=f"Running: {' '.join(cmd)}", transient_for=self, modal=True)
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
        text = Gtk.TextView(editable=False, monospace=True)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(text)
        
        content_box.append(progress)
        content_box.append(scroll)
        toolbar_view.set_content(content_box)
        dialog.present()
        
        def run():
            try:
                pulse_id = GLib.timeout_add(100, lambda: progress.pulse() or True)
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      universal_newlines=True, bufsize=1)
                buf = text.get_buffer()
                
                for line in iter(proc.stdout.readline, ''):
                    GLib.idle_add(lambda l=line: buf.insert(buf.get_end_iter(), l))
                
                proc.wait()
                GLib.source_remove(pulse_id)
                
                result = f"\n{'✓ Command completed successfully' if proc.returncode == 0 else f'✗ Command failed (exit code {proc.returncode})'}"
                GLib.idle_add(lambda: buf.insert(buf.get_end_iter(), result))
                
                if proc.returncode == 0:
                    GLib.idle_add(self.load_packages)
                    
            except Exception as e:
                if 'pulse_id' in locals():
                    GLib.source_remove(pulse_id)
                GLib.idle_add(lambda: buf.insert(buf.get_end_iter(), f"\nError: {e}"))
        
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

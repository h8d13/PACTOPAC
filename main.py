#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio
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
        
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)
        
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
        
        self.info_btn = Gtk.Button(label="Info", sensitive=False)
        self.info_btn.connect("clicked", self.show_package_info)
        
        self.install_btn = Gtk.Button(label="Install", sensitive=False)
        self.install_btn.add_css_class("suggested-action")
        self.install_btn.connect("clicked", lambda _: self.run_cmd(['pacman', '-S', '--noconfirm', self.selected]))
        
        self.remove_btn = Gtk.Button(label="Remove", sensitive=False)
        self.remove_btn.add_css_class("destructive-action")
        self.remove_btn.connect("clicked", lambda _: self.run_cmd(['pacman', '-R', '--noconfirm', self.selected]))
        
        update_btn = Gtk.Button(label="Update System")
        update_btn.connect("clicked", lambda _: self.run_cmd(['pacman', '-Syu']))
        
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
            box.append(status_icon)
            
            name_label = Gtk.Label(label=name, halign=Gtk.Align.START, hexpand=True)
            box.append(name_label)
            
            repo_label = Gtk.Label(label=repo)
            repo_label.add_css_class("dim-label")
            box.append(repo_label)
            
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
            self.info_btn.set_sensitive(False)
            self.install_btn.set_sensitive(False)
            self.remove_btn.set_sensitive(False)
    
    def show_package_info(self, button):
        """Show detailed package information"""
        if not self.selected:
            return
            
        dialog = Adw.Window(title=f"Package Info: {self.selected}", 
                           transient_for=self, modal=True)
        dialog.set_default_size(600, 500)
        
        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        
        toolbar_view.add_top_bar(header)
        dialog.set_content(toolbar_view)
        
        # Loading state
        spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        loading_label = Gtk.Label(label="Loading package information...")
        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, 
                             halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        loading_box.append(spinner)
        loading_box.append(loading_label)
        
        toolbar_view.set_content(loading_box)
        dialog.present()
        
        def load_info():
            try:
                # Get package info
                result = subprocess.run(['pacman', '-Si', self.selected], 
                                      capture_output=True, text=True, check=True)
                info_text = result.stdout
                
                # If not in repos, try installed packages
                if not info_text.strip():
                    result = subprocess.run(['pacman', '-Qi', self.selected], 
                                          capture_output=True, text=True, check=True)
                    info_text = result.stdout
                
                GLib.idle_add(self.display_package_info, dialog, toolbar_view, info_text)
                
            except subprocess.CalledProcessError:
                error_text = f"Could not retrieve information for package '{self.selected}'"
                GLib.idle_add(self.display_package_info, dialog, toolbar_view, error_text)
        
        threading.Thread(target=load_info, daemon=True).start()
    
    def display_package_info(self, dialog, toolbar_view, info_text):
        """Display the package information in a formatted way"""
        # Create scrollable content
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_margin_top(12)
        scroll.set_margin_bottom(12)
        scroll.set_margin_start(12)
        scroll.set_margin_end(12)
        
        # Parse and format the package info
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        
        if "Could not retrieve" in info_text:
            # Error case
            error_label = Gtk.Label(label=info_text, halign=Gtk.Align.CENTER)
            error_label.add_css_class("dim-label")
            content_box.append(error_label)
        else:
            # Parse package info
            lines = info_text.strip().split('\n')
            for line in lines:
                if ':' in line and not line.startswith(' '):
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Create info row
                    row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                    row_box.set_margin_top(3)
                    row_box.set_margin_bottom(3)
                    
                    # Key label (bold)
                    key_label = Gtk.Label(label=key, halign=Gtk.Align.START)
                    key_label.set_markup(f"<b>{key}</b>")
                    key_label.set_size_request(120, -1)
                    row_box.append(key_label)
                    
                    # Value label (selectable for copying)
                    value_label = Gtk.Label(label=value, halign=Gtk.Align.START, 
                                          hexpand=True, wrap=True, selectable=True)
                    
                    # Special styling for certain fields
                    if key.lower() in ['name', 'version']:
                        value_label.set_markup(f"<tt>{value}</tt>")
                    elif key.lower() == 'description':
                        value_label.add_css_class("dim-label")
                    
                    row_box.append(value_label)
                    content_box.append(row_box)
                    
                    # Add separator for readability
                    if key.lower() in ['version', 'description', 'dependencies']:
                        separator = Gtk.Separator()
                        separator.set_margin_top(6)
                        separator.set_margin_bottom(6)
                        content_box.append(separator)
        
        scroll.set_child(content_box)
        toolbar_view.set_content(scroll)
        
        return False
    
    def run_cmd(self, cmd):
        dialog = Adw.Window(title=f"Running: {' '.join(cmd)}", 
                           transient_for=self, modal=True)
        dialog.set_default_size(600, 400)
        
        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        
        toolbar_view.add_top_bar(header)
        dialog.set_content(toolbar_view)
        
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        
        progress = Gtk.ProgressBar()
        progress.set_show_text(True)
        progress.set_text("Starting...")
        content_box.append(progress)
        
        scroll = Gtk.ScrolledWindow(vexpand=True)
        text = Gtk.TextView(editable=False, monospace=True)
        scroll.set_child(text)
        content_box.append(scroll)
        
        toolbar_view.set_content(content_box)
        dialog.present()
        
        def auto_scroll():
            buf = text.get_buffer()
            end_iter = buf.get_end_iter()
            mark = buf.get_insert()
            buf.place_cursor(end_iter)
            text.scroll_mark_onscreen(mark)
            return False
        
        def pulse_progress():
            progress.pulse()
            return True
        
        def run():
            try:
                pulse_id = GLib.timeout_add(100, pulse_progress)
                
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      universal_newlines=True, bufsize=1)
                buf = text.get_buffer()
                
                GLib.idle_add(lambda: progress.set_text("Running command..."))
                
                for line in iter(proc.stdout.readline, ''):
                    def add_line(l=line):
                        buf.insert(buf.get_end_iter(), l)
                        GLib.idle_add(auto_scroll)
                        return False
                    GLib.idle_add(add_line)
                
                proc.wait()
                GLib.source_remove(pulse_id)
                
                if proc.returncode == 0:
                    result = "\n✓ Command completed successfully"
                    GLib.idle_add(lambda: progress.set_fraction(1.0))
                    GLib.idle_add(lambda: progress.set_text("Completed successfully"))
                    GLib.idle_add(lambda: progress.add_css_class("success"))
                    GLib.idle_add(self.load_packages)
                else:
                    result = f"\n✗ Command failed (exit code {proc.returncode})"
                    GLib.idle_add(lambda: progress.set_fraction(1.0))
                    GLib.idle_add(lambda: progress.set_text("Command failed"))
                    GLib.idle_add(lambda: progress.add_css_class("error"))
                
                GLib.idle_add(lambda: buf.insert(buf.get_end_iter(), result))
                GLib.idle_add(auto_scroll)
                    
            except Exception as e:
                if 'pulse_id' in locals():
                    GLib.source_remove(pulse_id)
                GLib.idle_add(lambda: progress.set_text("Error occurred"))
                GLib.idle_add(lambda: progress.add_css_class("error"))
                GLib.idle_add(lambda: buf.insert(buf.get_end_iter(), f"\nError: {e}"))
                GLib.idle_add(auto_scroll)
        
        threading.Thread(target=run, daemon=True).start()

class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.suckless.pacman")
        
    def do_activate(self):
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        
        win = PackageManager(self)
        win.present()

if __name__ == "__main__":
    Adw.init()
    app = App()
    app.run(sys.argv)

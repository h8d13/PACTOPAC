#!/bin/python3
import subprocess
import json
import os
import re

# Globals
FORM_FACTOR = None
GPU_VENDORS = []
DRIVERS_CONFIG = None

def load_drivers_config():
    global DRIVERS_CONFIG
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'drivers.json')
        with open(config_path, 'r') as f:
            DRIVERS_CONFIG = json.load(f)
        print("✓ Driver configuration loaded")
        return True
    except:
        print("✗ drivers.json not found")
        return False

def get_os_fields(field: str) -> str:
    try:
        result = subprocess.run(
            ["grep", "-oP", fr'(?<=^{field}=)[^\n]*', "/etc/os-release"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except:
        return ""

def get_usr():
    is_root = os.geteuid() == 0
    print(f"ROOT: {is_root}")
    return is_root

def get_ker():
    ker_info = subprocess.check_output("uname -r", shell=True).decode('utf-8').strip()
    print(f"Detected KER: {ker_info}")
    return ker_info

def get_cpu():
    cpu_info = subprocess.check_output("lscpu | grep -E 'Model name|Socket|Thread|Core|CPU(s)'", shell=True).decode('utf-8')
    print(f"Detected CPU: {cpu_info}")
    return cpu_info

def get_all_gpus():
    try:
        print("\n--- Checking GPU ---")
        result = subprocess.run(["lspci", "-nn"], capture_output=True, text=True, check=True)
        gpu_devices = []
        for line in result.stdout.split('\n'):
            if line.strip() and re.search(r'\[03[0-8][0-9]\]', line):
                gpu_devices.append(line.strip())
        
        if gpu_devices:
            print("Detected GPU devices:")
            for device in gpu_devices:
                print(f"  {device}")
        
        return gpu_devices
    except:
        return []

def detect_gpu_vendors():
    global GPU_VENDORS
    GPU_VENDORS = []
    
    gpu_devices = get_all_gpus()
    if not gpu_devices:
        return GPU_VENDORS
    
    found_vendors = []
    
    for device in gpu_devices:
        # Split the device string to get the vendor part (after the colon)
        # Format: "00:02.0 VGA compatible controller [0300]: Intel Corporation ..."
        if ':' in device:
            vendor_part = device.split(':', 2)[-1].upper()  # Get everything after the last colon
        else:
            vendor_part = device.upper()
        
        print(f"Checking vendor part: {vendor_part}")
        
        if "NVIDIA CORPORATION" in vendor_part or "NVIDIA" in vendor_part:
            if "nvidia" not in found_vendors:
                found_vendors.append("nvidia")
                print(f"Found NVIDIA: {device}")
        
        elif "INTEL CORPORATION" in vendor_part or "INTEL" in vendor_part:
            if "intel" not in found_vendors:
                found_vendors.append("intel")
                print(f"Found INTEL: {device}")
        
        elif "AMD" in vendor_part or "ATI" in vendor_part or "ADVANCED MICRO DEVICES" in vendor_part:
            if "amd" not in found_vendors:
                found_vendors.append("amd")
                print(f"Found AMD: {device}")
    
    # Priority order: nvidia > amd > intel
    # This is for detecting hybrid setups
    
    priority_order = ["nvidia", "amd", "intel"]
    GPU_VENDORS = [vendor for vendor in priority_order if vendor in found_vendors]
    
    print(f"Final GPU vendors: {GPU_VENDORS}")
    return GPU_VENDORS

def detect_form_factor():
    global FORM_FACTOR
    
    # Print chassis type
    try:
        print("\n--- Checking FORM ---")
        result = subprocess.run(["dmidecode", "-s", "chassis-type"], 
                              capture_output=True, text=True, check=True)
        print(f"Chassis Type: {result.stdout.strip()}")
    except:
        try:
            with open('/sys/class/dmi/id/chassis_type', 'r') as f:
                print(f"Chassis Type: {f.read().strip()}")
        except:
            print("Chassis Type: Unable to detect")
    
    # Check for battery (existing logic)
    try:
        battery_check = subprocess.run(["ls", "/sys/class/power_supply/"], capture_output=True, text=True)
        if battery_check.returncode == 0 and "BAT" in battery_check.stdout:
            FORM_FACTOR = "laptop"
            print(f"Form Factor: {FORM_FACTOR} (battery detected)")
            return FORM_FACTOR
    except:
        pass
    
    FORM_FACTOR = "desktop"
    print(f"Form Factor: {FORM_FACTOR}")
    return FORM_FACTOR

def check_gpu_drivers(vendor, auto_install=False):
    if not DRIVERS_CONFIG:
        return {}
    
    drivers = DRIVERS_CONFIG["gpu_drivers"].get(vendor, [])
    if not drivers:
        return {}
        
    results = {}
    for driver in drivers:
        results[driver] = check_install_package(driver, auto_install)
    
    return results

def check_microcode(auto_install=False):
    print("\n--- Checking CPU ---")

    cpu_info = get_cpu().upper()
    
    if not DRIVERS_CONFIG:
        return None
    
    if "AMD" in cpu_info:
        print("CPU Vendor: AMD")
        microcode_pkg = DRIVERS_CONFIG["microcode"]["amd"]
    elif "INTEL" in cpu_info:
        print("CPU Vendor: Intel")
        microcode_pkg = DRIVERS_CONFIG["microcode"]["intel"]
    else:
        return None
    
    return check_install_package(microcode_pkg, auto_install)

def check_power_management(auto_install=False):
    if not FORM_FACTOR:
        detect_form_factor()
    
    if not DRIVERS_CONFIG:
        return None
    
    power_pkg = DRIVERS_CONFIG["power_management"].get(FORM_FACTOR)
    if power_pkg:
        return check_install_package(power_pkg, auto_install)
    
    return None

def check_audio_utils(auto_install=False):
    print("\n--- Checking Audio Utils ---")
    alsa_status = check_install_package("alsa-utils", auto_install)
    
    # If alsa-utils is installed or was just installed, try to run aplay -l
    if alsa_status in ['installed', 'installed_now']:
        try:
            result = subprocess.run(["aplay", "-l"], capture_output=True, text=True, check=True)
            print("For HDMI use alsamixer! F6 select card > Then M to unmute channels.")
            print("Audio devices (aplay -l):")
            print(result.stdout)
        except subprocess.CalledProcessError as e:
            print(f"✗ aplay command failed: {e}")
            print("Stderr:", e.stderr)
        except FileNotFoundError:
            print("✗ aplay command not found (PATH issue?)")
    
    return alsa_status


def check_install_package(package_name, auto_install=False):
    try:
        result = subprocess.run(["pacman", "-Q", package_name], capture_output=True, text=True, check=True)
        print(f"✓ {package_name} is already installed: {result.stdout.strip()}")
        return 'installed'
    except:
        print(f"✗ {package_name} is NOT installed")
        
        if auto_install:
            try:
                subprocess.run(["sudo", "pacman", "-S", "--noconfirm", package_name], check=True)
                print(f"✓ {package_name} installed successfully")
                return 'installed_now'
            except:
                print(f"✗ Failed to install {package_name}")
                return 'install_failed'
        return 'not_installed'

if __name__ == "__main__":
    load_drivers_config()
    
    get_usr()
    get_ker()
    dist_val = get_os_fields("ID")
    dist_fam = get_os_fields("ID_LIKE")
    print(f"DV:{dist_val} - DF:{dist_fam}")
    
    detect_form_factor()
    check_power_management()

    check_microcode()

    detect_gpu_vendors()    
    # Check drivers for all detected GPUs
    for vendor in GPU_VENDORS:
        print(f"\n--- Checking {vendor.upper()} drivers ---")
        check_gpu_drivers(vendor)

    check_audio_utils()
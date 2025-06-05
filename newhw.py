#!/bin/python3
## hw.py
import subprocess
import json
import os
import re

# Globals
FORM_FACTOR = None
GPU_VENDORS = []  # Changed to list to support multiple GPUs
DRIVERS_CONFIG = None

def load_drivers_config():
    """Load driver configuration from JSON file"""
    global DRIVERS_CONFIG
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'drivers.json')
        with open(config_path, 'r') as f:
            DRIVERS_CONFIG = json.load(f)
        print("✓ Driver configuration loaded")
    except FileNotFoundError:
        print("✗ drivers.json not found.")
        return False
    except json.JSONDecodeError as e:
        print(f"✗ Error parsing drivers.json: {e}")
        return False
    return True

def rline(res):
    return res.strip()

def get_os_fields(field: str) -> str:
    try:
        result = subprocess.run(
            ["grep", "-oP", fr'(?<=^{field}=)[^\n]*', "/etc/os-release"],
            capture_output=True, text=True, check=True
        )
        return rline(result.stdout)
    except subprocess.CalledProcessError:
        return ""

def get_usr():
    usr_info = subprocess.check_output("whoami", shell=True).decode('utf-8').strip()
    is_root = usr_info == "root"
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
    """Get detailed information about all GPU devices"""
    try:
        # Use more comprehensive approach to detect all graphics devices
        result = subprocess.run(
            ["lspci", "-nn"], 
            capture_output=True, text=True, check=True
        )
        
        gpu_devices = []
        for line in result.stdout.split('\n'):
            if line.strip():
                # Look for class codes: 0300 (VGA), 0302 (3D), 0380 (Display)
                if re.search(r'\[03[0-8][0-9]\]', line):
                    gpu_devices.append(line.strip())
        
        if gpu_devices:
            print("Detected GPU devices:")
            for device in gpu_devices:
                print(f"  {device}")
        
        return gpu_devices
        
    except subprocess.CalledProcessError as e:
        print(f"Error getting GPU information: {e}")
        return []

def detect_gpu_vendors():
    """Detect all GPU vendors present in the system"""
    global GPU_VENDORS
    GPU_VENDORS = []
    
    try:
        gpu_devices = get_all_gpus()
        
        if not gpu_devices:
            print("No GPU devices found")
            return GPU_VENDORS
        
        vendor_priority = {"nvidia": 0, "amd": 1, "intel": 2}
        detected_vendors = {}
        
        for device in gpu_devices:
            device_upper = device.upper()
            vendor = None
            
            # Check for NVIDIA
            if any(keyword in device_upper for keyword in ["NVIDIA", "GEFORCE", "QUADRO", "GTX", "RTX"]):
                vendor = "nvidia"
            # Check for AMD/ATI
            elif any(keyword in device_upper for keyword in ["AMD", "ATI", "RADEON"]):
                vendor = "amd"
            # Check for Intel
            elif "INTEL" in device_upper and any(keyword in device_upper for keyword in ["GRAPHICS", "HD", "UHD", "IRIS"]):
                vendor = "intel"
            
            if vendor and vendor not in detected_vendors:
                detected_vendors[vendor] = device
        
        # Sort by priority (NVIDIA first, then AMD, then Intel)
        GPU_VENDORS = sorted(detected_vendors.keys(), key=lambda x: vendor_priority.get(x, 999))
        
        if GPU_VENDORS:
            print(f"Detected GPU vendors: {', '.join(GPU_VENDORS)}")
            for vendor in GPU_VENDORS:
                print(f"  {vendor.upper()}: {detected_vendors[vendor]}")
        else:
            print("No recognized GPU vendors found")
        
        return GPU_VENDORS
        
    except Exception as e:
        print(f"Error detecting GPU vendors: {e}")
        return []

def get_primary_gpu_vendor():
    """Get the primary GPU vendor (for driver installation)"""
    if not GPU_VENDORS:
        detect_gpu_vendors()
    
    if GPU_VENDORS:
        primary = GPU_VENDORS[0]  # First in priority order
        print(f"Primary GPU vendor: {primary}")
        return primary
    
    return "unknown"

def detect_form_factor():
    global FORM_FACTOR
    
    try:
        # Check for battery
        try:
            battery_check = subprocess.run(
                ["ls", "/sys/class/power_supply/"],
                capture_output=True, text=True, check=True
            )
            if "BAT" in battery_check.stdout:
                FORM_FACTOR = "laptop"
                print(f"Form Factor: {FORM_FACTOR} (battery detected)")
                return FORM_FACTOR
        except subprocess.CalledProcessError:
            pass
        
        # Check chassis type
        try:
            chassis_result = subprocess.run(
                ["sudo", "dmidecode", "-s", "chassis-type"],
                capture_output=True, text=True, check=True
            )
            chassis_type = chassis_result.stdout.strip().lower()
            print(f"Chassis type: {chassis_type}")
            
            if chassis_type in ["notebook", "laptop", "portable"]:
                FORM_FACTOR = "laptop"
            else:
                FORM_FACTOR = "desktop"
                
        except subprocess.CalledProcessError:
            FORM_FACTOR = "desktop"
        
        print(f"Form Factor: {FORM_FACTOR}")
        return FORM_FACTOR
        
    except Exception as e:
        print(f"Error detecting form factor: {e}")
        FORM_FACTOR = "desktop"
        print(f"Form Factor: {FORM_FACTOR} (default)")
        return FORM_FACTOR

def check_gpu_drivers(vendor=None, auto_install=False):
    """Check GPU drivers for specified vendor or primary GPU"""
    if vendor is None:
        vendor = get_primary_gpu_vendor()
    
    if vendor == "unknown":
        print("✗ Unknown GPU vendor, cannot check drivers")
        return {}
    
    if DRIVERS_CONFIG is None:
        print("✗ Driver configuration not loaded")
        return {}
    
    drivers = DRIVERS_CONFIG["gpu_drivers"].get(vendor, [])
    if not drivers:
        print(f"✗ No driver configuration found for {vendor}")
        return {}
    
    print(f"Checking {vendor} drivers: {', '.join(drivers)}")
    
    results = {}
    for driver in drivers:
        results[driver] = check_install_package(driver, auto_install)
    
    return results

def check_all_gpu_drivers(auto_install=False):
    """Check drivers for all detected GPU vendors"""
    if not GPU_VENDORS:
        detect_gpu_vendors()
    
    all_results = {}
    for vendor in GPU_VENDORS:
        print(f"\n--- Checking {vendor.upper()} drivers ---")
        all_results[vendor] = check_gpu_drivers(vendor, auto_install)
    
    return all_results

def check_install_package(package_name, auto_install=False):
    try:
        result = subprocess.run(
            ["pacman", "-Q", package_name],
            capture_output=True, text=True, check=True
        )
        print(f"✓ {package_name} is already installed: {result.stdout.strip()}")
        return 'installed'
        
    except subprocess.CalledProcessError:
        print(f"✗ {package_name} is NOT installed")
        
        if auto_install:
            print(f"Installing {package_name}...")
            try:
                subprocess.run(
                    ["sudo", "pacman", "-S", "--noconfirm", package_name],
                    capture_output=True, text=True, check=True
                )
                print(f"✓ {package_name} installed successfully")
                return 'installed_now'
                
            except subprocess.CalledProcessError as e:
                print(f"✗ Failed to install {package_name}: {e}")
                return 'install_failed'
        else:
            return 'not_installed'

def check_microcode(auto_install=False):
    try:
        cpu_info = get_cpu()
        
        if DRIVERS_CONFIG is None:
            print("✗ Driver configuration not loaded")
            return None
        
        if "AMD" in cpu_info.upper():
            print("CPU Vendor: AMD")
            microcode_pkg = DRIVERS_CONFIG["microcode"]["amd"]
        elif "INTEL" in cpu_info.upper():
            print("CPU Vendor: Intel")
            microcode_pkg = DRIVERS_CONFIG["microcode"]["intel"]
        else:
            print("✗ Unknown CPU vendor")
            return None
        
        return check_install_package(microcode_pkg, auto_install)
        
    except Exception as e:
        print(f"Error checking microcode: {e}")
        return None

def check_power_management(auto_install=False):
    """Check and optionally install power management packages"""
    if FORM_FACTOR is None:
        detect_form_factor()
    
    if DRIVERS_CONFIG is None:
        print("✗ Driver configuration not loaded")
        return None
    
    power_pkg = DRIVERS_CONFIG["power_management"].get(FORM_FACTOR)
    if power_pkg:
        return check_install_package(power_pkg, auto_install)
    else:
        print(f"✗ No power management package defined for {FORM_FACTOR}")
        return None

# Main execution
if __name__ == "__main__":
    # Load configuration first
    load_drivers_config()
    
    get_usr()
    get_ker()
    dist_val = get_os_fields("ID")
    dist_fam = get_os_fields("ID_LIKE")
    print(f"DV:{dist_val} - DF:{dist_fam}")
    
    detect_form_factor()
    check_power_management()
    
    # New improved GPU detection
    detect_gpu_vendors()
    check_microcode(auto_install=False)
    
    # Check drivers for all detected GPUs
    check_all_gpu_drivers(auto_install=False)
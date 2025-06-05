#!/bin/python3
## hw.py
import subprocess
import json
import os

# Globals
FORM_FACTOR = None
GPU_VENDOR = None
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
        # Fallback configuration
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

def get_gpu():
    gpu_info = subprocess.check_output("lspci | grep -i '3D\\|VGA'", shell=True).decode('utf-8')
    print(f"Detected GPU: {gpu_info}")
    return gpu_info

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
            chassis_result = subprocess.run(
                ["sudo", "dmidecode", "-s", "chassis-type"],
                capture_output=True, text=True, check=True
            )
            chassis_type = chassis_result.stdout.strip().lower()
            
            print(chassis_type)
            
            return FORM_FACTOR
            
        except subprocess.CalledProcessError:
            pass
        
        # Default fallback
        FORM_FACTOR = "desktop"
        print(f"Form Factor: {FORM_FACTOR} (fallback)")
        return FORM_FACTOR
        
    except Exception as e:
        print(f"Error detecting form factor: {e}")
        FORM_FACTOR = "desktop"
        print(f"Form Factor: {FORM_FACTOR} (default)")
        return FORM_FACTOR

def detect_gpu_vendor():
    global GPU_VENDOR
    
    try:
        gpu_info = get_gpu().upper()
        
        if "INTEL" in gpu_info:
            GPU_VENDOR = "intel"
        elif "AMD" in gpu_info or "ATI" in gpu_info or "RADEON" in gpu_info:
            GPU_VENDOR = "amd"
        elif "NVIDIA" in gpu_info or "GEFORCE" in gpu_info or "QUADRO" in gpu_info:
            GPU_VENDOR = "nvidia"
            
        print(f"GPU Vendor: {GPU_VENDOR}")
        return GPU_VENDOR
        
    except Exception as e:
        print(f"Error detecting GPU vendor: {e}")
        GPU_VENDOR = "unknown"
        return GPU_VENDOR

def check_gpu_drivers(auto_install=False):
    if GPU_VENDOR is None:
        detect_gpu_vendor()
    
    if DRIVERS_CONFIG is None:
        print("✗ Driver configuration not loaded")
        return {}
    
    drivers = DRIVERS_CONFIG["gpu_drivers"].get(GPU_VENDOR, DRIVERS_CONFIG["gpu_drivers"]["intel"])
    print(f"Checking {GPU_VENDOR} drivers: {', '.join(drivers)}")
    
    results = {}
    for driver in drivers:
        results[driver] = check_install_package(driver, auto_install)
    
    return results

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
    
    detect_gpu_vendor()
    check_microcode(auto_install=False)
    check_gpu_drivers(auto_install=False)
#!/bin/python3
## hw.py
import subprocess

# Globals
FORM_FACTOR = None
GPU_VENDOR = None

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
               FORM_FACTOR = "Laptop"
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
           
           laptop_types = ['laptop', 'notebook', 'portable', 'sub notebook', 'handheld']
           desktop_types = ['desktop', 'tower', 'mini tower']
           
           if any(ltype in chassis_type for ltype in laptop_types):
               FORM_FACTOR = "Laptop"
           elif any(dtype in chassis_type for dtype in desktop_types):
               FORM_FACTOR = "Desktop"
           else:
               FORM_FACTOR = "Desktop"
               
           print(f"Form Factor: {FORM_FACTOR} (chassis: {chassis_type})")
           return FORM_FACTOR
           
       except subprocess.CalledProcessError:
           pass
       
       # Default fallback
       FORM_FACTOR = "Desktop"
       print(f"Form Factor: {FORM_FACTOR} (fallback)")
       return FORM_FACTOR
       
   except Exception as e:
       print(f"Error detecting form factor: {e}")
       FORM_FACTOR = "Desktop"
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
        else:
            GPU_VENDOR = "unknown"
            
        print(f"GPU Vendor: {GPU_VENDOR}")
        return GPU_VENDOR
        
    except Exception as e:
        print(f"Error detecting GPU vendor: {e}")
        GPU_VENDOR = "unknown"
        return GPU_VENDOR

def check_gpu_drivers(auto_install=False):
   if GPU_VENDOR is None:
       detect_gpu_vendor()
   
   # Archinstall driver groups TO DO
   driver_groups = {
       'amd': ['mesa', 'xf86-video-amdgpu', 'vulkan-radeon'],
       'intel': ['mesa', 'vulkan-intel'],
       'nvidia': ['nvidia', 'nvidia-utils', 'nvidia-settings'],
       'unknown': ['mesa', 'xf86-video-vesa']
   }
   
   drivers = driver_groups.get(GPU_VENDOR, driver_groups['unknown'])
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
       
       if "AMD" in cpu_info.upper():
           print("CPU Vendor: AMD")
           microcode_pkg = "amd-ucode"
       elif "INTEL" in cpu_info.upper():
           print("CPU Vendor: Intel")
           microcode_pkg = "intel-ucode"
       else:
           print(f"Unknown CPU vendor in: {cpu_info}")
           return None
       
       return check_install_package(microcode_pkg, auto_install)
       
   except Exception as e:
       print(f"Error checking microcode: {e}")
       return None

get_usr()
get_ker()

dist_val = get_os_fields("ID")
dist_fam = get_os_fields("ID_LIKE")
print(f"DV:{dist_val} - DF:{dist_fam}")

detect_form_factor()

if FORM_FACTOR == "Laptop":
   check_install_package("power-profiles-daemon")
else:
   check_install_package("cpupower")

detect_gpu_vendor()

check_microcode(auto_install=False)
check_gpu_drivers(auto_install=False)

import platform
import psutil
import subprocess
import re

def get_cpu_info():
    cpu_name = platform.processor()
    physical_cores = psutil.cpu_count(logical=False)
    total_cores = psutil.cpu_count(logical=True)
    return {
        "cpu_name": cpu_name,
        "physical_cores": physical_cores,
        "total_cores": total_cores,
        "cpu_frequency_mhz": psutil.cpu_freq().current if psutil.cpu_freq() else None
    }

def get_ram_info():
    ram = psutil.virtual_memory()
    return {
        "total_ram_gb": round(ram.total / (1024**3), 2),
        "available_ram_gb": round(ram.available / (1024**3), 2)
    }

def get_nvidia_gpu():
    try:
        output = subprocess.check_output("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader", shell=True)
        lines = output.decode().strip().split("\n")
        gpus = []
        for line in lines:
            name, mem = line.split(",")
            gpus.append({
                "gpu_name": name.strip(),
                "gpu_memory_gb": float(mem.replace(" MiB", "").strip()) / 1024
            })
        return gpus
    except:
        return None

def get_amd_gpu():
    try:
        output = subprocess.check_output("wmic path win32_VideoController get Name,AdapterRAM", shell=True)
        lines = output.decode().strip().split("\n")[1:]
        gpus = []
        for line in lines:
            if line.strip():
                parts = re.split(r"\s{2,}", line.strip())
                if len(parts) == 2:
                    name, ram = parts
                    gpus.append({
                        "gpu_name": name.strip(),
                        "gpu_memory_gb": round(int(ram) / (1024**3), 2) if ram.isdigit() else None
                    })
        return gpus
    except:
        return None

def get_gpu_info():
    nvidia = get_nvidia_gpu()
    if nvidia:
        return {"type": "NVIDIA", "gpus": nvidia}
    
    amd = get_amd_gpu()
    if amd:
        return {"type": "AMD/Intel", "gpus": amd}
    
    return {"type": "None detected", "gpus": []}

# ---- RUN EVERYTHING ----

cpu = get_cpu_info()
ram = get_ram_info()
gpu = get_gpu_info()

print("=== CPU INFO ===")
print(cpu)

print("\n=== RAM INFO ===")
print(ram)

print("\n=== GPU INFO ===")
print(gpu)

"""Live local system telemetry for the dashboard."""

import os
import socket

import psutil

_GPU_READERS = None


def _load_gpu_readers():
    """Return callables returning (load%, name) for each GPU, or [] if unavailable."""
    global _GPU_READERS
    if _GPU_READERS is not None:
        return _GPU_READERS
    readers = []

    # NVIDIA via NVML (pynvml), the most common discrete GPU path.
    try:
        import pynvml

        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()

        def _nvidia(index: int) -> tuple[int, str] | None:
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(index)
                utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode("utf-8", "replace")
                return int(utilization.gpu), name
            except Exception:
                return None

        readers.extend(lambda index=index: _nvidia(index) for index in range(device_count))
    except Exception:
        pass

    # Windows performance counters as a generic fallback (Intel/AMD iGPU).
    if not readers and os.name == "nt":
        try:
            import subprocess

            def _wcounter() -> tuple[int, str] | None:
                try:
                    output = subprocess.run(
                        ["typeperf", "\\GPU Engine(*)\\Utilization Percentage", "-sc", "1"],
                        capture_output=True,
                        text=True,
                        timeout=3,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    ).stdout
                    for line in output.splitlines():
                        if "," in line and line.split(",")[-1].strip().strip('"').replace(".", "", 1).isdigit():
                            value = float(line.split(",")[-1].strip().strip('"'))
                            return int(min(100, round(value))), "GPU"
                except Exception:
                    return None
                return None

            readers.append(_wcounter)
        except Exception:
            pass

    _GPU_READERS = readers
    return readers


def get_system_state() -> dict[str, object]:
    """Return a best-effort snapshot without failing the user interface."""
    memory = psutil.virtual_memory()
    state: dict[str, object] = {
        "cpu": round(psutil.cpu_percent(interval=None)),
        "ram": round(memory.percent),
        "tasks": len(psutil.pids()),
        "memory": f"{memory.used / (1024 ** 3):.1f} GB",
        "status": "OPERATIONAL",
    }
    gpu_value: object = None
    gpu_name = ""
    for reader in _load_gpu_readers():
        try:
            result = reader()
        except Exception:
            result = None
        if result is not None:
            gpu_value, gpu_name = result
            break
    state["gpu"] = gpu_value if gpu_value is not None else "N/A"
    if gpu_name:
        state["gpu_name"] = gpu_name
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        state["network"] = probe.getsockname()[0]
        probe.close()
    except OSError:
        state["network"] = "Offline"
    try:
        disk = psutil.disk_usage(os.path.expanduser("~"))
        state["disk_used"] = f"{disk.used / (1024 ** 3):.1f} GB"
        state["disk_total"] = f"{disk.total / (1024 ** 3):.1f} GB"
    except OSError:
        pass
    return state

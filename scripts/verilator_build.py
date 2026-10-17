"""Build a Verilator timing model with the available Windows C++ toolchain."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def build_binary(root: Path, top: str, parameters: dict[str, int], sources: list[Path],
                 directory: Path, env: dict[str, str]) -> Path:
    """Generate and compile one standalone Verilator model under directory."""
    verilator_root = Path(env.get("VERILATOR_ROOT", r"C:\oss-cad-suite\oss-cad-suite\share\verilator"))
    verilator = shutil.which(env.get("VERILATOR", "verilator_bin"), path=env.get("PATH"))
    if not verilator:
        candidate = verilator_root.parent / "bin" / "verilator_bin.exe"
        if candidate.is_file():
            verilator = str(candidate)
    if not verilator or not verilator_root.is_dir():
        raise ValueError("Verilator C++ simulator and runtime are required")

    compiler = shutil.which(env.get("CXX", "g++"), path=env.get("PATH"))
    local_gxx = Path(r"C:\msys64\mingw64\bin\g++.exe")
    if not compiler and local_gxx.is_file():
        compiler = str(local_gxx)
    if not compiler:
        raise ValueError("g++ is required to build the accelerated Verilator simulator")

    directory.mkdir(parents=True, exist_ok=True)
    model_dir = directory / "verilator_model"
    if not model_dir.resolve().is_relative_to(directory.resolve()):
        raise ValueError("refusing to replace model directory outside build output")

    def tool_version(executable: str) -> str:
        result = subprocess.run([executable, "--version"], cwd=root, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=20, check=False)
        if result.returncode:
            raise ValueError(f"could not identify simulator tool version: {executable}")
        return result.stdout.strip().splitlines()[0]

    cache_data = {
        "schema": 1,
        "top": top,
        "parameters": parameters,
        "sources": [
            {"path": str(source.resolve().relative_to(root.resolve())),
             "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
            for source in sources
        ],
        "verilator": {"path": str(Path(verilator).resolve()),
                      "version": tool_version(verilator)},
        "compiler": {"path": str(Path(compiler).resolve()),
                     "version": tool_version(compiler)},
        "verilator_root": str(verilator_root.resolve()),
        "build_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    cache_key = hashlib.sha256(json.dumps(cache_data, sort_keys=True).encode()).hexdigest()
    cache_manifest = directory / "verilator_cache.json"
    binary = model_dir / f"V{top}.exe"
    if cache_manifest.is_file() and binary.is_file():
        try:
            cached = json.loads(cache_manifest.read_text(encoding="utf-8"))
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            if cached.get("key") == cache_key and cached.get("binary_sha256") == digest:
                print(f"Using cached accelerated {top} model", flush=True)
                return binary
        except (OSError, json.JSONDecodeError):
            pass
    if model_dir.exists():
        shutil.rmtree(model_dir)
    model_dir.mkdir(parents=True)
    build_env = env.copy()
    build_env["VERILATOR_ROOT"] = str(verilator_root)
    local_msys_bin = Path(r"C:\msys64\mingw64\bin")
    if local_msys_bin.is_dir():
        build_env["PATH"] = str(local_msys_bin) + os.pathsep + build_env.get("PATH", "")

    command = [verilator, "--cc", "--exe", "--main", "--timing", "--top-module", top,
               "-Wno-fatal", "--Mdir", str(model_dir)]
    command.extend(f"-G{name}={value}" for name, value in parameters.items())
    command.extend(str(path) for path in sources)
    print(f"Generating accelerated {top} model", flush=True)
    result = subprocess.run(command, cwd=root, env=build_env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, timeout=600)
    (directory / "verilator.log").write_text(result.stdout, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Verilator model generation failed:\n{result.stdout[-6000:]}")

    classes_file = model_dir / f"V{top}_classes.mk"
    lines = classes_file.read_text(encoding="utf-8").splitlines()
    class_names: list[str] = []
    reading = False
    for line in lines:
        if line.startswith(("VM_CLASSES_FAST +=", "VM_CLASSES_SLOW +=",
                            "VM_SUPPORT_FAST +=", "VM_SUPPORT_SLOW +=")):
            reading = True
            continue
        if reading:
            if not line.strip():
                reading = False
                continue
            class_names.extend(line.replace("\\", "").split())
    if not class_names:
        raise RuntimeError("Verilator produced no C++ class list")

    generated = [str(model_dir / f"{name}.cpp") for name in class_names]
    runtime = [str(verilator_root / "include" / name)
               for name in ("verilated.cpp", "verilated_timing.cpp", "verilated_threads.cpp")]
    compile_args = [compiler, "-std=gnu++17", "-O2", "-fcoroutines", "-DVL_TIME_CONTEXT",
                    "-DVERILATOR=1", "-DVM_COVERAGE=0", "-DVM_SC=0", "-DVM_TIMING=1",
                    "-DVM_TRACE=0", "-DVM_TRACE_FST=0", "-DVM_TRACE_VCD=0",
                    "-DVM_TRACE_SAIF=0", "-DVM_VPI=0", f"-I{model_dir}",
                    f"-I{verilator_root / 'include'}", f"-I{verilator_root / 'include' / 'vltstd'}",
                    *generated, *runtime, "-pthread", "-lpthread", "-latomic", "-o", str(binary)]
    print(f"Compiling accelerated model ({len(generated)} translation units)", flush=True)
    with (directory / "cxx_compile.log").open("wb") as log:
        compiled = subprocess.run(compile_args, cwd=model_dir, env=build_env,
                                  stdout=log, stderr=subprocess.STDOUT, timeout=900)
    if compiled.returncode or not binary.is_file():
        output = (directory / "cxx_compile.log").read_text(encoding="utf-8", errors="replace")
        raise RuntimeError(f"C++ model compile failed:\n{output[-6000:]}")
    cache_manifest.write_text(json.dumps({
        "key": cache_key,
        "inputs": cache_data,
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
    }, indent=2) + "\n", encoding="utf-8")
    return binary

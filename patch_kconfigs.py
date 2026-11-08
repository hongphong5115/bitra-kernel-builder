import os, re, sys

print("=== Running Bitra Kernel Source & Kconfig Patcher ===")

# 1. Neutralize gcc-wrapper.py in Makefile
if os.path.exists("Makefile"):
    with open("Makefile", "r", encoding="utf-8", errors="ignore") as f:
        makefile_content = f.read()
    if "scripts/gcc-wrapper.py" in makefile_content:
        makefile_content = re.sub(
            r"CC\s*=\s*\$\(PYTHON\)\s*\$\(srctree\)/scripts/gcc-wrapper\.py\s*\$\(REAL_CC\)",
            "CC\t\t= $(REAL_CC)",
            makefile_content
        )
        with open("Makefile", "w", encoding="utf-8") as f:
            f.write(makefile_content)
        print("Patched Makefile: CC = $(REAL_CC)")

# 2. Rewrite scripts/gcc-wrapper.py as pass-through runner
os.makedirs("scripts", exist_ok=True)
with open("scripts/gcc-wrapper.py", "w", encoding="utf-8") as f:
    f.write("#! /usr/bin/env python3\nimport sys, subprocess\nsys.exit(subprocess.call(sys.argv[1:]))\n")
try:
    os.chmod("scripts/gcc-wrapper.py", 0o755)
except Exception:
    pass
print("Rewrote scripts/gcc-wrapper.py as pass-through")

# 3. Fix broken awk logic in OplusKernelEnvConfig.mk
if os.path.exists("OplusKernelEnvConfig.mk"):
    with open("OplusKernelEnvConfig.mk", "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    new_lines = []
    skip = False
    for line in lines:
        if "OPLUS_FEATURE_POWERINFO_STANDBY" in line:
            skip = not skip # toggle block skip
            continue
        if not skip:
            new_lines.append(line)
    with open("OplusKernelEnvConfig.mk", "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    print("Cleaned OplusKernelEnvConfig.mk powerinfo block")

# 4. Remove OEM gitlinks if they exist
for dummy in ["kernel/sched_assist", "kernel/tuning"]:
    if os.path.exists(dummy):
        if os.path.isdir(dummy) and not os.path.islink(dummy):
            import shutil
            shutil.rmtree(dummy, ignore_errors=True)
        else:
            try:
                os.remove(dummy)
            except Exception:
                pass
        print(f"Removed dummy gitlink: {dummy}")

# 5. Universal Kconfig scanner
# Refined regex: must match 'source' followed by quotes OR a path containing '/'
pattern = re.compile(r"^(\s*)source\s+(\"([^\"]+)\"|'([^']+)'|([a-zA-Z0-9_\-.]+\/[a-zA-Z0-9_\-./]+))")

disabled_count = 0
for root, dirs, files in os.walk("."):
    for f in files:
        if "Kconfig" in f:
            fp = os.path.join(root, f)
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as kfile:
                    klines = kfile.readlines()
                changed = False
                out_lines = []
                for kline in klines:
                    m = pattern.match(kline)
                    if m:
                        indent = m.group(1)
                        target = m.group(3) or m.group(4) or m.group(5)
                        
                        # CRITICAL: NEVER disable runtime Kconfig variables like $(SRCARCH) or $(ARCH)
                        if "$" in target:
                            out_lines.append(kline)
                            continue
                            
                        # Check relative to repo root or relative to current Kconfig file
                        if not os.path.exists(target) and not os.path.exists(os.path.join(root, target)):
                            print(f"Disabled missing OEM Kconfig in {fp}: {target}")
                            out_lines.append(f"{indent}# source \"{target}\" # disabled missing OEM Kconfig\n")
                            changed = True
                            disabled_count += 1
                            continue
                    out_lines.append(kline)
                if changed:
                    with open(fp, "w", encoding="utf-8") as kfile:
                        kfile.writelines(out_lines)
            except Exception as e:
                pass

print(f"Universal Kconfig scanner completed. Total missing OEM sources disabled: {disabled_count}")

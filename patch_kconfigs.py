import os, re, sys

print("=== Running Bitra Kernel Source, Kconfig & Makefile Patcher ===")

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

# 4. Remove OEM dummy gitlinks if they exist
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

# 6. Universal Makefile scanner for missing OEM subdirectories
mf_fixed_count = 0
for root, dirs, files in os.walk("."):
    for f in files:
        if f in ["Makefile", "Kbuild"]:
            mf_path = os.path.join(root, f)
            try:
                with open(mf_path, "r", encoding="utf-8", errors="ignore") as mfile:
                    mlines = mfile.readlines()
                mchanged = False
                out_mlines = []
                for mline in mlines:
                    m = re.search(r"^\s*obj-[^+=]*\+=\s*([a-zA-Z0-9_\-]+)/", mline)
                    if m:
                        subdir = m.group(1)
                        full_subdir = os.path.join(root, subdir)
                        if not os.path.exists(full_subdir):
                            if subdir == "osdcardfs" and os.path.exists(os.path.join(root, "sdcardfs")):
                                out_mlines.append(mline.replace("osdcardfs/", "sdcardfs/"))
                                print(f"Redirected osdcardfs/ -> sdcardfs/ in {mf_path}")
                                mchanged = True
                                mf_fixed_count += 1
                                continue
                            else:
                                out_mlines.append(f"# {mline.strip()} # disabled missing OEM subdir\n")
                                print(f"Disabled missing OEM subdir: {subdir}/ in {mf_path}")
                                mchanged = True
                                mf_fixed_count += 1
                                continue
                    out_mlines.append(mline)
                if mchanged:
                    with open(mf_path, "w", encoding="utf-8") as mfile:
                        mfile.writelines(out_mlines)
            except Exception as e:
                pass

print(f"Universal Makefile scanner completed. Total missing OEM subdirs fixed: {mf_fixed_count}")

# 7. Comment out any missing healthinfo includes across the tree
hi_count = 0
for root, dirs, files in os.walk("."):
    for f in files:
        if f.endswith(".c") or f.endswith(".h"):
            c_path = os.path.join(root, f)
            try:
                with open(c_path, "r", encoding="utf-8", errors="ignore") as cf:
                    ccontent = cf.read()
                if "linux/healthinfo/" in ccontent:
                    ccontent = re.sub(r'#include\s*<linux/healthinfo/[^>]+>', '// [DISABLED MISSING OEM HEADER]', ccontent)
                    with open(c_path, "w", encoding="utf-8") as cf:
                        cf.write(ccontent)
                    print(f"Disabled missing healthinfo include in {c_path}")
                    hi_count += 1
            except Exception:
                pass
print(f"Disabled missing healthinfo includes: {hi_count}")

# 8. Fix Realme broken syntax in fs/pstore/ram.c
if os.path.exists("fs/pstore/ram.c"):
    with open("fs/pstore/ram.c", "r", encoding="utf-8", errors="ignore") as f:
        ramc = f.read()
    ramc = re.sub(
        r"if\s*\(!pdata->mem_size\s*\|\|\s*\(!pdata->record_size\s*&&[\s\S]*?!pdata->device_info_size\)\)\s*\{[\s\S]*?#endif[^\n]*",
        "if (!pdata->mem_size || (!pdata->record_size && !pdata->console_size && !pdata->ftrace_size && !pdata->pmsg_size)) {",
        ramc
    )
    ramc = re.sub(
        r"dump_mem_sz\s*=\s*cxt->size\s*-\s*cxt->console_size\s*-\s*cxt->ftrace_size[\s\S]*?#endif[^\n]*",
        "dump_mem_sz = cxt->size - cxt->console_size - cxt->ftrace_size - cxt->pmsg_size;",
        ramc
    )
    with open("fs/pstore/ram.c", "w", encoding="utf-8") as f:
        f.write(ramc)
    print("Fixed fs/pstore/ram.c syntax")

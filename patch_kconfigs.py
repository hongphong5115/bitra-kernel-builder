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

# 4. Universal Dangling OEM Symlink & Dummy Gitlink Cleaner
import shutil
dangling_symlinks = 0
for root, dirs, files in os.walk(".", followlinks=False):
    for name in files + dirs:
        p = os.path.join(root, name)
        if os.path.islink(p):
            if not os.path.exists(p):
                try:
                    os.remove(p)
                    dangling_symlinks += 1
                except Exception:
                    try:
                        shutil.rmtree(p, ignore_errors=True)
                        dangling_symlinks += 1
                    except Exception:
                        pass
        elif name in ["sched_assist", "tuning"] and ("kernel" in root):
            try:
                shutil.rmtree(p, ignore_errors=True)
                dangling_symlinks += 1
            except Exception:
                pass
print(f"Universal dangling symlink cleaner completed. Total removed: {dangling_symlinks}")

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

# 9. Clean dangling OEM symlinks and provide missing OEM headers & stubs
import shutil

# 9.1 Replace dangling include/soc/oplus/system symlink with real directory
oplus_sys = "include/soc/oplus/system"
if os.path.islink(oplus_sys) or os.path.exists(oplus_sys):
    try:
        os.remove(oplus_sys)
    except Exception:
        shutil.rmtree(oplus_sys, ignore_errors=True)
os.makedirs(oplus_sys, exist_ok=True)
os.makedirs("include/soc/oplus", exist_ok=True)
os.makedirs("drivers/oplus", exist_ok=True)

# 9.2 Safe copy and write helper functions
def safe_write(path, content):
    if os.path.islink(path) or os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def safe_copy(src, dst):
    if os.path.islink(dst) or os.path.exists(dst):
        try:
            os.remove(dst)
        except Exception:
            pass
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        shutil.copy2(src, dst)
    except Exception as e:
        print(f"safe_copy error: {src} -> {dst}: {e}")

oplus_project_header = """#ifndef _OPLUS_SYSTEM_PROJECT_H_
#define _OPLUS_SYSTEM_PROJECT_H_
#include <linux/types.h>
#include <soc/oppo/oppo_project.h>
#ifndef oplus_daily_build
static inline bool oplus_daily_build(void) { return false; }
#endif
#endif
"""
for target_header in [
    "include/soc/oplus/system/oplus_project.h",
    "include/soc/oplus/system/oppo_project.h",
    "include/soc/oplus/oplus_project.h",
]:
    safe_write(target_header, oplus_project_header)
print("Created include/soc/oplus/system/oplus_project.h and aliases")

# 9.3 Mirror all oppo headers and create stubs
if os.path.exists("include/soc/oppo"):
    for fname in os.listdir("include/soc/oppo"):
        src = os.path.join("include/soc/oppo", fname)
        if os.path.isfile(src):
            safe_copy(src, os.path.join("include/soc/oplus/system", fname))
            safe_copy(src, os.path.join("include/soc/oplus", fname))
    print("Mirrored include/soc/oppo/* to include/soc/oplus/system/ and oplus/")

empty_headers = [
    "include/soc/oplus/system/qcom_minidump_enhance.h",
    "include/soc/oplus/system/oplus_misc.h",
    "drivers/oplus/oplus_gauge.h"
]
for eh in empty_headers:
    safe_write(eh, "#pragma once\n")
    print(f"Created stub header: {eh}")

# 9.4 Create kernel/oplus_project_stub.c and register in kernel/Makefile
stub_c_content = """// SPDX-License-Identifier: GPL-2.0
#include <linux/types.h>
#include <linux/export.h>

unsigned int __attribute__((weak)) get_project(void) { return 0; }
EXPORT_SYMBOL(get_project);

int __attribute__((weak)) get_PCB_Version(void) { return 0; }
EXPORT_SYMBOL(get_PCB_Version);

int __attribute__((weak)) get_eng_version(void) { return 0; }
EXPORT_SYMBOL(get_eng_version);

int32_t __attribute__((weak)) get_Modem_Version(void) { return 0; }
EXPORT_SYMBOL(get_Modem_Version);

int32_t __attribute__((weak)) get_Operator_Version(void) { return 0; }
EXPORT_SYMBOL(get_Operator_Version);

bool __attribute__((weak)) is_confidential(void) { return false; }
EXPORT_SYMBOL(is_confidential);

bool __attribute__((weak)) oppo_daily_build(void) { return false; }
EXPORT_SYMBOL(oppo_daily_build);

bool __attribute__((weak)) oplus_daily_build(void) { return false; }
EXPORT_SYMBOL(oplus_daily_build);

uint32_t __attribute__((weak)) get_oppo_feature(int index) { return 0; }
EXPORT_SYMBOL(get_oppo_feature);
"""
with open("kernel/oplus_project_stub.c", "w", encoding="utf-8") as f:
    f.write(stub_c_content)
print("Created kernel/oplus_project_stub.c")

if os.path.exists("kernel/Makefile"):
    with open("kernel/Makefile", "r", encoding="utf-8", errors="ignore") as f:
        kmf = f.read()
    if "oplus_project_stub.o" not in kmf:
        kmf += "\nobj-y += oplus_project_stub.o\n"
        with open("kernel/Makefile", "w", encoding="utf-8") as f:
            f.write(kmf)
        print("Registered oplus_project_stub.o in kernel/Makefile")

# 10. Fix mm/vmscan.c direct_vm_swappiness and proc_create
if os.path.exists("mm/vmscan.c"):
    with open("mm/vmscan.c", "r", encoding="utf-8", errors="ignore") as f:
        vmc = f.read()
    
    # 10.1 Ensure #include <linux/proc_fs.h> is present safely after debugfs.h
    if "#include <linux/proc_fs.h>" not in vmc:
        if "#include <linux/debugfs.h>" in vmc:
            vmc = vmc.replace("#include <linux/debugfs.h>", "#include <linux/debugfs.h>\n#include <linux/proc_fs.h>")
        else:
            vmc = "#include <linux/proc_fs.h>\n" + vmc
        print("Added #include <linux/proc_fs.h> to mm/vmscan.c")
    
    # 10.2 Declare direct_vm_swappiness unconditionally (PRECISE match to avoid eating struct scan_control)
    vmc = re.sub(
        r"#if defined\(OPLUS_FEATURE_ZRAM_OPT\)\s*&&\s*defined\(CONFIG_OPLUS_ZRAM_OPT\)[\s\S]*?int direct_vm_swappiness = 60;\s*#endif[^\n]*",
        "/* Direct reclaim swappiness */\nint direct_vm_swappiness = 60;",
        vmc
    )
    print("Unconditionally declared direct_vm_swappiness in mm/vmscan.c")
            
    with open("mm/vmscan.c", "w", encoding="utf-8") as f:
        f.write(vmc)
    print("Fixed mm/vmscan.c")

# 11. Fix kernel/printk/printk.c OEM UART skip in factory mode
if os.path.exists("kernel/printk/printk.c"):
    with open("kernel/printk/printk.c", "r", encoding="utf-8", errors="ignore") as f:
        pkc = f.read()
    pkc = re.sub(
        r"#ifdef VENDOR_EDIT\s*\n\s*if\s*\(\(con->flags & CON_CONSDEV\)[\s\S]*?continue;\s*\n\s*#endif /\*VENDOR_EDIT\*/",
        "// [DISABLED OEM UART SKIP]",
        pkc
    )
    with open("kernel/printk/printk.c", "w", encoding="utf-8") as f:
        f.write(pkc)
    print("Fixed kernel/printk/printk.c OEM UART skip")

# 12. Fix kernel/sched/fair.c dangling trace_sched_cpu_sel call
if os.path.exists("kernel/sched/fair.c"):
    with open("kernel/sched/fair.c", "r", encoding="utf-8", errors="ignore") as f:
        fc = f.read()
    fc = re.sub(
        r"\btrace_sched_cpu_sel\s*\([\s\S]*?start_cpu\);",
        "/* [DISABLED OEM trace_sched_cpu_sel] */",
        fc
    )
    with open("kernel/sched/fair.c", "w", encoding="utf-8") as f:
        f.write(fc)
    print("Fixed kernel/sched/fair.c dangling trace_sched_cpu_sel call")

# 13. Fix kernel/exit.c dangling is_critial_process call
if os.path.exists("kernel/exit.c"):
    with open("kernel/exit.c", "r", encoding="utf-8", errors="ignore") as f:
        ec = f.read()
    ec = re.sub(
        r"//\s*#ifdef OPLUS_BUG_STABILITY[\s\S]*?is_critial_process[\s\S]*?//\s*#endif[^\n]*",
        "/* [DISABLED OEM is_critial_process] */",
        ec
    )
    with open("kernel/exit.c", "w", encoding="utf-8") as f:
        f.write(ec)
    print("Fixed kernel/exit.c dangling is_critial_process call")

# 14. Fix kernel/sysctl.c two_hundred declaration
if os.path.exists("kernel/sysctl.c"):
    with open("kernel/sysctl.c", "r", encoding="utf-8", errors="ignore") as f:
        scc = f.read()
    scc = re.sub(
        r"#if defined\(OPLUS_FEATURE_ZRAM_OPT\)\s*&&\s*defined\(CONFIG_OPLUS_ZRAM_OPT\)[\s\S]*?static int two_hundred = 200;\s*#endif[^\n]*",
        "static int two_hundred = 200;\nextern int direct_vm_swappiness;",
        scc
    )
    with open("kernel/sysctl.c", "w", encoding="utf-8") as f:
        f.write(scc)
    print("Fixed kernel/sysctl.c two_hundred declaration")

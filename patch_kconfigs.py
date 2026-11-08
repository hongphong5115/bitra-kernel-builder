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

# 6. Universal Makefile scanner for missing OEM subdirectories & missing source objects
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
                whole_file = "".join(mlines)
                for mline in mlines:
                    # 6.1 Check subdirectories
                    m = re.search(r"^\s*obj-[^+=]*\+=\s*([a-zA-Z0-9_\-/]+)/", mline)
                    if m:
                        subdir = m.group(1)
                        full_subdir = os.path.join(root, subdir)
                        has_mk = os.path.exists(os.path.join(full_subdir, "Makefile")) or os.path.exists(os.path.join(full_subdir, "Kbuild"))
                        if not os.path.exists(full_subdir) or not has_mk:
                            if subdir == "osdcardfs" and os.path.exists(os.path.join(root, "sdcardfs")):
                                out_mlines.append(mline.replace("osdcardfs/", "sdcardfs/"))
                                print(f"Redirected osdcardfs/ -> sdcardfs/ in {mf_path}")
                                mchanged = True
                                mf_fixed_count += 1
                                continue
                            else:
                                out_mlines.append(f"# {mline.strip()} # disabled missing OEM subdir or Makefile\n")
                                print(f"Disabled missing OEM subdir: {subdir}/ in {mf_path}")
                                mchanged = True
                                mf_fixed_count += 1
                                continue
                    
                    # 6.2 Check individual missing object files (dangling OEM .c files)
                    m_obj_line = re.search(r"^\s*obj-[^+=]*\+=\s*(.*)", mline)
                    if m_obj_line and not m:
                        tokens = m_obj_line.group(1).split()
                        has_missing = False
                        new_tokens = []
                        for token in tokens:
                            if token.endswith(".o"):
                                base = token[:-2]
                                c_src = os.path.join(root, base + ".c")
                                s_src = os.path.join(root, base + ".S")
                                s2_src = os.path.join(root, base + ".s")
                                is_comp = (f"{base}-objs" in whole_file) or (f"{base}-y" in whole_file) or (f"{base}-" in whole_file)
                                is_gen = any(k in base for k in ["devpts", "defkeymap", "consolemap", "logo_", "vdso", "kvm", "capflags", "kexec", "vsyscall"]) or any(k in root.replace('\\', '/') for k in ["drivers/tty/vt", "drivers/video/logo", "fs/devpts", "arch/arm64/kvm", "arch/x86"])
                                if not os.path.exists(c_src) and not os.path.exists(s_src) and not os.path.exists(s2_src) and not is_comp and not is_gen:
                                    has_missing = True
                                    print(f"Disabled missing OEM source obj: {token} in {mf_path}")
                                    continue
                            new_tokens.append(token)
                        if has_missing:
                            mchanged = True
                            mf_fixed_count += 1
                            if new_tokens:
                                prefix = mline[:m_obj_line.start(1)]
                                out_mlines.append(prefix + " ".join(new_tokens) + "\n")
                            else:
                                out_mlines.append(f"# {mline.strip()} # disabled all missing sources\n")
                            continue
                            
                    out_mlines.append(mline)
                if mchanged:
                    with open(mf_path, "w", encoding="utf-8") as mfile:
                        mfile.writelines(out_mlines)
            except Exception as e:
                pass

print(f"Universal Makefile scanner completed. Total missing OEM targets fixed: {mf_fixed_count}")

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
if os.path.islink(oplus_sys) and not os.path.exists(oplus_sys):
    try:
        os.remove(oplus_sys)
    except Exception:
        pass
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
    if not os.path.exists(target_header):
        safe_write(target_header, oplus_project_header)
print("Ensured include/soc/oplus/system/oplus_project.h and aliases exist")

# 9.3 Mirror all oppo headers and create stubs
if os.path.exists("include/soc/oppo"):
    for fname in os.listdir("include/soc/oppo"):
        src = os.path.join("include/soc/oppo", fname)
        if os.path.isfile(src):
            dst_sys = os.path.join("include/soc/oplus/system", fname)
            dst_op = os.path.join("include/soc/oplus", fname)
            if not os.path.exists(dst_sys):
                safe_copy(src, dst_sys)
            if not os.path.exists(dst_op):
                safe_copy(src, dst_op)
    print("Mirrored include/soc/oppo/* to include/soc/oplus/system/ and oplus/")

empty_headers = [
    "include/soc/oplus/system/qcom_minidump_enhance.h",
    "include/soc/oplus/system/oplus_misc.h",
    "drivers/oplus/oplus_gauge.h"
]
for eh in empty_headers:
    if not os.path.exists(eh):
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

# 15. Fix drivers/iio/adc/qcom-spmi-adc5.c battemp_for_adc field
if os.path.exists("drivers/iio/adc/qcom-spmi-adc5.c"):
    with open("drivers/iio/adc/qcom-spmi-adc5.c", "r", encoding="utf-8", errors="ignore") as f:
        adcc = f.read()
    adcc = adcc.replace(".battemp_for_adc = 1,", "/* .battemp_for_adc = 1 */")
    with open("drivers/iio/adc/qcom-spmi-adc5.c", "w", encoding="utf-8") as f:
        f.write(adcc)
    print("Fixed drivers/iio/adc/qcom-spmi-adc5.c battemp_for_adc field")

# 16. Fix net/oplus_nwpower/oplus_nwpower.c get_cached_platform_id / LAGOON
if os.path.exists("net/oplus_nwpower/oplus_nwpower.c"):
    with open("net/oplus_nwpower/oplus_nwpower.c", "r", encoding="utf-8", errors="ignore") as f:
        nwc = f.read()
    nwc = re.sub(
        r"bool bts_net_exist\(void\)\s*\{[\s\S]*?return bts_net_wakeup_buffer\[0\] == 0 \? false : true;\s*\}",
        "bool bts_net_exist(void)\n{\n\treturn bts_net_wakeup_buffer[0] == 0 ? false : true;\n}",
        nwc
    )
    with open("net/oplus_nwpower/oplus_nwpower.c", "w", encoding="utf-8") as f:
        f.write(nwc)
    print("Fixed net/oplus_nwpower/oplus_nwpower.c get_cached_platform_id")

# 17. Neutralize unbuildable proprietary ST laser autofocus driver (vl53L1)
# 17.1 Create stub header cam_cci_ctrl_interface.h in vl53L1/kona so any includes pass cleanly
vl53_kona_dir = "drivers/input/misc/vl53L1/kona"
if os.path.exists(vl53_kona_dir):
    stub_content = """#ifndef _CAM_CCI_CTRL_INTERFACE_H_
#define _CAM_CCI_CTRL_INTERFACE_H_
struct camera_cci_transfer {
    int cmd;
};
#define CAMERA_CCI_INIT 0
#define CAMERA_CCI_RELEASE 1
static inline int cam_cci_control_interface(struct camera_cci_transfer *p) { return 0; }
#endif
"""
    with open(os.path.join(vl53_kona_dir, "cam_cci_ctrl_interface.h"), "w", encoding="utf-8") as f:
        f.write(stub_content)
    print("Created stub cam_cci_ctrl_interface.h in drivers/input/misc/vl53L1/kona/")

# 17.2 Comment out vl53L1 in drivers/input/misc/Makefile
misc_mk = "drivers/input/misc/Makefile"
if os.path.exists(misc_mk):
    with open(misc_mk, "r", encoding="utf-8", errors="ignore") as f:
        mkc = f.read()
    mkc = re.sub(r"(\bobj-\$\(CONFIG_STMVL53L1\)\s*\+=\s*vl53L1/)", r"# \1", mkc)
    with open(misc_mk, "w", encoding="utf-8") as f:
        f.write(mkc)
    print("Disabled vl53L1 in drivers/input/misc/Makefile")

# 17.3 Disable CONFIG_STMVL53L1 in defconfigs
for defcfg in ["arch/arm64/configs/vendor/kona-perf_defconfig", "arch/arm64/configs/vendor/kona_defconfig"]:
    if os.path.exists(defcfg):
        with open(defcfg, "r", encoding="utf-8", errors="ignore") as f:
            dc = f.read()
        dc = re.sub(r"CONFIG_STMVL53L1=y", "CONFIG_STMVL53L1=n", dc)
        with open(defcfg, "w", encoding="utf-8") as f:
            f.write(dc)
        print(f"Disabled CONFIG_STMVL53L1 in {defcfg}")

# 18. Fix MMC host/card missing detect_change_retry and speed_class
# In Realme kernel, CONFIG_EMMC_SDCARD_OPTIMIZE expects detect_change_retry and speed_class in mmc_host / sd_ssr
if os.path.exists("include/linux/mmc/host.h"):
    with open("include/linux/mmc/host.h", "r", encoding="utf-8", errors="ignore") as f:
        hc = f.read()
    hc = re.sub(
        r"#ifdef\s+OPLUS_FEATURE_EMMC_SDCARD_OPTIMIZE\s*\n\s*int\s+detect_change_retry;\s*\n\s*#endif",
        "int detect_change_retry; /* Unconditional for CONFIG_EMMC_SDCARD_OPTIMIZE */",
        hc
    )
    with open("include/linux/mmc/host.h", "w", encoding="utf-8") as f:
        f.write(hc)
    print("Fixed include/linux/mmc/host.h detect_change_retry")

if os.path.exists("include/linux/mmc/card.h"):
    with open("include/linux/mmc/card.h", "r", encoding="utf-8", errors="ignore") as f:
        cc = f.read()
    cc = re.sub(
        r"#ifdef\s+OPLUS_FEATURE_EMMC_SDCARD_OPTIMIZE\s*\n\s*unsigned\s+int\s+speed_class;[^\n]*\n\s*#endif[^\n]*",
        "\tunsigned int\t\tspeed_class; /* Unconditional for CONFIG_EMMC_SDCARD_OPTIMIZE */",
        cc
    )
    with open("include/linux/mmc/card.h", "w", encoding="utf-8") as f:
        f.write(cc)
    print("Fixed include/linux/mmc/card.h speed_class")

if os.path.exists("drivers/mmc/core/Makefile"):
    with open("drivers/mmc/core/Makefile", "r", encoding="utf-8", errors="ignore") as f:
        mcc = f.read()
    if "OPLUS_FEATURE_EMMC_SDCARD_OPTIMIZE" not in mcc:
        mcc = "ccflags-y += -DOPLUS_FEATURE_EMMC_SDCARD_OPTIMIZE\n" + mcc
        with open("drivers/mmc/core/Makefile", "w", encoding="utf-8") as f:
            f.write(mcc)
        print("Added -DOPLUS_FEATURE_EMMC_SDCARD_OPTIMIZE to drivers/mmc/core/Makefile")

# 19. Fix drivers/nfc/nq-nci.c undeclared nci_reset_ntf and missing OPLUS_BUG_STABILITY
if os.path.exists("drivers/nfc/nq-nci.c"):
    with open("drivers/nfc/nq-nci.c", "r", encoding="utf-8", errors="ignore") as f:
        nc = f.read()
    if "#define OPLUS_BUG_STABILITY" not in nc:
        nc = "#define OPLUS_BUG_STABILITY 1\n" + nc
    nc = re.sub(
        r"ret\s*=\s*i2c_master_recv\s*\(\s*client\s*,\s*nci_reset_ntf\s*,\s*NCI_RESET_NTF_LEN\s*\);",
        "/* ret = i2c_master_recv(client, nci_reset_ntf, NCI_RESET_NTF_LEN); */",
        nc
    )
    with open("drivers/nfc/nq-nci.c", "w", encoding="utf-8") as f:
        f.write(nc)
    print("Fixed drivers/nfc/nq-nci.c OPLUS_BUG_STABILITY and nci_reset_ntf")

if os.path.exists("drivers/nfc/Makefile"):
    with open("drivers/nfc/Makefile", "r", encoding="utf-8", errors="ignore") as f:
        nmk = f.read()
    if "OPLUS_BUG_STABILITY" not in nmk:
        nmk = "ccflags-y += -DOPLUS_BUG_STABILITY\n" + nmk
        with open("drivers/nfc/Makefile", "w", encoding="utf-8") as f:
            f.write(nmk)
        print("Added -DOPLUS_BUG_STABILITY to drivers/nfc/Makefile")

# 20. Fix drivers/power/reset/msm-poweroff.c undeclared PON_RESTART_REASON_NORMAL
if os.path.exists("include/linux/input/qpnp-power-on.h"):
    with open("include/linux/input/qpnp-power-on.h", "r", encoding="utf-8", errors="ignore") as f:
        qpc = f.read()
    qpc = qpc.replace("#ifdef OPLUS_BUG_STABILITY\n/* Add for oplus boot mode*/", "/* Add for oplus boot mode*/")
    qpc = re.sub(r"(PON_RESTART_REASON_NORMAL\s*=\s*0x3E,)\s*\n#endif", r"\1", qpc)
    with open("include/linux/input/qpnp-power-on.h", "w", encoding="utf-8") as f:
        f.write(qpc)
    print("Fixed include/linux/input/qpnp-power-on.h PON_RESTART_REASON_NORMAL")

# 21. Fix drivers/power/supply/qcom/qpnp-fg-gen4.c undeclared batt_therm_chan in struct fg_gen4_chip
if os.path.exists("drivers/power/supply/qcom/qpnp-fg-gen4.c"):
    with open("drivers/power/supply/qcom/qpnp-fg-gen4.c", "r", encoding="utf-8", errors="ignore") as f:
        fgc = f.read()
    fgc = re.sub(
        r"#ifdef\s+OPLUS_FEATURE_CHG_BASIC\s*\n\s*struct\s+iio_channel\s*\*batt_therm_chan;\s*\n\s*#endif",
        "\tstruct iio_channel\t*batt_therm_chan; /* Unconditional for batt-therm channel */",
        fgc
    )
    with open("drivers/power/supply/qcom/qpnp-fg-gen4.c", "w", encoding="utf-8") as f:
        f.write(fgc)
    print("Fixed drivers/power/supply/qcom/qpnp-fg-gen4.c batt_therm_chan declaration")

# 22. Disable unbuildable proprietary UFSFEATURE / UFSPLUS add-on
# In Realme kernel, CONFIG_UFSFEATURE references missing UFSFEATURE_QUERY_OPCODE and creates static/non-static conflicts in ufshcd
for defcfg in ["arch/arm64/configs/vendor/kona-perf_defconfig", "arch/arm64/configs/vendor/kona_defconfig"]:
    if os.path.exists(defcfg):
        with open(defcfg, "r", encoding="utf-8", errors="ignore") as f:
            dc = f.read()
        dc = re.sub(r"CONFIG_UFSFEATURE=y", "CONFIG_UFSFEATURE=n", dc)
        dc = re.sub(r"CONFIG_UFSHPB=y", "CONFIG_UFSHPB=n", dc)
        dc = re.sub(r"CONFIG_UFSTW=y", "CONFIG_UFSTW=n", dc)
        dc = re.sub(r"CONFIG_UFSHID=y", "CONFIG_UFSHID=n", dc)
        dc = re.sub(r"CONFIG_OPLUS_ION_BOOSTPOOL=y", "CONFIG_OPLUS_ION_BOOSTPOOL=n", dc)
        with open(defcfg, "w", encoding="utf-8") as f:
            f.write(dc)
        print(f"Disabled CONFIG_UFSFEATURE & CONFIG_OPLUS_ION_BOOSTPOOL in {defcfg}")

if os.path.exists("drivers/scsi/ufs/Makefile"):
    with open("drivers/scsi/ufs/Makefile", "r", encoding="utf-8", errors="ignore") as f:
        umk = f.read()
    umk = re.sub(r"(\bobj-\$\(CONFIG_UFSFEATURE\)\s*\+=\s*ufsfeature\.o)", r"# \1", umk)
    umk = re.sub(r"(\bobj-\$\(CONFIG_UFSHPB\)\s*\+=\s*ufshpb\.o)", r"# \1", umk)
    umk = re.sub(r"(\bobj-\$\(CONFIG_UFSTW\)\s*\+=\s*ufstw\.o)", r"# \1", umk)
    umk = re.sub(r"(\bobj-\$\(CONFIG_UFSHID\)\s*\+=\s*ufshid\.o)", r"# \1", umk)
    with open("drivers/scsi/ufs/Makefile", "w", encoding="utf-8") as f:
        f.write(umk)
    print("Disabled ufsfeature in drivers/scsi/ufs/Makefile")

if os.path.exists("drivers/scsi/ufs/ufshcd.h"):
    with open("drivers/scsi/ufs/ufshcd.h", "r", encoding="utf-8", errors="ignore") as f:
        uhc = f.read()
    uhc = re.sub(
        r"#if defined\(CONFIG_UFSFEATURE\)[\s\S]*?#endif",
        "/* [DISABLED UFSFEATURE extern declarations] */",
        uhc
    )
    with open("drivers/scsi/ufs/ufshcd.h", "w", encoding="utf-8") as f:
        f.write(uhc)
    print("Neutralized UFSFEATURE declarations in drivers/scsi/ufs/ufshcd.h")

# 23. Fix drivers/staging/android/ion missing oplus_ion_boost_pool.h
ion_dir = "drivers/staging/android/ion"
if os.path.exists(ion_dir):
    stub_ion = """#ifndef _OPLUS_ION_BOOST_POOL_H_
#define _OPLUS_ION_BOOST_POOL_H_
#include <linux/types.h>
struct ion_boost_pool { int dummy; };
static inline struct ion_boost_pool *has_boost_pool(void *s, void *b) { return NULL; }
#endif
"""
    with open(os.path.join(ion_dir, "oplus_ion_boost_pool.h"), "w", encoding="utf-8") as f:
        f.write(stub_ion)
    print("Created stub drivers/staging/android/ion/oplus_ion_boost_pool.h")

if os.path.exists("drivers/staging/android/ion/ion_system_heap.c"):
    with open("drivers/staging/android/ion/ion_system_heap.c", "r", encoding="utf-8", errors="ignore") as f:
        ic = f.read()
    ic = re.sub(r'#ifdef\s+CONFIG_OPLUS_ION_BOOSTPOOL', '#if 0 /* DISABLED CONFIG_OPLUS_ION_BOOSTPOOL */', ic)
    # Define fallback for NR_IONCACHE_PAGES (when OPLUS_FEATURE_HEALTHINFO is disabled)
    if "NR_IONCACHE_PAGES" in ic and "#define NR_IONCACHE_PAGES" not in ic:
        ic = "#ifndef NR_IONCACHE_PAGES\n#define NR_IONCACHE_PAGES NR_FREE_PAGES\n#endif\n" + ic
    # Stub fill_pool_kworkthread to return 0 immediately instead of while-looping
    if "static int fill_pool_kworkthread(void *p)" in ic:
        ic = ic.replace(
            "static int fill_pool_kworkthread(void *p)\n{",
            "static int fill_pool_kworkthread(void *p)\n{\n\treturn 0;"
        )
    with open("drivers/staging/android/ion/ion_system_heap.c", "w", encoding="utf-8") as f:
        f.write(ic)
    print("Fixed drivers/staging/android/ion/ion_system_heap.c")

# 24. Create stub directory and headers for include/soc/oplus/system
sys_dir = "include/soc/oplus/system"
os.makedirs(sys_dir, exist_ok=True)

def write_stub_if_missing(filepath, content):
    if not os.path.exists(filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Created stub: {filepath}")
    else:
        print(f"Preserved existing OEM header: {filepath}")

# 24.1 kernel_fb.h
write_stub_if_missing(os.path.join(sys_dir, "kernel_fb.h"), """#ifndef _KERNEL_FB_H_
#define _KERNEL_FB_H_
#define FB_SENSOR 0
#define FB_SENSOR_ID_CRASH 0
static inline void set_subsys_crash_cause(const char *reason) {}
static inline int oplus_kevent_fb_str(int fb_type, int id, const char *reason) { return 0; }
#endif
""")

# 24.2 oplus_mm_kevent_fb.h
write_stub_if_missing(os.path.join(sys_dir, "oplus_mm_kevent_fb.h"), """#ifndef _OPLUS_MM_KEVENT_FB_H_
#define _OPLUS_MM_KEVENT_FB_H_
#define OPLUS_AUDIO_EVENTID_ADSP_CRASH 0
#define MM_FB_KEY_RATELIMIT_5MIN 0
#define OPLUS_MM_DIRVER_FB_EVENT_DISPLAY 0
static inline int mm_fb_audio_kevent_named(int event_id, int rate, const char *fmt, ...) { return 0; }
static inline int mm_fb_kevent(int event_id, const char *fmt, ...) { return 0; }
#endif
""")

# 24.3 boot_mode.h, oppo_project.h, oplus_project.h
if os.path.exists("include/soc/oppo/oppo_project.h"):
    with open("include/soc/oppo/oppo_project.h", "r", encoding="utf-8", errors="ignore") as f:
        opc = f.read()
    if "linux/types.h" not in opc:
        opc = "#include <linux/types.h>\n" + opc
    if "oplus_daily_build" not in opc:
        opc += "\n#define oplus_daily_build oppo_daily_build\n"
    with open("include/soc/oppo/oppo_project.h", "w", encoding="utf-8") as f:
        f.write(opc)
    print("Injected linux/types.h and oplus_daily_build alias to include/soc/oppo/oppo_project.h")

write_stub_if_missing(os.path.join(sys_dir, "boot_mode.h"), """#ifndef _SOC_OPLUS_BOOT_MODE_H_
#define _SOC_OPLUS_BOOT_MODE_H_
#include <linux/types.h>
#if __has_include(<soc/oppo/boot_mode.h>)
#include <soc/oppo/boot_mode.h>
#endif
#endif
""")

write_stub_if_missing(os.path.join(sys_dir, "oppo_project.h"), """#ifndef _SOC_OPLUS_OPPO_PROJECT_H_
#define _SOC_OPLUS_OPPO_PROJECT_H_
#include <linux/types.h>
#if __has_include(<soc/oppo/oppo_project.h>)
#include <soc/oppo/oppo_project.h>
#endif
#ifndef oplus_daily_build
#define oplus_daily_build oppo_daily_build
#endif
#endif
""")

write_stub_if_missing(os.path.join(sys_dir, "oplus_project.h"), """#ifndef _SOC_OPLUS_OPLUS_PROJECT_H_
#define _SOC_OPLUS_OPLUS_PROJECT_H_
#include <linux/types.h>
#if __has_include(<soc/oppo/oppo_project.h>)
#include <soc/oppo/oppo_project.h>
#endif
#ifndef oplus_daily_build
#define oplus_daily_build oppo_daily_build
#endif
#endif
""")

# 24.4 other stub headers
other_stubs = [
    ("hung_task_enhance.h", ""),
    ("oplus_brightscreen_check.h", ""),
    ("oplus_bscheck.h", ""),
    ("oplus_misc.h", ""),
    ("oplus_signal.h", ""),
    ("oplus_sync_time.h", ""),
    ("oppo_process.h", "static inline int is_critial_process(const char *comm) { return 0; }"),
    ("proc.h", ""),
    ("qcom_minidump_enhance.h", ""),
    ("uboot_utils.h", ""),
]

for hname, body in other_stubs:
    guard = "_" + hname.upper().replace(".", "_") + "_"
    target_path = os.path.join(sys_dir, hname)
    write_stub_if_missing(target_path, f"#ifndef {guard}\n#define {guard}\n{body}\n#endif\n")

print("Created all OEM stubs in include/soc/oplus/system/")

# Also neutralize kernel_fb in subsys-pil-tz.c
if os.path.exists("drivers/soc/qcom/subsys-pil-tz.c"):
    with open("drivers/soc/qcom/subsys-pil-tz.c", "r", encoding="utf-8", errors="ignore") as f:
        pzc = f.read()
    pzc = re.sub(r'#include\s*<soc/oplus/system/kernel_fb\.h>', '// #include <soc/oplus/system/kernel_fb.h>', pzc)
    pzc = re.sub(r'oplus_kevent_fb_str\([^;]*\);', '// oplus_kevent_fb_str;', pzc)
    with open("drivers/soc/qcom/subsys-pil-tz.c", "w", encoding="utf-8") as f:
        f.write(pzc)
    print("Neutralized kernel_fb calls in drivers/soc/qcom/subsys-pil-tz.c")

# 25. Fix drivers/soc/qcom/subsystem_restart.c missing OPLUS_BUG_STABILITY symbols
if os.path.exists("drivers/soc/qcom/subsystem_restart.c"):
    with open("drivers/soc/qcom/subsystem_restart.c", "r", encoding="utf-8", errors="ignore") as f:
        src = f.read()
    defs = """#define OPLUS_BUG_STABILITY 1
#include <linux/types.h>
#include <soc/oplus/system/oplus_project.h>
extern bool oem_is_fulldump(void);
"""
    if "#define OPLUS_BUG_STABILITY" not in src:
        src = defs + src
    with open("drivers/soc/qcom/subsystem_restart.c", "w", encoding="utf-8") as f:
        f.write(src)
    print("Injected OPLUS_BUG_STABILITY into drivers/soc/qcom/subsystem_restart.c")

# 26. Fix drivers/soc/qcom/socinfo.c unmatched brace in msm_read_hardware_id
if os.path.exists("drivers/soc/qcom/socinfo.c"):
    with open("drivers/soc/qcom/socinfo.c", "r", encoding="utf-8", errors="ignore") as f:
        soc_c = f.read()
    pattern = r'(\tif \(!cpu_of_id\[socinfo->v0_1\.id\]\.soc_id_string\)\s*goto err_path;\s*\n)#ifdef\s+OPLUS_ARCH_EXTENDS[\s\S]*?#endif\s*\n\s*ret = strlcat\(msm_soc_str, cpu_of_id\[socinfo->v0_1\.id\]\.soc_id_string,\s*\n\s*sizeof\(msm_soc_str\)\);\s*\n\s*\}'
    repl = r'''\1	ret = strlcat(msm_soc_str, cpu_of_id[socinfo->v0_1.id].soc_id_string,
			sizeof(msm_soc_str));'''
    soc_c = re.sub(pattern, repl, soc_c)
    with open("drivers/soc/qcom/socinfo.c", "w", encoding="utf-8") as f:
        f.write(soc_c)
    print("Fixed drivers/soc/qcom/socinfo.c syntax")

# 27. Fix drivers/soc/qcom/fsa4480-i2c.c missing dsi/dsi_display.h
if os.path.exists("drivers/soc/qcom/fsa4480-i2c.c"):
    with open("drivers/soc/qcom/fsa4480-i2c.c", "r", encoding="utf-8", errors="ignore") as f:
        fc = f.read()
    fc = re.sub(r'#include\s*["<]dsi/dsi_display\.h[">]', '// #include "dsi/dsi_display.h"', fc)
    fc = re.sub(
        r'struct dsi_display\s*\*display\s*=\s*get_main_display\(\);[\s\S]*?bool oplus_dp_support\s*=\s*[^;]+;',
        'bool oplus_dp_support = false;',
        fc
    )
    with open("drivers/soc/qcom/fsa4480-i2c.c", "w", encoding="utf-8") as f:
        f.write(fc)
    print("Fixed drivers/soc/qcom/fsa4480-i2c.c dsi dependency")

# 28. Fix drivers/staging/android/hans.c missing NETLINK_OPPO_HANS
if os.path.exists("include/uapi/linux/netlink.h"):
    with open("include/uapi/linux/netlink.h", "r", encoding="utf-8", errors="ignore") as f:
        nlc = f.read()
    nlc = re.sub(
        r"#ifdef\s+OPLUS_FEATURE_HANS_FREEZE\s*\n\s*#define\s+NETLINK_OPPO_HANS\s+(\d+)\s*[\s\S]*?#endif\s*/\*OPLUS_FEATURE_HANS_FREEZE\*/",
        r"#define NETLINK_OPPO_HANS \1",
        nlc
    )
    with open("include/uapi/linux/netlink.h", "w", encoding="utf-8") as f:
        f.write(nlc)
    print("Made NETLINK_OPPO_HANS unconditional in include/uapi/linux/netlink.h")

if os.path.exists("drivers/staging/android/hans.c"):
    with open("drivers/staging/android/hans.c", "r", encoding="utf-8", errors="ignore") as f:
        hc = f.read()
    if "#define NETLINK_OPPO_HANS" not in hc:
        hc = "#ifndef NETLINK_OPPO_HANS\n#define NETLINK_OPPO_HANS 29\n#endif\n" + hc
    with open("drivers/staging/android/hans.c", "w", encoding="utf-8") as f:
        f.write(hc)
    print("Injected NETLINK_OPPO_HANS into drivers/staging/android/hans.c")

if os.path.exists("include/linux/hans.h"):
    with open("include/linux/hans.h", "r", encoding="utf-8", errors="ignore") as f:
        hhc = f.read()
    if "#define NETLINK_OPPO_HANS" not in hhc:
        hhc = "#ifndef NETLINK_OPPO_HANS\n#define NETLINK_OPPO_HANS 29\n#endif\n" + hhc
    with open("include/linux/hans.h", "w", encoding="utf-8") as f:
        f.write(hhc)
    print("Injected NETLINK_OPPO_HANS into include/linux/hans.h")

# 29. Fix drivers/usb/pd/policy_engine.c undeclared pd_lobal
if os.path.exists("drivers/usb/pd/policy_engine.c"):
    with open("drivers/usb/pd/policy_engine.c", "r", encoding="utf-8", errors="ignore") as f:
        pec = f.read()
    pec = re.sub(
        r"#ifdef\s+OPLUS_FEATURE_CHG_BASIC\s*\n\s*struct\s+usbpd\s*\*pd_lobal;\s*\n\s*#endif",
        "struct usbpd *pd_lobal;",
        pec
    )
    pec = re.sub(
        r"#ifdef\s+OPLUS_FEATURE_CHG_BASIC\s*\n\s*pd_lobal\s*=\s*pd;\s*\n\s*#endif",
        "pd_lobal = pd;",
        pec
    )
    with open("drivers/usb/pd/policy_engine.c", "w", encoding="utf-8") as f:
        f.write(pec)
    print("Fixed drivers/usb/pd/policy_engine.c pd_lobal declaration")

# 30. Fix drivers/usb/pd/policy_engine.c missing oplus_wpc_set_wrx_en_value
if os.path.exists("drivers/usb/pd/policy_engine.c"):
    with open("drivers/usb/pd/policy_engine.c", "r", encoding="utf-8", errors="ignore") as f:
        pec = f.read()
    pec = re.sub(
        r"extern\s+void\s+oplus_wpc_set_wrx_en_value\s*\([^)]*\)\s*;",
        "void oplus_wpc_set_wrx_en_value(int value) {}\nEXPORT_SYMBOL(oplus_wpc_set_wrx_en_value);",
        pec
    )
    with open("drivers/usb/pd/policy_engine.c", "w", encoding="utf-8") as f:
        f.write(pec)
    print("Replaced extern oplus_wpc_set_wrx_en_value with implementation in policy_engine.c")

# 31. Fix kernel/panic_flush.c is_fulldump_enable
if os.path.exists("kernel/panic_flush.c"):
    with open("kernel/panic_flush.c", "r", encoding="utf-8", errors="ignore") as f:
        pfc = f.read()
    pfc = pfc.replace("extern bool is_fulldump_enable(void);", "bool __attribute__((weak)) is_fulldump_enable(void) { return false; }")
    if "is_fulldump_enable" not in pfc:
        pfc = "bool __attribute__((weak)) is_fulldump_enable(void) { return false; }\n" + pfc
    with open("kernel/panic_flush.c", "w", encoding="utf-8") as f:
        f.write(pfc)
    print("Defined is_fulldump_enable in kernel/panic_flush.c")

# 32. Fix drivers/power/supply/qcom/Makefile schgm-flash.o without smb5-lib
if os.path.exists("drivers/power/supply/qcom/Makefile"):
    with open("drivers/power/supply/qcom/Makefile", "r", encoding="utf-8", errors="ignore") as f:
        pmk = f.read()
    pmk = pmk.replace("schgm-flash.o", "")
    with open("drivers/power/supply/qcom/Makefile", "w", encoding="utf-8") as f:
        f.write(pmk)
    print("Removed schgm-flash.o from drivers/power/supply/qcom/Makefile")

# 33. Disable CONFIG_OPLUS_HANS & stub hans_check_frozen_transcation
for defcfg in ["arch/arm64/configs/vendor/kona-perf_defconfig", "arch/arm64/configs/vendor/kona_defconfig"]:
    if os.path.exists(defcfg):
        with open(defcfg, "r", encoding="utf-8", errors="ignore") as f:
            dc = f.read()
        dc = re.sub(r"CONFIG_OPLUS_HANS=y", "CONFIG_OPLUS_HANS=n", dc)
        with open(defcfg, "w", encoding="utf-8") as f:
            f.write(dc)

if os.path.exists("drivers/staging/android/Makefile"):
    with open("drivers/staging/android/Makefile", "r", encoding="utf-8", errors="ignore") as f:
        amk = f.read()
    amk = re.sub(r"(\bobj-\$\(CONFIG_OPLUS_HANS\)\s*\+=)", r"# \1", amk)
    with open("drivers/staging/android/Makefile", "w", encoding="utf-8") as f:
        f.write(amk)

if os.path.exists("drivers/staging/android/hans.c"):
    with open("drivers/staging/android/hans.c", "r", encoding="utf-8", errors="ignore") as f:
        hc = f.read()
    if "int hans_check_frozen_transcation" not in hc:
        hc += "\nint hans_check_frozen_transcation(void *t, void *p) { return 0; }\n"
        with open("drivers/staging/android/hans.c", "w", encoding="utf-8") as f:
            f.write(hc)

# 34. Fix include/linux/msm_drm_notify.h msm_drm_register_client
if os.path.exists("include/linux/msm_drm_notify.h"):
    with open("include/linux/msm_drm_notify.h", "r", encoding="utf-8", errors="ignore") as f:
        dhc = f.read()
    dhc = re.sub(
        r"#ifdef\s+CONFIG_DRM_MSM[\s\S]*?#endif",
        "static inline int msm_drm_register_client(struct notifier_block *nb) { return 0; }\nstatic inline int msm_drm_unregister_client(struct notifier_block *nb) { return 0; }",
        dhc
    )
    with open("include/linux/msm_drm_notify.h", "w", encoding="utf-8") as f:
        f.write(dhc)
    print("Inlined msm_drm_register_client in include/linux/msm_drm_notify.h")

# 35. Fix mm/vmscan.c kswapd_threads & drivers/soc/qcom/watchdog_v2.c cpu_idle_pc_state
if os.path.exists("mm/vmscan.c"):
    with open("mm/vmscan.c", "r", encoding="utf-8", errors="ignore") as f:
        vmc = f.read()
    vmc = re.sub(
        r"#ifndef CONFIG_OPLUS_MULTI_KSWAPD[\s\S]*?#endif\s*\/\*CONFIG_OPLUS_MULTI_KSWAPD\*\/",
        "#define DEF_KSWAPD_THREADS_PER_NODE 1\nint kswapd_threads = 1;\nint kswapd_threads_current = 1;",
        vmc
    )
    with open("mm/vmscan.c", "w", encoding="utf-8") as f:
        f.write(vmc)
    print("Fixed mm/vmscan.c kswapd_threads and kswapd_threads_current declaration")

if os.path.exists("drivers/soc/qcom/watchdog_v2.c"):
    with open("drivers/soc/qcom/watchdog_v2.c", "r", encoding="utf-8", errors="ignore") as f:
        wdc = f.read()
    wdc = wdc.replace("static int cpu_idle_pc_state[NR_CPUS];", "int cpu_idle_pc_state[NR_CPUS];")
    with open("drivers/soc/qcom/watchdog_v2.c", "w", encoding="utf-8") as f:
        f.write(wdc)
    print("Fixed drivers/soc/qcom/watchdog_v2.c cpu_idle_pc_state declaration")

# 36. Neutralize healthinfo in fs/proc/Makefile and defconfigs
if os.path.exists("fs/proc/Makefile"):
    with open("fs/proc/Makefile", "r", encoding="utf-8", errors="ignore") as f:
        pmf = f.read()
    pmf = re.sub(r'obj-y\s*\+=\s*healthinfo\/', '# obj-y += healthinfo/', pmf)
    pmf = re.sub(r'obj-y\s*\+=\s*task_cpustats\/', '# obj-y += task_cpustats/', pmf)
    with open("fs/proc/Makefile", "w", encoding="utf-8") as f:
        f.write(pmf)
    print("Neutralized healthinfo in fs/proc/Makefile")

for dc in [
    "arch/arm64/configs/vendor/kona-perf_defconfig",
    "arch/arm64/configs/vendor/kona_defconfig"
]:
    if os.path.exists(dc):
        with open(dc, "a", encoding="utf-8") as f:
            f.write("\nCONFIG_OPLUS_HEALTHINFO=n\nCONFIG_OPLUS_JANK_INFO=n\nCONFIG_DUMP_TASKS_MEM=n\nCONFIG_PROCESS_RECLAIM_ENHANCE=n\nCONFIG_VIRTUAL_RESERVE_MEMORY=n\nCONFIG_PHYSICAL_ANTI_FRAGMENTATION=n\nCONFIG_OPLUS_FEATURE_UXIO_FIRST=n\n")

# 37. Fix kswapd_unbind_cpu in kernel/sched/core.c and include/linux/swap.h
if os.path.exists("kernel/sched/core.c"):
    with open("kernel/sched/core.c", "r", encoding="utf-8", errors="ignore") as f:
        scc = f.read()
    if "int kswapd_unbind_cpu" not in scc:
        scc = scc.replace(
            "void upate_kswapd_unbind_cpu(void)",
            "int kswapd_unbind_cpu = -1;\nEXPORT_SYMBOL(kswapd_unbind_cpu);\nvoid upate_kswapd_unbind_cpu(void)"
        )
        with open("kernel/sched/core.c", "w", encoding="utf-8") as f:
            f.write(scc)
        print("Injected kswapd_unbind_cpu into kernel/sched/core.c")

if os.path.exists("include/linux/swap.h"):
    with open("include/linux/swap.h", "r", encoding="utf-8", errors="ignore") as f:
        swh = f.read()
    if "extern int kswapd_unbind_cpu;" not in swh:
        swh += "\nextern int kswapd_unbind_cpu;\n"
        with open("include/linux/swap.h", "w", encoding="utf-8") as f:
            f.write(swh)
        print("Injected extern kswapd_unbind_cpu into include/linux/swap.h")

# 38. Neutralize healthinfo, task_mem, process_mm_reclaim, reserve_area, and multi_freearea in mm/Makefile
if os.path.exists("mm/Makefile"):
    with open("mm/Makefile", "r", encoding="utf-8", errors="ignore") as f:
        mmf = f.read()
    mmf = re.sub(r'obj-y\s*\+=\s*healthinfo\/', '# obj-y += healthinfo/', mmf)
    mmf = re.sub(r'obj-y\s*\+=\s*task_mem\/', '# obj-y += task_mem/', mmf)
    mmf = re.sub(r'obj-\$\(CONFIG_DUMP_TASKS_MEM\)\s*\+=\s*task_mem\/', '# obj-$(CONFIG_DUMP_TASKS_MEM) += task_mem/', mmf)
    mmf = re.sub(r'obj-\$\(CONFIG_VIRTUAL_RESERVE_MEMORY\)\s*\+=\s*reserve_area\.o', '# obj-$(CONFIG_VIRTUAL_RESERVE_MEMORY) += reserve_area.o', mmf)
    mmf = re.sub(r'obj-\$\(CONFIG_PHYSICAL_ANTI_FRAGMENTATION\)\s*\+=\s*multi_freearea\.o', '# obj-$(CONFIG_PHYSICAL_ANTI_FRAGMENTATION) += multi_freearea.o', mmf)
    mmf = mmf.replace("process_mm_reclaim.o", "process_mm_reclaim_weak.o")
    with open("mm/Makefile", "w", encoding="utf-8") as f:
        f.write(mmf)
    print("Neutralized healthinfo, task_mem, reserve_area, multi_freearea, and switched to process_mm_reclaim_weak in mm/Makefile")

# 39. Neutralize special_opt in kernel/Makefile
if os.path.exists("kernel/Makefile"):
    with open("kernel/Makefile", "r", encoding="utf-8", errors="ignore") as f:
        kmf = f.read()
    kmf = re.sub(r'obj-y\s*\+=\s*special_opt\/', '# obj-y += special_opt/', kmf)
    with open("kernel/Makefile", "w", encoding="utf-8") as f:
        f.write(kmf)
    print("Neutralized special_opt in kernel/Makefile")

# 40. Neutralize uxio_first in block/Makefile
if os.path.exists("block/Makefile"):
    with open("block/Makefile", "r", encoding="utf-8", errors="ignore") as f:
        bmf = f.read()
    bmf = re.sub(r'obj-\$\(CONFIG_OPLUS_FEATURE_UXIO_FIRST\)\s*\+=\s*uxio_first\/', '# obj-$(CONFIG_OPLUS_FEATURE_UXIO_FIRST) += uxio_first/', bmf)
    with open("block/Makefile", "w", encoding="utf-8") as f:
        f.write(bmf)
    print("Neutralized uxio_first in block/Makefile")

# 41. Fix current_is_fg in drivers/block/zram/hybridswap/hybridswap_eswap.c
hs_path = "drivers/block/zram/hybridswap/hybridswap_eswap.c"
if os.path.exists(hs_path):
    with open(hs_path, "r", encoding="utf-8", errors="ignore") as f:
        hec = f.read()
    if "current_is_fg" in hec and "static inline int current_is_fg" not in hec:
        hec = "#define current_is_fg() (0)\n" + hec
        with open(hs_path, "w", encoding="utf-8") as f:
            f.write(hec)
        print("Injected current_is_fg fallback in hybridswap_eswap.c")

# 42. Fix unused variable ret2 in techpack/audio/asoc/codecs/ak4376/ak4376.c
ak_path = "techpack/audio/asoc/codecs/ak4376/ak4376.c"
if os.path.exists(ak_path):
    with open(ak_path, "r", encoding="utf-8", errors="ignore") as f:
        akc = f.read()
    akc = akc.replace("int ret = 0, ret2 = 0;", "int ret = 0, ret2 = 0;\n\t(void)ret2;")
    with open(ak_path, "w", encoding="utf-8") as f:
        f.write(akc)
    print("Fixed unused variable ret2 in ak4376.c")

# 43. Fix tfa98xx_v6.c speakerImpedance, np, and unused tfa98xx_parse_dt
tfa_path = "techpack/audio/asoc/codecs/tfa98xx-v6/tfa98xx_v6.c"
if os.path.exists(tfa_path):
    with open(tfa_path, "r", encoding="utf-8", errors="ignore") as f:
        tfac = f.read()
    tfac = tfac.replace(
        "#ifdef OPLUS_ARCH_EXTENDS\n\tint calibrate_done = 0;\n\tint speakerImpedance = 0;\n\t#endif /* OPLUS_ARCH_EXTENDS */",
        "\tint speakerImpedance = 0;\n#ifdef OPLUS_ARCH_EXTENDS\n\tint calibrate_done = 0;\n#endif"
    )
    tfac = tfac.replace(
        'pr_info("%s: addr=0x%x\\n", __func__, i2c->addr);',
        'pr_info("%s: addr=0x%x\\n", __func__, i2c->addr);\n\t(void)np;'
    )
    tfac = tfac.replace(
        "static int tfa98xx_parse_dt(",
        "static int __maybe_unused tfa98xx_parse_dt("
    )
    with open(tfa_path, "w", encoding="utf-8") as f:
        f.write(tfac)
    print("Fixed speakerImpedance, np, and tfa98xx_parse_dt in tfa98xx_v6.c")

# 44. Fix cam_cpas_hw.c num_camnoc_axi_ports
cpas_path = "techpack/camera/drivers/cam_cpas/cam_cpas_hw.c"
if os.path.exists(cpas_path):
    with open(cpas_path, "r", encoding="utf-8", errors="ignore") as f:
        cpasc = f.read()
    target_block = """\tif (soc_private->control_camnoc_axi_clk) {
\t\tCAM_INFO(CAM_CPAS, "applied camnoc axi clk[%lld]",
\t\t\tcpas_core->applied_camnoc_axi_rate);
\t} else {
\t\tfor (i = 0; i < cpas_core->num_camnoc_axi_ports; i++) {
\t\t\tCAM_INFO(CAM_CPAS,
\t\t\t\t"[%s] ab_bw[%lld] ib_bw[%lld] additional_bw[%lld] applied_ab[%lld] applied_ib[%lld]",
\t\t\t\tcpas_core->camnoc_axi_port[i].axi_port_name,
\t\t\t\tcpas_core->camnoc_axi_port[i].ab_bw,
\t\t\t\tcpas_core->camnoc_axi_port[i].ib_bw,
\t\t\t\tcpas_core->camnoc_axi_port[i].additional_bw,
\t\t\t\tcpas_core->camnoc_axi_port[i].applied_ab_bw,
\t\t\t\tcpas_core->camnoc_axi_port[i].applied_ib_bw);
\t\t}
\t}"""
    replacement_block = """#ifdef OPLUS_FEATURE_CAMERA_COMMON
\tif (soc_private->control_camnoc_axi_clk) {
\t\tCAM_INFO(CAM_CPAS, "applied camnoc axi clk[%lld]",
\t\t\tcpas_core->applied_camnoc_axi_rate);
\t} else {
\t\tfor (i = 0; i < cpas_core->num_camnoc_axi_ports; i++) {
\t\t\tCAM_INFO(CAM_CPAS,
\t\t\t\t"[%s] ab_bw[%lld] ib_bw[%lld] additional_bw[%lld] applied_ab[%lld] applied_ib[%lld]",
\t\t\t\tcpas_core->camnoc_axi_port[i].axi_port_name,
\t\t\t\tcpas_core->camnoc_axi_port[i].ab_bw,
\t\t\t\tcpas_core->camnoc_axi_port[i].ib_bw,
\t\t\t\tcpas_core->camnoc_axi_port[i].additional_bw,
\t\t\t\tcpas_core->camnoc_axi_port[i].applied_ab_bw,
\t\t\t\tcpas_core->camnoc_axi_port[i].applied_ib_bw);
\t\t}
\t}
#endif"""
    cpasc = cpasc.replace(target_block, replacement_block)
    with open(cpas_path, "w", encoding="utf-8") as f:
        f.write(cpasc)
    print("Fixed num_camnoc_axi_ports in cam_cpas_hw.c")

# 45. Fix KernelSU sucompat.c linux/pgtable.h on 4.19
for sucompat in [
    "drivers/kernelsu/feature/sucompat.c",
    "KernelSU-Next/kernel/feature/sucompat.c",
    "KernelSU/kernel/feature/sucompat.c"
]:
    if os.path.exists(sucompat):
        with open(sucompat, "r", encoding="utf-8", errors="ignore") as f:
            suc = f.read()
        if "#include <linux/pgtable.h>" in suc:
            suc = suc.replace(
                "#include <linux/pgtable.h>",
                "#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 10, 0)\n#include <linux/pgtable.h>\n#else\n#include <asm/pgtable.h>\n#endif"
            )
            with open(sucompat, "w", encoding="utf-8") as f:
                f.write(suc)
            print(f"Patched linux/pgtable.h in {sucompat}")

# 46. Fix unused temp in techpack/audio/soc/swr-mstr-ctrl.c
swr_path = "techpack/audio/soc/swr-mstr-ctrl.c"
if os.path.exists(swr_path):
    with open(swr_path, "r", encoding="utf-8", errors="ignore") as f:
        swrc = f.read()
    swrc = swrc.replace(
        "static void swrm_enable_slave_irq(struct swr_mstr_ctrl *swrm)\n{\n\tint i;\n\tint status = 0;\n\tu32 temp;",
        "static void swrm_enable_slave_irq(struct swr_mstr_ctrl *swrm)\n{\n\tint i;\n\tint status = 0;\n\tu32 __maybe_unused temp;"
    )
    with open(swr_path, "w", encoding="utf-8") as f:
        f.write(swrc)
    print("Fixed unused temp in swr-mstr-ctrl.c")

# 47. Fix trigger_id in techpack/camera/drivers/cam_req_mgr/cam_req_mgr_interface.h
crm_h_path = "techpack/camera/drivers/cam_req_mgr/cam_req_mgr_interface.h"
if os.path.exists(crm_h_path):
    with open(crm_h_path, "r", encoding="utf-8", errors="ignore") as f:
        crmh = f.read()
    target_crm = """struct cam_req_mgr_trigger_notify {
\tint32_t  link_hdl;
\tint32_t  dev_hdl;
\tint64_t  frame_id;
\tuint32_t trigger;
\tuint64_t sof_timestamp_val;
#ifdef OPLUS_FEATURE_CAMERA_COMMON
\tuint64_t req_id;
\tint32_t  trigger_id;
#endif
};"""
    repl_crm = """struct cam_req_mgr_trigger_notify {
\tint32_t  link_hdl;
\tint32_t  dev_hdl;
\tint64_t  frame_id;
\tuint32_t trigger;
\tuint64_t sof_timestamp_val;
\tint32_t  trigger_id;
#ifdef OPLUS_FEATURE_CAMERA_COMMON
\tuint64_t req_id;
#endif
};"""
    crmh = crmh.replace(target_crm, repl_crm)
    with open(crm_h_path, "w", encoding="utf-8") as f:
        f.write(crmh)
    print("Fixed trigger_id in cam_req_mgr_interface.h")

# 48. Fix cam_ois_core.c undeclared CAM_GET_OIS_EIS_HALL
ois_path = "techpack/camera/drivers/cam_sensor_module/cam_ois/cam_ois_core.c"
if os.path.exists(ois_path):
    with open(ois_path, "r", encoding="utf-8", errors="ignore") as f:
        oisc = f.read()
    target_ois = """#ifdef OPLUS_FEATURE_CAMERA_COMMON
       case CAM_GET_OIS_EIS_HALL:
       case CAM_WRITE_CALIBRATION_DATA:
       case CAM_WRITE_AE_SYNC_DATA:{
           rc = oplus_cam_ois_driver_cmd(o_ctrl,arg);
           if (rc < 0){
               goto release_mutex;
           }
           break;
       }
#endif"""
    repl_ois = """#if 0
       case CAM_GET_OIS_EIS_HALL:
       case CAM_WRITE_CALIBRATION_DATA:
       case CAM_WRITE_AE_SYNC_DATA:{
           rc = oplus_cam_ois_driver_cmd(o_ctrl,arg);
           if (rc < 0){
               goto release_mutex;
           }
           break;
       }
#endif"""
    oisc = oisc.replace(target_ois, repl_ois)
    with open(ois_path, "w", encoding="utf-8") as f:
        f.write(oisc)
    print("Fixed CAM_GET_OIS_EIS_HALL in cam_ois_core.c")















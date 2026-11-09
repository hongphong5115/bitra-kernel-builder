import os, re, sys

print("=== Running KernelSU-Next Patch for Linux 4.19 ===")

ksu_dir = "drivers/kernelsu"
if not os.path.exists(ksu_dir):
    print(f"Error: {ksu_dir} does not exist!")
    sys.exit(1)

# 1. Fix pgtable.h include for arm64 4.19
for root, dirs, files in os.walk(ksu_dir):
    for f in files:
        if f.endswith(('.c', '.h')):
            p = os.path.join(root, f)
            with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                c = fp.read()
            if "<linux/pgtable.h>" in c:
                c = c.replace("<linux/pgtable.h>", "<asm/pgtable.h>")
                with open(p, "w", encoding="utf-8") as fp:
                    fp.write(c)

# 2. Fix copy_to_kernel_nofault fallback for 4.19
for root, dirs, files in os.walk(ksu_dir):
    for f in files:
        if f.endswith(('.c', '.h')):
            p = os.path.join(root, f)
            with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                c = fp.read()
            if "copy_to_kernel_nofault" in c and "probe_kernel_write" not in c:
                c = "#include <linux/version.h>\n#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 8, 0)\n#define copy_to_kernel_nofault probe_kernel_write\n#endif\n" + c
                with open(p, "w", encoding="utf-8") as fp:
                    fp.write(c)

# 3. Fix KERNEL_VERSION(4, 14, 222) check
for root, dirs, files in os.walk(ksu_dir):
    for f in files:
        if f.endswith(('.c', '.h')):
            p = os.path.join(root, f)
            with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                c = fp.read()
            if "KERNEL_VERSION(4, 14, 222)" in c:
                c = c.replace("LINUX_VERSION_CODE >= KERNEL_VERSION(4, 14, 222)", "LINUX_VERSION_CODE >= KERNEL_VERSION(5, 1, 0)")
                with open(p, "w", encoding="utf-8") as fp:
                    fp.write(c)

# 4. Fix ksu_access_ok in compat/kernel_compat.c
compat_p = os.path.join(ksu_dir, "compat/kernel_compat.c")
if os.path.exists(compat_p):
    with open(compat_p, "r", encoding="utf-8", errors="ignore") as fp:
        c = fp.read()
    if "ksu_access_ok" not in c:
        c = "#include <linux/version.h>\n#include <linux/mm.h>\n#include <linux/slab.h>\n#include <linux/vmalloc.h>\n#include <linux/uaccess.h>\n#ifndef ksu_access_ok\n#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 0, 0)\n#define ksu_access_ok(addr, size) access_ok(addr, size)\n#else\n#define ksu_access_ok(addr, size) access_ok(VERIFY_READ, addr, size)\n#endif\n#endif\n" + c
        with open(compat_p, "w", encoding="utf-8") as fp:
            fp.write(c)

# 5. Fix TWA_RESUME / TWA_SIGNAL
for root, dirs, files in os.walk(ksu_dir):
    for f in files:
        if f.endswith(('.c', '.h')):
            p = os.path.join(root, f)
            with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                c = fp.read()
            if ("TWA_RESUME" in c or "task_work_add" in c) and "#ifndef TWA_RESUME" not in c:
                c = "#include <linux/version.h>\n#ifndef TWA_RESUME\n#define TWA_RESUME true\n#endif\n#ifndef TWA_NONE\n#define TWA_NONE false\n#endif\n#ifndef TWA_SIGNAL\n#define TWA_SIGNAL true\n#endif\n" + c
                with open(p, "w", encoding="utf-8") as fp:
                    fp.write(c)

# 6. Fix strncpy_from_user_nofault declaration
for root, dirs, files in os.walk(ksu_dir):
    for f in files:
        if f.endswith(('.c', '.h')):
            p = os.path.join(root, f)
            with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                c = fp.read()
            if "strncpy_from_user_nofault" in c and "long strncpy_from_user_nofault" not in c:
                c = "long strncpy_from_user_nofault(char *dst, const void __user *unsafe_addr, long count);\n" + c
                with open(p, "w", encoding="utf-8") as fp:
                    fp.write(c)

# 7. Patch drivers/kernelsu/Kbuild for Kprobes hook mode and composite linking
kbuild_p = os.path.join(ksu_dir, "Kbuild")
if os.path.exists(kbuild_p):
    with open(kbuild_p, "r", encoding="utf-8", errors="ignore") as fp:
        kc = fp.read()
    
    # Prepend mkdir for all subdirectories in $(obj) so out-of-tree builds (O=out) never fail with missing directory error
    mkdir_rule = "$(shell mkdir -p $(addprefix $(obj)/, core compat feature hook infra manager policy runtime selinux sulog supercall preinit))\n"
    if "mkdir -p $(addprefix $(obj)" not in kc:
        kc = mkdir_rule + kc

    # Force HAVE_KSU_HOOK := 0 so it never errors out on hook verification
    kc = re.sub(r'HAVE_KSU_HOOK\s*\?=\s*1', 'HAVE_KSU_HOOK := 0', kc)
    kc = re.sub(r'ifneq\s*\(\$\(HAVE_KSU_HOOK\),0\).*?endif', '# Hook check bypassed for Kprobes', kc, flags=re.DOTALL)
    
    # Set kernelsu-y and composite object linking so all kernelsu-objs are linked into built-in kernel
    if "kernelsu_core.o" not in kc:
        composite_rule = """
cmd_ksu_ld = $(LD) $(ld_flags) -r -o $@ $(filter-out FORCE,$^)
$(obj)/kernelsu_core.o: $(addprefix $(obj)/,$(kernelsu-objs)) FORCE
\t$(call if_changed,ksu_ld)
targets += $(obj)/kernelsu_core.o
obj-$(CONFIG_KSU) := kernelsu_core.o
kernelsu-y := $(kernelsu-objs)
"""
        kc = kc.replace("obj-$(CONFIG_KSU) += kernelsu.o", composite_rule)
    
    with open(kbuild_p, "w", encoding="utf-8") as fp:
        fp.write(kc)
    print("Patched drivers/kernelsu/Kbuild with mkdir, HAVE_KSU_HOOK=0 and composite kernelsu_core.o link rule")

print("=== KernelSU-Next Patch Complete ===")

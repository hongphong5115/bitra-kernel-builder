# Bitra (Realme GT Neo 2 5G) Kernel Builder: NoMount + SuSFS + APatch

This repository provides an automated GitHub Actions CI pipeline to build a monolithic Linux `4.19.157-perf+` kernel for the **Realme GT Neo 2 5G** (`bitra` / `RMX3370`, Snapdragon 870 `SM8250`) on **Android 13** (Realme UI 4.0 / ColorOS 13.1).

## Features Integrated
1. **NoMount Built-in (`CONFIG_NOMOUNT=y`)**:
   - Zero-mount VFS hijacking with zero entries in `/proc/self/mountinfo`.
   - Zero-footprint Keyring IPC returning `-ENOKEY` to eliminate the detection oracle.
   - RCU-walk safety and memory barrier fixes for clean teardown.
2. **SuSFS 4.19 (`CONFIG_KSU_SUSFS=y`)**:
   - Mount ID isolation & kernel kallsyms symbol filter (`nm_*`, `nomount_*`).
   - Concealment of root indicators, modules, and processes.
3. **APatch Root Integration**:
   - Kernel binary pre-patching via `kptools` with user-specified SuperKey.
   - Preserves root without tripping bootloader state checks.
4. **AnyKernel3 Zip Packaging**:
   - Automatically outputs `AnyKernel3-NoMount-bitra.zip` ready to flash via TWRP Recovery.

## How to Build via GitHub Actions
1. Push this folder to a GitHub repository:
   ```bash
   git remote add origin https://github.com/<your-username>/<your-repo-name>.git
   git branch -M master
   git push -u origin master
   ```
2. In your GitHub repository, navigate to the **Actions** tab.
3. Select **Build Bitra Kernel with NoMount, SuSFS & APatch**.
4. Click **Run workflow**:
   - Enter your desired **APatch SuperKey** (default: `AntigravityRoot`).
   - Target branch: `android-13`.
5. Once compilation finishes (~10-15 minutes), download `AnyKernel3-NoMount-bitra.zip` from the workflow artifacts.
6. Reboot to TWRP Recovery on your Realme GT Neo 2 (`sde26`) and flash the zip.

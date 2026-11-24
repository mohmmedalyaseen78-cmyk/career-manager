# Target device (verified from user's DxDiag, 2026-11-22 21:14)
- ASUS K42F laptop, BIOS 2009
- CPU: Intel Core i3 M350 @ 2.27 GHz (2 cores / 4 threads) -- NOT the E7500 mentioned in the first spec
- RAM: 6 GB (5.9 GB usable)
- GPU: Intel HD Graphics (1st gen), 64 MB dedicated + shared, driver 8.15.10.2900, WDDM 1.1, Direct3D feature level 10_0 only
- Display: 1366x768 @ 60 Hz, 100% DPI
- OS: Windows 10 Pro 22H2 (build 19045) x64, Arabic regional settings
- Design consequences: no GPU reliance (software rendering must be fine), UI must fit 1366x768, no AVX-only binaries, SSE4.2 available.
- Not yet measured: disk type (HDD/SSD), .NET Framework release, WebView2 presence (run tools/diagnose.bat).

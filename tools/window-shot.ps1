# window-shot.ps1 — capture one Windows-side window by title substring.
#
# WSLg draws Linux windows as Windows windows (hosted by msrdc), so the only
# reliable way to screenshot them is from the Windows side: an in-WSL capture
# (scrot/xwd) comes out blank. Called by take_shot.sh.
#
# Why the GetWindow chain instead of EnumWindows: from a WSL-spawned
# PowerShell, EnumWindows has been observed to visit only its own console
# window, while walking the HWND list returns every top-level window.
#
# WSLg titles look like "<document or app title> (Ubuntu-22.04)". MuseScore
# names its window after the open score, not "MuseScore", so the default
# pattern matches the distro suffix instead of the app name.
#
# Prints TITLE:/SIZE:/NOTE: lines then OK, or ERROR:<CODE>: and exits 1.

param(
    [Parameter(Mandatory = $true)][string]$OutFile,
    [string]$Title = "",
    [int]$AutoFocus = 1,
    [int]$AutoMaximize = 0
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;

public class WinShot {
    [DllImport("user32.dll")] public static extern IntPtr GetTopWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr h, uint cmd);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsZoomed(IntPtr h);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr ctx);

    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }

    public static string Text(IntPtr h) {
        int len = GetWindowTextLength(h);
        if (len <= 0) return "";
        var sb = new StringBuilder(len + 1);
        GetWindowText(h, sb, sb.Capacity);
        return sb.ToString();
    }

    public static int Area(IntPtr h) {
        RECT r;
        if (!GetWindowRect(h, out r)) return 0;
        int w = r.Right - r.Left, hh = r.Bottom - r.Top;
        return (w > 0 && hh > 0) ? w * hh : 0;
    }
}
'@

# Per-monitor-v2 DPI awareness: GetWindowRect then returns physical pixels,
# matching what CopyFromScreen samples.
[void][WinShot]::SetProcessDpiAwarenessContext([IntPtr](-4))

$candidates = New-Object System.Collections.ArrayList
$titles = New-Object System.Collections.ArrayList
$hwnd = [WinShot]::GetTopWindow([IntPtr]::Zero)
$guard = 0
while ($hwnd -ne [IntPtr]::Zero -and $guard -lt 600) {
    $guard++
    $text = [WinShot]::Text($hwnd)
    if ($text -and [WinShot]::IsWindowVisible($hwnd)) {
        [void]$titles.Add($text)
        $area = [WinShot]::Area($hwnd)
        if ($area -le 0) { $hwnd = [WinShot]::GetWindow($hwnd, 2); continue }
        $match = if ($Title) {
            $text.IndexOf($Title, [StringComparison]::OrdinalIgnoreCase) -ge 0
        } else {
            $text -match "\((Ubuntu|Debian|kali|fedora|arch)[^)]*\)\s*$"
        }
        if ($match) { [void]$candidates.Add([pscustomobject]@{ Hwnd = $hwnd; Text = $text; Area = $area }) }
    }
    $hwnd = [WinShot]::GetWindow($hwnd, 2)
}

if ($candidates.Count -eq 0) {
    $needle = if ($Title) { "'$Title'" } else { "a WSLg window" }
    Write-Output "ERROR:NOT_FOUND: no visible window matching $needle"
    if ($titles.Count -gt 0) {
        Write-Output ("VISIBLE: " + (($titles | Select-Object -First 12) -join " | "))
    }
    exit 1
}

$pick = $candidates | Sort-Object -Property Area -Descending | Select-Object -First 1
if ($candidates.Count -gt 1) {
    $others = ($candidates | Sort-Object -Property Area -Descending | Select-Object -Skip 1 |
               ForEach-Object { $_.Text }) -join " | "
    Write-Output "NOTE:MULTIPLE_MATCHES (picked the largest; also open: $others)"
}

$hwnd = $pick.Hwnd
Write-Output "TITLE:$($pick.Text)"

$SW_RESTORE = 9
$SW_MAXIMIZE = 3

if ([WinShot]::IsIconic($hwnd)) {
    if ($AutoFocus -ne 1) {
        Write-Output "ERROR:MINIMIZED: window is minimized"
        exit 1
    }
    [void][WinShot]::ShowWindow($hwnd, $SW_RESTORE)
    Start-Sleep -Milliseconds 300
    if ([WinShot]::IsIconic($hwnd)) {
        Write-Output "ERROR:MINIMIZED_RESTORE_FAILED: ShowWindow(SW_RESTORE) had no effect"
        exit 1
    }
}

if ([WinShot]::GetForegroundWindow() -ne $hwnd) {
    if ($AutoFocus -ne 1) {
        Write-Output "ERROR:NOT_FOCUSED: window is not in the foreground"
        exit 1
    }
    [void][WinShot]::SetForegroundWindow($hwnd)
    Start-Sleep -Milliseconds 300
    if ([WinShot]::GetForegroundWindow() -ne $hwnd) {
        Write-Output "NOTE:FOCUS_FAILED (Windows refused foreground; capturing anyway)"
    }
}

if ($AutoMaximize -eq 1) {
    if ([WinShot]::IsZoomed($hwnd)) {
        Write-Output "NOTE:ALREADY_MAXIMIZED"
    } else {
        [void][WinShot]::ShowWindow($hwnd, $SW_MAXIMIZE)
        Start-Sleep -Milliseconds 400
        if ([WinShot]::IsZoomed($hwnd)) { Write-Output "NOTE:MAXIMIZED" }
        else { Write-Output "NOTE:MAXIMIZE_FAILED (captured at current size)" }
    }
}

$rect = New-Object WinShot+RECT
[void][WinShot]::GetWindowRect($hwnd, [ref]$rect)
$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top
if ($width -le 0 -or $height -le 0) {
    Write-Output "ERROR:BAD_SIZE: invalid window rect ${width}x${height}"
    exit 1
}
Write-Output "SIZE:${width}x${height}"

$bmp = New-Object System.Drawing.Bitmap $width, $height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($rect.Left, $rect.Top, 0, 0, (New-Object System.Drawing.Size($width, $height)))
$dir = Split-Path -Parent $OutFile
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
$bmp.Save($OutFile, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "OK"

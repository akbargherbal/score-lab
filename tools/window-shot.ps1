# window-shot.ps1 — capture one Windows-side window by title substring.
#
# WSLg draws Linux windows as Windows windows (hosted by msrdc), so the only
# reliable way to screenshot them is from the Windows side: an in-WSL capture
# (scrot/xwd) comes out blank. Called by take_shot.sh; not meant to be run
# from WSL directly.
#
# Why the GetWindow chain instead of EnumWindows: from a WSL-spawned
# PowerShell, EnumWindows has been observed to visit only its own console
# window, while walking the HWND list returns every top-level window.
#
# WSLg titles look like "<document or app title> (Ubuntu-22.04)". MuseScore
# names its window after the open score, not "MuseScore", so the default
# pattern matches the distro suffix instead of the app name.
#
# Output: TITLE:/SIZE:/NOTE: lines then OK, or ERROR:<CODE>: and exit 1.

param(
    [string]$OutFile = "",
    [string]$Title = "",
    [int]$AutoFocus = 1,
    [int]$AutoMaximize = 0,
    [switch]$ClientArea,
    [switch]$List,
    [int]$ParkCursor = 1
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
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr ctx);

    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
    public struct POINT { public int X; public int Y; }

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

[void][WinShot]::SetProcessDpiAwarenessContext([IntPtr](-4))

$candidates = New-Object System.Collections.ArrayList
$all = New-Object System.Collections.ArrayList
$hwnd = [WinShot]::GetTopWindow([IntPtr]::Zero)
$guard = 0
while ($hwnd -ne [IntPtr]::Zero -and $guard -lt 600) {
    $guard++
    $text = [WinShot]::Text($hwnd)
    if ($text -and [WinShot]::IsWindowVisible($hwnd)) {
        $area = [WinShot]::Area($hwnd)
        if ($area -gt 0) {
            $r = New-Object WinShot+RECT
            [void][WinShot]::GetWindowRect($hwnd, [ref]$r)
            $entry = [pscustomobject]@{
                Hwnd = $hwnd; Text = $text; Area = $area
                Width = $r.Right - $r.Left; Height = $r.Bottom - $r.Top
                Wslg = ($text -match "\((Ubuntu|Debian|kali|fedora|arch)[^)]*\)\s*$")
            }
            [void]$all.Add($entry)
            $match = if ($Title) {
                $text.IndexOf($Title, [StringComparison]::OrdinalIgnoreCase) -ge 0
            } else {
                $entry.Wslg
            }
            if ($match) { [void]$candidates.Add($entry) }
        }
    }
    $hwnd = [WinShot]::GetWindow($hwnd, 2)
}

if ($List) {
    foreach ($e in ($all | Sort-Object -Property Area -Descending)) {
        $tag = if ($e.Wslg) { "wslg" } else { "win " }
        Write-Output ("{0} {1,5}x{2,-5} {3}" -f $tag, $e.Width, $e.Height, $e.Text)
    }
    exit 0
}

if ($candidates.Count -eq 0) {
    $needle = if ($Title) { "'$Title'" } else { "a WSLg window" }
    Write-Output "ERROR:NOT_FOUND: no visible window matching $needle"
    if ($all.Count -gt 0) {
        $sample = ($all | Sort-Object -Property Area -Descending |
                   Select-Object -First 8 | ForEach-Object { $_.Text }) -join " | "
        Write-Output "VISIBLE: $sample"
    }
    exit 1
}

# Prefer the window the user is actually looking at; a killed app can leave a
# stale WSLg window behind with the same size as the live one.
$fg = [WinShot]::GetForegroundWindow()
$pick = $candidates | Where-Object { $_.Hwnd -eq $fg } | Select-Object -First 1
$how = "foreground"
if (-not $pick) {
    $how = "largest"
    $pick = $candidates | Sort-Object -Property Area -Descending | Select-Object -First 1
}
if ($candidates.Count -gt 1) {
    $others = ($candidates | Where-Object { $_.Hwnd -ne $pick.Hwnd } |
               ForEach-Object { $_.Text }) -join " | "
    Write-Output "NOTE:MULTIPLE_MATCHES ($how picked; also: $others)"
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

if ($ClientArea) {
    $rect = New-Object WinShot+RECT
    [void][WinShot]::GetClientRect($hwnd, [ref]$rect)
    $origin = New-Object WinShot+POINT
    [void][WinShot]::ClientToScreen($hwnd, [ref]$origin)
    $left = $origin.X
    $top = $origin.Y
    $width = $rect.Right - $rect.Left
    $height = $rect.Bottom - $rect.Top
} else {
    $rect = New-Object WinShot+RECT
    [void][WinShot]::GetWindowRect($hwnd, [ref]$rect)
    $left = $rect.Left
    $top = $rect.Top
    $width = $rect.Right - $rect.Left
    $height = $rect.Bottom - $rect.Top
}

if ($width -le 0 -or $height -le 0) {
    Write-Output "ERROR:BAD_SIZE: invalid capture rect ${width}x${height}"
    exit 1
}
Write-Output "SIZE:${width}x${height}"

# A pointer left over the taskbar (or a toolbar) paints hover flyouts into the
# capture. Park it in the top-left corner first; harmless, and the caller can
# opt out with -ParkCursor 0.
# Windows keeps taskbar previews on screen for a moment after the pointer
# leaves, so wait long enough for them to fade before copying pixels.
if ($ParkCursor -eq 1) { [void][WinShot]::SetCursorPos(2, 2); Start-Sleep -Milliseconds 900 }
else { Start-Sleep -Milliseconds 250 }

$bmp = New-Object System.Drawing.Bitmap $width, $height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($left, $top, 0, 0, (New-Object System.Drawing.Size($width, $height)))
$dir = Split-Path -Parent $OutFile
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
$bmp.Save($OutFile, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "OK"

param(
    [string]$OutputDir = ".\crop_screenshots",
    [Alias("Slots")]
    [string]$SlotList = "1,2,3,4"
)

$ErrorActionPreference = "Stop"

$Slots = @()
foreach ($part in ($SlotList -split "[,\s]+")) {
    if ($part -match "^[1-4]$") {
        $Slots += [int]$part
    }
}
if ($Slots.Count -eq 0) {
    $Slots = @(1,2,3,4)
}

$source = @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Threading;

public static class RunnerWindowCapture
{
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowTextLength(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);

    [DllImport("dwmapi.dll")]
    public static extern int DwmGetWindowAttribute(IntPtr hwnd, int dwAttribute, out RECT pvAttribute, int cbAttribute);

    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool BringWindowToTop(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

    [DllImport("user32.dll")]
    public static extern bool SetProcessDPIAware();

    public static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
    public static readonly IntPtr HWND_NOTOPMOST = new IntPtr(-2);

    public const int SW_RESTORE = 9;
    public const uint SWP_NOSIZE = 0x0001;
    public const uint SWP_NOMOVE = 0x0002;
    public const uint SWP_SHOWWINDOW = 0x0040;

    // DWM extended frame bounds are the visible window frame. GetWindowRect can include
    // the invisible resize border, which adds extra empty pixels around Windows 10/11 windows.
    public const int DWMWA_EXTENDED_FRAME_BOUNDS = 9;

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    public class WindowInfo
    {
        public IntPtr Hwnd;
        public string Title;
    }

    public static List<WindowInfo> GetWindows()
    {
        var windows = new List<WindowInfo>();
        EnumWindows(delegate (IntPtr hwnd, IntPtr lParam)
        {
            if (!IsWindowVisible(hwnd)) return true;
            int length = GetWindowTextLength(hwnd);
            if (length <= 0) return true;

            var sb = new StringBuilder(length + 1);
            GetWindowText(hwnd, sb, sb.Capacity);
            string title = sb.ToString();
            if (!String.IsNullOrWhiteSpace(title))
            {
                windows.Add(new WindowInfo { Hwnd = hwnd, Title = title });
            }
            return true;
        }, IntPtr.Zero);
        return windows;
    }

    public static void ForceWindowToFront(IntPtr hwnd)
    {
        ShowWindow(hwnd, SW_RESTORE);
        Thread.Sleep(120);
        SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
        Thread.Sleep(120);
        BringWindowToTop(hwnd);
        SetForegroundWindow(hwnd);
        Thread.Sleep(120);
        SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
        Thread.Sleep(300);
    }

    public static bool GetVisibleWindowRect(IntPtr hwnd, out RECT rect, out string rectSource)
    {
        int hr = DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, out rect, Marshal.SizeOf(typeof(RECT)));
        if (hr == 0)
        {
            rectSource = "DWM visible frame";
            return true;
        }

        rectSource = "GetWindowRect fallback";
        return GetWindowRect(hwnd, out rect);
    }

    public static string CaptureSlot(int slot, string outputDir, string timestamp)
    {
        string prefix = "RUNNER " + slot.ToString();
        WindowInfo match = null;

        foreach (var window in GetWindows())
        {
            if (window.Title.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) &&
                window.Title.IndexOf("VLC", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                match = window;
                break;
            }
        }

        if (match == null)
        {
            return "MISSING|" + prefix;
        }

        ForceWindowToFront(match.Hwnd);

        RECT rect;
        string rectSource;
        if (!GetVisibleWindowRect(match.Hwnd, out rect, out rectSource))
        {
            return "ERROR|Could not read window rectangle for " + prefix;
        }

        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width <= 0 || height <= 0)
        {
            return "ERROR|Window has invalid size for " + prefix + ": " + width + "x" + height;
        }

        Directory.CreateDirectory(outputDir);
        string path = Path.Combine(outputDir, "runner" + slot.ToString() + "_" + timestamp + ".png");

        using (var bmp = new Bitmap(width, height))
        using (var g = Graphics.FromImage(bmp))
        {
            g.CopyFromScreen(rect.Left, rect.Top, 0, 0, new Size(width, height), CopyPixelOperation.SourceCopy);
            bmp.Save(path, ImageFormat.Png);
        }

        return "OK|" + path + "|" + match.Title + "|" + width.ToString() + "x" + height.ToString() + "|" + rectSource;
    }
}
"@

try {
    Add-Type -TypeDefinition $source -ReferencedAssemblies System.Drawing
} catch {
    # The class may already exist in the same PowerShell process. Continue if so.
}

try {
    [RunnerWindowCapture]::SetProcessDPIAware() | Out-Null
} catch {}

$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

foreach ($slot in $Slots) {
    try {
        $result = [RunnerWindowCapture]::CaptureSlot($slot, $OutputDir, $timestamp)
        if ($result.StartsWith("OK|")) {
            $parts = $result.Split("|", 5)
            Write-Host "OK Runner $slot -> $($parts[1])  [$($parts[3])]  $($parts[4])  Window: $($parts[2])"
        } elseif ($result.StartsWith("MISSING|")) {
            Write-Host "MISSING Runner ${slot}: no visible VLC window found with title starting RUNNER ${slot}"
        } else {
            Write-Host $result
        }
    } catch {
        Write-Host "ERROR Runner ${slot}: $($_.Exception.Message)"
    }
}

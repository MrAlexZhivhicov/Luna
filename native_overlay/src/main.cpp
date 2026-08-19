#include <windows.h>
#include <shellapi.h>
#include <objidl.h>
#include <ole2.h>
#include <gdiplus.h>
#include <dwmapi.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cwctype>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>

#pragma comment(lib, "gdiplus.lib")
#pragma comment(lib, "dwmapi.lib")
#pragma comment(lib, "shell32.lib")

using namespace Gdiplus;

namespace {

struct OverlayState {
    bool enabled = false;
    bool aimEnabled = false;
    bool autoShoot = false;
    bool showFov = false;
    bool crosshairEnabled = false;
    bool watermark = false;
    bool overlayFps = false;
    bool overlayClock = false;
    bool aimIndicator = false;
    bool worldFilter = false;
    bool worldNightMode = false;
    bool menuOpen = false;
    bool splashOpen = false;
    float splashOpacity = 1.0f;
    float textLevel = 0.0f;
    float aimFov = 0.0f;
    float crosshairSize = 6.0f;
    float worldFilterStrength = 12.0f;
    float watermarkX = 12.0f;
    float watermarkY = 12.0f;
    COLORREF fovColor = RGB(155, 92, 255);
    COLORREF crosshairColor = RGB(255, 255, 255);
    COLORREF nameColor = RGB(244, 244, 247);
    COLORREF worldFilterColor = RGB(120, 149, 199);
    RECT targetRect{0, 0, 0, 0};
    HWND gameHwnd = nullptr;
    HWND menuHwnd = nullptr;
};

struct DibSurface {
    HDC dc = nullptr;
    HBITMAP bitmap = nullptr;
    HBITMAP oldBitmap = nullptr;
    void* bits = nullptr;
    int width = 0;
    int height = 0;

    ~DibSurface() {
        Reset();
    }

    void Reset() {
        if (dc != nullptr) {
            if (oldBitmap != nullptr) {
                SelectObject(dc, oldBitmap);
                oldBitmap = nullptr;
            }
            if (bitmap != nullptr) {
                DeleteObject(bitmap);
                bitmap = nullptr;
            }
            DeleteDC(dc);
            dc = nullptr;
        }
        bits = nullptr;
        width = 0;
        height = 0;
    }

    bool Ensure(int newWidth, int newHeight) {
        if (newWidth <= 0 || newHeight <= 0) {
            Reset();
            return false;
        }
        if (dc != nullptr && width == newWidth && height == newHeight) {
            return true;
        }
        Reset();
        width = newWidth;
        height = newHeight;
        HDC screen = GetDC(nullptr);
        dc = CreateCompatibleDC(screen);
        ReleaseDC(nullptr, screen);
        if (dc == nullptr) {
            return false;
        }
        BITMAPINFO bmi{};
        bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
        bmi.bmiHeader.biWidth = width;
        bmi.bmiHeader.biHeight = -height;
        bmi.bmiHeader.biPlanes = 1;
        bmi.bmiHeader.biBitCount = 32;
        bmi.bmiHeader.biCompression = BI_RGB;
        bitmap = CreateDIBSection(dc, &bmi, DIB_RGB_COLORS, &bits, nullptr, 0);
        if (bitmap == nullptr || bits == nullptr) {
            Reset();
            return false;
        }
        oldBitmap = static_cast<HBITMAP>(SelectObject(dc, bitmap));
        return true;
    }
};

std::wstring Trim(const std::wstring& value) {
    size_t start = 0;
    while (start < value.size() && std::iswspace(value[start])) {
        ++start;
    }
    size_t end = value.size();
    while (end > start && std::iswspace(value[end - 1])) {
        --end;
    }
    return value.substr(start, end - start);
}

bool ParseBool(const std::unordered_map<std::wstring, std::wstring>& kv, const wchar_t* key, bool fallback) {
    auto it = kv.find(key);
    if (it == kv.end()) {
        return fallback;
    }
    const std::wstring value = Trim(it->second);
    return value == L"1" || value == L"true" || value == L"True";
}

int ParseInt(const std::unordered_map<std::wstring, std::wstring>& kv, const wchar_t* key, int fallback) {
    auto it = kv.find(key);
    if (it == kv.end()) {
        return fallback;
    }
    try {
        return std::stoi(Trim(it->second));
    } catch (...) {
        return fallback;
    }
}

float ParseFloat(const std::unordered_map<std::wstring, std::wstring>& kv, const wchar_t* key, float fallback) {
    auto it = kv.find(key);
    if (it == kv.end()) {
        return fallback;
    }
    try {
        return std::stof(Trim(it->second));
    } catch (...) {
        return fallback;
    }
}

COLORREF ParseColor(const std::unordered_map<std::wstring, std::wstring>& kv, const wchar_t* key, COLORREF fallback) {
    auto it = kv.find(key);
    if (it == kv.end()) {
        return fallback;
    }
    std::wstring value = Trim(it->second);
    if (value.size() != 7 || value[0] != L'#') {
        return fallback;
    }
    try {
        int r = std::stoi(value.substr(1, 2), nullptr, 16);
        int g = std::stoi(value.substr(3, 2), nullptr, 16);
        int b = std::stoi(value.substr(5, 2), nullptr, 16);
        return RGB(r, g, b);
    } catch (...) {
        return fallback;
    }
}

std::unordered_map<std::wstring, std::wstring> ReadKeyValues(const std::filesystem::path& path) {
    std::unordered_map<std::wstring, std::wstring> out;
    std::wifstream stream(path);
    stream.imbue(std::locale(".UTF-8"));
    if (!stream) {
        return out;
    }
    std::wstring line;
    while (std::getline(stream, line)) {
        size_t pos = line.find(L'=');
        if (pos == std::wstring::npos) {
            continue;
        }
        std::wstring key = Trim(line.substr(0, pos));
        std::wstring value = Trim(line.substr(pos + 1));
        if (!key.empty()) {
            out[key] = value;
        }
    }
    return out;
}

bool UpdateStateFromFile(const std::filesystem::path& path, OverlayState& state, std::filesystem::file_time_type& stamp) {
    std::error_code ec;
    const auto currentStamp = std::filesystem::last_write_time(path, ec);
    if (ec) {
        return false;
    }
    if (currentStamp == stamp) {
        return false;
    }
    stamp = currentStamp;
    const auto kv = ReadKeyValues(path);
    state.enabled = ParseBool(kv, L"enabled", state.enabled);
    state.aimEnabled = ParseBool(kv, L"aim_enabled", state.aimEnabled);
    state.autoShoot = ParseBool(kv, L"auto_shoot", state.autoShoot);
    state.showFov = ParseBool(kv, L"show_fov", state.showFov);
    state.crosshairEnabled = ParseBool(kv, L"crosshair_enabled", state.crosshairEnabled);
    state.watermark = ParseBool(kv, L"watermark", state.watermark);
    state.watermarkX = ParseFloat(kv, L"watermark_x", state.watermarkX);
    state.watermarkY = ParseFloat(kv, L"watermark_y", state.watermarkY);
    state.overlayFps = ParseBool(kv, L"overlay_fps", state.overlayFps);
    state.overlayClock = ParseBool(kv, L"overlay_clock", state.overlayClock);
    state.aimIndicator = ParseBool(kv, L"aim_indicator", state.aimIndicator);
    state.worldFilter = ParseBool(kv, L"world_filter", state.worldFilter);
    state.worldNightMode = ParseBool(kv, L"world_night_mode", state.worldNightMode);
    state.menuOpen = ParseBool(kv, L"menu_open", state.menuOpen);
    state.splashOpen = ParseBool(kv, L"splash_open", state.splashOpen);
    state.splashOpacity = std::clamp(ParseFloat(kv, L"splash_opacity", state.splashOpacity), 0.0f, 1.0f);
    state.textLevel = std::clamp(ParseFloat(kv, L"text_level", state.textLevel), 0.0f, 1.0f);
    state.aimFov = ParseFloat(kv, L"aim_fov", state.aimFov);
    state.crosshairSize = ParseFloat(kv, L"crosshair_size", state.crosshairSize);
    state.worldFilterStrength = std::clamp(ParseFloat(
        kv, L"world_filter_strength", state.worldFilterStrength), 0.0f, 35.0f);
    state.fovColor = ParseColor(kv, L"fov_color", state.fovColor);
    state.crosshairColor = ParseColor(kv, L"crosshair_color", state.crosshairColor);
    state.nameColor = ParseColor(kv, L"name_color", state.nameColor);
    state.worldFilterColor = ParseColor(kv, L"world_filter_color", state.worldFilterColor);
    state.targetRect.left = ParseInt(kv, L"x", state.targetRect.left);
    state.targetRect.top = ParseInt(kv, L"y", state.targetRect.top);
    const int width = ParseInt(kv, L"width", state.targetRect.right - state.targetRect.left);
    const int height = ParseInt(kv, L"height", state.targetRect.bottom - state.targetRect.top);
    state.targetRect.right = state.targetRect.left + width;
    state.targetRect.bottom = state.targetRect.top + height;
    state.gameHwnd = reinterpret_cast<HWND>(static_cast<uintptr_t>(ParseInt(kv, L"game_hwnd", 0)));
    state.menuHwnd = reinterpret_cast<HWND>(static_cast<uintptr_t>(ParseInt(kv, L"menu_hwnd", 0)));
    return true;
}

HWND FindWindowForPid(DWORD pid) {
    struct Context {
        DWORD pid = 0;
        HWND hwnd = nullptr;
    } ctx{pid, nullptr};
    EnumWindows(
        [](HWND hwnd, LPARAM lParam) -> BOOL {
            auto* ctxPtr = reinterpret_cast<Context*>(lParam);
            DWORD windowPid = 0;
            GetWindowThreadProcessId(hwnd, &windowPid);
            if (windowPid != ctxPtr->pid || !IsWindowVisible(hwnd)) {
                return TRUE;
            }
            if (GetWindow(hwnd, GW_OWNER) != nullptr) {
                return TRUE;
            }
            ctxPtr->hwnd = hwnd;
            return FALSE;
        },
        reinterpret_cast<LPARAM>(&ctx)
    );
    return ctx.hwnd;
}

bool IsEligibleForeground(HWND overlay, const OverlayState& state) {
    const HWND foreground = GetForegroundWindow();
    return foreground == state.gameHwnd || foreground == state.menuHwnd || foreground == overlay;
}

Color MakeColor(COLORREF color, BYTE alpha = 255) {
    return Color(alpha, GetRValue(color), GetGValue(color), GetBValue(color));
}

void FillRectAlpha(Graphics& graphics, int x, int y, int w, int h, const Color& color) {
    SolidBrush brush(color);
    graphics.FillRectangle(&brush, x, y, w, h);
}

void DrawCrosshair(Graphics& graphics, int width, int height, float size, COLORREF color) {
    Pen pen(MakeColor(color), 1.0f);
    const float cx = static_cast<float>(width) * 0.5f;
    const float cy = static_cast<float>(height) * 0.5f;
    graphics.DrawLine(&pen, cx - size, cy, cx - 2.0f, cy);
    graphics.DrawLine(&pen, cx + 2.0f, cy, cx + size, cy);
    graphics.DrawLine(&pen, cx, cy - size, cx, cy - 2.0f);
    graphics.DrawLine(&pen, cx, cy + 2.0f, cx, cy + size);
}

void DrawFov(Graphics& graphics, int width, int height, float aimFov, COLORREF color) {
    const double radius = std::tan(aimFov * 3.14159265358979323846 / 180.0) / std::tan(45.0 * 3.14159265358979323846 / 180.0) * width * 0.5;
    const float r = static_cast<float>(radius);
    Pen pen(MakeColor(color), 1.2f);
    pen.SetAlignment(PenAlignmentCenter);
    graphics.DrawEllipse(&pen, width * 0.5f - r, height * 0.5f - r, r * 2.0f, r * 2.0f);
}

void DrawTextLine(Graphics& graphics, const std::wstring& text, const RectF& rect, const Font& font, const Color& color, StringAlignment align) {
    StringFormat format;
    format.SetAlignment(align);
    format.SetLineAlignment(StringAlignmentNear);
    SolidBrush brush(color);
    graphics.DrawString(text.c_str(), -1, &font, rect, &format, &brush);
}

void DrawWatermark(Graphics& graphics, float x, float y) {
    FillRectAlpha(graphics, static_cast<int>(x), static_cast<int>(y), 152, 26, Color(232, 15, 17, 22));
    Pen border(Color(220, 105, 110, 122), 1.0f);
    graphics.DrawRectangle(&border, x, y, 152.0f, 26.0f);
    FillRectAlpha(graphics, static_cast<int>(x), static_cast<int>(y), 152, 2, Color(255, 230, 84, 63));
    FontFamily family(L"Verdana");
    Font font(&family, 9.0f, FontStyleBold, UnitPixel);
    DrawTextLine(graphics, L"LUNA  /  CPP", RectF(x + 11.0f, y + 6.0f, 130.0f, 16.0f), font, Color(255, 242, 240, 234), StringAlignmentNear);
}

void DrawClock(Graphics& graphics, int width, const OverlayState& state, int fpsValue) {
    FontFamily family(L"Verdana");
    Font font(&family, 11.0f, FontStyleRegular, UnitPixel);
    Font fontBold(&family, 11.0f, FontStyleBold, UnitPixel);
    const float left = static_cast<float>(width - 148);
    const float panelHeight = state.overlayClock && state.overlayFps ? 45.0f : 27.0f;
    FillRectAlpha(graphics, static_cast<int>(left), 8, 136, static_cast<int>(panelHeight), Color(232, 15, 17, 22));
    Pen border(Color(220, 105, 110, 122), 1.0f);
    graphics.DrawRectangle(&border, left, 8.0f, 136.0f, panelHeight);
    FillRectAlpha(graphics, static_cast<int>(left), 8, 136, 2, Color(255, 230, 84, 63));
    if (state.overlayFps) {
        std::wstringstream fps;
        fps << L"OVR " << fpsValue << L" FPS";
        DrawTextLine(graphics, fps.str(), RectF(left + 10.0f, 15.0f, 116.0f, 18.0f), fontBold, Color(255, 242, 240, 234), StringAlignmentFar);
    }
    if (state.overlayClock) {
        SYSTEMTIME local{};
        GetLocalTime(&local);
        wchar_t buffer[16]{};
        swprintf_s(buffer, L"%02u:%02u:%02u", local.wHour, local.wMinute, local.wSecond);
        const float clockY = state.overlayFps ? 32.0f : 15.0f;
        DrawTextLine(graphics, buffer, RectF(left + 10.0f, clockY, 116.0f, 18.0f), font, Color(255, 170, 174, 184), StringAlignmentFar);
    }
}

void DrawIndicator(Graphics& graphics, int width, int height) {
    FontFamily family(L"Verdana");
    Font font(&family, 11.0f, FontStyleBold, UnitPixel);
    const int left = width / 2 - 62;
    const int top = height - 38;
    FillRectAlpha(graphics, left, top, 124, 26, Color(232, 15, 17, 22));
    Pen border(Color(220, 105, 110, 122), 1.0f);
    graphics.DrawRectangle(&border, static_cast<float>(left), static_cast<float>(top), 124.0f, 26.0f);
    FillRectAlpha(graphics, left, top, 124, 2, Color(255, 230, 84, 63));
    DrawTextLine(graphics, L"AIM ACTIVE", RectF(static_cast<REAL>(left), static_cast<REAL>(top + 7), 124.0f, 16.0f), font, Color(255, 242, 240, 234), StringAlignmentCenter);
}

void DrawSplash(Graphics& graphics, int width, int height, float opacity, float textLevel) {
    const BYTE alpha = static_cast<BYTE>(std::clamp(opacity, 0.0f, 1.0f) * 255.0f);
    FillRectAlpha(graphics, 0, 0, width, height, Color(alpha, 0, 0, 0));
    const BYTE shade = static_cast<BYTE>(std::clamp(textLevel, 0.0f, 1.0f) * 255.0f);
    FontFamily ui(L"Segoe UI");
    Font title(&ui, 28.0f, FontStyleBold, UnitPixel);
    Font sub(&ui, 10.0f, FontStyleRegular, UnitPixel);
    DrawTextLine(graphics, L"LUNA", RectF(0.0f, static_cast<REAL>(height / 2 - 42), static_cast<REAL>(width), 32.0f), title, Color(255, shade, shade, shade), StringAlignmentCenter);
    Pen pen(Color(180, shade, shade, shade), 1.0f);
    graphics.DrawLine(&pen, static_cast<REAL>(width / 2 - 110), static_cast<REAL>(height / 2 + 18), static_cast<REAL>(width / 2 + 110), static_cast<REAL>(height / 2 + 18));
    DrawTextLine(graphics, L"DESKTOP CONTROL UTILITY", RectF(0.0f, static_cast<REAL>(height / 2 + 24), static_cast<REAL>(width), 16.0f), sub, Color(220, shade, shade, shade), StringAlignmentCenter);
}

void DrawMenuDim(Graphics& graphics, int width, int height) {
    FillRectAlpha(graphics, 0, 0, width, height, Color(22, 5, 5, 5));
}

void Present(HWND hwnd, DibSurface& surface, int x, int y, int width, int height) {
    POINT ptDst{x, y};
    SIZE size{width, height};
    POINT ptSrc{0, 0};
    BLENDFUNCTION blend{};
    blend.BlendOp = AC_SRC_OVER;
    blend.SourceConstantAlpha = 255;
    blend.AlphaFormat = AC_SRC_ALPHA;
    HDC screen = GetDC(nullptr);
    UpdateLayeredWindow(hwnd, screen, &ptDst, &size, surface.dc, &ptSrc, 0, &blend, ULW_ALPHA);
    ReleaseDC(nullptr, screen);
}

void HideOverlay(HWND hwnd) {
    ShowWindow(hwnd, SW_HIDE);
}

void ShowOverlay(HWND hwnd) {
    ShowWindow(hwnd, SW_SHOWNOACTIVATE);
}

}  // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR commandLine, int) {
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argv == nullptr || argc < 4) {
        return 1;
    }
    const DWORD pid = static_cast<DWORD>(_wtoi(argv[1]));
    const std::filesystem::path statePath = argv[2];
    const DWORD ownerPid = static_cast<DWORD>(_wtoi(argv[3]));
    LocalFree(argv);

    HANDLE ownerProcess = OpenProcess(SYNCHRONIZE, FALSE, ownerPid);
    if (ownerProcess == nullptr) {
        return 4;
    }

    GdiplusStartupInput gdiplusStartupInput;
    ULONG_PTR gdiplusToken = 0;
    if (GdiplusStartup(&gdiplusToken, &gdiplusStartupInput, nullptr) != Ok) {
        return 2;
    }

    WNDCLASSW wc{};
    wc.lpfnWndProc = DefWindowProcW;
    wc.hInstance = instance;
    wc.lpszClassName = L"MilkyWayNativeOverlayWindow";
    RegisterClassW(&wc);

    HWND hwnd = CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        wc.lpszClassName,
        L"NativeOverlay",
        WS_POPUP,
        0,
        0,
        1,
        1,
        nullptr,
        nullptr,
        instance,
        nullptr
    );
    if (hwnd == nullptr) {
        GdiplusShutdown(gdiplusToken);
        return 3;
    }

    MARGINS margins{-1};
    DwmExtendFrameIntoClientArea(hwnd, &margins);

    OverlayState state;
    state.gameHwnd = FindWindowForPid(pid);
    DibSurface surface;
    std::filesystem::file_time_type stamp{};
    auto fpsTick = std::chrono::steady_clock::now();
    int frameCounter = 0;
    int fpsValue = 0;

    bool running = true;
    while (running) {
        if (WaitForSingleObject(ownerProcess, 0) != WAIT_TIMEOUT) {
            break;
        }
        MSG msg{};
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_QUIT) {
                running = false;
            }
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        if (!running) {
            break;
        }

        if (state.gameHwnd == nullptr || !IsWindow(state.gameHwnd)) {
            state.gameHwnd = FindWindowForPid(pid);
        }
        const bool stateChanged = UpdateStateFromFile(statePath, state, stamp);

        const int width = state.targetRect.right - state.targetRect.left;
        const int height = state.targetRect.bottom - state.targetRect.top;
        const bool wantsFov = (state.aimEnabled || state.autoShoot) && state.showFov;
        const bool wantsExtras = state.crosshairEnabled || state.watermark || state.overlayFps || state.overlayClock || state.aimIndicator || state.worldFilter || state.worldNightMode || state.menuOpen || state.splashOpen;
        const bool shouldDraw = state.enabled && width > 0 && height > 0 && (wantsFov || wantsExtras);
        if (!shouldDraw || !IsEligibleForeground(hwnd, state)) {
            HideOverlay(hwnd);
            Sleep(8);
            continue;
        }

        if (!surface.Ensure(width, height)) {
            Sleep(16);
            continue;
        }
        ShowOverlay(hwnd);

        // All native primitives are static between IPC updates. Re-presenting
        // a fullscreen layered DIB ~160 times/s needlessly stalls DWM and the
        // game's presentation queue. The one-second refresh keeps clock/FPS live.
        const auto beforeDraw = std::chrono::steady_clock::now();
        const auto sinceFpsTick = std::chrono::duration_cast<std::chrono::milliseconds>(beforeDraw - fpsTick).count();
        if (!stateChanged && sinceFpsTick < 1000) {
            Sleep(8);
            continue;
        }

        auto* pixels = static_cast<std::uint32_t*>(surface.bits);
        std::fill(pixels, pixels + static_cast<size_t>(width) * static_cast<size_t>(height), 0u);

        Graphics graphics(surface.dc);
        graphics.SetSmoothingMode(SmoothingModeAntiAlias);
        graphics.SetTextRenderingHint(TextRenderingHintAntiAliasGridFit);
        graphics.SetCompositingMode(CompositingModeSourceOver);

        if (state.worldNightMode) {
            FillRectAlpha(graphics, 0, 0, width, height, Color(34, 8, 16, 30));
        }
        if (state.worldFilter) {
            const BYTE alpha = static_cast<BYTE>(std::clamp(
                state.worldFilterStrength * 2.55f, 0.0f, 90.0f));
            FillRectAlpha(graphics, 0, 0, width, height,
                          MakeColor(state.worldFilterColor, alpha));
        }

        if (state.splashOpen) {
            DrawSplash(graphics, width, height, state.splashOpacity, state.textLevel);
        } else if (state.menuOpen) {
            DrawMenuDim(graphics, width, height);
        }
        if (state.watermark) {
            DrawWatermark(graphics, state.watermarkX, state.watermarkY);
        }
        DrawClock(graphics, width, state, fpsValue);
        if (state.aimIndicator && (state.aimEnabled || state.autoShoot)) {
            DrawIndicator(graphics, width, height);
        }
        if (state.crosshairEnabled) {
            DrawCrosshair(graphics, width, height, state.crosshairSize, state.crosshairColor);
        }
        if (wantsFov) {
            DrawFov(graphics, width, height, state.aimFov, state.fovColor);
        }

        Present(hwnd, surface, state.targetRect.left, state.targetRect.top, width, height);

        ++frameCounter;
        const auto now = std::chrono::steady_clock::now();
        const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - fpsTick).count();
        if (elapsed >= 1000) {
            fpsValue = static_cast<int>(frameCounter * 1000 / std::max<long long>(elapsed, 1));
            frameCounter = 0;
            fpsTick = now;
        }
        Sleep(6);
    }

    surface.Reset();
    DestroyWindow(hwnd);
    GdiplusShutdown(gdiplusToken);
    CloseHandle(ownerProcess);
    return 0;
}

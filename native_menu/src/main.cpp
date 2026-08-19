#include <windows.h>
#include <commctrl.h>

#include <filesystem>
#include <fstream>
#include <string>
#include <unordered_map>

#pragma comment(lib, "comctl32.lib")

namespace {
constexpr int IdWatermark = 101;
constexpr int IdFps = 102;
constexpr int IdClock = 103;
constexpr int IdCrosshair = 104;
constexpr int IdFov = 105;
constexpr int IdCrosshairSize = 106;
constexpr int IdFovSize = 107;
constexpr int IdClose = 108;

std::filesystem::path statePath;
HWND windowHandle = nullptr;
bool visible = false;
bool closed = false;

std::unordered_map<std::wstring, std::wstring> ReadState() {
    std::unordered_map<std::wstring, std::wstring> values;
    std::wifstream stream(statePath);
    stream.imbue(std::locale::classic());
    std::wstring line;
    while (std::getline(stream, line)) {
        const auto split = line.find(L'=');
        if (split != std::wstring::npos) values[line.substr(0, split)] = line.substr(split + 1);
    }
    return values;
}

bool Flag(const std::unordered_map<std::wstring, std::wstring>& values, const wchar_t* key, bool fallback) {
    const auto it = values.find(key);
    return it == values.end() ? fallback : it->second == L"1";
}

int Number(const std::unordered_map<std::wstring, std::wstring>& values, const wchar_t* key, int fallback) {
    const auto it = values.find(key);
    if (it == values.end()) return fallback;
    try { return std::stoi(it->second); } catch (...) { return fallback; }
}

bool Checked(int id) { return SendDlgItemMessageW(windowHandle, id, BM_GETCHECK, 0, 0) == BST_CHECKED; }

void WriteState() {
    const auto temporary = statePath.wstring() + L".tmp";
    std::wofstream stream(temporary, std::ios::trunc);
    stream.imbue(std::locale::classic());
    stream << L"visible=" << (visible ? 1 : 0) << L'\n';
    stream << L"closed=" << (closed ? 1 : 0) << L'\n';
    stream << L"hwnd=" << reinterpret_cast<uintptr_t>(windowHandle) << L'\n';
    stream << L"watermark=" << Checked(IdWatermark) << L'\n';
    stream << L"overlay_fps=" << Checked(IdFps) << L'\n';
    stream << L"overlay_clock=" << Checked(IdClock) << L'\n';
    stream << L"crosshair_enabled=" << Checked(IdCrosshair) << L'\n';
    stream << L"show_fov=" << Checked(IdFov) << L'\n';
    stream << L"crosshair_size=" << SendDlgItemMessageW(windowHandle, IdCrosshairSize, TBM_GETPOS, 0, 0) << L'\n';
    stream << L"aim_fov=" << SendDlgItemMessageW(windowHandle, IdFovSize, TBM_GETPOS, 0, 0) << L'\n';
    stream.close();
    std::error_code error;
    std::filesystem::rename(temporary, statePath, error);
    if (error) {
        std::filesystem::remove(statePath, error);
        std::filesystem::rename(temporary, statePath, error);
    }
}

void Toggle() {
    visible = !visible;
    ShowWindow(windowHandle, visible ? SW_SHOW : SW_HIDE);
    if (visible) { SetForegroundWindow(windowHandle); SetFocus(windowHandle); }
    WriteState();
}

HWND AddControl(const wchar_t* type, const wchar_t* text, DWORD style, int x, int y, int w, int h, int id) {
    return CreateWindowExW(0, type, text, WS_CHILD | WS_VISIBLE | style, x, y, w, h,
                           windowHandle, reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)), GetModuleHandleW(nullptr), nullptr);
}

LRESULT CALLBACK WindowProc(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam) {
    switch (message) {
    case WM_CREATE: {
        windowHandle = hwnd;
        const auto initial = ReadState();
        HFONT font = CreateFontW(-17, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET,
                                 OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
        AddControl(L"STATIC", L"LUNA  /  NATIVE UI", SS_LEFT, 24, 18, 420, 30, 0);
        AddControl(L"STATIC", L"OVERLAY", SS_LEFT, 24, 66, 180, 24, 0);
        AddControl(L"BUTTON", L"Watermark", BS_AUTOCHECKBOX, 24, 100, 200, 28, IdWatermark);
        AddControl(L"BUTTON", L"FPS counter", BS_AUTOCHECKBOX, 24, 136, 200, 28, IdFps);
        AddControl(L"BUTTON", L"Clock", BS_AUTOCHECKBOX, 24, 172, 200, 28, IdClock);
        AddControl(L"STATIC", L"CROSSHAIR / FOV", SS_LEFT, 260, 66, 220, 24, 0);
        AddControl(L"BUTTON", L"Crosshair", BS_AUTOCHECKBOX, 260, 100, 200, 28, IdCrosshair);
        AddControl(L"BUTTON", L"FOV circle", BS_AUTOCHECKBOX, 260, 136, 200, 28, IdFov);
        AddControl(L"STATIC", L"Crosshair size", SS_LEFT, 260, 180, 150, 22, 0);
        AddControl(TRACKBAR_CLASSW, L"", TBS_HORZ | TBS_NOTICKS, 260, 204, 230, 28, IdCrosshairSize);
        AddControl(L"STATIC", L"FOV size", SS_LEFT, 260, 246, 150, 22, 0);
        AddControl(TRACKBAR_CLASSW, L"", TBS_HORZ | TBS_NOTICKS, 260, 270, 230, 28, IdFovSize);
        AddControl(L"STATIC", L"F1 — show / hide", SS_LEFT, 24, 326, 220, 24, 0);
        AddControl(L"BUTTON", L"Close", BS_PUSHBUTTON, 390, 320, 100, 32, IdClose);
        EnumChildWindows(hwnd, [](HWND child, LPARAM value) -> BOOL { SendMessageW(child, WM_SETFONT, value, TRUE); return TRUE; }, reinterpret_cast<LPARAM>(font));
        const int checks[] = {IdWatermark, IdFps, IdClock, IdCrosshair, IdFov};
        const wchar_t* keys[] = {L"watermark", L"overlay_fps", L"overlay_clock", L"crosshair_enabled", L"show_fov"};
        for (int i = 0; i < 5; ++i) SendDlgItemMessageW(hwnd, checks[i], BM_SETCHECK, Flag(initial, keys[i], false) ? BST_CHECKED : BST_UNCHECKED, 0);
        SendDlgItemMessageW(hwnd, IdCrosshairSize, TBM_SETRANGE, TRUE, MAKELPARAM(2, 24));
        SendDlgItemMessageW(hwnd, IdCrosshairSize, TBM_SETPOS, TRUE, Number(initial, L"crosshair_size", 6));
        SendDlgItemMessageW(hwnd, IdFovSize, TBM_SETRANGE, TRUE, MAKELPARAM(1, 30));
        SendDlgItemMessageW(hwnd, IdFovSize, TBM_SETPOS, TRUE, Number(initial, L"aim_fov", 6));
        visible = true;
        SetTimer(hwnd, 1, 50, nullptr);
        WriteState();
        return 0;
    }
    case WM_HOTKEY: if (wParam == 1) Toggle(); return 0;
    case WM_COMMAND:
        if (LOWORD(wParam) == IdClose) { DestroyWindow(hwnd); return 0; }
        WriteState(); return 0;
    case WM_HSCROLL: WriteState(); return 0;
    case WM_TIMER: WriteState(); return 0;
    case WM_CLOSE: DestroyWindow(hwnd); return 0;
    case WM_DESTROY:
        closed = true; visible = false; WriteState(); UnregisterHotKey(hwnd, 1); PostQuitMessage(0); return 0;
    }
    return DefWindowProcW(hwnd, message, wParam, lParam);
}
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR commandLine, int show) {
    statePath = commandLine;
    if (statePath.empty()) return 2;
    INITCOMMONCONTROLSEX controls{sizeof(controls), ICC_BAR_CLASSES};
    InitCommonControlsEx(&controls);
    WNDCLASSEXW wc{sizeof(wc)};
    wc.lpfnWndProc = WindowProc;
    wc.hInstance = instance;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hbrBackground = CreateSolidBrush(RGB(18, 18, 18));
    wc.lpszClassName = L"MilkyWayNativeMenu";
    RegisterClassExW(&wc);
    HWND hwnd = CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW, wc.lpszClassName, L"Luna",
                                WS_POPUP | WS_CAPTION | WS_SYSMENU, CW_USEDEFAULT, CW_USEDEFAULT, 530, 410,
                                nullptr, nullptr, instance, nullptr);
    if (!hwnd) return 3;
    RegisterHotKey(hwnd, 1, MOD_NOREPEAT, VK_F1);
    ShowWindow(hwnd, show);
    UpdateWindow(hwnd);
    MSG message{};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) { TranslateMessage(&message); DispatchMessageW(&message); }
    return static_cast<int>(message.wParam);
}

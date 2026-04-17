import sys
import customtkinter
import os
import psutil
import ctypes
import json
import shutil
import win32gui
import win32process
import win32con
import time
import threading
import keyboard
from Managers.AccountsManager import AccountManager
from Managers.LogManager import LogManager
from Managers.SettingsManager import SettingsManager


class ControlFrame(customtkinter.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, width=250)
        self.logManager = LogManager()
        self._auto_move_lock = threading.Lock()
        self._auto_move_active = False
        self._docked_windows = []
        self._dock_window_size = (640, 480)
        self._dock_grid_size = (2, 2)
        self._dock_slot_padding = 4
        self.accounts_list_frame = None

        self.grid(row=1, column=3, padx=(20, 20), pady=(20, 0), sticky="nsew")

        data = [
            ("Move all CS windows", None, self.move_all_cs_windows),
            ("Kill ALL CS & Steam processes", "red", self.kill_all_cs_and_steam),
            ("Launch BES", "darkgreen", self.launch_bes),
            ("Launch SRT", "darkgreen", self.launch_srt),
            ("Support Developer", "darkgreen", self.sendCasesMe),
        ]

        for text, color, func in data:
            b = customtkinter.CTkButton(self, text=text, fg_color=color, command=func)
            b.pack(pady=10)

    def _load_runtime_maps(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        runtime_path = os.path.join(project_root, "runtime.json")

        login_to_pid = {}
        pid_to_login = {}

        with open(runtime_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for item in data:
            login = item.get("login")
            cs2_pid = item.get("CS2Pid")
            if not login or cs2_pid is None:
                continue
            try:
                pid = int(cs2_pid)
            except (TypeError, ValueError):
                continue
            login_to_pid[login] = pid
            pid_to_login[pid] = login

        return login_to_pid, pid_to_login

    @staticmethod
    def _get_active_cs2_pids():
        pids = set()
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if (proc.info.get("name") or "").lower() == "cs2.exe":
                    pids.add(proc.info["pid"])
            except Exception:
                pass
        return pids

    def move_all_cs_windows(self):
        print("🔀 Расстановка окон CS2 по порядку аккаунтов...")

        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass



        # 1) Порядок строго из аккаунтов в UI
        accounts_order = [acc.login for acc in AccountManager().accounts]
        if not accounts_order:
            print("❌ Список аккаунтов пуст")
            return

        # 2) runtime.json -> карты login<->pid
        try:
            login_to_pid, pid_to_login = self._load_runtime_maps()
        except Exception as e:
            print(f"❌ Ошибка чтения runtime.json: {e}")
            return

        print(f"✅ КАРТА runtime.json: {len(login_to_pid)} login→pid")

        active_cs2_pids = self._get_active_cs2_pids()
        if not active_cs2_pids:
            print("❌ Активные cs2.exe процессы не найдены")
            return

        # 3) Ищем окна только для активных cs2 pid
        hwnd_by_pid = {}

        def enum_cb(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd) or not win32gui.IsWindowEnabled(hwnd):
                    return True
                if win32gui.GetParent(hwnd) != 0:
                    return True

                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid not in active_cs2_pids:
                    return True
                if pid in hwnd_by_pid:
                    return True

                title = win32gui.GetWindowText(hwnd)
                if not title:
                    return True

                hwnd_by_pid[pid] = hwnd

                # по возможности нормализуем заголовок
                login = pid_to_login.get(pid)
                if login:
                    try:
                        win32gui.SetWindowText(hwnd, f"[FREE] {login}")
                    except Exception:
                        pass
            except Exception:
                pass
            return True

        win32gui.EnumWindows(enum_cb, None)

        # 4) Строим упорядоченный список окон строго по accounts_order
        ordered_windows = []
        for login in accounts_order:
            pid = login_to_pid.get(login)
            hwnd = hwnd_by_pid.get(pid)
            if hwnd and win32gui.IsWindow(hwnd):
                ordered_windows.append((login, pid, hwnd))

        if not ordered_windows:
            print("❌ Не найдено подходящих окон CS2 для расстановки")
            return

        # 5) Ставим окна в сетку 2x2 (640x480) внутри области UI слева.
        max_columns, max_rows = self._dock_grid_size
        max_slots = max_columns * max_rows

        app_window = self.winfo_toplevel()
        slots = self._get_grid_slots(app_window)
        if not slots:
            print("❌ Не удалось получить координаты слотов 2x2 в панели")
            return

        placed = 0
        self._docked_windows = []
        for idx, (login, pid, hwnd) in enumerate(ordered_windows[:max_slots]):
            row, col, x, y, window_width, window_height = slots[idx]
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.MoveWindow(hwnd, x, y, window_width, window_height, True)
                print(f"📍 {idx + 1}. {login} (PID {pid}) -> row={row + 1}, col={col + 1}, pos=({x},{y})")
                placed += 1
                self._docked_windows.append((login, pid, hwnd))
            except Exception as e:
                print(f"⚠️ Не удалось переместить {login}: {e}")

        print(f"✅ Размещено окон: {placed}")
        self._raise_docked_windows_once()

        if self.accounts_list_frame:
            self.accounts_list_frame.set_green_for_launched_cs2(active_cs2_pids)

    def _get_grid_slots(self, app_window):
        slots = [] 
        width, height = self._dock_window_size 
        spacing = 1
        max_columns, max_rows = self._dock_grid_size
        try:
            app_window.update_idletasks()

            ui_slots = getattr(app_window, "ui_grid_slots", None) or []
            for idx, slot in enumerate(ui_slots[: max_columns * max_rows]):
                if not slot.winfo_exists(): 
                    continue 
                row = idx // max_columns 
                col = idx % max_columns 
                pad = self._dock_slot_padding
                x = slot.winfo_rootx() + pad
                y = slot.winfo_rooty() + pad
                slot_width = max(200, slot.winfo_width() - (pad * 2))
                slot_height = max(120, slot.winfo_height() - (pad * 2))
                slots.append((row, col, x, y, slot_width, slot_height)) 

            if len(slots) >= max_columns * max_rows:
                return slots

            anchor = getattr(app_window, "ui_grid_anchor", None) 
            if anchor and anchor.winfo_exists(): 
                base_x = anchor.winfo_rootx()
                base_y = anchor.winfo_rooty()
            else: 
                base_x = app_window.winfo_rootx() + 18 
                base_y = app_window.winfo_rooty() + 70 

            slots = []
            for idx in range(max_columns * max_rows):
                row = idx // max_columns
                col = idx % max_columns
                x = base_x + col * (width + spacing)
                y = base_y + row * (height + spacing)
                slots.append((row, col, x, y, width, height))
        except Exception:
            return []
        return slots

    def _raise_docked_windows_once(self):
        if not self._docked_windows:
            return

        for _, _, hwnd in self._docked_windows:
            if not hwnd or not win32gui.IsWindow(hwnd):
                continue
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetWindowPos( 
                    hwnd, 
                    win32con.HWND_TOPMOST,
                    0, 
                    0, 
                    0, 
                    0, 
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE, 
                )
            except Exception:
                continue

    def raise_docked_windows(self):
        self._raise_docked_windows_once()

    def sync_docked_windows_with_panel(self):
        if not self._docked_windows:
            return

        app_window = self.winfo_toplevel()
        slots = self._get_grid_slots(app_window)
        if not slots:
            return

        for idx, (_, _, hwnd) in enumerate(self._docked_windows):
            if idx >= len(slots):
                break
            if not hwnd or not win32gui.IsWindow(hwnd):
                continue
            _, _, x, y, width, height = slots[idx]
            try:
                if win32gui.IsIconic(hwnd):
                    continue
                win32gui.MoveWindow(hwnd, x, y, width, height, True)
                win32gui.SetWindowPos(
                    hwnd,
                    win32con.HWND_TOPMOST,
                    0,
                    0,
                    0,
                    0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
                )
            except Exception:
                continue

    def set_docked_windows_minimized(self, minimized):
        if not self._docked_windows:
            return
        show_cmd = win32con.SW_MINIMIZE if minimized else win32con.SW_RESTORE
        for _, _, hwnd in self._docked_windows:
            if not hwnd or not win32gui.IsWindow(hwnd):
                continue
            try:
                win32gui.ShowWindow(hwnd, show_cmd)
            except Exception:
                continue

        if not minimized:
            self.sync_docked_windows_with_panel()

    def check_cs2_and_update_colors(self):
        launched_pids = self._get_active_cs2_pids()
        if self.accounts_list_frame:
            self.accounts_list_frame.set_green_for_launched_cs2(launched_pids)

    def set_accounts_list_frame(self, frame):
        self.accounts_list_frame = frame

    def sendCasesMe(self):
        os.system("start https://steamcommunity.com/tradeoffer/new/?partner=1820312068&token=IfT_ec3_")

    def kill_all_cs_and_steam(self):
        """💀 УБИВАЕТ ВСЕ CS2 & Steam процессы + ПРАВИЛЬНЫЕ ЦВЕТА (оранжевые НЕ трогаем!)"""
        print("💀 УБИВАЮ ВСЕ CS2 & Steam процессы!")
        killed = 0
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if "cs2" in name or "steam" in name or "csgo" in name:
                    proc.kill()
                    print(f"💀 [{proc.info['pid']}] {proc.info.get('name')}")
                    killed += 1
            except Exception:
                pass
        print(f"✅ УБИТО {killed} процессов!")

        try:
            account_manager = AccountManager()
            for acc in account_manager.accounts:
                if hasattr(acc, "steamProcess"):
                    acc.steamProcess = None
                if hasattr(acc, "CS2Process"):
                    acc.CS2Process = None
                if self.accounts_list_frame and self.accounts_list_frame.is_farmed_account(acc):
                    acc.setColor("#ff9500")
                elif self.accounts_list_frame and self.accounts_list_frame.is_drop_ready_account(acc):
                    acc.setColor("#a855f7")
                else:
                    acc.setColor("#DCE4EE")
        except Exception as e:
            print(f"⚠️ Ошибка UI: {e}")

        if self.accounts_list_frame:
            self.accounts_list_frame.update_label()

        self._clear_steam_userdata()

    def _clear_steam_userdata(self):
        settings_manager = SettingsManager()
        steam_path = settings_manager.get("SteamPath", r"C:\\Program Files (x86)\\Steam\\steam.exe")
        steam_dir = os.path.dirname(steam_path)
        userdata_path = os.path.join(steam_dir, "userdata")
        if not os.path.isdir(userdata_path):
            print(f"⚠️ userdata папка не найдена: {userdata_path}")
            return

        removed = 0
        for entry in os.listdir(userdata_path):
            entry_path = os.path.join(userdata_path, entry)
            try:
                if os.path.isdir(entry_path):
                    shutil.rmtree(entry_path, ignore_errors=True)
                else:
                    os.remove(entry_path)
                removed += 1
            except Exception as exc:
                print(f"⚠️ Не удалось удалить {entry_path}: {exc}")

        print(f"🧹 userdata очищена, удалено элементов: {removed}")

    def launch_bes(self):
        base_path = (
            os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(sys.argv[0]))
        )
        bes_path = os.path.join(base_path, "BES", "BES.exe")
        if os.path.exists(bes_path):
            try:
                os.startfile(bes_path)
                print("✅ BES запущен!")
            except Exception as e:
                print(f"❌ Ошибка BES: {e}")
        else:
            print(f"❌ BES.exe не найден: {bes_path}")

    def launch_srt(self):
        base_path = (
            os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(sys.argv[0]))
        )
        srt_path = os.path.join(base_path, "SteamRouteTool", "SteamRouteTool.exe")
        if os.path.exists(srt_path):
            try:
                os.startfile(srt_path)
                print("✅ SRT запущен!")
            except Exception as e:
                print(f"❌ Ошибка SRT: {e}")
        else:
            print(f"❌ SRT.exe не найден: {srt_path}")

    def auto_move_after_4_cs2(self, delay=1, callback=None, cancel_check=None):
        """Ждёт 4 окна CS2, двигает их, вызывает callback"""
        with self._auto_move_lock:
            if self._auto_move_active:
             
                return False
            self._auto_move_active = True
        threading.Thread(
            target=self._wait_4_cs2_and_move,
            args=(delay, callback, cancel_check),
            daemon=True,
        ).start()
        return True
    def _press_ctrl_q(self):
        try:
            keyboard.press_and_release("ctrl+q")

            return True
        except Exception as e:
            self.logManager.add_log(f"⚠️ AUTO: failed to press Ctrl+Q: {e}")
            return False
    def _wait_4_cs2_and_move(self, delay, callback, cancel_check):
        """Внутренний метод ожидания + перемещения"""
        print("👀 Ожидаю запуск 4 CS2...")

        start_detect_time = None

        try:
            while True:
                if cancel_check and cancel_check():
                    self.logManager.add_log("🛑 Auto move отменён")
                    return

                cs2_pids = list(self._get_active_cs2_pids())

                if len(cs2_pids) >= 4:
                    if start_detect_time is None:
                        start_detect_time = time.time()
                        self.logManager.add_log(f"⏳ Найдено 4 CS2 → жду {delay} сек")
                    elif time.time() - start_detect_time >= delay:
                        if cancel_check and cancel_check():
                            self.logManager.add_log("🛑 Auto move отменён")
                            return

                        self.logManager.add_log("🚀 Таймер истёк → Make lobbies + Start Game")
                        self.move_all_cs_windows()

                        self._press_ctrl_q()
                        if callback:
                            try:
                                if cancel_check and cancel_check():
                                    self.logManager.add_log("🛑 Callback отменён")
                                    return
                                callback()
                            except Exception as e:
                                self.logManager.add_log(f"❌ Callback error: {e}")
                        return
                else:
                    start_detect_time = None

                time.sleep(2)
        finally:
            with self._auto_move_lock:
                self._auto_move_active = False

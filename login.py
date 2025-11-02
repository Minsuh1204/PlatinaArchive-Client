import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk

import keyring
from keyring.backends import Windows
import requests

keyring.set_keyring(Windows.WinVaultKeyring())
KEYRING_SERVICE_ID = "PlatinaArchiveClient"
KEYRING_USER_ID = "main_api_key"

if getattr(sys, "frozen", False):
    base_dir = os.path.dirname(sys.executable)
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))


def _check_local_key():
    return keyring.get_password(KEYRING_SERVICE_ID, KEYRING_USER_ID)


def delete_local_key():
    keyring.delete_password(KEYRING_SERVICE_ID, KEYRING_USER_ID)


class LoginWindow(tk.Toplevel):
    def __init__(self, parent, success_callback):
        super().__init__(parent)
        self.parent = parent
        self.success_callback = success_callback
        self.title("PLATiNA-ARCHiVE 로그인")
        self.center_window()
        self.transient(parent)
        self.grab_set()
        self.create_widgets()

    def center_window(self):
        self.update_idletasks()
        width = 300
        height = 200

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        x = (screen_width - width) // 2
        y = (screen_height - height) // 2

        self.geometry(f"{width}x{height}+{x}+{y}")

    def create_widgets(self):
        # Decoder name
        ttk.Label(self, text="이름: ").pack(pady=5)
        self.name_entry = ttk.Entry(self)
        self.name_entry.pack(pady=2, padx=10, fill="x")

        # Password
        ttk.Label(self, text="비밀번호: ").pack(pady=5)
        self.password_entry = ttk.Entry(self, show="*")
        self.password_entry.pack(pady=2, padx=10, fill="x")

        # Login button
        ttk.Button(self, text="로그인", command=self.attempt_login).pack(pady=10)
        self.bind("<Return>", lambda x: self.attempt_login())

    def attempt_login(self):
        name = self.name_entry.get().strip()
        password = self.password_entry.get().strip()
        api_login_endpoint = "https://www.platina-archive.app/api/v1/login"
        if not name or not password:
            messagebox.showerror("Error", "이름과 비밀번호는 공백일 수 없습니다.")
            return
        try:
            response = requests.post(
                api_login_endpoint, json={"name": name, "password": password}
            )
            response.raise_for_status()

            data = response.json()
            api_key = data.get("key")

            if api_key:
                keyring.set_password(KEYRING_SERVICE_ID, KEYRING_USER_ID, api_key)
                self.destroy()
                self.success_callback(name, api_key)
            else:
                messagebox.showerror(
                    "Error", "Register failed: Server did not return a key."
                )

        except requests.exceptions.HTTPError as e:
            # Handle 400 (bad creds) or 500 errors
            error_message = response.json().get("msg", "Invalid username or password")
            messagebox.showerror("로그인 실패", error_message)
        except Exception as e:
            messagebox.showerror(
                "Connection Error", f"Could not connect to server: {e}"
            )


class RegisterWindow(tk.Toplevel):
    def __init__(self, parent, success_callback):
        super().__init__(parent)
        self.parent = parent
        self.success_callback = success_callback
        self.title("PLATiNA-ARCHiVE 등록")
        self.center_window()
        self.transient(parent)
        self.grab_set()
        self.create_widgets()

    def center_window(self):
        self.update_idletasks()
        width = 300
        height = 200

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        x = (screen_width - width) // 2
        y = (screen_height - height) // 2

        self.geometry(f"{width}x{height}+{x}+{y}")

    def create_widgets(self):
        # Decoder name
        ttk.Label(self, text="이름: ").pack(pady=5)
        self.name_entry = ttk.Entry(self)
        self.name_entry.pack(pady=2, padx=10, fill="x")

        # Password
        ttk.Label(self, text="비밀번호: ").pack(pady=5)
        self.password_entry = ttk.Entry(self, show="*")
        self.password_entry.pack(pady=2, padx=10, fill="x")

        # Register button
        ttk.Button(self, text="등록", command=self.attempt_register).pack(pady=10)
        self.bind("<Return>", lambda x: self.attempt_register())

    def attempt_register(self):
        name = self.name_entry.get().strip()
        password = self.password_entry.get().strip()
        register_endpoint = "https://www.platina-archive.app/api/v1/register"

        if not name or not password:
            messagebox.showerror("Error", "이름과 비밀번호는 공백일 수 없습니다.")
            return

        try:
            response = requests.post(
                register_endpoint, json={"name": name, "password": password}
            )
            response.raise_for_status()

            data = response.json()
            api_key = data.get("key")

            if api_key:
                keyring.set_password(KEYRING_SERVICE_ID, KEYRING_USER_ID, api_key)
                self.destroy()
                self.success_callback(name, api_key)
            else:
                messagebox.showerror(
                    "Error", "Register failed: Server did not return a key."
                )

        except requests.exceptions.HTTPError as e:
            # Handle 400 (bad creds) or 500 errors
            error_message = response.json().get("msg", "Invalid username or password")
            messagebox.showerror("등록 실패", error_message)
        except Exception as e:
            messagebox.showerror(
                "Connection Error", f"Could not connect to server: {e}"
            )

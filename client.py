from __future__ import annotations

import math
import sys
import os
import threading
import time
import tkinter as tk
from datetime import datetime, timezone
from tkinter import messagebox, ttk

import requests
from PIL import Image, ImageTk
from pynput import keyboard

from analyzer import (
    ScreenshotAnalyzer,
    fetch_archive,
    fetch_songs,
    fetch_latest_client_version,
    version_to_string,
)
from login import RegisterWindow, _check_local_key, load_key_from_file
from models import AnalysisReport, DecodeResult, ArchiveException

VERSION = (0, 2, 5)
current_version_str = version_to_string(VERSION)
if getattr(sys, "frozen", False):
    BASEDIR = os.path.dirname(sys.executable)
else:
    BASEDIR = os.path.dirname(os.path.abspath(__file__))


class PlatinaArchiveClient:
    def __init__(self, app):
        self.app = app
        app.title(f"PLATiNA::ARCHIVE Client {current_version_str}")
        app.geometry("800x600")
        app.resizable(False, False)

        # Set app icon
        icon_path = os.path.join(BASEDIR, "icon.ico")
        if os.path.exists(icon_path):
            self.app.iconbitmap(icon_path)

        app.configure(bg="#E0E0E0")
        app.protocol("WM_DELETE_WINDOW", self._on_close)

        self.hotkey_listener = self._setup_global_hotkey()
        self.hotkey_listener.start()
        self.analyzer = None
        self.archive = None
        self.decoder_name = None
        self.api_key = _check_local_key() or load_key_from_file()

        self.top_frame = ttk.Frame(app, style="Top.TFrame")
        self.top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

        # self.title_label = ttk.Label(self.top_frame, text="Test")

        self.main_content_frame = ttk.Frame(app, style="Main.TFrame")
        self.main_content_frame.pack(
            side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5
        )

        self.jacket_canvas = tk.Canvas(
            self.main_content_frame,
            width=200,
            height=200,
            bg="white",
            relief=tk.FLAT,
            bd=0,
        )
        self.jacket_canvas.grid(
            row=0, column=0, rowspan=3, padx=10, pady=10, sticky="nw"
        )
        self.jacket_photo = None  # For PhotoImage object

        # Info Labels Frame
        self.info_frame = ttk.Frame(self.main_content_frame, style="Info.TFrame")
        self.info_frame.grid(row=0, column=1, rowspan=3, padx=10, pady=10, sticky="nwe")
        self.info_frame.grid_columnconfigure(0, weight=1)  # Allow info frame to expand

        # Song Name
        self.song_name_label = ttk.Label(
            self.info_frame, text="", font=("Roboto", 12, "bold")
        )
        self.song_name_label.pack(anchor="w", pady=2)

        # Judge Rate
        self.judge_rate_label = ttk.Label(
            self.info_frame, text="", font=("Roboto", 12, "bold")
        )
        self.judge_rate_label.pack(anchor="w", pady=2)

        # Score
        self.score_label = ttk.Label(
            self.info_frame, text="", font=("Roboto", 12, "bold")
        )
        self.score_label.pack(anchor="w", pady=2)

        # PATCH
        self.patch_label = ttk.Label(
            self.info_frame, text="", font=("Roboto", 12, "bold")
        )
        self.patch_label.pack(anchor="w", pady=2)

        # Lines and Difficulty (can be on one line or separate)
        self.lines_diff_label = ttk.Label(
            self.info_frame, text="", font=("Roboto", 12, "bold")
        )
        self.lines_diff_label.pack(anchor="w", pady=2)

        # --- Log Output Frame (mimics the lower section) ---
        self.log_frame = ttk.Frame(app, style="Log.TFrame")
        self.log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.log_text = tk.Text(
            self.log_frame,
            wrap=tk.WORD,
            height=10,
            font=("Roboto", 9),
            bg="#F0F0F0",
            fg="black",
        )
        self.log_text.tag_config("general", foreground="black")
        self.log_text.tag_config("error", foreground="red")
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.log_scrollbar = ttk.Scrollbar(self.log_frame, command=self.log_text.yview)
        self.log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=self.log_scrollbar.set)

        # --- Button for Triggering Analysis ---
        self.analyze_button = ttk.Button(
            app, text="Analyze Screenshot (Alt+Insert)", command=self.run_analysis
        )
        self.analyze_button.pack(side=tk.BOTTOM, pady=5)

        self.log_message(
            "Alt+PrtSc, Alt+Insert 단축키를 통해 곡 선택 화면, 결과창에서 기록을 분석할 수 있습니다."
        )

        # --- Button for reloading song DB ---
        self.reload_db_button = ttk.Button(
            app, text="Reload song DB", command=self.load_db
        )
        self.reload_db_button.pack(side=tk.BOTTOM, pady=5)
        latest_version = fetch_latest_client_version()
        if latest_version > VERSION:
            latest_version_str = version_to_string(latest_version)
            self.log_message(
                f"새로운 클라이언트 버전이 탐지되었습니다, 업데이트를 권장드립니다. ({current_version_str} -> {latest_version_str})"
            )
        else:
            self.log_message("클라이언트가 최신 버전입니다.")

        if not self.api_key:
            messagebox.showinfo(
                "플라티나 아카이브 등록",
                "새로운 디코더를 발견 했습니다, 이름과 비밀번호를 설정해주세요.",
            )
            RegisterWindow(self.app, self._handle_successful_register)
        else:
            self.decoder_name = self.api_key.split("::")[0]
            self.log_message(f"{self.decoder_name}님, 환영합니다.")
            self.archive = fetch_archive(self.api_key)
        self.load_db()

    def _handle_successful_register(self, name: str, api_key: str):
        self.decoder_name = name
        self.api_key = api_key
        self.archive = fetch_archive(self.api_key)
        self.log_message(f"등록 성공. 환영합니다, {name}님.")

    def _setup_global_hotkey(self):
        """Setup the global hotkey <Alt+Insert>"""
        hotkeys = {"<alt>+<insert>": self.run_analysis_thread}
        return keyboard.GlobalHotKeys(hotkeys)

    def run_analysis_thread(self):
        """
        Callback function for global hotkey
        It launches the analysis in new thread to avoid freezing the GUI
        """
        thread = threading.Thread(target=self._execute_analysis)
        thread.daemon = True
        thread.start()

    def _execute_analysis(self):
        """Run the analysis"""
        self.log_message("Hotkey detected...")
        try:
            report = self.analyzer.extract_info()
            self.app.after(
                0, self.update_display, report
            )  # Use tkinter's after method to ensure display update is on the main thread
        except ArchiveException as e:
            self.log_error(e)

    def load_db(self):
        # Fetch song data
        song_data = None
        while not song_data:
            try:
                song_data = fetch_songs()
            except:
                time.sleep(0.5)  # Try again after 0.5s
        self.log_message(f"곡 데이터 {len(song_data)}개 로딩 완료")
        self.analyzer = ScreenshotAnalyzer(song_data)

    def log_message(self, msg):
        now = datetime.now()
        structured_time = f"[{now.hour:02d}:{now.minute:02d}:{now.second:02d}] "
        self.log_text.insert(tk.END, structured_time + msg + "\n", "general")
        self.log_text.see(tk.END)

    def log_error(self, err: ArchiveException):
        now = datetime.now()
        structured_time = f"[{now.hour:02d}:{now.minute:02d}:{now.second:02d}] "
        self.log_text.insert(tk.END, structured_time + str(err) + "\n", "error")
        self.log_text.see(tk.END)

    def update_display(self, report: AnalysisReport):
        # Size: 400x400
        resized_jacket_image = report.jacket_image.resize(
            (200, 200), Image.Resampling.LANCZOS
        )
        self.jacket_photo = ImageTk.PhotoImage(resized_jacket_image)
        self.jacket_canvas.delete("all")
        self.jacket_canvas.create_image(0, 0, image=self.jacket_photo, anchor=tk.NW)

        # Update labels
        self.song_name_label.config(text=report.song.title)
        judge_text = f"Judge: {report.judge}% ({report.rank})"
        if report.is_maximum_patch:
            judge_text += " [MAXIMUM P.A.T.C.H.]"
        elif report.is_perfect_decode:
            judge_text += " [PERFECT DECODE]"
        elif report.is_full_combo:
            judge_text += " [FULL COMBO]"
        self.judge_rate_label.config(text=judge_text)
        self.score_label.config(text=f"Score: {report.score:,}")
        self.patch_label.config(text=f"P.A.T.C.H.: {report.patch}")
        self.lines_diff_label.config(
            text=f"{report.line}L {report.difficulty} Lv.{report.level}"
        )

        # Log results
        self.log_message("--- Analysis Complete ---")
        # self.log_message(f"Read hash: {report.jacket_hash}")
        # self.log_message(f"Match distance: {report.match_distance}")
        if report.match_distance > 5:
            self.log_message(
                f"Warning: Jacket match distance {report.match_distance} is high. Result might be uncertain."
            )
        # Do sanity check for ocr-read level
        if not report.level in report.song.get_available_levels(
            report.line, report.difficulty
        ):
            self.log_message(
                f"Warning: Level {report.level} is NOT registered on DB. Result might be uncertain."
            )

        # Compare to user's archive
        archive_key = (
            f"{report.song.id}|{report.line}|{report.difficulty}|{report.level}"
        )
        utc_now = datetime.now(timezone.utc)
        existing_archive = self.archive.get(
            archive_key,
            DecodeResult(
                report.song.id,
                report.line,
                report.difficulty,
                report.level,
                0.0,
                0,
                0.0,
                utc_now,
                False,
                False,
            ),
        )
        if report.judge > existing_archive.judge:
            self.log_higher_score_and_report(report, existing_archive)
            return
        elif report.judge == existing_archive.judge:
            if report.score > existing_archive.score:
                self.log_higher_score_and_report(report, existing_archive)
                return
            elif report.score == existing_archive.score:
                if report.is_full_combo and not existing_archive.is_full_combo:
                    self.log_higher_score_and_report(report, existing_archive)
                    return
        # Not a better score
        dt = utc_now - existing_archive.decoded_at
        dt_msg = f"{dt.days}일, {dt.seconds // 3600}시간 전"
        self.log_message(
            f" [미갱신] {report.song.title} {report.line}L {report.difficulty} Lv.{report.level} ({dt_msg})"
        )
        judge_msg = f"Best Judge: {existing_archive.judge}%"
        if existing_archive.is_max_patch:
            judge_msg += " [MAXIMUM P.A.T.C.H.]"
        elif existing_archive.judge == 100:
            judge_msg += " [PERFECT DECODE]"
        elif existing_archive.is_full_combo:
            judge_msg += " [FULL COMBO]"
        self.log_message(judge_msg)
        self.log_message(f"Best Score: {existing_archive.score:,}")
        self.log_message(f"Best P.A.T.C.H.: {existing_archive.patch}")

    def log_higher_score_and_report(
        self, new_archive: AnalysisReport, existing_archive: DecodeResult
    ):
        self.log_message(
            f" [갱신] {new_archive.song.title} {new_archive.line}L {new_archive.difficulty} Lv.{new_archive.level}"
        )
        judge_msg = f"Judge: {existing_archive.judge}%"
        if existing_archive.judge == 100:
            judge_msg += " [PERFECT DECODE]"
        elif existing_archive.is_full_combo:
            judge_msg += " [FULL COMBO]"
        judge_msg += f" -> {new_archive.judge}%"
        if new_archive.is_maximum_patch:
            judge_msg += " [MAXIMUM P.A.T.C.H.]"
        elif new_archive.is_perfect_decode:
            judge_msg += " [PERFECT DECODE]"
        elif new_archive.is_full_combo:
            judge_msg += " [FULL COMBO]"
        djudge = round(new_archive.judge - existing_archive.judge, 4)
        judge_msg += f" (+{djudge}%p)"

        self.log_message(judge_msg)
        dscore = new_archive.score - existing_archive.score
        if dscore >= 0:
            self.log_message(
                f"Score: {existing_archive.score:,} -> {new_archive.score:,} (+{dscore:,})"
            )
        else:
            self.log_message(
                f"Score: {existing_archive.score:,} -> {new_archive.score:,} ({dscore:,})"
            )
        dpatch = round(new_archive.patch - existing_archive.patch, 2)
        self.log_message(
            f"P.A.T.C.H.: {existing_archive.patch} -> {new_archive.patch} (+{dpatch})"
        )
        if (
            new_archive.is_perfect_decode
            and not new_archive.total_notes == 0
            and not new_archive.is_maximum_patch
        ):
            theoretical_perfect_high = math.ceil(new_archive.total_notes * 0.98)
            need_perfect_high = theoretical_perfect_high - new_archive.perfect_high
            self.log_message(f"패론치까지 단 {need_perfect_high}개!")
        # report higher score to the server
        update_archive_endpoint = (
            "https://www.platina-archive.app/api/v1/update_archive"
        )
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        requests.post(update_archive_endpoint, json=new_archive.json(), headers=headers)
        # update internal archive
        archive_key = f"{new_archive.song.id}|{new_archive.line}|{new_archive.difficulty}|{new_archive.level}"
        internal_archive = self.archive.get(
            archive_key,
            DecodeResult(
                new_archive.song.id,
                new_archive.line,
                new_archive.difficulty,
                new_archive.level,
                0.0,
                0,
                0.0,
                datetime.now(timezone.utc),
                False,
                False,
            ),
        )
        internal_archive.judge = new_archive.judge
        internal_archive.score = new_archive.score
        internal_archive.patch = new_archive.patch
        internal_archive.decoded_at = datetime.now(timezone.utc)
        internal_archive.is_full_combo = new_archive.is_full_combo
        internal_archive.is_max_patch = new_archive.is_maximum_patch
        self.archive[archive_key] = internal_archive

    def _on_close(self):
        """Stops the global hotkey listener and closes the app"""
        self.hotkey_listener.stop()
        self.app.destroy()

    def run_analysis(self, event=None):
        self.log_message("Reading clipboard for image...")
        try:
            report = self.analyzer.extract_info()
            self.update_display(report)
        except ArchiveException as e:
            self.log_error(e)


if __name__ == "__main__":
    root = tk.Tk()

    style = ttk.Style()
    style.theme_use("clam")

    style.configure("Top.TFrame", background="#E0E0E0")
    style.configure("Main.TFrame", background="#F8F8F8")
    style.configure("Info.TFrame", background="#F8F8F8")
    style.configure("Log.TFrame", background="#E0E0E0")
    style.configure("TCheckbutton", background="#E0E0E0")

    client = PlatinaArchiveClient(root)
    root.mainloop()

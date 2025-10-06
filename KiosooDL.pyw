#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import re
import subprocess
import json
import datetime
import webbrowser
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QTextEdit, QProgressBar, QFileDialog, QCheckBox,
    QMessageBox, QListWidget, QListWidgetItem, QTabWidget, QInputDialog,
    QAbstractItemView, QSystemTrayIcon, QTableWidget, QTableWidgetItem,
    QHeaderView, QSpinBox, QStyle
)
from PyQt5.QtCore import (
    QThread, pyqtSignal, Qt, QSettings, QThreadPool, QRunnable, pyqtSlot, QObject,
    QSize
)
from PyQt5.QtGui import QIcon

# --- Application Constants ---
ORG_NAME = "HiepLV"
APP_NAME = "KiosooDL"
APP_VERSION = "2.2" # Version updated for bugfix

# --- Dark Theme Stylesheet ---
DARK_STYLESHEET = """
QWidget {
    background-color: #2b2b2b;
    color: #f0f0f0;
    font-size: 9pt;
}
QTabWidget::pane {
    border-top: 2px solid #3c3c3c;
}
QTabBar::tab {
    background: #2b2b2b;
    border: 1px solid #3c3c3c;
    padding: 8px;
    border-bottom: none;
}
QTabBar::tab:selected, QTabBar::tab:hover {
    background: #3c3c3c;
}
QLineEdit, QTextEdit, QSpinBox {
    background-color: #3c3c3c;
    border: 1px solid #555;
    padding: 5px;
    border-radius: 3px;
}
QPushButton {
    background-color: #555;
    border: 1px solid #666;
    padding: 5px 10px;
    border-radius: 3px;
}
QPushButton:hover {
    background-color: #666;
}
QPushButton:pressed {
    background-color: #444;
}
QComboBox {
    background-color: #3c3c3c;
    border: 1px solid #555;
    padding: 5px;
    border-radius: 3px;
}
QListWidget, QTableWidget {
    background-color: #3c3c3c;
    border: 1px solid #555;
}
QHeaderView::section {
    background-color: #555;
    padding: 4px;
    border: 1px solid #3c3c3c;
}
QProgressBar {
    border: 1px solid #555;
    border-radius: 3px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #0078d7;
}
"""

# -----------------------
# Helper Functions
# -----------------------
def get_subprocess_kwargs():
    kwargs = {}
    if os.name == "nt":
        try:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        except Exception:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = si
    return kwargs

def find_ytdlp_executable():
    exe_names = ["yt-dlp.exe" if os.name == "nt" else "yt-dlp"]
    bundled_path = os.path.join(os.getcwd(), exe_names[0])
    if os.path.exists(bundled_path):
        return bundled_path
    for name in exe_names:
        try:
            cmd = ["where", name] if os.name == "nt" else ["which", name]
            res = subprocess.run(cmd, capture_output=True, text=True, **get_subprocess_kwargs())
            if res.returncode == 0 and res.stdout.strip():
                return name
        except Exception:
            pass
    return "yt-dlp"

YTDLP_CMD = find_ytdlp_executable()

# -----------------------
# Worker Signals
# -----------------------
class WorkerSignals(QObject):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(str, int) # (url, percentage)
    finished_signal = pyqtSignal(dict)

# -----------------------
# Download Worker (QRunnable)
# -----------------------
class DownloadWorker(QRunnable):
    def __init__(self, url_item, quality_key, options, save_path, archive_file, cookies_file):
        super().__init__()
        self.signals = WorkerSignals()
        self.url_item = url_item
        self.url = url_item["url"]
        self.quality_key = quality_key
        self.options = options
        self.save_path = save_path
        self.archive_file = archive_file
        self.cookies_file = cookies_file
        self.process = None
        self._is_stopped = False
        self.video_id = self.url # Initialize with URL as fallback

    def stop(self):
        self._is_stopped = True
        if self.process:
            try:
                self.process.kill()
            except Exception:
                pass
    
    def get_video_id(self):
        try:
            res = subprocess.run([YTDLP_CMD, "--get-id", self.url], capture_output=True, text=True, check=True, **get_subprocess_kwargs())
            self.video_id = res.stdout.strip()
        except Exception:
            # Keep URL as ID if fetching fails
            self.video_id = self.url

    def run(self):
        self.get_video_id()
        self.signals.log_signal.emit(f"▶️ Bắt đầu tải: {self.url}")
        
        output_format = self.options.get("output_format", "mp4")
        is_audio_only = self.options.get("audio_only", False)
        
        if is_audio_only:
            fmt = "bestaudio[ext=m4a]/bestaudio"
        elif self.quality_key == "Best":
            fmt = "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
        elif "p" in self.quality_key:
            res = self.quality_key.replace("p", "")
            fmt = f"bestvideo[height<={res}][vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[height<={res}]+bestaudio/best[height<={res}]"
        else:
            fmt = "bestaudio[ext=m4a]/bestaudio"

        out_template = "%(title)s [%(id)s].%(ext)s"
        if self.options.get("numbering"):
            index = self.url_item.get("batch_index")
            total = self.url_item.get("batch_total")
            if index is not None and total is not None:
                num_digits = len(str(total))
                out_template = f"{index:0{num_digits}d} - {out_template}"

        cmd = [YTDLP_CMD, "-f", fmt, "-o", os.path.join(self.save_path, out_template)]

        if is_audio_only:
            cmd += ["-x", "--audio-format", output_format]
        else:
            cmd += ["--merge-output-format", output_format]

        if self.cookies_file and os.path.exists(self.cookies_file):
            cmd += ["--cookies", self.cookies_file]

        cmd += ["--sleep-interval", "5", "--max-sleep-interval", "10"]

        if self.options.get("subtitle_auto"):
            sub_lang = self.options.get("sub_lang", "auto")
            cmd += ["--write-auto-subs", "--convert-subs", "srt"]
            if sub_lang != "auto":
                cmd += ["--sub-langs", sub_lang]

        if self.options.get("subtitle_manual"):
            cmd += ["--write-subs", "--convert-subs", "srt"]
            sub_lang = self.options.get("sub_lang", "auto")
            if sub_lang != "auto":
                cmd += ["--sub-langs", sub_lang]

        if self.options.get("thumbnail"): cmd += ["--write-thumbnail", "--convert-thumbnails", "jpg"]
        if self.options.get("metadata"): cmd += ["--write-info-json"]
        if self.options.get("sponsorblock"): cmd += ["--sponsorblock-remove", "all"]
        if self.archive_file: cmd += ["--download-archive", self.archive_file]
        
        cmd.append(self.url)

        final_filepath, title, success = "", "", False
        
        try:
            self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1, **get_subprocess_kwargs())
            
            for line in self.process.stdout:
                if self._is_stopped: break
                self.signals.log_signal.emit(line.strip())
                
                m_progress = re.search(r"\[download\]\s+([\d\.]+)%", line)
                if m_progress:
                    self.signals.progress_signal.emit(self.url, int(float(m_progress.group(1))))
                
                m_merge = re.search(r"Merging formats into \"(.*)\"", line)
                if m_merge: final_filepath = m_merge.group(1)
                m_dest = re.search(r"\[download\] Destination: (.*)", line)
                if m_dest and not final_filepath: final_filepath = m_dest.group(1)
                m_audio = re.search(r"\[ExtractAudio\] Destination: (.*)", line)
                if m_audio: final_filepath = m_audio.group(1)

            rc = self.process.wait()
            if self._is_stopped:
                self.signals.log_signal.emit(f"⛔ Đã dừng: {self.url}")
            elif rc == 0:
                self.signals.log_signal.emit(f"✅ Hoàn tất: {self.url}")
                self.signals.progress_signal.emit(self.url, 100)
                success = True
            else:
                self.signals.log_signal.emit(f"⚠️ Lỗi (mã {rc}) khi tải: {self.url}")
        
        except Exception as e:
            self.signals.log_signal.emit(f"❌ Lỗi nghiêm trọng khi tải {self.url}: {e}")
        
        title = os.path.splitext(os.path.basename(final_filepath))[0] if final_filepath else self.video_id
        
        result = {
            "url": self.url, "id": self.video_id, "success": success,
            "filepath": final_filepath, "title": title, "date": datetime.datetime.now().isoformat()
        }
        self.signals.finished_signal.emit(result)

# -----------------------
# Other Worker Threads
# -----------------------
class ListFormatsThread(QThread):
    result_signal = pyqtSignal(list, str); log_signal = pyqtSignal(str)
    def __init__(self, url, cookies_file=None):
        super().__init__(); self.url = url; self.cookies_file = cookies_file
    def run(self):
        self.log_signal.emit(f"📑 Đang lấy formats cho: {self.url}"); cmd = [YTDLP_CMD, "--list-formats", self.url]
        if self.cookies_file and os.path.exists(self.cookies_file): cmd += ["--cookies", self.cookies_file]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True, **get_subprocess_kwargs()); lines = proc.stdout.splitlines(); formats = []
            for line in lines:
                if not line.strip() or re.match(r'^[\-\=]{2,}$', line.strip()) or (re.search(r'format|ID', line, re.I) and not re.match(r'^\s*\d', line)): continue
                parts = line.strip().split()
                if not parts: continue
                formats.append((parts[0], line.rstrip()))
            self.log_signal.emit(f"✅ Lấy được {len(formats)} format."); self.result_signal.emit(formats, self.url)
        except Exception as e: self.log_signal.emit(f"❌ Lỗi khi list formats: {e}"); self.result_signal.emit([], self.url)

class ExtractThread(QThread):
    log_signal = pyqtSignal(str); finished_signal = pyqtSignal(list)
    def __init__(self, url, save_path, batch_size=50):
        super().__init__(); self.url = url; self.save_path = save_path; self.batch_size = batch_size
    def run(self):
        self.log_signal.emit("📑 Bắt đầu trích xuất..."); cmd = [YTDLP_CMD, "--flat-playlist", "--get-id", self.url]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True, **get_subprocess_kwargs()); ids = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
            if not ids: self.log_signal.emit("⚠️ Không tìm thấy video nào."); self.finished_signal.emit([]); return
            links = [f"https://www.youtube.com/watch?v={vid}" for vid in ids]; total = len(links); parts = []
            for i in range(0, total, self.batch_size):
                part = links[i:i+self.batch_size]; start = i+1; end = i + len(part); filename = os.path.join(self.save_path, f"playlist_{start}-{end}.txt")
                with open(filename, "w", encoding="utf-8") as f: f.write("\n".join(part))
                parts.append(filename); self.log_signal.emit(f"✅ Lưu {len(part)} links -> {os.path.basename(filename)}")
            self.log_signal.emit(f"🔚 Trích xuất hoàn tất. Tổng {total} video."); self.finished_signal.emit(parts)
        except Exception as e: self.log_signal.emit(f"❌ Lỗi khi extract: {e}"); self.finished_signal.emit([])

# -----------------------
# Main UI
# -----------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.thread_pool = QThreadPool()
        self.download_queue = []
        self.active_workers = {}
        self.history = []
        self.history_file = os.path.join(os.getcwd(), "history.json")
        self.log_path = os.path.join(os.getcwd(), "log.txt")

        self.init_ui()
        self.load_settings()
        self.load_history()

    def init_ui(self):
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} - By Lý Văn Hiệp")
        self.setWindowIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
        self.setAcceptDrops(True)

        main_layout = QVBoxLayout(self)
        tabs = QTabWidget()
        
        self.setup_download_tab(tabs)
        self.setup_extract_tab(tabs)
        self.setup_batch_tab(tabs)
        self.setup_history_tab(tabs)
        self.setup_settings_tab(tabs)

        main_layout.addWidget(tabs)
        self.log_area = QTextEdit(readOnly=True)
        main_layout.addWidget(QLabel("Log:"))
        main_layout.addWidget(self.log_area)
        
        self.tray_icon = QSystemTrayIcon(self.style().standardIcon(QStyle.SP_ArrowDown), self)
        self.tray_icon.setToolTip(f"{APP_NAME}")
        self.tray_icon.show()

    def setup_download_tab(self, tabs):
        tab = QWidget(); layout = QVBoxLayout(tab)
        
        self.url_input = QTextEdit(placeholderText="Nhập link (mỗi link một dòng) hoặc kéo thả vào đây")
        self.url_input.setFixedHeight(80)
        layout.addWidget(self.url_input)

        grid = QHBoxLayout()
        grid.addWidget(QLabel("Chất lượng:"))
        self.quality_combo = QComboBox(); self.quality_combo.addItems(["Best", "1080p", "720p", "480p"])
        grid.addWidget(self.quality_combo)
        grid.addWidget(QLabel("Định dạng:"))
        self.format_combo = QComboBox(); self.format_combo.addItems(["mp4", "mkv", "webm"])
        grid.addWidget(self.format_combo)
        self.cb_audio_only = QCheckBox("Chỉ âm thanh"); self.cb_audio_only.stateChanged.connect(self.toggle_audio_options)
        grid.addWidget(self.cb_audio_only); grid.addStretch(); layout.addLayout(grid)

        grid2 = QHBoxLayout()
        self.cb_number = QCheckBox("Đánh số"); self.cb_sub_auto = QCheckBox("Phụ đề Auto")
        self.cb_sub_manual = QCheckBox("Phụ đề Manual"); self.cb_thumb = QCheckBox("Thumbnail")
        self.cb_meta = QCheckBox("Metadata"); self.cb_sponsor = QCheckBox("SponsorBlock")
        for w in [self.cb_number, self.cb_sub_auto, self.cb_sub_manual, self.cb_thumb, self.cb_meta, self.cb_sponsor]: grid2.addWidget(w)
        layout.addLayout(grid2)
        
        self.sub_lang_combo = QComboBox()
        self.sub_lang_combo.addItem("Tiếng Anh", "en"); self.sub_lang_combo.addItem("Tiếng Việt", "vi")
        self.sub_lang_combo.addItem("Tiếng Hàn", "ko"); self.sub_lang_combo.addItem("Tiếng Nhật", "ja")
        self.sub_lang_combo.addItem("Tự động (Mặc định)", "auto")
        self.cb_sub_auto.stateChanged.connect(lambda: self.sub_lang_combo.setEnabled(self.cb_sub_auto.isChecked() or self.cb_sub_manual.isChecked()))
        self.cb_sub_manual.stateChanged.connect(lambda: self.sub_lang_combo.setEnabled(self.cb_sub_auto.isChecked() or self.cb_sub_manual.isChecked()))
        layout.addWidget(self.sub_lang_combo)

        path_layout = QHBoxLayout()
        self.folder_input = QLineEdit(placeholderText="Thư mục lưu"); btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self.choose_folder)
        path_layout.addWidget(QLabel("Lưu vào:")); path_layout.addWidget(self.folder_input); path_layout.addWidget(btn_browse)
        layout.addLayout(path_layout)

        cookies_layout = QHBoxLayout()
        self.cookies_input = QLineEdit(placeholderText="Tùy chọn: đường dẫn file cookies.txt"); btn_browse_cookies = QPushButton("Browse...")
        btn_browse_cookies.clicked.connect(self.choose_cookies_file)
        cookies_layout.addWidget(QLabel("Cookies:")); cookies_layout.addWidget(self.cookies_input); cookies_layout.addWidget(btn_browse_cookies)
        layout.addLayout(cookies_layout)
        
        actions = QHBoxLayout()
        self.btn_action = QPushButton(self.style().standardIcon(QStyle.SP_MediaPlay), "Tải xuống")
        self.btn_stop_all = QPushButton(self.style().standardIcon(QStyle.SP_MediaStop), "Dừng tất cả")
        self.btn_list_formats = QPushButton("List Formats")
        for w in [self.btn_action, self.btn_stop_all, self.btn_list_formats]: actions.addWidget(w)
        layout.addLayout(actions)
        
        self.progress_table = QTableWidget(0, 2)
        self.progress_table.setHorizontalHeaderLabels(["Link / Video", "Trạng thái"])
        self.progress_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.progress_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.progress_table.verticalHeader().setVisible(False)
        layout.addWidget(self.progress_table)

        self.btn_action.clicked.connect(self.on_action_clicked)
        self.btn_stop_all.clicked.connect(self.on_stop_all_clicked)
        self.btn_list_formats.clicked.connect(self.on_list_formats_clicked)
        
        tabs.addTab(tab, "Tải xuống")

    def setup_extract_tab(self, tabs):
        tab = QWidget(); layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Link Playlist/Channel:")); self.extract_url_input = QLineEdit()
        layout.addWidget(self.extract_url_input)
        path_layout = QHBoxLayout(); self.extract_folder_input = QLineEdit()
        self.btn_extract_browse = QPushButton("Browse..."); self.btn_extract_browse.clicked.connect(self.choose_folder_extract)
        path_layout.addWidget(QLabel("Lưu vào:")); path_layout.addWidget(self.extract_folder_input); path_layout.addWidget(self.btn_extract_browse)
        layout.addLayout(path_layout)
        self.btn_extract_do = QPushButton("Trích xuất Links ra .txt"); self.btn_extract_do.clicked.connect(self.on_extract_do_clicked)
        layout.addWidget(self.btn_extract_do)
        layout.addWidget(QLabel("Các file batch đã tạo:")); self.extract_batch_list = QListWidget()
        layout.addWidget(self.extract_batch_list); layout.addStretch(); tabs.addTab(tab, "Trích xuất Playlist")

    def setup_batch_tab(self, tabs):
        tab = QWidget(); layout = QVBoxLayout(tab)
        btn_layout = QHBoxLayout(); self.btn_batch_add = QPushButton("Thêm file .txt"); self.btn_batch_remove = QPushButton("Xóa file đã chọn")
        btn_layout.addWidget(self.btn_batch_add); btn_layout.addWidget(self.btn_batch_remove); layout.addLayout(btn_layout)
        self.batch_list = QListWidget(); self.batch_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.batch_list)
        action_layout = QHBoxLayout(); self.btn_batch_download_selected = QPushButton("Tải các file đã chọn")
        action_layout.addWidget(self.btn_batch_download_selected); layout.addLayout(action_layout)
        self.btn_batch_add.clicked.connect(self.on_load_txt_clicked); self.btn_batch_remove.clicked.connect(self.on_remove_batch_clicked)
        self.btn_batch_download_selected.clicked.connect(self.on_batch_download_selected); tabs.addTab(tab, "Quản lý Batch")
        
    def setup_history_tab(self, tabs):
        tab = QWidget(); layout = QVBoxLayout(tab)
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(["Tiêu đề", "Ngày tải", "Trạng thái", "Đường dẫn", "URL"])
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.history_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history_table.customContextMenuRequested.connect(self.history_context_menu)
        layout.addWidget(self.history_table); tabs.addTab(tab, "Lịch sử")

    def setup_settings_tab(self, tabs):
        tab = QWidget(); layout = QVBoxLayout(tab)
        self.cb_dark_mode = QCheckBox("Giao diện tối (Dark Mode)"); self.cb_dark_mode.stateChanged.connect(self.toggle_dark_mode)
        layout.addWidget(self.cb_dark_mode)
        concur_layout = QHBoxLayout(); concur_layout.addWidget(QLabel("Số luồng tải đồng thời:"))
        self.spin_concur_downloads = QSpinBox(minimum=1, maximum=10, value=2); concur_layout.addWidget(self.spin_concur_downloads)
        layout.addLayout(concur_layout)
        self.cb_auto_update_check = QCheckBox("Tự động kiểm tra cập nhật yt-dlp khi khởi động"); layout.addWidget(self.cb_auto_update_check)
        btn_update = QPushButton("Kiểm tra cập nhật yt-dlp ngay"); btn_update.clicked.connect(self.on_update_clicked)
        btn_clear_settings = QPushButton("Xóa cài đặt đã lưu"); btn_clear_settings.clicked.connect(self.clear_settings)
        btn_clear_history = QPushButton("Xóa lịch sử tải xuống"); btn_clear_history.clicked.connect(self.clear_history)
        for w in [btn_update, btn_clear_settings, btn_clear_history]: layout.addWidget(w)
        layout.addStretch(); tabs.addTab(tab, "Cài đặt")

    def on_action_clicked(self):
        urls_text = self.url_input.toPlainText().strip()
        if not urls_text: QMessageBox.warning(self, "Thiếu dữ liệu", "Vui lòng nhập ít nhất một link video."); return
        urls = [line.strip() for line in urls_text.split('\n') if line.strip()]
        self.url_input.clear(); self.add_urls_to_queue(urls)

    def on_stop_all_clicked(self):
        self.log("⛔ Dừng tất cả các lượt tải...")
        self.download_queue.clear()
        for worker in list(self.active_workers.values()): worker.stop()
        self.active_workers.clear(); self.progress_table.setRowCount(0)

    def toggle_audio_options(self, state):
        is_audio = state == Qt.Checked
        self.format_combo.clear()
        self.format_combo.addItems(["mp3", "m4a", "opus", "wav"] if is_audio else ["mp4", "mkv", "webm"])
        self.quality_combo.setEnabled(not is_audio)

    @pyqtSlot(dict)
    def on_single_download_finished(self, result):
        url = result["url"]
        if url in self.active_workers:
            del self.active_workers[url]
        
        self.add_to_history(result)
        self.process_queue()

        for row in range(self.progress_table.rowCount()):
            item = self.progress_table.item(row, 0)
            if item and item.text() == url:
                self.progress_table.removeRow(row)
                break
        
        if not self.active_workers and not self.download_queue:
            self.log("✅ Tất cả các lượt tải đã hoàn tất.")
            self.tray_icon.showMessage("Hoàn tất", "Tất cả các video đã được tải xong.", QSystemTrayIcon.Information, 5000)

    @pyqtSlot(str, int)
    def update_progress(self, url, percentage):
        for row in range(self.progress_table.rowCount()):
            item = self.progress_table.item(row, 0)
            if item and item.text() == url:
                widget = self.progress_table.cellWidget(row, 1)
                if widget:
                    widget.setValue(percentage)
                break

    def add_urls_to_queue(self, urls):
        total = len(urls)
        for i, url in enumerate(urls):
            item = {"url": url, "batch_index": i + 1, "batch_total": total}
            self.download_queue.append(item)
        self.log(f"➕ Đã thêm {len(urls)} link vào hàng chờ.")
        self.process_queue()
    
    def process_queue(self):
        max_concurrent = self.spin_concur_downloads.value()
        while len(self.active_workers) < max_concurrent and self.download_queue:
            url_item = self.download_queue.pop(0)
            url = url_item["url"]
            if url in self.active_workers: continue

            options = {
                "numbering": self.cb_number.isChecked(), "subtitle_auto": self.cb_sub_auto.isChecked(),
                "subtitle_manual": self.cb_sub_manual.isChecked(), "sub_lang": self.sub_lang_combo.currentData(),
                "thumbnail": self.cb_thumb.isChecked(), "metadata": self.cb_meta.isChecked(),
                "sponsorblock": self.cb_sponsor.isChecked(), "audio_only": self.cb_audio_only.isChecked(),
                "output_format": self.format_combo.currentText(),
            }
            save_path = self.folder_input.text() or os.getcwd()
            archive_file = os.path.join(save_path, "download_archive.txt")
            cookies_file = self.cookies_input.text()

            worker = DownloadWorker(url_item, self.quality_combo.currentText(), options, save_path, archive_file, cookies_file)
            worker.signals.log_signal.connect(self.log)
            worker.signals.progress_signal.connect(self.update_progress)
            worker.signals.finished_signal.connect(self.on_single_download_finished)
            
            row_position = self.progress_table.rowCount()
            self.progress_table.insertRow(row_position)
            self.progress_table.setItem(row_position, 0, QTableWidgetItem(url))
            progress_bar = QProgressBar(); progress_bar.setValue(0)
            self.progress_table.setCellWidget(row_position, 1, progress_bar)
            
            self.active_workers[url] = worker
            self.thread_pool.start(worker)

    def load_settings(self):
        self.resize(self.settings.value("size", QSize(950, 800)))
        self.move(self.settings.value("pos", self.pos()))
        self.folder_input.setText(self.settings.value("save_path", os.getcwd()))
        self.cookies_input.setText(self.settings.value("cookies_path", ""))
        self.quality_combo.setCurrentText(self.settings.value("quality", "Best"))
        self.spin_concur_downloads.setValue(int(self.settings.value("max_concurrent", 2)))
        for cb_name in ["number", "sub_auto", "sub_manual", "thumb", "meta", "sponsor", "audio_only", "dark_mode", "auto_update_check"]:
            cb = getattr(self, f"cb_{cb_name}", None)
            if cb: cb.setChecked(self.settings.value(f"cb_{cb_name}", False, type=bool))
        if self.settings.value("auto_update_check", True, type=bool): self.on_update_clicked(silent=True)
    
    def save_settings(self):
        self.settings.setValue("size", self.size())
        self.settings.setValue("pos", self.pos())
        self.settings.setValue("save_path", self.folder_input.text())
        self.settings.setValue("cookies_path", self.cookies_input.text())
        self.settings.setValue("quality", self.quality_combo.currentText())
        self.settings.setValue("max_concurrent", self.spin_concur_downloads.value())
        for cb_name in ["number", "sub_auto", "sub_manual", "thumb", "meta", "sponsor", "audio_only", "dark_mode", "auto_update_check"]:
            cb = getattr(self, f"cb_{cb_name}", None)
            if cb: self.settings.setValue(f"cb_{cb_name}", cb.isChecked())

    def load_history(self):
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f: self.history = json.load(f)
        except Exception as e: self.log(f"⚠️ Không thể tải lịch sử: {e}"); self.history = []
        self.populate_history_table()

    def add_to_history(self, result_dict):
        self.history.insert(0, result_dict); self.populate_history_table()
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f: json.dump(self.history, f, indent=2, ensure_ascii=False)
        except Exception as e: self.log(f"⚠️ Không thể lưu lịch sử: {e}")
    
    def populate_history_table(self):
        self.history_table.setRowCount(0)
        for item in self.history:
            row = self.history_table.rowCount(); self.history_table.insertRow(row)
            self.history_table.setItem(row, 0, QTableWidgetItem(item.get("title", "")))
            date_str = item.get("date", "");
            try: date_str = datetime.datetime.fromisoformat(date_str).strftime("%Y-%m-%d %H:%M")
            except: pass
            self.history_table.setItem(row, 1, QTableWidgetItem(date_str))
            status_item = QTableWidgetItem("✅" if item.get("success") else "❌"); status_item.setTextAlignment(Qt.AlignCenter)
            self.history_table.setItem(row, 2, status_item)
            self.history_table.setItem(row, 3, QTableWidgetItem(item.get("filepath", ""))); self.history_table.setItem(row, 4, QTableWidgetItem(item.get("url", "")))

    def clear_settings(self):
        if QMessageBox.question(self, "Xác nhận", "Bạn có chắc muốn xóa tất cả cài đặt đã lưu?") == QMessageBox.Yes:
            self.settings.clear(); self.log("⚙️ Đã xóa cài đặt.")

    def clear_history(self):
        if QMessageBox.question(self, "Xác nhận", "Bạn có chắc muốn xóa toàn bộ lịch sử tải xuống?") == QMessageBox.Yes:
            self.history = []; self.populate_history_table()
            if os.path.exists(self.history_file): os.remove(self.history_file)
            self.log("🗑️ Đã xóa lịch sử.")
    
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText(): event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasText(): self.url_input.append(event.mimeData().text())
        if event.mimeData().hasUrls():
            urls, txt_files = [], []
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    path = url.toLocalFile()
                    if path.lower().endswith(".txt"): txt_files.append(path)
                else: urls.append(url.toString())
            if urls: self.url_input.append("\n".join(urls))
            if txt_files: self.load_txt_files(txt_files)

    def log(self, msg):
        self.log_area.append(msg)
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())
        try:
            with open(self.log_path, "a", encoding="utf-8", errors='replace') as f:
                f.write(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")
        except: pass

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu", self.folder_input.text() or os.getcwd())
        if folder: self.folder_input.setText(folder)
    
    def choose_cookies_file(self):
        file, _ = QFileDialog.getOpenFileName(self, "Chọn file cookies", "", "Text files (*.txt)")
        if file: self.cookies_input.setText(file)

    def choose_folder_extract(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục", self.extract_folder_input.text() or os.getcwd())
        if folder: self.extract_folder_input.setText(folder)

    def on_update_clicked(self, silent=False):
        self.log("🔄 Kiểm tra cập nhật yt-dlp...")
        try:
            res = subprocess.run([YTDLP_CMD, "-U"], capture_output=True, text=True, **get_subprocess_kwargs())
            output = res.stdout.strip(); self.log(output)
            if not silent: QMessageBox.information(self, "Cập nhật", "yt-dlp đã là phiên bản mới nhất." if "is up to date" in output else f"Kết quả cập nhật:\n\n{output}")
        except Exception as e:
            self.log(f"❌ Lỗi khi cập nhật: {e}")
            if not silent: QMessageBox.warning(self, "Lỗi", f"Không thể cập nhật yt-dlp: {e}")

    def on_list_formats_clicked(self):
        url = self.url_input.toPlainText().strip().split('\n')[0]
        if not url: QMessageBox.warning(self, "Thiếu dữ liệu", "Vui lòng nhập link video."); return
        self.list_thread = ListFormatsThread(url, self.cookies_input.text())
        self.list_thread.log_signal.connect(self.log); self.list_thread.result_signal.connect(self.on_formats_ready); self.list_thread.start()
    
    def on_formats_ready(self, formats, url):
        if not formats: self.log("⚠️ Không có format để hiển thị."); return
        items = [f"{fid}  {line}" for fid, line in formats]
        item, ok = QInputDialog.getItem(self, "Chọn format ID", f"Formats cho:\n{url}", items, 0, False)
        if ok and item:
            selected_id = item.split()[0]; self.log(f"🎯 Đã chọn format tùy chỉnh: {selected_id}")
            QMessageBox.information(self, "Format đã chọn", f"ID Format '{selected_id}' đã được ghi nhận. Để sử dụng, bạn cần xây dựng chuỗi format thủ công và dùng công cụ dòng lệnh.")

    def on_extract_do_clicked(self):
        url = self.extract_url_input.text().strip(); save_path = self.extract_folder_input.text().strip() or os.getcwd()
        if not url: QMessageBox.warning(self, "Thiếu dữ liệu", "Nhập link kênh/playlist"); return
        os.makedirs(save_path, exist_ok=True); self.extract_thread = ExtractThread(url, save_path)
        self.extract_thread.log_signal.connect(self.log); self.extract_thread.finished_signal.connect(self.on_extract_finished); self.extract_thread.start()

    def on_extract_finished(self, generated_files):
        for f in generated_files:
            it = QListWidgetItem(os.path.basename(f)); it.setData(Qt.UserRole, f); self.extract_batch_list.addItem(it)
            if f not in [self.batch_list.item(i).data(Qt.UserRole) for i in range(self.batch_list.count())]:
                i2 = QListWidgetItem(os.path.basename(f)); i2.setData(Qt.UserRole, f); self.batch_list.addItem(i2)
    
    def on_load_txt_clicked(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn file .txt", "", "Text files (*.txt)")
        if files: self.load_txt_files(files)

    def load_txt_files(self, files):
        for file in files:
            if file not in [self.batch_list.item(i).data(Qt.UserRole) for i in range(self.batch_list.count())]:
                item = QListWidgetItem(os.path.basename(file)); item.setData(Qt.UserRole, file); self.batch_list.addItem(item)
                self.log(f"📂 Đã nạp file batch: {file}")

    def on_remove_batch_clicked(self):
        for item in self.batch_list.selectedItems(): self.batch_list.takeItem(self.batch_list.row(item))
            
    def on_batch_download_selected(self):
        selected_items = self.batch_list.selectedItems()
        if not selected_items: QMessageBox.warning(self, "Thiếu dữ liệu", "Vui lòng chọn file .txt trong danh sách."); return
        all_urls = set()
        for item in selected_items:
            filepath = item.data(Qt.UserRole)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    urls_in_file = [line.strip() for line in f if line.strip()]
                    for url in urls_in_file:
                        all_urls.add(url)
            except Exception as e: self.log(f"❌ Lỗi khi đọc file {filepath}: {e}")
        
        # We need to maintain the order from the file for numbering, a set does not do this.
        # Let's read them into a list instead.
        ordered_urls = []
        seen_urls = set()
        for item in selected_items:
            filepath = item.data(Qt.UserRole)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    for line in f:
                        url = line.strip()
                        if url and url not in seen_urls:
                            ordered_urls.append(url)
                            seen_urls.add(url)
            except Exception as e: self.log(f"❌ Lỗi khi đọc file {filepath}: {e}")
            
        if ordered_urls: self.add_urls_to_queue(ordered_urls)
        else: self.log("⚠️ Không tìm thấy URL nào trong các file đã chọn.")

    def toggle_dark_mode(self, state):
        self.setStyleSheet(DARK_STYLESHEET if state == Qt.Checked else "")

    def history_context_menu(self, pos):
        row = self.history_table.rowAt(pos)
        if row < 0: return
        menu = self.history_table.createStandardContextMenu()
        filepath = self.history_table.item(row, 3).text(); url = self.history_table.item(row, 4).text()
        if filepath and os.path.exists(filepath):
            menu.addAction("Mở file").triggered.connect(lambda: webbrowser.open(f"file:///{filepath}"))
            menu.addAction("Mở thư mục chứa file").triggered.connect(lambda: webbrowser.open(f"file:///{os.path.dirname(filepath)}"))
        if url: menu.addAction("Sao chép URL").triggered.connect(lambda: QApplication.clipboard().setText(url))
        menu.exec_(self.history_table.mapToGlobal(pos))
    
    def closeEvent(self, event):
        self.on_stop_all_clicked(); self.thread_pool.waitForDone(); self.save_settings(); event.accept()

# -----------------------
# Entry point
# -----------------------
def main():
    app = QApplication(sys.argv); app.setStyle("Fusion"); win = MainWindow(); win.show(); sys.exit(app.exec_())

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import re
import subprocess
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QTextEdit, QProgressBar, QFileDialog, QCheckBox,
    QRadioButton, QButtonGroup, QMessageBox, QListWidget, QListWidgetItem,
    QTabWidget, QInputDialog, QAbstractItemView
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt

# -----------------------
# Helper: subprocess kwargs to hide windows on Windows
# -----------------------
def get_subprocess_kwargs():
    """
    Returns kwargs dict to pass to subprocess.run / subprocess.Popen so that on
    Windows child console windows are not shown. On other platforms returns {}.
    """
    kwargs = {}
    if os.name == "nt":
        # Prefer CREATE_NO_WINDOW when available
        try:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        except Exception:
            # fallback to STARTUPINFO approach
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = si
    return kwargs

# -----------------------
# Helper: find yt-dlp executable name
# -----------------------
def find_ytdlp_executable():
    exe_names = []
    if os.name == "nt":
        exe_names.append(os.path.join(os.getcwd(), "yt-dlp.exe"))
    else:
        exe_names.append(os.path.join(os.getcwd(), "yt-dlp"))
    exe_names.append("yt-dlp")
    exe_names.append("yt-dlp.exe")
    for name in exe_names:
        try:
            if os.path.isabs(name) and os.path.exists(name):
                return name
            else:
                if os.name == "nt":
                    # use kwargs to avoid popping console
                    res = subprocess.run(["where", name], capture_output=True, text=True, **get_subprocess_kwargs())
                    if res.returncode == 0 and res.stdout.strip():
                        return name
                else:
                    res = subprocess.run(["which", name], capture_output=True, text=True, **get_subprocess_kwargs())
                    if res.returncode == 0 and res.stdout.strip():
                        return name
        except Exception:
            pass
    return "yt-dlp"

YTDLP_CMD = find_ytdlp_executable()

# -----------------------
# Worker thread: List formats
# -----------------------
class ListFormatsThread(QThread):
    result_signal = pyqtSignal(list, str)  # list of (format_id, line), url
    log_signal = pyqtSignal(str)

    def __init__(self, url, cookies_file=None):
        super().__init__()
        self.url = url
        self.cookies_file = cookies_file

    def run(self):
        self.log_signal.emit(f"📑 Đang lấy formats cho: {self.url}")
        cmd = [YTDLP_CMD, "--list-formats", self.url]
        if self.cookies_file and os.path.exists(self.cookies_file):
            cmd += ["--cookies", self.cookies_file]
            self.log_signal.emit(f"🍪 Sử dụng cookies từ: {os.path.basename(self.cookies_file)}")
            
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True, **get_subprocess_kwargs())
            lines = proc.stdout.splitlines()
            formats = []
            # skip header lines until we find a table: heuristics
            for line in lines:
                if not line.strip():
                    continue
                # skip header-like lines
                if re.search(r'format|format code|ID', line, re.I) and len(line.split()) > 1 and not re.match(r'^\s*\d', line):
                    continue
                # skip separator lines
                if re.match(r'^[\-\=]{2,}$', line.strip()):
                    continue
                # attempt to get first token as id
                parts = line.strip().split()
                if not parts:
                    continue
                fid = parts[0]
                # avoid lines that are summary lines like "Sorted by" etc.
                if re.search(r'^[A-Za-z]', fid) and not re.match(r'^\d', fid):
                    # try to find a token that looks like an id
                    found = False
                    for tok in parts:
                        if re.match(r'^[0-9A-Za-z\+\-\.]+$', tok):
                            fid = tok
                            found = True
                            break
                    if not found:
                        continue
                formats.append((fid, line.rstrip()))
            if not formats:
                self.log_signal.emit("⚠️ Không lấy được bất kỳ format nào.")
            else:
                self.log_signal.emit(f"✅ Lấy được {len(formats)} format.")
            self.result_signal.emit(formats, self.url)
        except subprocess.CalledProcessError as e:
            stderr = getattr(e, "stderr", None)
            self.log_signal.emit(f"❌ yt-dlp trả về lỗi khi list formats: {(stderr.strip() if stderr else e)}")
            self.result_signal.emit([], self.url)
        except Exception as e:
            self.log_signal.emit(f"❌ Lỗi khi list formats: {e}")
            self.result_signal.emit([], self.url)

# -----------------------
# Worker: find/extract playlist/channel ids
# -----------------------
class ExtractThread(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(list)

    def __init__(self, url, save_path, batch_size=50):
        super().__init__()
        self.url = url
        self.save_path = save_path
        self.batch_size = batch_size

    def run(self):
        self.log_signal.emit("📑 Bắt đầu trích xuất danh sách video...")
        cmd = [YTDLP_CMD, "--flat-playlist", "--get-id", self.url]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True, **get_subprocess_kwargs())
            ids = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
            if not ids:
                self.log_signal.emit("⚠️ Không tìm thấy video nào.")
                self.finished_signal.emit([])
                return

            links = [f"https://www.youtube.com/watch?v={vid}" for vid in ids]
            total = len(links)
            parts = []
            for i in range(0, total, self.batch_size):
                part = links[i:i+self.batch_size]
                start = i+1
                end = i + len(part)
                filename = os.path.join(self.save_path, f"playlist_{start}-{end}.txt")
                with open(filename, "w", encoding="utf-8") as f:
                    f.write("\n".join(part))
                parts.append(filename)
                self.log_signal.emit(f"✅ Lưu {len(part)} links -> {os.path.basename(filename)}")

            self.log_signal.emit(f"🔚 Trích xuất hoàn tất. Tổng {total} video, chia thành {len(parts)} file.")
            self.finished_signal.emit(parts)

        except subprocess.CalledProcessError as e:
            stderr = getattr(e, "stderr", None)
            self.log_signal.emit(f"❌ Lỗi khi extract: {(stderr.strip() if stderr else e)}")
            self.finished_signal.emit([])
        except Exception as e:
            self.log_signal.emit(f"❌ Lỗi khi extract: {e}")
            self.finished_signal.emit([])

# -----------------------
# Worker thread for downloading
# -----------------------
class DownloadThread(QThread):
    log_signal = pyqtSignal(str)
    percent_signal = pyqtSignal(int)
    finished_signal = pyqtSignal()

    def __init__(self, urls, quality_key, options, save_path, archive_file=None, cookies_file=None):
        super().__init__()
        self.urls = urls[:]
        self.quality_key = quality_key
        self.options = options
        self.save_path = save_path
        self.archive_file = archive_file
        self.cookies_file = cookies_file
        self.process = None
        self._stop_requested = False

    def build_format(self):
        if isinstance(self.quality_key, str) and (self.quality_key.lower().startswith("custom:") or self.quality_key.lower().startswith("format:")):
            return self.quality_key.split(":", 1)[1]
        if self.quality_key == "Best":
            return "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo+bestaudio"
        elif self.quality_key == "720p":
            return ("bestvideo[height<=720][vcodec^=avc1]+bestaudio[ext=m4a]"
                            "/bestvideo[height<=720]+bestaudio")
        elif self.quality_key == "480p":
            return ("bestvideo[height<=480][vcodec^=avc1]+bestaudio[ext=m4a]"
                            "/bestvideo[height<=480]+bestaudio")
        else:
            return "bestaudio[ext=m4a]/bestaudio"

    def run(self):
        fmt = self.build_format()
        total = len(self.urls)
        for idx, url in enumerate(self.urls, start=1):
            if self._stop_requested:
                self.log_signal.emit("⛔ Download stopped by user.")
                break

            self.log_signal.emit(f"▶️ Đang tải video {idx}/{total}: {url}")

            out_template = "%(title)s [%(id)s].%(ext)s"
            if self.options.get("numbering"):
                if total > 1:
                    out_template = f"{idx:03d} - %(title)s [%(id)s].%(ext)s"
                else:
                    out_template = "%(autonumber)s - %(title)s [%(id)s].%(ext)s"

            cmd = [
                YTDLP_CMD,
                "-f", fmt,
                "--merge-output-format", "mp4",
                "-o", os.path.join(self.save_path, out_template),
            ]
            
            # --- NEW: Add cookies if provided ---
            if self.cookies_file and os.path.exists(self.cookies_file):
                cmd += ["--cookies", self.cookies_file]
            # --- END NEW ---

            # --- FIX: Thêm độ trễ để tránh bị YouTube chặn (Lỗi 429) ---
            cmd += ["--sleep-interval", "10"]
            cmd += ["--max-sleep-interval", "20"]
            # --- END FIX ---

            if self.options.get("subtitle"):
                cmd += ["--write-auto-subs", "--convert-subs", "srt"]
            if self.options.get("thumbnail"):
                cmd += ["--write-thumbnail", "--convert-thumbnails", "jpg"]
            if self.options.get("metadata"):
                cmd += ["--write-info-json"]
            if self.options.get("concurrent_fragments", True):
                cmd += ["--concurrent-fragments", "5"]

            if self.archive_file:
                cmd += ["--download-archive", self.archive_file]

            cmd += [url]

            try:
                popen_kwargs = get_subprocess_kwargs()
                self.process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, **popen_kwargs
                )
            except Exception as e:
                self.log_signal.emit(f"❌ Không thể chạy yt-dlp: {e}")
                break

            for raw_line in self.process.stdout:
                if self._stop_requested:
                    try:
                        self.process.terminate()
                        self.process.kill()
                    except Exception:
                        pass
                    self.log_signal.emit("⛔ Download stopped by user.")
                    break

                line = raw_line.rstrip("\n")
                self.log_signal.emit(line)

                m = re.search(r"(\d{1,3}(?:\.\d+)?)%", line)
                if m:
                    try:
                        pct = float(m.group(1))
                        self.percent_signal.emit(max(0, min(100, int(pct))))
                    except Exception:
                        pass

            try:
                rc = self.process.wait()
                if rc == 0:
                    self.percent_signal.emit(100)
                    self.log_signal.emit(f"✅ Hoàn tất video {idx}/{total}")
                elif rc in (3221225786, -1073741510):
                    self.log_signal.emit(f"⛔ Quá trình đã bị hủy (mã exit: {rc}).")
                else:
                    self.log_signal.emit(f"⚠️ yt-dlp trả về mã {rc} cho {url}")
            except Exception as e:
                self.log_signal.emit(f"⚠️ Lỗi khi chờ yt-dlp: {e}")

            self.process = None

        self.finished_signal.emit()

    def stop(self):
        self._stop_requested = True
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass

# -----------------------
# Main UI
# -----------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Downloader By Lý Văn Hiệp")
        self.resize(900, 720) # Increased height for new widget

        # state
        self.download_thread = None
        self.extract_thread = None
        self.list_thread = None
        self.current_batch_files = []
        self.selected_format_id = None
        self.log_path = os.path.join(os.getcwd(), "log.txt")

        # UI layout using QTabWidget
        main_layout = QVBoxLayout()
        tabs = QTabWidget()

        # --- Tab: Download ---
        tab_download = QWidget()
        dl_layout = QVBoxLayout()

        row1 = QHBoxLayout()
        self.url_input = QTextEdit()
        self.url_input.setPlaceholderText("Nhập một hoặc nhiều link video / playlist / channel (mỗi link một dòng)")
        self.url_input.setFixedHeight(80)
        row1.addWidget(QLabel("Link:"))
        row1.addWidget(self.url_input)
        dl_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Chất lượng:"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["Best", "720p", "480p", "Audio"])
        row2.addWidget(self.quality_combo)

        self.cb_number = QCheckBox("Đánh số trước tên")
        self.cb_sub = QCheckBox("Phụ đề auto -> .srt")
        self.cb_thumb = QCheckBox("Thumbnail (jpg)")
        self.cb_meta = QCheckBox("Metadata (.json)")
        row2.addWidget(self.cb_number)
        row2.addWidget(self.cb_sub)
        row2.addWidget(self.cb_thumb)
        row2.addWidget(self.cb_meta)
        dl_layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Thư mục lưu (mặc định: hiện hành)")
        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.clicked.connect(self.choose_folder)
        row3.addWidget(QLabel("Lưu vào:"))
        row3.addWidget(self.folder_input)
        row3.addWidget(self.btn_browse)
        dl_layout.addLayout(row3)
        
        # --- NEW: Cookies file input ---
        row_cookies = QHBoxLayout()
        self.cookies_input = QLineEdit()
        self.cookies_input.setPlaceholderText("Tùy chọn: đường dẫn đến file cookies.txt")
        self.btn_browse_cookies = QPushButton("Browse...")
        self.btn_browse_cookies.clicked.connect(self.choose_cookies_file)
        row_cookies.addWidget(QLabel("File Cookies:"))
        row_cookies.addWidget(self.cookies_input)
        row_cookies.addWidget(self.btn_browse_cookies)
        dl_layout.addLayout(row_cookies)
        # --- END NEW ---

        row4 = QHBoxLayout()
        self.btn_action = QPushButton("Thực hiện")
        self.btn_stop = QPushButton("Stop")
        self.btn_update = QPushButton("Update yt-dlp")
        self.btn_list_formats = QPushButton("List Formats")
        self.btn_load_txt = QPushButton("Load .txt")
        self.btn_open_folder = QPushButton("Mở thư mục")
        row4.addWidget(self.btn_action)
        row4.addWidget(self.btn_stop)
        row4.addWidget(self.btn_list_formats)
        row4.addWidget(self.btn_update)
        row4.addWidget(self.btn_load_txt)
        row4.addWidget(self.btn_open_folder)
        dl_layout.addLayout(row4)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        dl_layout.addWidget(self.progress)

        dl_layout.addWidget(QLabel("Log:"))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        dl_layout.addWidget(self.log_area)

        tab_download.setLayout(dl_layout)
        tabs.addTab(tab_download, "Tải Video")

        # --- Tab: Extract Playlist ---
        tab_extract = QWidget()
        ex_layout = QVBoxLayout()

        ex_row1 = QHBoxLayout()
        self.extract_url_input = QLineEdit()
        self.extract_url_input.setPlaceholderText("Nhập link playlist / channel để extract")
        ex_row1.addWidget(QLabel("Link:"))
        ex_row1.addWidget(self.extract_url_input)
        ex_layout.addLayout(ex_row1)

        ex_row2 = QHBoxLayout()
        self.extract_folder_input = QLineEdit()
        self.extract_folder_input.setPlaceholderText("Thư mục lưu file .txt (mặc định: hiện hành)")
        self.btn_extract_browse = QPushButton("Browse...")
        self.btn_extract_browse.clicked.connect(self.choose_folder_extract)
        self.btn_extract_do = QPushButton("Extract -> .txt (50/link)")
        ex_row2.addWidget(QLabel("Lưu vào:"))
        ex_row2.addWidget(self.extract_folder_input)
        ex_row2.addWidget(self.btn_extract_browse)
        ex_row2.addWidget(self.btn_extract_do)
        ex_layout.addLayout(ex_row2)

        ex_layout.addWidget(QLabel("Các file batch được tạo:"))
        self.extract_batch_list = QListWidget()
        ex_layout.addWidget(self.extract_batch_list)

        tab_extract.setLayout(ex_layout)
        tabs.addTab(tab_extract, "Extract Playlist")

        # --- Tab: Batch Manager ---
        tab_batch = QWidget()
        bm_layout = QVBoxLayout()

        bm_row1 = QHBoxLayout()
        bm_row1.addWidget(QLabel("Danh sách file .txt (batch):"))
        self.btn_batch_add = QPushButton("Add .txt")
        self.btn_batch_remove = QPushButton("Remove Selected")
        bm_row1.addWidget(self.btn_batch_add)
        bm_row1.addWidget(self.btn_batch_remove)
        bm_layout.addLayout(bm_row1)

        self.batch_list = QListWidget()
        self.batch_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        bm_layout.addWidget(self.batch_list)

        bm_row2 = QHBoxLayout()
        self.btn_batch_download_selected = QPushButton("Tải file batch đã chọn")
        self.btn_batch_open_folder = QPushButton("Mở thư mục chứa file")
        bm_row2.addWidget(self.btn_batch_download_selected)
        bm_row2.addWidget(self.btn_batch_open_folder)
        bm_layout.addLayout(bm_row2)

        tab_batch.setLayout(bm_layout)
        tabs.addTab(tab_batch, "Batch Manager")

        main_layout.addWidget(tabs)
        self.setLayout(main_layout)

        # connect signals
        self.btn_action.clicked.connect(self.on_action_clicked)
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        self.btn_update.clicked.connect(self.on_update_clicked)
        self.btn_load_txt.clicked.connect(self.on_load_txt_clicked)
        self.btn_open_folder.clicked.connect(self.on_open_folder_clicked)
        self.btn_list_formats.clicked.connect(self.on_list_formats_clicked)
        self.btn_extract_do.clicked.connect(self.on_extract_do_clicked)
        self.btn_batch_add.clicked.connect(self.on_load_txt_clicked)
        self.btn_batch_remove.clicked.connect(self.on_remove_batch_clicked)
        self.batch_list.itemDoubleClicked.connect(self.on_batch_double_clicked)
        self.btn_batch_download_selected.clicked.connect(self.on_batch_download_selected)
        self.btn_batch_open_folder.clicked.connect(self.on_open_batch_folder_clicked)

    def log(self, msg):
        self.log_area.append(msg)
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu", os.getcwd())
        if folder:
            self.folder_input.setText(folder)
            self.log(f"📂 Đã chọn thư mục: {folder}")
            self.log_path = os.path.join(folder, "log.txt")

    # --- NEW: Cookies file selector ---
    def choose_cookies_file(self):
        file, _ = QFileDialog.getOpenFileName(self, "Chọn file cookies", "", "Text files (*.txt)")
        if file:
            self.cookies_input.setText(file)
            self.log(f"🍪 Đã chọn file cookies: {file}")
    # --- END NEW ---

    def choose_folder_extract(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu extract", os.getcwd())
        if folder:
            self.extract_folder_input.setText(folder)
            self.log(f"📂 Đã chọn thư mục extract: {folder}")

    def on_open_folder_clicked(self):
        folder = self.folder_input.text().strip() or os.getcwd()
        if os.path.exists(folder):
            try:
                if sys.platform.startswith("win"):
                    os.startfile(folder)
                elif sys.platform.startswith("darwin"):
                    subprocess.Popen(["open", folder])
                else:
                    subprocess.Popen(["xdg-open", folder])
            except Exception as e:
                self.log(f"⚠️ Không thể mở thư mục: {e}")
        else:
            self.log("⚠️ Thư mục không tồn tại.")

    def on_open_batch_folder_clicked(self):
        selected = self.batch_list.selectedItems()
        if not selected:
            QMessageBox.information(self, "No selection", "Chọn 1 file trong danh sách batch để mở thư mục.")
            return
        filepath = selected[0].data(Qt.UserRole)
        folder = os.path.dirname(filepath)
        if os.path.exists(folder):
            try:
                if sys.platform.startswith("win"):
                    os.startfile(folder)
                elif sys.platform.startswith("darwin"):
                    subprocess.Popen(["open", folder])
                else:
                    subprocess.Popen(["xdg-open", folder])
            except Exception as e:
                self.log(f"⚠️ Không thể mở thư mục: {e}")

    def on_list_formats_clicked(self):
        url = self.url_input.toPlainText().strip().split('\n')[0]
        if not url:
            QMessageBox.warning(self, "Thiếu dữ liệu", "Vui lòng nhập link video.")
            return
        self.btn_list_formats.setEnabled(False)
        cookies_file = self.cookies_input.text().strip()
        self.list_thread = ListFormatsThread(url, cookies_file)
        self.list_thread.log_signal.connect(self.log)
        self.list_thread.result_signal.connect(self.on_formats_ready)
        self.list_thread.start()

    def on_formats_ready(self, formats, url):
        self.btn_list_formats.setEnabled(True)
        if not formats:
            self.log("⚠️ Không có formats để hiển thị.")
            return

        items = []
        for fid, line in formats:
            rest = line
            m = re.match(r'^\s*' + re.escape(fid) + r'\s*(.*)$', line)
            if m:
                rest = m.group(1).strip()
            items.append(f"{fid}  {rest}")

        item, ok = QInputDialog.getItem(self, "Chọn format ID",
                                      f"Formats khả dụng cho:\n{url}\n\nChọn 1 format để tải (ID sẽ được lưu):",
                                      items, 0, False)
        if ok and item:
            selected_id = item.split()[0]
            self.selected_format_id = selected_id
            self.log(f"🎯 Đã chọn format: {selected_id}")
            custom_label = f"Custom:{selected_id}"
            if custom_label not in [self.quality_combo.itemText(i) for i in range(self.quality_combo.count())]:
                self.quality_combo.addItem(custom_label)
            self.quality_combo.setCurrentText(custom_label)

    def on_update_clicked(self):
        self.log("🔄 Cập nhật yt-dlp...")
        try:
            res = subprocess.run([YTDLP_CMD, "-U"], capture_output=True, text=True, **get_subprocess_kwargs())
            self.log(res.stdout.strip())
            if res.returncode == 0:
                self.log("✅ Update yt-dlp hoàn tất.")
            else:
                self.log(f"⚠️ yt-dlp -U trả về mã {res.returncode}")
        except Exception as e:
            self.log(f"❌ Lỗi update yt-dlp: {e}")

    def on_load_txt_clicked(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn .txt (có thể chọn nhiều)", "", "Text files (*.txt)")
        if not files:
            return
        for file in files:
            if file not in self.current_batch_files:
                self.current_batch_files.append(file)
                item = QListWidgetItem(os.path.basename(file))
                item.setData(Qt.UserRole, file)
                self.batch_list.addItem(item)
                self.log(f"📂 Đã nạp file batch: {file}")
        for f in files:
            try:
                exists = [self.extract_batch_list.item(i).data(Qt.UserRole) for i in range(self.extract_batch_list.count())]
            except Exception:
                exists = []
            if f not in exists:
                it = QListWidgetItem(os.path.basename(f))
                it.setData(Qt.UserRole, f)
                self.extract_batch_list.addItem(it)

    def on_remove_batch_clicked(self):
        selected = self.batch_list.selectedItems()
        if not selected:
            return
        for it in selected:
            filepath = it.data(Qt.UserRole)
            row = self.batch_list.row(it)
            self.batch_list.takeItem(row)
            try:
                self.current_batch_files.remove(filepath)
            except ValueError:
                pass
            self.log(f"🗑️ Đã xóa khỏi batch list: {filepath}")

    def on_batch_double_clicked(self, item):
        filepath = item.data(Qt.UserRole)
        reply = QMessageBox.question(self, "Tải batch",
                                     f"Tải tất cả video trong file:\n{os.path.basename(filepath)} ?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    urls = [ln.strip() for ln in f if ln.strip()]
                if urls:
                    save_path = self.folder_input.text().strip() or os.getcwd()
                    self.start_download(urls, save_path)
            except Exception as e:
                self.log(f"❌ Lỗi khi đọc batch: {e}")

    def on_batch_download_selected(self):
        selected = self.batch_list.selectedItems()
        if not selected:
            QMessageBox.information(self, "Chọn file", "Vui lòng chọn ít nhất một file .txt trong Batch Manager.")
            return
        aggregated = []
        seen = set()
        for it in selected:
            filepath = it.data(Qt.UserRole)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    for ln in f:
                        ln = ln.strip()
                        if not ln:
                            continue
                        if ln not in seen:
                            seen.add(ln)
                            aggregated.append(ln)
            except Exception as e:
                self.log(f"❌ Lỗi khi đọc {filepath}: {e}")

        if not aggregated:
            self.log("⚠️ Không có URL để tải từ các file đã chọn.")
            return

        save_path = self.folder_input.text().strip() or os.getcwd()
        self.start_download(aggregated, save_path)

    def on_action_clicked(self):
        save_path = self.folder_input.text().strip() or os.getcwd()
        if not os.path.isdir(save_path):
            try:
                os.makedirs(save_path, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, "Lỗi", f"Không thể tạo thư mục: {e}")
                return

        urls_from_input = [line.strip() for line in self.url_input.toPlainText().strip().split('\n') if line.strip()]

        if urls_from_input:
            if len(urls_from_input) == 1 and urls_from_input[0].lower().endswith(".txt") and os.path.exists(urls_from_input[0]):
                try:
                    with open(urls_from_input[0], "r", encoding="utf-8") as f:
                        urls = [ln.strip() for ln in f if ln.strip()]
                    if urls:
                        self.start_download(urls, save_path)
                    else:
                        self.log(f"⚠️ File {urls_from_input[0]} rỗng.")
                except Exception as e:
                    self.log(f"❌ Lỗi đọc file {urls_from_input[0]}: {e}")
            else:
                self.start_download(urls_from_input, save_path)
            return

        selected_items = self.batch_list.selectedItems()
        if selected_items:
            self.on_batch_download_selected()
            return

        QMessageBox.warning(self, "Thiếu dữ liệu", "Vui lòng nhập link hoặc chọn một file trong Batch Manager.")

    def start_download(self, urls, save_path):
        options = {
            "numbering": self.cb_number.isChecked(),
            "subtitle": self.cb_sub.isChecked(),
            "thumbnail": self.cb_thumb.isChecked(),
            "metadata": self.cb_meta.isChecked(),
            "concurrent_fragments": True
        }
        quality_key = self.quality_combo.currentText()
        if self.selected_format_id and not quality_key.lower().startswith("custom:"):
            pass

        if quality_key.lower().startswith("custom:"):
            quality_key = quality_key.split(":", 1)[1]

        archive_file = os.path.join(save_path, "downloads.txt")
        self.log_path = os.path.join(save_path, "log.txt")
        
        # --- MODIFIED: Get cookies file path ---
        cookies_file = self.cookies_input.text().strip()
        if cookies_file and not os.path.exists(cookies_file):
            self.log(f"⚠️ File cookies không tồn tại: {cookies_file}. Bỏ qua.")
            cookies_file = None
        elif cookies_file:
             self.log(f"🍪 Sẽ sử dụng cookies từ: {os.path.basename(cookies_file)}")


        self.btn_action.setEnabled(False)
        self.progress.setValue(0)
        self.log(f"▶️ Bắt đầu tải {len(urls)} video vào: {save_path}")

        self.download_thread = DownloadThread(urls, quality_key, options, save_path, archive_file=archive_file, cookies_file=cookies_file)
        self.download_thread.log_signal.connect(self.log)
        self.download_thread.percent_signal.connect(self.progress.setValue)
        self.download_thread.finished_signal.connect(self.on_download_finished)
        self.download_thread.start()

    def on_download_finished(self):
        self.log("✅ Hoàn tất tải.")
        self.btn_action.setEnabled(True)
        self.progress.setValue(100)
        self.download_thread = None

    def on_stop_clicked(self):
        if self.download_thread:
            self.download_thread.stop()
            self.log("⛔ Đã gửi yêu cầu dừng.")
        else:
            self.log("⚠️ Không có tiến trình download.")

    def on_extract_do_clicked(self):
        url = self.extract_url_input.text().strip()
        save_path = self.extract_folder_input.text().strip() or os.getcwd()
        if not url:
            QMessageBox.warning(self, "Thiếu dữ liệu", "Nhập link kênh/playlist để extract")
            return
        if not os.path.isdir(save_path):
            try:
                os.makedirs(save_path, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, "Lỗi", f"Không thể tạo thư mục: {e}")
                return
        self.btn_extract_do.setEnabled(False)
        self.log(f"📑 Extract từ: {url}")
        self.extract_thread = ExtractThread(url, save_path, batch_size=50)
        self.extract_thread.log_signal.connect(self.log)
        self.extract_thread.finished_signal.connect(self.on_extract_finished)
        self.extract_thread.start()

    def on_extract_finished(self, generated_files):
        self.btn_extract_do.setEnabled(True)
        for f in generated_files:
            it = QListWidgetItem(os.path.basename(f))
            it.setData(Qt.UserRole, f)
            self.extract_batch_list.addItem(it)
            if f not in self.current_batch_files:
                self.current_batch_files.append(f)
                i2 = QListWidgetItem(os.path.basename(f))
                i2.setData(Qt.UserRole, f)
                self.batch_list.addItem(i2)
        if generated_files:
            self.log(f"📂 Đã tạo {len(generated_files)} file batch.")
        else:
            self.log("⚠️ Không tạo được file batch.")

# -----------------------
# Entry point
# -----------------------
def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()

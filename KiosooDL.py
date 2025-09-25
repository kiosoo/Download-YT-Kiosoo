#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import re
import subprocess
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QTextEdit, QProgressBar, QFileDialog, QCheckBox,
    QRadioButton, QButtonGroup, QMessageBox, QListWidget, QListWidgetItem
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt

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
                    res = subprocess.run(["where", name], capture_output=True, text=True)
                    if res.returncode == 0 and res.stdout.strip():
                        return name
                else:
                    res = subprocess.run(["which", name], capture_output=True, text=True)
                    if res.returncode == 0 and res.stdout.strip():
                        return name
        except Exception:
            pass
    return "yt-dlp"

YTDLP_CMD = find_ytdlp_executable()

# -----------------------
# Worker thread for downloading
# -----------------------
class DownloadThread(QThread):
    log_signal = pyqtSignal(str)
    percent_signal = pyqtSignal(int)
    finished_signal = pyqtSignal()

    def __init__(self, urls, quality_key, options, save_path):
        super().__init__()
        self.urls = urls[:]
        self.quality_key = quality_key
        self.options = options
        self.save_path = save_path
        self.process = None
        self._stop_requested = False

    def build_format(self):
        if self.quality_key == "Best":
            fmt = "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo+bestaudio"
        elif self.quality_key == "720p":
            fmt = ("bestvideo[height<=720][vcodec^=avc1]+bestaudio[ext=m4a]"
                   "/bestvideo[height<=720]+bestaudio")
        elif self.quality_key == "480p":
            fmt = ("bestvideo[height<=480][vcodec^=avc1]+bestaudio[ext=m4a]"
                   "/bestvideo[height<=480]+bestaudio")
        else:
            fmt = "bestaudio[ext=m4a]/bestaudio"
        return fmt

    def run(self):
        fmt = self.build_format()
        total = len(self.urls)
        for idx, url in enumerate(self.urls, start=1):
            if self._stop_requested:
                self.log_signal.emit("⛔ Download stopped by user.")
                break

            self.log_signal.emit(f"▶️ Đang tải video {idx}/{total}: {url}")

            out_template = "%(title)s.%(ext)s"
            if self.options.get("numbering"):
                out_template = "%(playlist_index)03d - %(title)s.%(ext)s"

            cmd = [
                YTDLP_CMD,
                "-f", fmt,
                "--merge-output-format", "mp4",
                "-o", os.path.join(self.save_path, out_template),
            ]

            if self.options.get("subtitle"):
                cmd += ["--write-auto-subs", "--convert-subs", "srt"]
            if self.options.get("thumbnail"):
                cmd += ["--write-thumbnail", "--convert-thumbnails", "jpg"]
            if self.options.get("metadata"):
                cmd += ["--write-info-json"]
            if self.options.get("concurrent_fragments", True):
                cmd += ["--concurrent-fragments", "5"]
            cmd += [url]

            try:
                self.process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
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
                self.process.kill()
            except Exception:
                pass

# -----------------------
# Worker for extracting playlist/channel
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
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
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

        except Exception as e:
            self.log_signal.emit(f"❌ Lỗi khi extract: {e}")
            self.finished_signal.emit([])

# -----------------------
# Main UI
# -----------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Downloader - All-in-One")
        self.resize(820, 620)

        main = QVBoxLayout()

        row1 = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Nhập link video / playlist / channel")
        row1.addWidget(QLabel("Link:"))
        row1.addWidget(self.url_input)

        self.radio_download = QRadioButton("Tải ngay")
        self.radio_extract = QRadioButton("Extract -> .txt (50/link)")
        self.radio_download.setChecked(True)
        radio_group = QButtonGroup(self)
        radio_group.addButton(self.radio_download)
        radio_group.addButton(self.radio_extract)
        row1.addWidget(self.radio_download)
        row1.addWidget(self.radio_extract)
        main.addLayout(row1)

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
        main.addLayout(row2)

        row3 = QHBoxLayout()
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Thư mục lưu (mặc định: hiện hành)")
        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.clicked.connect(self.choose_folder)
        row3.addWidget(QLabel("Lưu vào:"))
        row3.addWidget(self.folder_input)
        row3.addWidget(self.btn_browse)
        main.addLayout(row3)

        row4 = QHBoxLayout()
        self.btn_action = QPushButton("Thực hiện")
        self.btn_stop = QPushButton("Stop")
        self.btn_update = QPushButton("Update yt-dlp")
        self.btn_load_txt = QPushButton("Load .txt")
        self.btn_open_folder = QPushButton("Mở thư mục")
        row4.addWidget(self.btn_action)
        row4.addWidget(self.btn_stop)
        row4.addWidget(self.btn_update)
        row4.addWidget(self.btn_load_txt)
        row4.addWidget(self.btn_open_folder)
        main.addLayout(row4)

        main.addWidget(QLabel("Danh sách file .txt (batch):"))
        self.batch_list = QListWidget()
        main.addWidget(self.batch_list)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        main.addWidget(self.progress)

        main.addWidget(QLabel("Log:"))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        main.addWidget(self.log_area)
        self.setLayout(main)

        self.download_thread = None
        self.extract_thread = None
        self.current_batch_files = []

        self.btn_action.clicked.connect(self.on_action_clicked)
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        self.btn_update.clicked.connect(self.on_update_clicked)
        self.btn_load_txt.clicked.connect(self.on_load_txt_clicked)
        self.btn_open_folder.clicked.connect(self.on_open_folder_clicked)
        self.batch_list.itemDoubleClicked.connect(self.on_batch_double_clicked)

    def log(self, msg):
        self.log_area.append(msg)
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu", os.getcwd())
        if folder:
            self.folder_input.setText(folder)
            self.log(f"📂 Đã chọn thư mục: {folder}")

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

    def on_action_clicked(self):
        url = self.url_input.text().strip()
        save_path = self.folder_input.text().strip() or os.getcwd()
        if not os.path.isdir(save_path):
            try:
                os.makedirs(save_path, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, "Lỗi", f"Không thể tạo thư mục: {e}")
                return

        if self.radio_download.isChecked():
            selected_items = self.batch_list.selectedItems()
            if selected_items:
                filepath = selected_items[0].data(Qt.UserRole)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        urls = [ln.strip() for ln in f if ln.strip()]
                    if urls:
                        self.start_download(urls, save_path)
                except Exception as e:
                    self.log(f"❌ Lỗi đọc file {filepath}: {e}")
            else:
                if url.lower().endswith(".txt") and os.path.exists(url):
                    try:
                        with open(url, "r", encoding="utf-8") as f:
                            urls = [ln.strip() for ln in f if ln.strip()]
                        if urls:
                            self.start_download(urls, save_path)
                    except Exception as e:
                        self.log(f"❌ Lỗi đọc file {url}: {e}")
                else:
                    if not url:
                        QMessageBox.warning(self, "Thiếu dữ liệu", "Vui lòng nhập link hoặc chọn .txt")
                        return
                    self.start_download([url], save_path)
        else:
            if not url:
                QMessageBox.warning(self, "Thiếu dữ liệu", "Nhập link kênh/playlist để extract")
                return
            self.start_extract(url, save_path)

    def start_download(self, urls, save_path):
        options = {
            "numbering": self.cb_number.isChecked(),
            "subtitle": self.cb_sub.isChecked(),
            "thumbnail": self.cb_thumb.isChecked(),
            "metadata": self.cb_meta.isChecked(),
            "concurrent_fragments": True
        }
        quality_key = self.quality_combo.currentText()
        self.btn_action.setEnabled(False)
        self.progress.setValue(0)
        self.log(f"▶️ Bắt đầu tải {len(urls)} video vào: {save_path}")

        self.download_thread = DownloadThread(urls, quality_key, options, save_path)
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

    def start_extract(self, url, save_path):
        self.btn_action.setEnabled(False)
        self.log(f"📑 Extract từ: {url}")
        self.extract_thread = ExtractThread(url, save_path, batch_size=50)
        self.extract_thread.log_signal.connect(self.log)
        self.extract_thread.finished_signal.connect(self.on_extract_finished)
        self.extract_thread.start()

    def on_extract_finished(self, generated_files):
        self.btn_action.setEnabled(True)
        self.current_batch_files = generated_files
        self.batch_list.clear()
        for f in generated_files:
            item = QListWidgetItem(os.path.basename(f))
            item.setData(Qt.UserRole, f)
            self.batch_list.addItem(item)
        if generated_files:
            self.log(f"📂 Đã tạo {len(generated_files)} file batch.")
        else:
            self.log("⚠️ Không tạo được file batch.")

    def on_load_txt_clicked(self):
        file, _ = QFileDialog.getOpenFileName(self, "Chọn .txt", "", "Text files (*.txt)")
        if not file:
            return
        self.current_batch_files.append(file)
        item = QListWidgetItem(os.path.basename(file))
        item.setData(Qt.UserRole, file)
        self.batch_list.addItem(item)
        self.log(f"📂 Đã nạp file batch: {file}")

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

    def on_update_clicked(self):
        self.log("🔄 Cập nhật yt-dlp...")
        try:
            res = subprocess.run([YTDLP_CMD, "-U"], capture_output=True, text=True)
            self.log(res.stdout.strip())
            if res.returncode == 0:
                self.log("✅ Update yt-dlp hoàn tất.")
            else:
                self.log(f"⚠️ yt-dlp -U trả về mã {res.returncode}")
        except Exception as e:
            self.log(f"❌ Lỗi update yt-dlp: {e}")

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

# YouTube Downloader - All in One (GUI)

Công cụ tải video YouTube bằng **PyQt5 + yt-dlp** với đầy đủ tính năng:
- Tải video đơn, playlist, hoặc cả kênh.
- Trích xuất toàn bộ danh sách video -> chia thành file `.txt` (50 link / file).
- Hỗ trợ tải theo batch từ file `.txt`.
- Tùy chọn chất lượng (ưu tiên H.264, fallback VP9/AV1).
- Tải phụ đề auto (ngôn ngữ gốc) -> `.srt`.
- Tải thumbnail (convert `.jpg`).
- Xuất metadata `.json`.
- Ghi số thứ tự `playlist_index` vào tên file.
- Thanh progress % + log thời gian thực.
- Nút cập nhật yt-dlp trực tiếp trong giao diện.

## 📦 Cài đặt

### 1. Clone repo
```bash
git clone https://github.com/USERNAME/youtube-downloader-gui.git
cd youtube-downloader-gui

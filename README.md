# 🎬 Download-YT-Kiosoo

Ứng dụng GUI tải video YouTube sử dụng [yt-dlp](https://github.com/yt-dlp/yt-dlp).  
Hỗ trợ tải video, playlist, kênh; quản lý batch; chọn format; ghi log ra file.  
Được viết bằng **Python + PyQt5**.

---

## 🚀 Tính năng
- Tải video / playlist / kênh với chất lượng tuỳ chọn.
- **List Formats** → chọn chính xác `format_id` để tải.
- **Batch Manager** → nạp nhiều file `.txt` và tải cùng lúc.
- **Extract Playlist** → tách playlist thành nhiều file `.txt` (50 link / file).
- Tự động bỏ qua video đã tải (`--download-archive downloads.txt`).
- Lưu log ra file `log.txt` để dễ theo dõi batch lớn.
- Giao diện phân tab (Download / Extract Playlist / Batch Manager).

---

## 🛠 Yêu cầu hệ thống

- Python **3.8+**
- Git (để clone repo)
- Windows, Linux hoặc macOS

---

## 📥 Cài đặt

### 1. Cài Python & Git
- Tải [Python](https://www.python.org/downloads/) (tick vào ô *Add to PATH* khi cài đặt).
- Tải [Git](https://git-scm.com/downloads).

### 2. Clone repo
```bash
git clone https://github.com/kiosoo/Download-YT-Kiosoo.git
cd Download-YT-Kiosoo
pip install -r requirements.txt


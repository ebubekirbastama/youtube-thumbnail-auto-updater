import os
import re
import threading
import subprocess
import customtkinter as ctk
from tkinter import messagebox

from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
# www.ebubekirbastama.com.tr
# ==================== AYARLAR ====================
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CREDENTIALS_FILE = "credentials.json"   # Google Cloud'dan aldığın dosya
TOKEN_FILE = "token.json"               # İlk yetkiden sonra oluşacak

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")


# ==================== YARDIMCI FONKSİYONLAR ====================

def get_youtube_service():
    """token.json varsa oradan okur, yoksa bir kere tarayıcıdan yetki ister."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def extract_video_id(url: str):
    m = re.search(r"(?:v=|be/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def parse_time_to_seconds(value: str) -> float:
    """
    12          -> 12 sn
    0:12        -> 12 sn
    2:57        -> 177 sn
    1:05:30     -> 3930 sn
    """
    value = value.strip()
    parts = value.split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        raise ValueError(f"Zaman formatı hatalı: {value}")

    if len(parts) == 1:
        return parts[0]
    elif len(parts) == 2:
        m, s = parts
        return m * 60 + s
    elif len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s
    else:
        raise ValueError(f"Zaman formatı hatalı: {value}")


def capture_frame_at_second(url: str, video_id: str, output_path: str, second: float):
    """
    Videoyu indirir, verilen saniyeden tek kare alır, videoyu siler.
    """
    temp_video = f"temp_{video_id}.mp4"

    # 1) videoyu indir
    subprocess.run([
        "yt-dlp", "-f", "bestvideo[height<=1080]",
        "-o", temp_video, url
    ], check=True)

    # 2) o saniyeden kare al
    subprocess.run([
        "ffmpeg", "-y",
        "-ss", str(second),
        "-i", temp_video,
        "-frames:v", "1",
        "-q:v", "2",
        output_path
    ], check=True)

    if not os.path.exists(output_path):
        raise FileNotFoundError(f"Kare çıkarılamadı: {output_path}")

    # 3) geçici video sil
    if os.path.exists(temp_video):
        os.remove(temp_video)


def upload_thumbnail(youtube, video_id: str, thumbnail_path: str):
    request = youtube.thumbnails().set(
        videoId=video_id,
        media_body=thumbnail_path
    )
    response = request.execute()

    # yüklendiyse resmi sil
    if os.path.exists(thumbnail_path):
        os.remove(thumbnail_path)

    return response


# ==================== UYGULAMA SINIFI ====================

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("🎥 YouTube Thumbnail Otomatikleyici")
        self.geometry("950x720")
        self.minsize(900, 650)

        # satırları tutacağımız liste (her eleman dict: {frame, url_label, time_entry, url})
        self.rows = []

        # üst panel
        top_frame = ctk.CTkFrame(self)
        top_frame.pack(fill="x", padx=15, pady=15)

        ctk.CTkLabel(top_frame, text="YouTube linklerini buraya yapıştır (alt alta):", font=("Segoe UI", 15)).pack(anchor="w")
        self.input_box = ctk.CTkTextbox(top_frame, height=90)
        self.input_box.pack(fill="x", pady=5)

        add_btn = ctk.CTkButton(top_frame, text="⬇️ Listeye Aktar", command=self.add_links_to_list)
        add_btn.pack(pady=5, anchor="e")

        # scrollable liste alanı
        list_frame = ctk.CTkFrame(self)
        list_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        ctk.CTkLabel(list_frame, text="Liste (her satır için zaman girilebilir):", font=("Segoe UI", 15)).pack(anchor="w", pady=(5, 5))

        self.scrollable = ctk.CTkScrollableFrame(list_frame, height=300)
        self.scrollable.pack(fill="both", expand=True)

        # başlık satırı
        header = ctk.CTkFrame(self.scrollable)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        header.grid_columnconfigure(0, weight=5)
        header.grid_columnconfigure(1, weight=1)
        header.grid_columnconfigure(2, weight=0)

        ctk.CTkLabel(header, text="URL", anchor="w").grid(row=0, column=0, padx=5, sticky="w")
        ctk.CTkLabel(header, text="Zaman", anchor="w").grid(row=0, column=1, padx=5, sticky="w")
        ctk.CTkLabel(header, text="Sil").grid(row=0, column=2, padx=5)

        # alt kısım (buton + progress + log)
        bottom_frame = ctk.CTkFrame(self)
        bottom_frame.pack(fill="x", padx=15, pady=(0, 15))

        self.start_btn = ctk.CTkButton(bottom_frame, text="🚀 Başlat", command=self.start_process)
        self.start_btn.pack(side="left", padx=(0, 15), pady=10)

        self.progress_var = ctk.DoubleVar(value=0)
        self.progress_bar = ctk.CTkProgressBar(bottom_frame, variable=self.progress_var)
        self.progress_bar.pack(side="left", fill="x", expand=True, pady=10)

        # log kutusu
        ctk.CTkLabel(self, text="İşlem Günlüğü:", font=("Segoe UI", 15)).pack(anchor="w", padx=15)
        self.log_box = ctk.CTkTextbox(self, height=150)
        self.log_box.pack(fill="both", expand=False, padx=15, pady=(0, 15))

    # ========== SATIR EKLEME ==========

    def add_links_to_list(self):
        text = self.input_box.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Uyarı", "Önce link yapıştır.")
            return

        lines = [l.strip() for l in text.splitlines() if l.strip()]
        current_row_index = len(self.rows) + 1  # header 0'daydı

        for line in lines:
            # her link için satır oluştur
            row_frame = ctk.CTkFrame(self.scrollable)
            row_frame.grid(row=current_row_index, column=0, pady=3, sticky="ew")
            row_frame.grid_columnconfigure(0, weight=5)
            row_frame.grid_columnconfigure(1, weight=1)
            row_frame.grid_columnconfigure(2, weight=0)

            # URL label (uzun olabilir)
            url_label = ctk.CTkLabel(row_frame, text=line, anchor="w", wraplength=500, justify="left")
            url_label.grid(row=0, column=0, padx=5, sticky="w")

            # zaman entry (boş bırakılabilir)
            time_entry = ctk.CTkEntry(row_frame, width=100, placeholder_text="0:12 / 57 / 1:02:30")
            time_entry.grid(row=0, column=1, padx=5, sticky="w")

            # sil butonu
            del_btn = ctk.CTkButton(row_frame, text="X", width=35,
                                    command=lambda rf=row_frame: self.delete_row(rf))
            del_btn.grid(row=0, column=2, padx=5)

            # rows listesine ekle
            self.rows.append({
                "frame": row_frame,
                "url": line,
                "time_entry": time_entry
            })

            current_row_index += 1

        # inputu temizle
        self.input_box.delete("1.0", "end")

    def delete_row(self, frame):
        # rows listesinden de düş
        for r in self.rows:
            if r["frame"] == frame:
                self.rows.remove(r)
                break
        frame.destroy()

    # ========== BAŞLAT ==========

    def start_process(self):
        if not self.rows:
            messagebox.showwarning("Uyarı", "Listede video yok.")
            return

        # butonu kilitle
        self.start_btn.configure(state="disabled")
        self.progress_var.set(0)
        self.log_box.delete("1.0", "end")

        t = threading.Thread(target=self.run_process_thread)
        t.start()

    def run_process_thread(self):
        try:
            youtube = get_youtube_service()
        except Exception as e:
            self.log(f"❌ YouTube yetkilendirme hatası: {e}")
            self.start_btn.configure(state="normal")
            return

        total = len(self.rows)
        done = 0

        for row in list(self.rows):  # kopya üzerinden döneriz
            url = row["url"]
            time_text = row["time_entry"].get().strip()

            # zaman boş ise 0 kabul
            if time_text == "":
                seconds = 0.0
            else:
                try:
                    seconds = parse_time_to_seconds(time_text)
                except ValueError as e:
                    self.log(f"❌ {url} zaman hatası: {e}")
                    done += 1
                    self.progress_var.set(done / total)
                    continue

            video_id = extract_video_id(url)
            if not video_id:
                self.log(f"❌ Geçersiz YouTube linki: {url}")
                done += 1
                self.progress_var.set(done / total)
                continue

            thumb_path = f"thumb_{video_id}.jpg"

            try:
                self.log(f"🎞️ {url} -> {seconds} sn'den kare alınıyor...")
                capture_frame_at_second(url, video_id, thumb_path, seconds)

                self.log(f"⬆️ {video_id} küçük resim yükleniyor...")
                upload_thumbnail(youtube, video_id, thumb_path)

                self.log(f"✅ {video_id} tamamlandı ve resim silindi.\n")
            except Exception as e:
                self.log(f"❌ {url} hata: {e}\n")

            done += 1
            self.progress_var.set(done / total)

        self.log("🟢 Tüm videolar işlendi.")
        self.start_btn.configure(state="normal")

    def log(self, text: str):
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")


if __name__ == "__main__":
    app = App()
    app.mainloop()

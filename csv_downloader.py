import csv
import os
import re
import time
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlparse, unquote
import requests
from requests.adapters import HTTPAdapter, Retry

URL_REGEX = re.compile(r'https?://[^\s,"\'<>]+', re.IGNORECASE)

WIN_RESERVED = {
    "CON","PRN","AUX","NUL",
    "COM1","COM2","COM3","COM4","COM5","COM6","COM7","COM8","COM9",
    "LPT1","LPT2","LPT3","LPT4","LPT5","LPT6","LPT7","LPT8","LPT9"
}

def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = "".join(ch for ch in name if 31 < ord(ch) != 127)
    name = name.rstrip(" .")
    if not name:
        name = "soubor"
    base = os.path.splitext(name)[0]
    ext = os.path.splitext(name)[1]
    if base.upper() in WIN_RESERVED:
        base = f"_{base}"
    safe = (base[:150] + ext) if len(base) > 150 else base + ext
    return safe

def unique_path(folder: str, filename: str) -> str:
    path = os.path.join(folder, filename)
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(filename)
    i = 1
    while True:
        candidate = os.path.join(folder, f"{base} ({i}){ext}")
        if not os.path.exists(candidate):
            return candidate
        i += 1

def filename_from_content_disposition(cd: str) -> str | None:
    if not cd:
        return None
    import urllib.parse
    m = re.search(r'filename\*\s*=\s*[^\'"]*\'\'([^;]+)', cd, flags=re.IGNORECASE)
    if m:
        try:
            return unquote(m.group(1))
        except Exception:
            pass
    m = re.search(r'filename\s*=\s*"([^"]+)"', cd, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'filename\s*=\s*([^;]+)', cd, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None

def pick_csv_and_folder(root) -> tuple[str | None, str | None]:
    root.withdraw()
    csv_path = filedialog.askopenfilename(
        title="Vyber CSV soubor",
        filetypes=[("CSV soubory", "*.csv"), ("Všechny soubory", "*.*")]
    )
    if not csv_path:
        return None, None
    out_dir = filedialog.askdirectory(title="Vyber cílovou složku pro stažené soubory")
    if not out_dir:
        return None, None
    return csv_path, out_dir

def extract_urls_from_csv(csv_path: str) -> list[str]:
    urls: list[str] = []
    seen = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            for cell in row:
                if not cell:
                    continue
                for url in URL_REGEX.findall(cell):
                    url = url.strip().strip('"').strip("'")
                    if url and url.lower().startswith(("http://","https://")):
                        if url not in seen:
                            urls.append(url)
                            seen.add(url)
    return urls

def derive_filename(url: str, response: requests.Response) -> str:
    cd = response.headers.get("Content-Disposition")
    name = filename_from_content_disposition(cd)
    if not name:
        parsed = urlparse(url)
        name = os.path.basename(parsed.path)
        if not name:
            name = "soubor"
    return sanitize_filename(unquote(name))

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("CSV Downloader")
        self.root.geometry("500x300")
        self.root.resizable(False, False)

        tk.Label(self.root, text="Vyber CSV a cílovou složku, poté začne stahování.").pack(padx=16, pady=(16,8))

        self.start_btn = ttk.Button(self.root, text="Vybrat soubory a spustit", command=self.start)
        self.start_btn.pack(pady=8)

        self.progress = ttk.Progressbar(self.root, length=460, mode="determinate")
        self.progress.pack(padx=16, pady=(8, 4))
        self.progress["value"] = 0

        self.status = tk.Label(self.root, text="Připraveno", anchor="w")
        self.status.pack(fill="x", padx=16, pady=(0,4))

        # Proxy a nastavení retry/timeout/rate
        frame_opts = tk.Frame(self.root)
        frame_opts.pack(pady=4, padx=16, fill="x")

        tk.Label(frame_opts, text="Proxy (http://host:port) nepovinné:").grid(row=0, column=0, sticky="w")
        self.proxy_entry = tk.Entry(frame_opts, width=40)
        self.proxy_entry.grid(row=0, column=1, sticky="w")

        tk.Label(frame_opts, text="Retry:").grid(row=1, column=0, sticky="w")
        self.retry_entry = tk.Entry(frame_opts, width=5)
        self.retry_entry.insert(0, "5")
        self.retry_entry.grid(row=1, column=1, sticky="w")

        tk.Label(frame_opts, text="Timeout (s):").grid(row=2, column=0, sticky="w")
        self.timeout_entry = tk.Entry(frame_opts, width=5)
        self.timeout_entry.insert(0, "30")
        self.timeout_entry.grid(row=2, column=1, sticky="w")

        tk.Label(frame_opts, text="Requests per second (0 = max):").grid(row=3, column=0, sticky="w")
        self.rate_entry = tk.Entry(frame_opts, width=5)
        self.rate_entry.insert(0, "0")
        self.rate_entry.grid(row=3, column=1, sticky="w")

        # Stav
        self.urls: list[str] = []
        self.out_dir = ""
        self.total = 0
        self.ok_count = 0
        self.errors: list[str] = []

    def start(self):
        csv_path, out_dir = pick_csv_and_folder(self.root)
        if not csv_path or not out_dir:
            messagebox.showinfo("Zrušeno", "Nebyl vybrán CSV soubor nebo cílová složka.")
            return

        self.out_dir = out_dir
        self.urls = extract_urls_from_csv(csv_path)
        if not self.urls:
            messagebox.showerror("Chyba", "V CSV se nenašly žádné URL (http/https).")
            return

        try:
            self.retry = int(self.retry_entry.get())
            self.timeout = int(self.timeout_entry.get())
            self.rate_limit = float(self.rate_entry.get())
        except Exception:
            messagebox.showerror("Chyba", "Nastavení retry/timeout/rate musí být číslo.")
            return

        proxy_val = self.proxy_entry.get().strip()
        self.proxies = {"http": proxy_val, "https": proxy_val} if proxy_val else None

        self.total = len(self.urls)
        self.progress["maximum"] = self.total
        self.progress["value"] = 0
        self.status.config(text=f"Nalezeno URL: {self.total}. Začínám stahovat…")
        self.start_btn.config(state="disabled")
        self.ok_count = 0
        self.errors = []

        self.session = requests.Session()
        retries = Retry(total=self.retry, backoff_factor=0.5, status_forcelist=[500,502,503,504])
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        threading.Thread(target=self.download_all, daemon=True).start()

    def download_all(self):
        for idx, url in enumerate(self.urls, 1):
            try:
                with self.session.get(url, stream=True, timeout=self.timeout, proxies=self.proxies) as r:
                    r.raise_for_status()
                    filename = derive_filename(url, r)
                    save_path = unique_path(self.out_dir, filename)
                    with open(save_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024*64):
                            if chunk:
                                f.write(chunk)
                self.ok_count += 1
            except Exception as e:
                self.errors.append(f"{url} → {e}")

            # Aktualizace progress bar a status
            self.root.after(0, lambda idx=idx, url=url: self.update_progress(idx, url))

            if self.rate_limit > 0:
                time.sleep(1/self.rate_limit)

        self.root.after(0, self.finish)

    def update_progress(self, idx, url):
        self.progress["value"] = idx
        self.status.config(text=f"Stahuji {idx}/{self.total}: {url}")
        self.root.update_idletasks()

    def finish(self):
        self.start_btn.config(state="normal")
        failed = len(self.errors)
        ok = self.ok_count
        total = self.total
        if failed == 0 and ok == total and total>0:
            messagebox.showinfo("Hotovo", f"Úspěšně staženo {ok}/{total} souborů.")
        else:
            err_preview = "\n".join(self.errors[:10]) if failed else "—"
            messagebox.showwarning(
                "Dokončeno s chybami",
                f"Staženo: {ok}/{total}\nChyby: {failed}\n\nPrvních pár chyb:\n{err_preview}"
            )
        self.status.config(text="Hotovo")

def main():
    app = App()
    app.root.mainloop()

if __name__ == "__main__":
    main()

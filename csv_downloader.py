import csv
import os
import re
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import requests
from urllib.parse import urlparse, unquote

URL_REGEX = re.compile(r'https?://[^\s,"\'<>]+', re.IGNORECASE)

# Windows rezervované názvy
WIN_RESERVED = {
    "CON","PRN","AUX","NUL",
    "COM1","COM2","COM3","COM4","COM5","COM6","COM7","COM8","COM9",
    "LPT1","LPT2","LPT3","LPT4","LPT5","LPT6","LPT7","LPT8","LPT9"
}

def sanitize_filename(name: str) -> str:
    """Očistí název souboru pro Windows/macOS."""
    # odstraníme nebezpečné znaky pro Windows
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    # odstranit neviditelné/řídící znaky
    name = "".join(ch for ch in name if 31 < ord(ch) != 127)
    # oříznout mezery/tečky na konci (Windows)
    name = name.rstrip(" .")
    # prázdné -> default
    if not name:
        name = "soubor"
    base = os.path.splitext(name)[0]
    ext = os.path.splitext(name)[1]
    # kontrola rezervovaných názvů
    if base.upper() in WIN_RESERVED:
        base = f"_{base}"
    # rozumná délka
    safe = (base[:150] + ext) if len(base) > 150 else base + ext
    return safe

def unique_path(folder: str, filename: str) -> str:
    """Vrátí unikátní cestu (přidává ' (1)', ' (2)' před příponu)."""
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
    """Zkusí vytáhnout filename z Content-Disposition."""
    if not cd:
        return None
    # filename* (RFC 5987): filename*=UTF-8''name.ext
    m = re.search(r'filename\*\s*=\s*[^\'"]*\'\'([^;]+)', cd, flags=re.IGNORECASE)
    if m:
        try:
            return unquote(m.group(1))
        except Exception:
            pass
    # filename="name.ext" nebo filename=name.ext
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
    """Najde všechny http(s) URL ve všech sloupcích CSV (odstraní uvozovky/mezery)."""
    urls: list[str] = []
    seen = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            for cell in row:
                if not cell:
                    continue
                # najít všechny URL v buňce
                for url in URL_REGEX.findall(cell):
                    url = url.strip().strip('"').strip("'")
                    if url and url.lower().startswith(("http://","https://")):
                        if url not in seen:
                            urls.append(url)
                            seen.add(url)
    return urls

def derive_filename(url: str, response: requests.Response) -> str:
    """Určí název souboru z hlaviček nebo z URL cesty."""
    cd = response.headers.get("Content-Disposition")
    name = filename_from_content_disposition(cd)
    if not name:
        parsed = urlparse(url)
        name = os.path.basename(parsed.path)
        if not name:
            name = "soubor"
    # dekódovat %20 apod.
    name = unquote(name)
    return sanitize_filename(name)

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("CSV Downloader")
        self.root.geometry("420x140")
        self.root.resizable(False, False)

        # UI (základní okno jen s tlačítkem start)
        self.label = tk.Label(self.root, text="Vyber CSV a cílovou složku, poté začne stahování.")
        self.label.pack(padx=16, pady=(16, 8))

        self.start_btn = ttk.Button(self.root, text="Vybrat soubory a spustit", command=self.start)
        self.start_btn.pack(pady=8)

        self.progress = ttk.Progressbar(self.root, length=360, mode="determinate")
        self.progress.pack(padx=16, pady=(8, 4))
        self.progress["value"] = 0

        self.status = tk.Label(self.root, text="Připraveno", anchor="w")
        self.status.pack(fill="x", padx=16, pady=(0, 8))

        # stav
        self.urls: list[str] = []
        self.out_dir = ""
        self.total = 0
        self.index = 0
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

        self.total = len(self.urls)
        self.progress["maximum"] = self.total
        self.progress["value"] = 0
        self.status.config(text=f"Nalezeno URL: {self.total}. Začínám stahovat…")
        self.start_btn.config(state="disabled")

        # spustit stahování po malém delay (aby se UI stihlo překreslit)
        self.root.after(50, self.download_next)

    def download_next(self):
        if self.index >= self.total:
            # hotovo
            self.finish()
            return

        url = self.urls[self.index]
        self.status.config(text=f"Stahuji {self.index+1}/{self.total}: {url}")
        self.root.update_idletasks()

        try:
            with requests.get(url, stream=True, timeout=30) as r:
                r.raise_for_status()
                filename = derive_filename(url, r)
                save_path = unique_path(self.out_dir, filename)

                bytes_written = 0
                with open(save_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 64):
                        if chunk:
                            f.write(chunk)
                            bytes_written += len(chunk)

                if bytes_written == 0:
                    # smazat prázdný soubor a zapsat chybu
                    try:
                        os.remove(save_path)
                    except Exception:
                        pass
                    raise IOError("Stažen nulový obsah (0 B)")
                self.ok_count += 1

        except Exception as e:
            self.errors.append(f"{url} → {e}")

        # posunout progress
        self.index += 1
        self.progress["value"] = self.index

        # další soubor
        self.root.after(10, self.download_next)

    def finish(self):
        # reaktivovat tlačítko
        self.start_btn.config(state="normal")
        # souhrn
        failed = len(self.errors)
        ok = self.ok_count
        total = self.total
        if failed == 0 and ok == total and total > 0:
            messagebox.showinfo("Hotovo", f"Úspěšně staženo {ok}/{total} souborů.")
        else:
            # ukaž první chyby (aby měl uživatel vodítko)
            err_preview = "\n".join(self.errors[:10]) if failed else "—"
            messagebox.showwarning(
                "Dokončeno s chybami",
                f"Staženo: {ok}/{total}\nChyby: {failed}\n\nPrvních pár chyb:\n{err_preview}"
            )
        self.status.config(text="Hotovo")

def main():
    # Na Windows s PyInstaller --windowed nebývá konzole → vše děláme přes GUI/messagebox
    app = App()
    app.root.mainloop()

if __name__ == "__main__":
    main()

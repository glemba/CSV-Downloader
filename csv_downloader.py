import csv
import os
import tkinter as tk
from tkinter import filedialog, messagebox
import requests
from tqdm import tqdm

def select_csv_file():
    """Nechá uživatele vybrat CSV soubor."""
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Vyber CSV soubor",
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
    )
    return file_path

def select_output_dir():
    """Nechá uživatele vybrat cílovou složku."""
    root = tk.Tk()
    root.withdraw()
    folder_path = filedialog.askdirectory(
        title="Vyber cílovou složku pro stažené soubory"
    )
    return folder_path

def read_urls_from_csv(csv_file):
    """Načte URL adresy z CSV a očistí je od uvozovek a mezer."""
    urls = []
    with open(csv_file, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            url = row[0].strip()
            url = url.strip('"').strip("'")  # odstraní případné uvozovky
            if url:
                urls.append(url)
    return urls

def download_files(urls, output_dir):
    """Stáhne všechny soubory s progress barem."""
    for url in tqdm(urls, desc="Stahování souborů", unit="soubor"):
        try:
            response = requests.get(url, stream=True, timeout=15)
            response.raise_for_status()
            filename = os.path.basename(url.split("?")[0])  # odstraní query parametry
            if not filename:
                filename = "soubor"
            file_path = os.path.join(output_dir, filename)
            with open(file_path, "wb") as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
        except Exception as e:
            print(f"❌ Chyba při stahování {url}: {e}")

def main():
    csv_file = select_csv_file()
    if not csv_file:
        messagebox.showwarning("Zrušeno", "Nebyl vybrán žádný CSV soubor.")
        return

    output_dir = select_output_dir()
    if not output_dir:
        messagebox.showwarning("Zrušeno", "Nebyla vybrána cílová složka.")
        return

    urls = read_urls_from_csv(csv_file)
    if not urls:
        messagebox.showerror("Chyba", "CSV soubor neobsahuje žádné platné URL.")
        return

    download_files(urls, output_dir)
    messagebox.showinfo("Hotovo", "Stahování dokončeno!")

if __name__ == "__main__":
    main()

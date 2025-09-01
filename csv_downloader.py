import csv
import os
import requests
import threading
from tkinter import Tk, filedialog, messagebox, ttk, Label

class DownloaderApp:
    def __init__(self, master):
        self.master = master
        self.master.withdraw()  # hide root window until needed

        # Step 1: select CSV
        csv_path = filedialog.askopenfilename(
            title="Select CSV file",
            filetypes=[("CSV Files", "*.csv")]
        )
        if not csv_path:
            messagebox.showinfo("Cancelled", "No CSV file selected.")
            self.master.destroy()
            return

        # Step 2: select target folder
        target_dir = filedialog.askdirectory(title="Select folder to save downloads")
        if not target_dir:
            messagebox.showinfo("Cancelled", "No folder selected.")
            self.master.destroy()
            return

        self.csv_path = csv_path
        self.target_dir = target_dir

        # Step 3: parse URLs
        self.urls = []
        with open(self.csv_path, newline='', encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                for cell in row:
                    if cell.startswith("http://") or cell.startswith("https://"):
                        self.urls.append(cell)

        if not self.urls:
            messagebox.showinfo("No URLs", "No URLs found in CSV.")
            self.master.destroy()
            return

        # Step 4: show progress window
        self.progress_win = Tk()
        self.progress_win.title("Downloading files...")

        self.label = Label(self.progress_win, text="Downloading...")
        self.label.pack(pady=10)

        self.progress = ttk.Progressbar(
            self.progress_win, length=400, mode="determinate", maximum=len(self.urls)
        )
        self.progress.pack(padx=20, pady=20)

        # Run downloads in separate thread so GUI doesn't freeze
        threading.Thread(target=self.download_files, daemon=True).start()

        self.progress_win.mainloop()

    def download_files(self):
        errors = []
        count = 0

        for url in self.urls:
            try:
                r = requests.get(url, timeout=30)
                if r.status_code == 200:
                    filename = os.path.basename(url.split("?")[0]) or f"file_{count}"
                    save_path = os.path.join(self.target_dir, filename)
                    with open(save_path, "wb") as out:
                        out.write(r.content)
                else:
                    errors.append(f"{url} (HTTP {r.status_code})")
            except Exception as e:
                errors.append(f"{url} ({e})")

            count += 1
            self.progress["value"] = count
            self.label.config(text=f"Downloading {count}/{len(self.urls)}")
            self.progress_win.update_idletasks()

        # After downloads
        self.progress_win.destroy()
        if errors:
            msg = (
                f"Finished with errors.\n\nDownloaded {len(self.urls) - len(errors)} "
                f"files, {len(errors)} failed.\n\nFirst errors:\n" + "\n".join(errors[:5])
            )
        else:
            msg = f"All {len(self.urls)} files downloaded successfully!"
        messagebox.showinfo("Download complete", msg)
        self.master.destroy()

if __name__ == "__main__":
    root = Tk()
    app = DownloaderApp(root)

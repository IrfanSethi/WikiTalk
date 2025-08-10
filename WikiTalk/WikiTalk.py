import tkinter as tk

from wikitalk.gui import AppGUI


if __name__ == "__main__":
    try:
        root = tk.Tk()
        AppGUI(root)
        root.mainloop()
    except KeyboardInterrupt:
        pass

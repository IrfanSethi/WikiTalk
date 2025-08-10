import tkinter as tk

from .gui import AppGUI


def main() -> None:
    root = tk.Tk()
    AppGUI(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any
import tkinter.font as tkfont
import webbrowser

from . import APP_NAME, DB_FILENAME
from .db import Database
from .llm import LLMClient
from .orchestrator import ChatOrchestrator
from .utils import app_data_dir, parse_wikipedia_url
from .wiki import WikipediaClient


# Wikipedia-inspired palette (modern, airy)
WIKI_BG_PAGE = "#f6f7f8"         # page gray (slightly lighter)
WIKI_BG_SIDEBAR = "#f3f4f6"      # subtle contrast for sidebar
WIKI_BG_CONTENT = "#ffffff"      # content white
WIKI_FG_TEXT = "#202122"         # primary text
WIKI_FG_MUTED = "#6a7176"        # muted text (a bit warmer)
WIKI_BORDER = "#dfe2e6"          # lighter subtle border
WIKI_LINK = "#3366cc"            # modern link blue
WIKI_LINK_VISITED = "#7953a9"    # modern visited purple


class AppGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_NAME)
        root.geometry("1100x700")

        # Fonts and theme first
        self._init_fonts()
        self._apply_theme()

        # Core services
        self.db = Database(app_data_dir() / DB_FILENAME)
        self.wiki = WikipediaClient()
        self.llm = LLMClient()
        self.orch = ChatOrchestrator(self.db, self.wiki, self.llm)

        # State
        self.current_session_id = None
        self.network_queue = queue.Queue()
        self._visited_links = set()
        self._current_article_url = None
        # Input history for quick recall
        self._input_history = []
        self._input_history_idx = -1

        # UI
        self._build_ui()
        self._load_sessions()
        self._init_llm_check()
        self._poll_queue()

    # Choose fonts with graceful fallbacks to mimic Wikipedia (serif headings, clean sans body).
    def _init_fonts(self) -> None:
        families = {f.lower(): f for f in tkfont.families()}

        def pick(preferred, size, weight="normal"):
            for fam in preferred:
                key = fam.lower()
                if key in families:
                    return tkfont.Font(family=families[key], size=size, weight=weight)
            return tkfont.Font(size=size, weight=weight)

        # Wikipedia uses a serif for headings and sans-serif for body text
        self.font_heading = pick(["Linux Libertine", "Georgia", "Times New Roman", "Times", "Serif"], 16, "bold")
        self.font_body = pick(["Segoe UI", "Arial", "Helvetica", "Nimbus Sans", "Liberation Sans", "Sans"], 12)
        self.font_mono = pick(["Consolas", "Courier New", "Courier", "Monospace"], 11)
        # Link font based on body with underline
        self.font_link = tkfont.Font(font=self.font_body)
        try:
            self.font_link.configure(underline=1)
        except Exception:
            pass

    # Apply a neutral ttk theme and Wikipedia-like colors/styles
    def _apply_theme(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Root background
        self.root.configure(bg=WIKI_BG_PAGE)

        # Frame styles
        style.configure("Wiki.Page.TFrame", background=WIKI_BG_PAGE)
        style.configure("Wiki.Sidebar.TFrame", background=WIKI_BG_SIDEBAR)
        style.configure("Wiki.TopBar.TFrame", background=WIKI_BG_PAGE)
        style.configure("Wiki.Content.TFrame", background=WIKI_BG_CONTENT)

        # Labels
        style.configure("Wiki.TLabel", background=WIKI_BG_PAGE, foreground=WIKI_FG_TEXT, font=self.font_body)
        style.configure("Wiki.SidebarLabel.TLabel", background=WIKI_BG_SIDEBAR, foreground=WIKI_FG_TEXT, font=self.font_body)
        style.configure("Wiki.Brand.TLabel", background=WIKI_BG_PAGE, foreground=WIKI_FG_TEXT, font=self.font_heading)
        style.configure("Wiki.Muted.TLabel", background=WIKI_BG_PAGE, foreground=WIKI_FG_MUTED, font=self.font_body)

        # Buttons and entries
        style.configure("Wiki.TButton", background=WIKI_BG_PAGE, foreground=WIKI_FG_TEXT, padding=(10, 6), relief="flat")
        style.map("Wiki.TButton", background=[["active", "#eef3f8"]])
        # Primary button (accented) for key actions
        style.configure("Wiki.Primary.TButton", background=WIKI_LINK, foreground="#ffffff", padding=(12, 6), relief="flat")
        style.map("Wiki.Primary.TButton", background=[["active", "#275cbc"]])
        style.configure("Wiki.TEntry", fieldbackground=WIKI_BG_CONTENT, background=WIKI_BG_PAGE, foreground=WIKI_FG_TEXT, padding=(12, 6))
        # Link label
        style.configure("Wiki.Link.TLabel", background=WIKI_BG_PAGE, foreground=WIKI_LINK, font=self.font_link)

        # Scrollbar style (supported options vary by theme)
        try:
            style.configure("Wiki.Vertical.TScrollbar", background=WIKI_BORDER, troughcolor=WIKI_BG_CONTENT, arrowcolor=WIKI_FG_MUTED)
        except Exception:
            pass

    # Prompt for key if missing and run a background sanity check.
    def _init_llm_check(self):
        if not self.llm.available():
            key = simpledialog.askstring(
                "Gemini API Key",
                "Enter your Gemini API key (will be used for this session only).\n"
                "Tip: set it permanently with PowerShell: `\n[Environment]::SetEnvironmentVariable(\"GEMINI_API_KEY\", \"<key>\", \"User\")`",
                parent=self.root,
                show="*",
            )
            if key and key.strip():
                os.environ["GEMINI_API_KEY"] = key.strip()
                self.llm.gemini_api_key = key.strip()

        def work():
            ok, msg = self.llm.sanity_check()
            self.network_queue.put(("llm_ok" if ok else "llm_error", msg))

        threading.Thread(target=work, daemon=True).start()

    # Build the window layout (sessions list, URL bar, chat, input, status).
    def _build_ui(self):
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)

        # Sidebar
        left = ttk.Frame(self.root, padding=6, style="Wiki.Sidebar.TFrame")
        left.grid(row=0, column=0, sticky="nsw")
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)

        # Header with dynamic count
        self.lbl_sessions = ttk.Label(left, text="Sessions", style="Wiki.SidebarLabel.TLabel", font=self.font_heading)
        self.lbl_sessions.grid(row=0, column=0, sticky="w")

        # Filter box
        filter_row = ttk.Frame(left, style="Wiki.Sidebar.TFrame")
        filter_row.grid(row=1, column=0, sticky="ew", pady=(4, 2))
        filter_row.columnconfigure(0, weight=1)
        self.sessions_filter_var = tk.StringVar()
        self.sessions_filter = ttk.Entry(filter_row, textvariable=self.sessions_filter_var, style="Wiki.TEntry")
        self.sessions_filter.grid(row=0, column=0, sticky="ew")
        self.sessions_filter.bind("<KeyRelease>", self._on_sessions_filter)
        self.sessions_filter.bind("<Escape>", lambda e: (self._on_sessions_filter_clear(), "break"))

        self.sessions_list = tk.Listbox(left, height=10)
        self.sessions_list.grid(row=2, column=0, sticky="nsew", pady=(4, 4))
        # Sidebar list visual tweaks
        self.sessions_list.configure(
            bg=WIKI_BG_SIDEBAR,
            fg=WIKI_FG_TEXT,
            selectbackground="#eaf3ff",
            selectforeground=WIKI_FG_TEXT,
            highlightthickness=1,
            highlightbackground=WIKI_BORDER,
            relief="flat",
            activestyle="none",
        )
        self.sessions_list.bind("<<ListboxSelect>>", self._on_select_session)
        self.sessions_list.bind("<Double-Button-1>", self._on_rename_session)

        btns = ttk.Frame(left, style="Wiki.Sidebar.TFrame")
        btns.grid(row=3, column=0, sticky="ew")
        ttk.Button(btns, text="New", style="Wiki.TButton", command=self._new_session).pack(side=tk.LEFT)
        ttk.Button(btns, text="Delete", style="Wiki.TButton", command=self._delete_session).pack(side=tk.LEFT, padx=(6, 0))

        # Context menu for sessions list (right-click)
        self.sessions_menu = tk.Menu(self.root, tearoff=0)
        self.sessions_menu.add_command(label="New Session", command=self._new_session)
        self.sessions_menu.add_command(label="Rename", command=self._on_rename_session)
        self.sessions_menu.add_command(label="Delete", command=self._delete_session)
        self.sessions_list.bind("<Button-3>", self._on_sessions_context)

        # Main area
        main = ttk.Frame(self.root, padding=6, style="Wiki.Page.TFrame")
        main.grid(row=0, column=1, sticky="nsew")
        # Expand chat row (2); keep input row (3) non-expanding
        main.rowconfigure(2, weight=1)
        main.rowconfigure(3, weight=0)
        main.columnconfigure(0, weight=1)

        # Top bar with brand and URL
        top = ttk.Frame(main, style="Wiki.TopBar.TFrame")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        # Brand row
        brand = ttk.Frame(top, style="Wiki.TopBar.TFrame")
        brand.grid(row=0, column=0, columnspan=3, sticky="ew")
        ttk.Label(brand, text="WikiTalk", style="Wiki.Brand.TLabel").pack(side=tk.LEFT)
        ttk.Label(brand, text=" · a Wikipedia chat companion", style="Wiki.Muted.TLabel").pack(side=tk.LEFT, padx=(4, 0))
        # URL row
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Wikipedia URL:", style="Wiki.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.entry_article = ttk.Entry(top, style="Wiki.TEntry")
        self.entry_article.grid(row=1, column=1, sticky="ew", padx=(6, 6), pady=(6, 0))
        ttk.Button(top, text="Load", style="Wiki.Primary.TButton", command=self._load_article_clicked).grid(row=1, column=2, pady=(6, 0))
        self.lbl_article = ttk.Label(top, text="No article loaded", style="Wiki.Muted.TLabel")
        self.lbl_article.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 8))

        # Divider line
        try:
            divider = ttk.Separator(main, orient="horizontal")
        except Exception:
            divider = tk.Frame(main, height=1, bg=WIKI_BORDER, bd=0, highlightthickness=0)
        divider.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        # Content "card" with subtle border
        content = tk.Frame(main, bg=WIKI_BG_CONTENT, highlightbackground=WIKI_BORDER, highlightthickness=1, bd=0)
        content.grid(row=2, column=0, sticky="nsew")
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)

        # Chat text inside content card
        self.chat = tk.Text(content, wrap=tk.WORD, state=tk.DISABLED, bg=WIKI_BG_CONTENT, fg=WIKI_FG_TEXT, relief="flat")
        self.chat.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.chat.configure(font=self.font_body, insertbackground=WIKI_FG_TEXT, spacing1=4, spacing3=8)
        self.chat.tag_configure("user", foreground=WIKI_LINK, font=(self.font_body.actual("family"), self.font_body.actual("size"), "bold"))
        self.chat.tag_configure("assistant", foreground=WIKI_FG_TEXT, font=self.font_body)
        self.chat.tag_configure("meta", foreground=WIKI_FG_MUTED, font=self.font_body)
        # message block styling
        try:
            self.chat.tag_configure("sep", lmargin1=0, lmargin2=0, rmargin=0, spacing1=4, spacing3=8)
            self.chat.tag_configure("bubble_user", background="#f0f6ff")
            self.chat.tag_configure("bubble_assistant", background="#fafafa")
        except Exception:
            pass
        self.chat.tag_configure("link", foreground=WIKI_LINK, underline=True, font=self.font_body)
        self.chat.tag_configure("link_visited", foreground=WIKI_LINK_VISITED, underline=True, font=self.font_body)
        self.chat.tag_bind("link", "<Enter>", lambda e: self.chat.config(cursor="hand2"))
        self.chat.tag_bind("link", "<Leave>", lambda e: self.chat.config(cursor=""))
        self.chat.tag_bind("link_visited", "<Enter>", lambda e: self.chat.config(cursor="hand2"))
        self.chat.tag_bind("link_visited", "<Leave>", lambda e: self.chat.config(cursor=""))
        yscroll = ttk.Scrollbar(content, orient="vertical", command=self.chat.yview, style="Wiki.Vertical.TScrollbar")
        self.chat.configure(yscrollcommand=yscroll.set)
        yscroll.grid(row=0, column=1, sticky="ns", pady=8)

        # Bottom input area
        bottom = ttk.Frame(main, style="Wiki.Page.TFrame")
        bottom.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        bottom.columnconfigure(0, weight=1)
        # Single-line message entry that visually matches the Send button
        self._msg_var = tk.StringVar()
        self.entry_msg = ttk.Entry(bottom, style="Wiki.TEntry", textvariable=self._msg_var)
        self.entry_msg.grid(row=0, column=0, sticky="ew", ipady=4)
        self.entry_msg.bind("<Return>", self._on_entry_return)
        self.entry_msg.bind("<Up>", self._on_entry_history_up)
        self.entry_msg.bind("<Down>", self._on_entry_history_down)
        self.btn_send = ttk.Button(bottom, text="Send", style="Wiki.Primary.TButton", command=self._send_clicked)
        self.btn_send.grid(row=0, column=1, padx=(6, 0))
        # Enable/disable Send based on content
        def _toggle_send(*_):
            try:
                has_text = bool(self._msg_var.get().strip())
                state = tk.NORMAL if has_text else tk.DISABLED
                self.btn_send.configure(state=state)
            except Exception:
                pass
        self._msg_var.trace_add("write", _toggle_send)
        _toggle_send()

        # Status bar
        self.status = ttk.Label(main, text="Ready", anchor="w", style="Wiki.Muted.TLabel")
        self.status.grid(row=4, column=0, sticky="ew", pady=(6, 0))

        # Make article label clickable to open the source in browser
        def _open_article(event=None):
            try:
                if self._current_article_url:
                    webbrowser.open(self._current_article_url)
            except Exception:
                pass

        self.lbl_article.bind("<Button-1>", _open_article)
        self.lbl_article.configure(cursor="hand2")
        # Focus input on load
        try:
            self.entry_msg.focus_set()
        except Exception:
            pass

    def _init_message_placeholder(self) -> None:
        """Add a subtle placeholder to the message box and handle focus."""
        placeholder = "Ask anything about the article…"
        muted = "#9aa0a6"
        active = WIKI_FG_TEXT

        def set_placeholder():
            self.entry_msg.configure(state=tk.NORMAL)
            if not self.entry_msg.get("1.0", tk.END).strip():
                self.entry_msg.insert("1.0", placeholder)
                self.entry_msg.tag_add("ph", "1.0", tk.END)
                self.entry_msg.tag_configure("ph", foreground=muted)
                self._placeholder_active = True

        def clear_placeholder():
            if getattr(self, "_placeholder_active", False):
                self.entry_msg.delete("1.0", tk.END)
                self.entry_msg.tag_delete("ph")
                self._placeholder_active = False

        def on_focus_in(event):
            if getattr(self, "_placeholder_active", False):
                clear_placeholder()

        def on_focus_out(event):
            if not self.entry_msg.get("1.0", tk.END).strip():
                set_placeholder()

        self.entry_msg.bind("<FocusIn>", on_focus_in)
        self.entry_msg.bind("<FocusOut>", on_focus_out)
        set_placeholder()

    # Populate sessions list and select one (or create a new session).
    def _load_sessions(self):
        self.sessions_list.delete(0, tk.END)
        all_sessions = self.db.list_sessions()
        self._sessions_cache = all_sessions
        # Apply filter if any
        q = getattr(self, "sessions_filter_var", tk.StringVar()).get().strip().lower() if hasattr(self, "sessions_filter_var") else ""
        if q:
            sessions = [s for s in all_sessions if q in (s[1] or "").lower() or q in (s[4] or "").lower()]
        else:
            sessions = all_sessions
        # Update header count
        if hasattr(self, "lbl_sessions"):
            try:
                self.lbl_sessions.configure(text=f"Sessions ({len(sessions)})")
            except Exception:
                pass
        for s in sessions:
            # tuple: id, name, created_at, language, article_title, article_url
            sid, name, created_at, language, article_title, *_ = s
            label = name
            if article_title:
                label += f"  ·  {article_title}"
            self.sessions_list.insert(tk.END, label)
        if sessions:
            self.sessions_list.select_set(0)
            self._select_session_by_index(0)
        else:
            self._new_session()

    # Create a new session and select it.
    def _new_session(self):
        name = simpledialog.askstring("New Session", "Enter a name:", parent=self.root) or f"Session {int(time.time())}"
        sid = self.db.create_session(name)
        self._load_sessions()
        for idx, s in enumerate(self._sessions_cache):
            if s[0] == sid:
                self.sessions_list.select_clear(0, tk.END)
                self.sessions_list.select_set(idx)
                self._select_session_by_index(idx)
                break

    # Delete the selected session.
    def _delete_session(self):
        idxs = self.sessions_list.curselection()
        if not idxs:
            return
        idx = idxs[0]
        sid = self._sessions_cache[idx][0]
        if messagebox.askyesno("Delete Session", "Delete this session and its messages?"):
            self.db.delete_session(sid)
            self._load_sessions()
            self._clear_chat()

    # Prompt to rename the selected session.
    def _on_rename_session(self, event=None):
        idxs = self.sessions_list.curselection()
        if not idxs:
            return
        idx = idxs[0]
        sid, name, *_ = self._sessions_cache[idx]
        new_name = simpledialog.askstring("Rename Session", "New name:", initialvalue=name, parent=self.root)
        if new_name and new_name.strip():
            self.db.rename_session(sid, new_name.strip())
            self._load_sessions()

    # Handle selecting a session from the list.
    def _on_select_session(self, event=None):
        idxs = self.sessions_list.curselection()
        if not idxs:
            return
        self._select_session_by_index(idxs[0])

    def _on_sessions_filter(self, event=None):
        # Reload list according to current filter text; keep best-effort selection
        sel = self.sessions_list.curselection()
        selected_idx = sel[0] if sel else None
        self._load_sessions()
        if selected_idx is not None and selected_idx < self.sessions_list.size():
            self.sessions_list.select_set(selected_idx)

    def _on_sessions_filter_clear(self):
        if hasattr(self, "sessions_filter_var"):
            self.sessions_filter_var.set("")
        self._load_sessions()

    def _on_sessions_context(self, event):
        try:
            self.sessions_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.sessions_menu.grab_release()

    # Apply the selected session and reload chat from DB.
    def _select_session_by_index(self, idx: int):
        s = self._sessions_cache[idx]
        self.current_session_id = s[0]
        article_title = s[4]
        article_url = s[5] if len(s) > 5 else None
        self.lbl_article.configure(text=(article_title or "No article loaded"))
        # Restore URL field and click-through link
        try:
            self.entry_article.delete(0, tk.END)
            if article_url:
                self.entry_article.insert(0, article_url)
            self._current_article_url = article_url
        except Exception:
            pass
        self._reload_chat()

    # Reload chat history into the chat view.
    def _reload_chat(self):
        if self.current_session_id is None:
            return
        self._clear_chat()
        for mid, session_id, role, text, created_at, citations in self.db.list_messages(self.current_session_id):
            self._append_chat(role, text)
            if citations:
                try:
                    c = json.loads(citations)
                    src = c.get("article", {})
                    secs = c.get("sections", [])
                    line = f"Sources: {src.get('title','')}  {src.get('url','')}  Sections: {', '.join(secs)}"
                    self._append_meta(line)
                except Exception:
                    pass

    # Clear the chat text widget.
    def _clear_chat(self):
        self.chat.configure(state=tk.NORMAL)
        self.chat.delete("1.0", tk.END)
        self.chat.configure(state=tk.DISABLED)

    # Append a message to the chat view with simple role styling.
    def _append_chat(self, role: str, text: str):
        self.chat.configure(state=tk.NORMAL)
        # visual separator between messages
        if self.chat.index("end-1c") != "1.0":
            self._insert_separator()
        if role == "user":
            self.chat.insert(tk.END, "You:\n", ("user",))
            self.chat.insert(tk.END, text + "\n\n", ("assistant", "bubble_user"))
        else:
            self.chat.insert(tk.END, "WikiTalk:\n", ("user",))
            self.chat.insert(tk.END, text + "\n\n", ("assistant", "bubble_assistant"))
        self.chat.configure(state=tk.DISABLED)
        self.chat.see(tk.END)

    # Append a metadata line (sources/citations) below a message.
    def _append_meta(self, text: str):
        """Append citation/info line and render URLs as clickable links."""
        self.chat.configure(state=tk.NORMAL)
        if "http" in text:
            before, sep, after = text.partition("http")
            self.chat.insert(tk.END, before, ("meta",))
            if sep:
                url_token = "http" + after.split()[0]
                self._insert_link(url_token)
                remaining = after[len(url_token) - 4:]
                self.chat.insert(tk.END, remaining, ("meta",))
        else:
            self.chat.insert(tk.END, text, ("meta",))
        self.chat.insert(tk.END, "\n\n", ("meta",))
        self.chat.configure(state=tk.DISABLED)
        self.chat.see(tk.END)

    def _insert_link(self, url: str, label: str | None = None) -> None:
        label = label or url
        start = self.chat.index(tk.END)
        self.chat.insert(tk.END, label)
        end = self.chat.index(tk.END)
        # Use a unique tag per link to avoid handler collisions
        base_tag = "link_visited" if url in self._visited_links else "link"
        unique_tag = f"{base_tag}_{start}"
        self.chat.tag_add(unique_tag, start, end)
        # Ensure style of unique tag matches base
        for option in ("foreground", "underline", "font"):
            try:
                self.chat.tag_configure(unique_tag, **{option: self.chat.tag_cget(base_tag, option)})
            except Exception:
                pass

        def open_link(event, u=url, s=start, e=end, ut=unique_tag):
            try:
                webbrowser.open(u)
                self._visited_links.add(u)
                # swap visual style to visited
                self.chat.tag_configure(ut, foreground=WIKI_LINK_VISITED, underline=True)
            except Exception:
                pass

        self.chat.tag_bind(unique_tag, "<Button-1>", open_link)

    def _on_entry_return(self, event):
        self._send_clicked()
        return "break"

    def _on_entry_history_up(self, event):
        if not getattr(self, "_input_history", None):
            return "break"
        if self._input_history_idx == -1:
            self._input_history_idx = len(self._input_history) - 1
        else:
            self._input_history_idx = max(0, self._input_history_idx - 1)
        val = self._input_history[self._input_history_idx] if self._input_history else ""
        if hasattr(self, "_msg_var"):
            self._msg_var.set(val)
        else:
            self.entry_msg.delete(0, tk.END)
            self.entry_msg.insert(0, val)
        return "break"

    def _on_entry_history_down(self, event):
        if not getattr(self, "_input_history", None):
            return "break"
        if self._input_history_idx == -1:
            return "break"
        self._input_history_idx += 1
        if self._input_history_idx >= len(self._input_history):
            self._input_history_idx = -1
            if hasattr(self, "_msg_var"):
                self._msg_var.set("")
            else:
                self.entry_msg.delete(0, tk.END)
        else:
            val = self._input_history[self._input_history_idx]
            if hasattr(self, "_msg_var"):
                self._msg_var.set(val)
            else:
                self.entry_msg.delete(0, tk.END)
                self.entry_msg.insert(0, val)
        return "break"

    def _insert_separator(self) -> None:
        try:
            # Insert a small spacer line
            self.chat.insert(tk.END, "\n", ("sep",))
            sep_frame = tk.Frame(self.chat, height=2, bg="#e8ebef", bd=0, highlightthickness=0)
            self.chat.window_create(tk.END, window=sep_frame)
            self.chat.insert(tk.END, "\n", ("sep",))
        except Exception:
            # Fallback to a simple dashed line if embedding fails
            self.chat.insert(tk.END, "\n", ("sep",))
            self.chat.insert(tk.END, "-" * 60 + "\n", ("meta",))

    # Handle sending a user question; run answer generation in a thread.
    def _send_clicked(self):
        if self.current_session_id is None:
            messagebox.showinfo(APP_NAME, "Create or select a session first.")
            return
        # Read from the Entry's StringVar if present
        msg = (self._msg_var.get().strip() if hasattr(self, "_msg_var") else self.entry_msg.get().strip())
        if not msg:
            return
        # Maintain input history and clear the field
        try:
            if not self._input_history or self._input_history[-1] != msg:
                self._input_history.append(msg)
            self._input_history_idx = -1
        except Exception:
            pass
        if hasattr(self, "_msg_var"):
            self._msg_var.set("")
        else:
            self.entry_msg.delete(0, tk.END)
        self.db.add_message(self.current_session_id, "user", msg)
        self._append_chat("user", msg)
        self._set_status("Thinking…")

        def work():
            try:
                answer, citations = self.orch.answer_question(self.current_session_id, msg)
                self.network_queue.put(("answer", (answer, citations)))
            except Exception as e:
                self.network_queue.put(("error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    # Load and cache the article specified in the URL bar; save selection to the session.
    def _load_article_clicked(self):
        if self.current_session_id is None:
            messagebox.showinfo(APP_NAME, "Create or select a session first.")
            return
        url_text = self.entry_article.get().strip()
        if not url_text:
            messagebox.showinfo(APP_NAME, "Paste a Wikipedia URL (e.g., https://en.wikipedia.org/wiki/Alan_Turing).")
            return
        self._set_status("Loading article…")

        def work():
            try:
                lang, title = parse_wikipedia_url(url_text)
                self.wiki.language = lang
                data = self.wiki.fetch_page_extract(title)
                if not data:
                    raise ValueError("Article not found.")
                real_title = data.get("title", title)
                self.db.upsert_article(
                    real_title,
                    lang,
                    data.get("pageid"),
                    data.get("revision_id"),
                    data.get("url"),
                    data.get("extract", ""),
                )
                self.db.set_session_article(self.current_session_id, real_title, data.get("url"))
                self.db.set_session_language(self.current_session_id, lang)
                # store URL for click-through
                self._current_article_url = data.get("url")
                self.network_queue.put(("article", real_title))
            except Exception as e:
                self.network_queue.put(("error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    # Process background events from worker threads (answers, status, errors).
    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.network_queue.get_nowait()
                if kind == "answer":
                    answer, citations = payload
                    self.db.add_message(self.current_session_id, "assistant", answer, citations)
                    self._append_chat("assistant", answer)
                    src = citations.get("article", {})
                    secs = citations.get("sections", [])
                    line = f"Sources: {src.get('title','')}  {src.get('url','')}  Sections: {', '.join(secs)}"
                    self._append_meta(line)
                    self._set_status("Ready")
                    self._refresh_session_label_article()
                elif kind == "article":
                    title = payload
                    self.lbl_article.configure(text=title)
                    self._set_status(f"Loaded: {title}")
                    # Reflect current URL into the URL entry for persistence/visibility
                    try:
                        self.entry_article.delete(0, tk.END)
                        if self._current_article_url:
                            self.entry_article.insert(0, self._current_article_url)
                    except Exception:
                        pass
                    self._refresh_session_label_article()
                elif kind == "llm_ok":
                    self._set_status(payload or "Gemini ready")
                elif kind == "llm_error":
                    self._set_status("Gemini not ready")
                    messagebox.showwarning(
                        APP_NAME,
                        (payload or "Gemini check failed.")
                        + "\n\nSet your key in PowerShell and restart VS Code:\n"
                        + "[Environment]::SetEnvironmentVariable(\"GEMINI_API_KEY\", \"<key>\", \"User\")",
                    )
                elif kind == "error":
                    self._set_status("Error")
                    messagebox.showerror(APP_NAME, str(payload))
                else:
                    pass
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._poll_queue)

    # Refresh session list UI to display updated article titles without losing selection.
    def _refresh_session_label_article(self):
        sel = self.sessions_list.curselection()
        selected_idx = sel[0] if sel else None
        self._load_sessions()
        if selected_idx is not None and selected_idx < self.sessions_list.size():
            self.sessions_list.select_set(selected_idx)

    # Update the status bar text.
    def _set_status(self, text: str):
        self.status.configure(text=text)

# WikiTalk

## Introduction
WikiTalk is a modern desktop application that lets you chat with Wikipedia articles using advanced language models. It provides a clean, Wikipedia-inspired interface for exploring topics, asking questions, and getting concise, well-cited answers—all powered by Gemini and live Wikipedia data.

Instead of passively reading long articles, you can engage in conversations asking questions, clarifying concepts, and exploring topics in more depth. The application uses Google’s Gemini language model to deliver accurate, context aware answers, always grounded in the latest Wikipedia content.

## Features
- Chat with Wikipedia articles using Gemini LLM (Google AI)
- Search and load articles in any language
- Context-aware Q&A with citations to article sections
- Session management: save, rename, and delete chat histories
- Fast, local caching of articles for offline use
- Wikipedia-inspired UI with modern, accessible design
- No account required; works locally

## Screenshots
> ![WikiTalk]()

## Installation

1. Clone the repository:
```powershell
git clone https://github.com/yourusername/wikitalk.git
cd wikitalk
```

2. Create and activate a Python 3.12+ virtual environment:
```powershell
python -m venv env
.\env\Scripts\Activate.ps1
```

3. Install dependencies:
```powershell
pip install -r requirements.txt
```

4. (Optional) Set your Gemini API key:
   - Set the `GEMINI_API_KEY` environment variable.

## Usage

1. Run the application:
 ```powershell
python WikiTalk.py
```

2. Search for a Wikipedia article, select it, and start chatting!
3. Manage sessions, ask questions, and explore answers with citations.

## Technologies

- Python 3.12+
- Tkinter (GUI)
- SQLite (local database)
- Gemini LLM (Google AI, via API)
- Wikipedia API

## Why This Project

WikiTalk was created to make Wikipedia exploration more interactive and accessible. Instead of reading long articles, you can ask direct questions and get concise, cited answers. It’s ideal for students, researchers, and anyone curious about the world—without ads, distractions, or privacy concerns.

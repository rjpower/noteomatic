# NoteOMatic: From Handwriting to Digital Notes

Transform your handwritten notes into searchable digital content with ease.

![Before: Handwritten Note](static/notebook.webp)
![After: Digital Note View](static/note-view.webp)

In addition to the transcription and rendering of your (if like mine) terrible
handwriting, you also get automatic tagging, hyperlinking, a nice note index and
more!

# Installation

Install UV:

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

# Configuration

Configuration is managed by Pydantic-Settings; you can use either a .env file or
environment variables to adjust the configuration. By default you'll only need a
Gemini API key to load notes:

```
export NOTEOMATIC_GEMINI_API_KEY=...
```

# Running the server

```
uv run flask --app noteomatic.app:app run --port=8000 [--host=...]
```

# Importing Notes

You can import notes via the web interace (just click the upload link), by
syncing with a Google Drive file (you'll need to setup your own application and
OAuth credentials for this), or via the command line.

## Sync with Google Drive

You can sync with a Google Drive folder using the `sync` command. You'll need to
create a Google OAuth credential with Google Drive access, and put the client
secrets into `credentials/client_secret.json`:

https://console.cloud.google.com/auth/scopes

```
uv run scripts/manage.py sync
```

## Syncing files on disk

Alternatively, you can load new notes on the command line using the submit command:

```
uv run scripts/manage.py submit --source=path/to/pdf_or_glob
```

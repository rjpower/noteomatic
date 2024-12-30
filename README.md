# Installation

Install UV:

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

# Configuration

Configuration is managed by Pydantic-Settings and environment variables. You can
setup a basic .env with:

```
cat > .env <<HERE
NOTEOMATIC_DB_URL=sqlite:///build/notes.db
HERE
```

# Importing Notes

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

# Running the server

```
 FLASK_DEBUG=1 uv run flask --app noteomatic.app:app run --reload --port=8000 [--host=...]
```
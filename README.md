# Installation

Install UV:

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

# Importing Notes


## Sync with Google Drive

You can sync with a Google Drive folder using the `sync` command. You'll need to
create a Google OAuth credential with Google Drive access, and put the client
secrets into `credentials/client_secret.json`:

https://console.cloud.google.com/auth/scopes


the scope to request is: https://www.googleapis.com/auth/drive.readonly
```
uv run scripts/extract.py sync
```

## Syncing files on disk

```
uv run scripts/extract.py submit --source=path/to/pdf_or_glob
```

# Running the browser

```
 FLASK_DEBUG=1 uv run flask --app noteomatic.app:app run --reload --port=8000
```

# Running in the browser, and listening to a public ip address:

```

 FLASK_DEBUG=1 uv run flask --app noteomatic.app:app run --reload --port=8000 --host 0.0.0.0

```

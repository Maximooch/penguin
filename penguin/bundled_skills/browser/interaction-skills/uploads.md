# Uploads

Use file-upload helpers when interacting with `<input type="file">`. Avoid
coordinate-only upload flows unless the site hides the input and no selector is
available.

## Preferred Flow

Find the file input and set it directly:

```python
upload_file("input[type=file]", "/absolute/path/to/file.png")
```

Then verify the UI shows the selected file, preview, progress bar, or upload
completion state.

## Hidden Inputs

Many apps hide the input behind a button. Click the visible button only if it
creates or reveals an input. Prefer DOM inspection over native file dialogs:

```python
js("[...document.querySelectorAll('input[type=file]')].map((e, i) => ({i, accept: e.accept, multiple: e.multiple}))")
```

## Edge Cases

- Multiple files require an API that supports setting several paths.
- `accept` filters are hints; still verify file type/extension before upload.
- Drag-and-drop upload zones may need synthetic `DataTransfer` events if no file
  input exists.
- Never upload sensitive local files without explicit user confirmation.

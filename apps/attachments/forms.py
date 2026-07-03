"""Upload form: whitelisted file types (documents, no executables) and a size cap."""

from __future__ import annotations

from pathlib import Path

from django import forms

MAX_SIZE_MB = 25
ALLOWED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".txt",
    ".csv",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".eml",
}


def validate_upload(upload) -> None:
    """Raise ValidationError unless the upload passes the type whitelist and size cap."""
    suffix = Path(upload.name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise forms.ValidationError(
            f"{upload.name}: file type “{suffix or '?'}” not allowed ({allowed})."
        )
    if upload.size > MAX_SIZE_MB * 1024 * 1024:
        raise forms.ValidationError(f"{upload.name}: exceeds the {MAX_SIZE_MB} MB limit.")


class AttachmentForm(forms.Form):
    file = forms.FileField()

    def clean_file(self):
        upload = self.cleaned_data["file"]
        validate_upload(upload)
        return upload


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """FileField accepting several files at once (Django's documented pattern)."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, list | tuple):
            uploads = [single_clean(entry, initial) for entry in data]
        else:
            uploads = [single_clean(data, initial)] if data else []
        for upload in uploads:
            validate_upload(upload)
        return uploads

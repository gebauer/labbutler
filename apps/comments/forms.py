from django import forms


class CommentForm(forms.Form):
    body = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), max_length=4000, strip=True)

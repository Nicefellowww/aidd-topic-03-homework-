from django import forms

from .models import Share, generate_uid


class ShareModelForm(forms.ModelForm):
    """Форма создания и редактирования инструмента.

    Price and trend fields are intentionally excluded: they are calculated by
    the background price update task.
    """

    class Meta:
        model = Share
        fields = ("figi", "isin", "name", "ticker", "currency", "uid")
        help_texts = {
            "uid": "Необязательно. Если оставить пустым, будет создан автоматически.",
        }

    def clean_uid(self):
        return self.cleaned_data.get("uid") or generate_uid()

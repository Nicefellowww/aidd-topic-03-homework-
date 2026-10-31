from django import forms
from django.conf import settings

from .models import WatchItem, Portfolio, Trade, Strategy, PriceHistory, Share


class WatchForm(forms.ModelForm):
    class Meta:
        model = WatchItem
        fields = ['share', 'source', 'condition', 'target', 'active']
        labels = {'share': 'Акция', 'source': 'Источник', 'condition': 'Условие', 'target': 'Целевая цена', 'active': 'Включено'}

    def __init__(self, *args, owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        self.fields['source'].initial = settings.MARKET_DATA_PROVIDER
        if self.instance.pk:
            self.fields['share'].disabled = True
            self.fields['source'].disabled = True

    def clean(self):
        data = super().clean()
        if data.get('share') and WatchItem.objects.filter(owner=self.owner, share=data['share']).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Эта акция уже в вашем списке.')
        return data


class PortfolioForm(forms.ModelForm):
    class Meta:
        model = Portfolio
        fields = ['name', 'currency']
        labels = {'name': 'Название', 'currency': 'Валюта (rub, usd…)'}

    def clean_currency(self):
        value = self.cleaned_data['currency'].strip().lower()
        if not value.isalpha():
            raise forms.ValidationError('Укажите буквенный код валюты.')
        return value


class TradeForm(forms.ModelForm):
    class Meta:
        model = Trade
        fields = ['share', 'side', 'quantity', 'price']
        labels = {'share': 'Акция', 'side': 'Операция', 'quantity': 'Количество', 'price': 'Цена за единицу'}

    def __init__(self, *args, portfolio, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['share'].queryset = Share.objects.filter(currency__iexact=portfolio.currency)


class StrategyForm(forms.ModelForm):
    class Meta:
        model = Strategy
        fields = ['name', 'share', 'source', 'initial_capital', 'buy_below', 'sell_above', 'order_quantity', 'active']
        labels = {'name': 'Название', 'share': 'Акция', 'source': 'Источник', 'initial_capital': 'Начальный капитал',
                  'buy_below': 'Купить при цене ≤', 'sell_above': 'Продать при цене ≥', 'order_quantity': 'Количество покупки', 'active': 'Включена'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['source'].initial = settings.MARKET_DATA_PROVIDER
        if self.instance.pk:
            for name in ['share', 'source', 'initial_capital']:
                self.fields[name].disabled = True


class HistoryPeriodForm(forms.Form):
    source = forms.ChoiceField(choices=PriceHistory._meta.get_field('source').choices, label='Источник')
    start = forms.DateField(required=False, label='С даты', widget=forms.DateInput(attrs={'type': 'date'}))
    end = forms.DateField(required=False, label='По дату', widget=forms.DateInput(attrs={'type': 'date'}))

    def clean(self):
        data = super().clean()
        if data.get('start') and data.get('end') and data['start'] > data['end']:
            raise forms.ValidationError('Начало периода позже конца.')
        return data

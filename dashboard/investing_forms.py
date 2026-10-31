from django import forms
from django.core.exceptions import ValidationError
from .models import WatchItem, Portfolio, Strategy, Share
from .services.investing import positive


class PositiveDecimal(forms.DecimalField):
    def __init__(self, **kwargs):
        super().__init__(max_digits=27, decimal_places=9, **kwargs)

    def validate(self, value):
        super().validate(value)
        if value is not None:
            positive(value)


class WatchForm(forms.ModelForm):
    target = PositiveDecimal(label='Целевая цена')

    class Meta:
        model = WatchItem
        fields = ['share', 'direction', 'target']
        labels = {'share': 'Акция', 'direction': 'Условие'}


class PortfolioForm(forms.ModelForm):
    class Meta:
        model = Portfolio
        fields = ['name', 'currency']
        labels = {'name': 'Название', 'currency': 'Валюта'}

    def clean_currency(self):
        return self.cleaned_data['currency'].strip().lower()


class TradeForm(forms.Form):
    share = forms.ModelChoiceField(queryset=Share.objects.all(), label='Акция')
    side = forms.ChoiceField(choices=[('buy', 'Покупка'), ('sell', 'Продажа')], label='Операция')
    quantity = PositiveDecimal(label='Количество')
    price = PositiveDecimal(label='Цена исполнения')


class StrategyForm(forms.ModelForm):
    buy_below = PositiveDecimal(label='Купить при цене ≤')
    sell_above = PositiveDecimal(label='Продать при цене ≥')
    quantity = PositiveDecimal(label='Количество одной покупки')
    initial_capital = PositiveDecimal(label='Начальный виртуальный капитал')

    class Meta:
        model = Strategy
        fields = ['name', 'share', 'buy_below', 'sell_above', 'quantity', 'initial_capital', 'enabled']
        labels = {'name': 'Название', 'share': 'Акция', 'enabled': 'Включена'}

    def clean(self):
        data = super().clean()
        if data.get('buy_below') and data.get('sell_above') and data['buy_below'] >= data['sell_above']:
            raise ValidationError('Цена продажи должна быть выше цены покупки.')
        return data


class StrategyRulesForm(StrategyForm):
    class Meta(StrategyForm.Meta):
        fields = ['name', 'buy_below', 'sell_above', 'enabled']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ('quantity', 'initial_capital'):
            self.fields.pop(field, None)


class PeriodForm(forms.Form):
    start = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}), label='С даты (UTC)')
    end = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}), label='По дату (UTC)')

    def clean(self):
        data = super().clean()
        if data.get('start') and data.get('end') and data['start'] > data['end']:
            raise ValidationError('Начало периода должно быть не позже окончания.')
        return data

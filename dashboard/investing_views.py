from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .models import WatchItem, Notification, Portfolio, Strategy, Share
from .investing_forms import WatchForm, PortfolioForm, TradeForm, StrategyForm, StrategyRulesForm, PeriodForm
from .services.investing import execute_trade, portfolio_summary, precise
from .services.graph import history_graph


def page(request, **context):
    return render(request, 'dashboard/investing.html', context)


@login_required(login_url='user:auth')
def watches(request):
    form = WatchForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            watch, _ = WatchItem.objects.get_or_create(owner=request.user, share=form.cleaned_data['share'],
                defaults={'target': form.cleaned_data['target']})
            watch = WatchItem.objects.select_for_update().get(pk=watch.pk)
            watch.direction, watch.target = form.cleaned_data['direction'], form.cleaned_data['target']
            watch.active = False
            watch.last_observation = watch.share.observations.last()
            watch.save()
        return redirect('dashboard:watches')
    return page(request, title='Наблюдение', form=form, watches=WatchItem.objects.filter(owner=request.user).select_related('share'),
                notifications=Notification.objects.filter(owner=request.user).order_by('-pk'),
                help='Повторное добавление акции меняет цель. Отслеживание начинается со следующей новой котировки. После выхода из условия уведомление может сработать снова.')


@login_required(login_url='user:auth')
@require_POST
def watch_delete(request, pk):
    get_object_or_404(WatchItem, pk=pk, owner=request.user).delete()
    return redirect('dashboard:watches')


@login_required(login_url='user:auth')
@require_POST
def notification_read(request, pk):
    item = get_object_or_404(Notification, pk=pk, owner=request.user)
    item.read = True
    item.save(update_fields=['read'])
    return redirect('dashboard:watches')


@login_required(login_url='user:auth')
def portfolios(request):
    form = PortfolioForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        item = form.save(commit=False)
        item.owner = request.user
        item.save()
        return redirect('dashboard:portfolio', pk=item.pk)
    return page(request, title='Виртуальные портфели', form=form,
                portfolios=Portfolio.objects.filter(owner=request.user, strategy__isnull=True))


@login_required(login_url='user:auth')
def portfolio(request, pk):
    item = get_object_or_404(Portfolio, owner=request.user, pk=pk)
    managed = Strategy.objects.filter(portfolio=item).exists()
    form = TradeForm(request.POST or None)
    if request.method == 'POST':
        if managed:
            return HttpResponseForbidden('Портфель управляется стратегией.')
        elif form.is_valid():
            try:
                execute_trade(item, **form.cleaned_data)
                return redirect('dashboard:portfolio', pk=pk)
            except ValidationError as exc:
                form.add_error(None, exc)
    return page(request, title=item.name, portfolio=item, form=None if managed else form,
                summary=portfolio_summary(item), trades=item.trades.select_related('share'),
                help='Только виртуальные сделки. Цена вводится пользователем. Оценка — по последней цене каталога; валюта портфеля: '+item.currency)


@login_required(login_url='user:auth')
def strategies(request):
    form = StrategyForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            strategy = form.save(commit=False)
            strategy.owner = request.user
            strategy.cash = strategy.initial_capital
            strategy.portfolio = Portfolio.objects.create(owner=request.user, name=strategy.name, currency=strategy.share.currency.lower())
            strategy.last_observation = strategy.share.observations.last()
            strategy.save()
        return redirect('dashboard:strategy', pk=strategy.pk)
    return page(request, title='Симулятор стратегий', form=form, strategies=Strategy.objects.filter(owner=request.user),
                help='Покупка фиксированного количества при цене ≤ порога, если позиция пуста и хватает денег. Продажа всей позиции при цене ≥ порога. Исполнение по цене новой сохранённой котировки; без комиссий, проскальзывания, дивидендов и конвертации. Старые котировки не торгуются.')


@login_required(login_url='user:auth')
@precise
def strategy(request, pk):
    item = get_object_or_404(Strategy, owner=request.user, pk=pk)
    form = StrategyRulesForm(request.POST or None, instance=item)
    if request.method == 'POST' and form.is_valid():
        # Lock against the worker; never overwrite its cash or watermark.
        with transaction.atomic():
            locked = Strategy.objects.select_for_update().get(pk=item.pk)
            for field in ('name', 'buy_below', 'sell_above', 'enabled'):
                setattr(locked, field, form.cleaned_data[field])
            locked.save(update_fields=['name', 'buy_below', 'sell_above', 'enabled'])
        return redirect('dashboard:strategy', pk=pk)
    summary = portfolio_summary(item.portfolio)
    equity = item.cash + summary['value'] if summary['value'] is not None else None
    profit = equity - item.initial_capital if equity is not None else None
    return page(request, title=item.name, form=form, strategy=item, summary=summary,
                equity=equity, profit=profit,
                percent=profit / item.initial_capital * 100 if profit is not None else None,
                events=item.events.select_related('observation'), trades=item.portfolio.trades.select_related('share'),
                help='Правила применяются при обработке новых записей. Выключенные котировки отмечаются обработанными. Все сделки виртуальные.')


@precise
def history(request, pk):
    share = get_object_or_404(Share, pk=pk)
    form = PeriodForm(request.GET)
    observations = share.observations.all()
    if form.is_valid():
        if form.cleaned_data.get('start'):
            observations = observations.filter(timestamp__date__gte=form.cleaned_data['start'])
        if form.cleaned_data.get('end'):
            observations = observations.filter(timestamp__date__lte=form.cleaned_data['end'])
    else:
        observations = observations.none()
    rows = list(observations)
    currencies = {row.currency for row in rows}
    change = rows[-1].price - rows[0].price if rows and len(currencies) == 1 else None
    percent = change / rows[0].price * Decimal(100) if change is not None and rows[0].price else None
    return page(request, title='Накопленная история: '+share.ticker, period_form=form, observations=rows,
                change=change, percent=percent, plot_div=history_graph(rows) if rows else '',
                help='Только сохранённые в БД котировки. Изменение — между первой и последней точкой периода; при смене валюты не рассчитывается. Процент от нулевой цены не определён.')
